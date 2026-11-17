"""Prove the packed-load and projection state handoffs in the widened mapped controller."""

import ast
from collections import defaultdict
from contextlib import ExitStack
from functools import cache
import json
from pathlib import Path
import re

from sympy import Symbol, false, true
from sympy.logic.boolalg import And, Equivalent, Not, Or, Xor
from sympy.logic.inference import satisfiable

from build_tri_oracle_booth_chip_seed import hierarchy
from verify_tri_oracle_booth_chip_link import named_bindings
from verify_tri_oracle_corrected_booth_roundtrip import ROOT, TOP, digest, read
from verify_tri_oracle_wide_compute_overlap import LIBRARY, RESOURCE
from verify_tri_oracle_wide_seed_resources import ACCELERATOR, catalog, module_text


INSTANCE = re.compile(rb"(?m)^[ \t]+([\w$]+)\s+(\\\S+|[\w$]+)\s*\(([^;]+)\);")
CELL = re.compile(r"(?m)^cell\s+\((\w+)\)\s*\{")
TOKEN = re.compile(r"\w+|[!()+*^]")
STATES = (19, 20, 12, 13)
FAULT_STATES = (14, 15)


def liberty_expression(function, pins):
    """Parse the Boolean syntax of the standard cells used in the cone."""
    pieces = TOKEN.findall(function)
    assert "".join(pieces) == re.sub(r"\s+", "", function)
    operators = {"*": "&", "+": "|", "!": "~"}
    expression = ""
    previous = ""
    for piece in pieces:
        if (previous.isalnum() or previous == ")") and (piece.isalnum() or piece in {"(", "!"}):
            expression += "&"
        expression += operators.get(piece, piece)
        previous = piece

    def interpret(node):
        if isinstance(node, ast.Name):
            return pins[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            return Not(interpret(node.operand))
        if isinstance(node, ast.BinOp):
            return {ast.BitAnd: And, ast.BitOr: Or, ast.BitXor: Xor}[type(node.op)](
                interpret(node.left), interpret(node.right))
        raise ValueError(ast.dump(node))

    return interpret(ast.parse(expression, mode="eval").body)


def cells(library):
    definitions = list(CELL.finditer(library))
    return {match[1]: library[match.end():end] for match, end in
            zip(definitions, [item.start() for item in definitions[1:]] + [len(library)], strict=True)}


def fsm(module, library):
    instances, drivers = {}, defaultdict(list)
    for master, name, fields in INSTANCE.findall(module):
        if not fields.strip().startswith(b"."):
            continue
        wiring = named_bindings(fields)
        label = name.removeprefix(b"\\").decode()
        assert label not in instances
        instances[label] = master.decode(), wiring
        for pin in {"Z", "ZN"} & wiring.keys():
            drivers[wiring[pin]].append((master.decode(), pin, wiring))
    aliases = {}
    for name, value in re.findall(rb"(?m)^\s*assign\s+(\w+(?:\[\d+\])?)\s*=\s*(\w+(?:\[\d+\])?|1'b[01])\s*;", module):
        assert name not in aliases
        aliases[name] = value

    uses = set()

    @cache
    def cell_function(master, pin):
        match = re.search(rf"(?ms)^  pin\s*\({pin}\)\s*\{{(.*?)(?=^  \}})", library[master])
        return re.search(r'(?m)^\s*function\s*:\s*"([^"]+)"', match[1])[1]

    def logic(wire):
        if wire in (b"1'b0", b"1'b1"):
            return true if wire.endswith(b"1") else false
        return Symbol(wire.decode())

    @cache
    def function_of(wire):
        if wire in aliases:
            return logic(aliases[wire])
        if wire not in drivers:
            return None
        (master, pin, wiring), = drivers[wire]
        uses.add(master)
        function = cell_function(master, pin)
        arguments = {name: logic(wiring[name]) for name in set(TOKEN.findall(function)) & wiring.keys()}
        assert all(name != pin for name in arguments)
        return liberty_expression(function, arguments)

    def cone(expression):
        visited, active, clauses = set(), set(), []

        def visit(signal):
            assert signal not in active, signal
            if signal in visited:
                return
            active.add(signal)
            driver = function_of(str(signal).encode())
            if driver is not None:
                for term in driver.free_symbols:
                    visit(term)
                clauses.append(Equivalent(signal, driver))
            active.remove(signal)
            visited.add(signal)

        for signal in expression.free_symbols:
            visit(signal)
        return And(*clauses)

    bits, next_bits = [], []
    for index in range(5):
        master, wiring = instances[f"state_reg[{index}]"]
        assert master in {"DFCND1BWP12T40P140", "DFCNQD1BWP12T40P140"}
        source = library[master]
        for attribute, value in (("clocked_on", "CP"), ("next_state", "D"), ("clear", "(!CDN)")):
            assert re.search(rf'\b{attribute}\s*:\s*"\s*{re.escape(value)}\s*"', source)
        assert wiring["CP"] == b"clk" and wiring["CDN"] == b"rst_n" and wiring["Q"] == b"state[%d]" % index
        assert cell_function(master, "Q") == "IQ"
        if "QN" in wiring:
            # Use the complement of the same physical state flop.
            assert cell_function(master, "QN") == "IQN"
            complement = Symbol(wiring["QN"].decode())
        else:
            complement = None
        bits.append((Symbol(wiring["Q"].decode()), complement, wiring["D"]))
    for _, _, wire in bits:
        next_bits.append(logic(wire))
    return instances, logic, bits, next_bits, uses, cone


def modes(bits, value):
    env = {Symbol("rst_n"): true}
    for index, (signal, complement, _) in enumerate(bits):
        high = bool(value & (1 << index))
        env[signal] = true if high else false
        if complement is not None:
            env[complement] = false if high else true
    return env


def target_state(next_bits, value):
    return And(*(bit if value & (1 << index) else Not(bit) for index, bit in enumerate(next_bits)))


def verify():
    resources = read(RESOURCE)
    candidate, = (Path(path) for path in resources["evidence_sha256"] if path.endswith("/placement_seed/candidate.v"))
    assert digest(candidate) == resources["candidate_sha256"]
    with ExitStack() as stack:
        modules = catalog(stack, (candidate,))
        children, _ = hierarchy(modules)
        master = TOP.encode()
        path = ACCELERATOR.strip(b"/").split(b"/") + [b"layer", b"layer", b"feedforward", b"compute", b"compute", b"tensor"]
        for name in path:
            master = children(master)[name]
        module = module_text(modules, master.decode())
    instances, logic, bits, next_bits, used, cone = fsm(module, cells(LIBRARY.read_text()))
    loader, loader_pins = instances["packed_loader"]
    engine, engine_pins = instances["sequencer"]
    stage, stage_pins = instances["packed_write_stage"]
    fabric, fabric_pins = instances["fabric"]
    assert (loader, engine, stage) == ("tri_oracle_native_reset_copy_15", "tri_oracle_native_reset_copy_34",
                                      "tri_oracle_native_reset_copy_33")
    assert fabric == "tri_oracle_native_token_map_copy_6"
    for signal in ("done_valid", "done_ready", "done_error"):
        assert stage_pins["loader_" + signal] == loader_pins[signal]
    assert stage_pins["load_valid"] == loader_pins["load_valid"]
    assert stage_pins["write_valid"] == fabric_pins["wide_load_valid"]
    for suffix in ("valid", "ready"):
        assert engine_pins["backend_cmd_" + suffix] == fabric_pins["cmd_" + suffix]
    assert engine_pins["in_weight_base"] == b"{1'b0,1'b0,1'b0,1'b0,1'b0}"
    load_start, load_wait, compute_start, compute_wait = STATES
    decodes = {
        "load_configuration": (logic(loader_pins["cfg_valid"]), load_start),
        "projection_configuration": (logic(engine_pins["in_valid"]), compute_start),
        "projection_retire_ready": (logic(engine_pins["done_ready"]), compute_wait),
    }
    flop_values = And(Symbol("rst_n"), *(Equivalent(signal, Not(complement))
                                        for signal, complement, _ in bits if complement is not None))
    state_outputs = [signal for signal, _, _ in bits]
    for name, (expression, expected_state) in decodes.items():
        condition = target_state(state_outputs, expected_state)
        assert satisfiable(And(flop_values, cone(expression), Not(Equivalent(expression, condition)))) is False, name
    load_start_signal = decodes["load_configuration"][0]
    incorrect_decode = Equivalent(load_start_signal, target_state(state_outputs, load_wait))
    assert satisfiable(And(flop_values, cone(load_start_signal), Not(incorrect_decode))) is not False

    checks = {}

    def check(name, state, condition, *successors):
        substitutions = modes(bits, state)
        before_advance = condition.xreplace(substitutions)
        decision = Or(*(target_state(next_bits, result) for result in successors))
        equations = cone(And(condition, decision)).xreplace(substitutions)
        premise = And(equations, before_advance)
        assert satisfiable(premise) is not False, name
        counterexample = satisfiable(And(premise, Not(decision.xreplace(substitutions))))
        if counterexample is not False:
            observed = sum(1 << bit for bit, signal in enumerate(next_bits) if counterexample[signal])
            raise AssertionError((name, observed, successors))
        checks[name] = {"from": state, "allowed_successors": list(successors)}

    load_ready = logic(loader_pins["cfg_ready"])
    load_done = logic(stage_pins["done_valid"])
    compute_ready = logic(engine_pins["in_ready"])
    compute_done = logic(engine_pins["done_valid"])
    check("hold_load_offer_under_backpressure", load_start, Not(load_ready), load_start, *FAULT_STATES)
    check("accepted_load_offer_waits_for_data", load_start, load_ready, load_wait, *FAULT_STATES)
    check("hold_load_until_staged_write_completion", load_wait, Not(load_done), load_wait)
    check("completed_load_enters_projection_or_cancels", load_wait, load_done, compute_start, *FAULT_STATES)
    check("hold_projection_offer_under_backpressure", compute_start, Not(compute_ready), compute_start, *FAULT_STATES)
    check("accepted_projection_waits_for_retirement", compute_start, compute_ready, compute_wait, *FAULT_STATES)
    check("hold_projection_until_completion", compute_wait, Not(compute_done), compute_wait, *FAULT_STATES)
    return {
        "state": "wide_tensor_controller_projection_handoff_verified",
        "candidate_sha256": resources["candidate_sha256"], "controller_master": master.decode(),
        "physical_controller_bits": len(bits), "enumerated_state_encodings": 32,
        "drain_and_flush_state_encodings": list(FAULT_STATES),
        "checked_decodes": {key: state for key, (_, state) in decodes.items()},
        "verified_transitions": checks, "verified_combinational_cell_types": sorted(used),
        "completion_stage_master": stage,
        "projection_weight_base_at_launch": 0,
        "checked_weight_write_and_projection_command_fabric_bindings": True,
        "scope": "Static proof from the standard-cell gates and Liberty truth functions with reset released. "
                 "Boundary inputs outside the selected cone are free Boolean values. "
                 "The result applies to the widened chip's controller with the existing weight and projection interfaces.",
        "evidence_sha256": {str(path): digest(path) for path in (
            RESOURCE, candidate, LIBRARY, Path(__file__).resolve().relative_to(ROOT))},
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))

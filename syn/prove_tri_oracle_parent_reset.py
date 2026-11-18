"""Prove stable two-state parent reset distribution; timing remains unqualified."""

from hashlib import sha256
from itertools import product
import re

from prove_tri_oracle_packaged_products import BooleanGraph, PIN
from prove_tri_oracle_packaged_reductions import DecisionGraph

INSTANCE = re.compile(rb"\b([\w$]+)\s+(\\\S+|[\w$]+)\s*\(\s*(\.[^;]*)\);")
ASSIGN = re.compile(rb"\bassign\s+([^;]+);")
IDENTIFIER = re.compile(r"(?:\\([A-Za-z0-9_$.\[\]:]+)\s*|([A-Za-z_$][\w$]*))")
RAW_IDENTIFIER = rb"(?:\\[A-Za-z0-9_$.:\[\]]+\s+|[A-Za-z_$][\w$]*)"
DECLARATION = re.compile(
    rb"\b(input|output|wire)\s+(?:wire\s+)?(?:signed\s+)?"
    rb"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+)?("
    + RAW_IDENTIFIER
    + rb"(?:\s*,\s*"
    + RAW_IDENTIFIER
    + rb")*)\s*;"
)


def identifier(text):
    match = IDENTIFIER.fullmatch(text.strip())
    if not match:
        raise ValueError("Unsupported identifier: " + text[:80])
    return match[1] or match[2]


class Module:
    def __init__(self, body):
        self.sha256 = sha256(body).hexdigest()
        clean = re.sub(
            rb"\\[^\s]+|/\*[\s\S]*?\*/|//[^\n]*",
            lambda m: m[0] if m[0].startswith(b"\\") else b"",
            body,
        )
        header = re.match(rb"\s*module\s+[\w$]+\s*\(([^;]*)\)\s*;", clean)
        if not header or not clean.rstrip().endswith(b"endmodule"):
            raise ValueError("Unsupported module header or ending")
        ports = [identifier(x.decode()) for x in header[1].split(b",")]
        assert len(ports) == len(set(ports)), "Repeated module port"
        rest = clean[header.end() :].rstrip()[: -len(b"endmodule")]
        self.declared, self.directions, self.bits = {}, {}, set()
        for match in DECLARATION.finditer(rest):
            bounds = (int(match[2]), int(match[3])) if match[2] is not None else None
            for raw in match[4].split(b","):
                name = identifier(raw.decode())
                assert name not in self.declared, "Repeated net declaration"
                self.declared[name] = bounds
                labels = self.net_bits(name)
                assert not self.bits.intersection(labels), "Ambiguous declared bit"
                self.bits.update(labels)
                if match[1] in (b"input", b"output"):
                    self.directions[name] = match[1].decode()
        assert set(ports) == self.directions.keys(), "Port declarations differ"
        rest = DECLARATION.sub(b"", rest)
        self.assignments = {}
        for match in ASSIGN.finditer(rest):
            sides = match[1].decode().split("=")
            assert len(sides) == 2, "Unsupported assignment"
            left, right = (self.expression(x) for x in sides)
            assert left and len(left) == len(right), "Assignment width differs"
            assert not any(x.startswith("1'") for x in left), (
                "Constant assignment destination"
            )
            for lhs, rhs in zip(left, right, strict=True):
                assert lhs not in self.assignments, "Multiple assignment drivers"
                self.assignments[lhs] = rhs
        rest = ASSIGN.sub(b"", rest)
        self.cells = {}
        for match in INSTANCE.finditer(rest):
            master, instance = match[1].decode(), identifier(match[2].decode())
            assert instance not in self.cells, "Duplicate instance"
            fields = match[3]
            matches = PIN.findall(fields)
            pins = {identifier(pin.decode()): raw.decode() for pin, raw in matches}
            assert len(pins) == len(matches), "Repeated instance pin"
            assert not PIN.sub(b"", fields).strip(b" \t\r\n,"), (
                "Unsupported named connection"
            )
            self.cells[instance] = master, pins
        assert not INSTANCE.sub(b"", rest).strip(), "Unsupported parent statement"

    def net_bits(self, name):
        bounds = self.declared[name]
        if bounds is None:
            return (name,)
        first, last = bounds
        step = 1 if last > first else -1
        return tuple(f"{name}[{bit}]" for bit in range(first, last + step, step))

    def expression(self, text):
        text = text.strip()
        if not text:
            return ()
        if text.startswith("{") and text.endswith("}"):
            depth, start, parts = 0, 1, []
            for i, char in enumerate(text[1:-1], 1):
                depth += (char == "{") - (char == "}")
                assert depth >= 0, "Unbalanced concatenation"
                if char == "," and depth == 0:
                    parts.extend(self.expression(text[start:i]))
                    start = i + 1
            assert depth == 0, "Unbalanced concatenation"
            parts.extend(self.expression(text[start:-1]))
            assert parts, "Empty concatenation"
            return tuple(parts)
        literal = re.fullmatch(r"(\d+)'([bBhHdD])([0-9a-fA-F_]+)", text)
        if literal:
            width = int(literal[1])
            assert 0 < width <= 100000, "Invalid literal width"
            base = {"b": 2, "h": 16, "d": 10}[literal[2].lower()]
            value = int(literal[3].replace("_", ""), base) & ((1 << width) - 1)
            return tuple(f"1'b{(value >> b) & 1}" for b in range(width - 1, -1, -1))
        if text.startswith("\\"):
            match = re.fullmatch(
                r"\\([A-Za-z0-9_$.\[\]:]+)\s+(?:\[\s*(\d+)\s*(?::\s*(\d+)\s*)?\])?\s*",
                text + " ",
            )
        else:
            match = re.fullmatch(
                r"([A-Za-z_$][\w$]*)(?:\[\s*(\d+)\s*(?::\s*(\d+)\s*)?\])?\s*", text
            )
        if not match:
            raise ValueError("Unsupported net expression: " + text[:80])
        name, first, last = match.groups()
        assert name in self.declared, "Undeclared net: " + name
        if first is None:
            return self.net_bits(name)
        bounds = self.declared[name]
        assert bounds is not None, "Selected scalar net"
        first, last = int(first), int(last if last is not None else first)
        assert min(bounds) <= min(first, last) <= max(first, last) <= max(bounds), (
            "Out-of-range selection"
        )
        if first != last:
            assert (first > last) == (bounds[0] > bounds[1]), "Reversed part selection"
        step = 1 if last > first else -1
        return tuple(f"{name}[{bit}]" for bit in range(first, last + step, step))

    def bit_direction(self, net):
        for name, direction in self.directions.items():
            if net == name or (
                self.declared[name] is not None and net in self.net_bits(name)
            ):
                return direction
        return None


class ResetHierarchy:
    def __init__(self, body, masters, library, states, *, guard=lambda: None):
        self.body, self.masters, self.library, self.states = (
            body,
            masters,
            library,
            states,
        )
        self.guard = guard
        self.graph = BooleanGraph()
        self.contexts, self.modules, self.visiting, self.cones = {}, {}, set(), {}
        self.used_library_pins = set()

    def module(self, master):
        if master not in self.modules:
            self.guard()
            self.modules[master] = Module(self.body(master))
        return self.modules[master]

    def child(self, context, instance):
        master, _, _ = self.contexts[context]
        child, pins = self.module(master).cells[instance]
        assert child in self.masters, "Unknown hierarchy module"
        path = f"{context}/{instance}" if context else instance
        if path not in self.contexts:
            self.contexts[path] = child, context, pins
        return path

    def direction(self, master, pin):
        if master in self.masters:
            return self.module(master).directions[pin]
        self.used_library_pins.add((master, pin))
        if (master, pin) not in self.library:
            raise ValueError(f"Unknown library pin on reset cone: {master}.{pin}")
        return self.library[master, pin]["direction"]

    def drivers(self, context, net):
        master, _, _ = self.contexts[context]
        module = self.module(master)
        found = (
            [("assign", module.assignments[net])] if net in module.assignments else []
        )
        for instance, (kind, pins) in module.cells.items():
            for pin, value in pins.items():
                # Lexical filtering only skips bindings that cannot contain this bit.
                if net.split("[")[0] not in value:
                    continue
                bits = module.expression(value)
                if net not in bits:
                    continue
                direction = self.direction(kind, pin)
                if direction == "output":
                    found.extend(
                        ("cell", instance, kind, pin, offset, len(bits), pins)
                        for offset, bit in enumerate(bits)
                        if bit == net
                    )
                else:
                    assert direction == "input", "Unsupported pin direction"
        return found

    def trace(self, context, net):
        if net in ("1'b0", "1'b1"):
            return int(net[-1])
        key = context, net
        if key in self.cones:
            return self.cones[key]
        assert key not in self.visiting, "Combinational cycle"
        self.visiting.add(key)
        master, parent, pins = self.contexts[context]
        module = self.module(master)
        assert net in module.bits, "Undeclared internal bit"
        drivers = self.drivers(context, net)
        if module.bit_direction(net) == "input":
            assert not drivers, "Input port has an internal driver"
            if parent is None:
                result = self.graph.variable("top." + net)
            else:
                owner = self.module(self.contexts[parent][0])
                port = next(
                    name for name in module.directions if net in module.net_bits(name)
                )
                formal, actual = module.net_bits(port), owner.expression(pins[port])
                assert len(formal) == len(actual), "Hierarchy input width differs"
                result = self.trace(parent, actual[formal.index(net)])
        else:
            assert len(drivers) == 1, (
                "Expected one internal driver",
                context,
                net,
                len(drivers),
            )
            (driver,) = drivers
            if driver[0] == "assign":
                result = self.trace(context, driver[1])
            else:
                _, instance, kind, pin, offset, width, connected = driver
                if kind in self.masters:
                    formal = self.module(kind).net_bits(pin)
                    assert len(formal) == width, "Hierarchy output width differs"
                    result = self.trace(self.child(context, instance), formal[offset])
                else:
                    assert width == 1, "Library output is not scalar"
                    function = self.library[kind, pin]["function"]
                    if self.states.get(kind):
                        assert self.states[kind] == {"ff": 1}, (
                            "Unsupported sequential source"
                        )
                        assert function in ("IQ", "IQN"), "Unsupported state output"
                        # Independent polarities conservatively include every stable
                        # state, without assuming a clear/preset complement invariant.
                        result = self.graph.variable(f"{context}/{instance}:{function}")
                    else:
                        assert function, "Missing combinational output function"
                        values = {}
                        for symbol in set(re.findall(r"[A-Za-z_]\w*", function)):
                            assert self.direction(kind, symbol) == "input", (
                                "Function references non-input"
                            )
                            bits = module.expression(connected[symbol])
                            assert len(bits) == 1, "Library input is not scalar"
                            values[symbol] = self.trace(context, bits[0])
                        result = self.graph.function(function, values)
        self.visiting.remove(key)
        self.cones[key] = result
        return result

    def prove(self, top, aliases):
        self.contexts[""] = top, None, None
        roots, rows = [], []
        for path, names in aliases.items():
            self.guard()
            context = ""
            for instance in path.split("/"):
                context = self.child(context, instance)
            module = self.module(self.contexts[context][0])
            assert "rst_n" in names and len(names) == len(set(names)), (
                "Reset alias inventory differs"
            )
            current = []
            for name in names:
                assert (
                    module.directions.get(name) == "input"
                    and module.declared[name] is None
                ), "Reset alias is not a scalar input"
                current.append(self.trace(context, name))
            roots.extend(current)
            rows.append(
                {
                    "path": path,
                    "module": self.contexts[context][0],
                    "aliases": list(names),
                    "root_count": len(current),
                }
            )
        assert roots, "No reset roots"
        leaves = sorted(set().union(*(self.graph.dependencies(root) for root in roots)))
        assert len(leaves) <= 16, "Reset proof state space unexpectedly large"
        decision = DecisionGraph(leaves)
        identities = decision.convert(self.graph, roots)
        assert len(set(identities)) == 1, "Reset aliases differ across mapped arrays"
        assert identities[0] not in (0, 1), "Reset function is constant"
        assert "top.rst_n" in leaves, (
            "Top reset dominance requires dependence on top reset"
        )
        cases = 0
        for bits in product((0, 1), repeat=len(leaves)):
            values = dict(zip(leaves, bits, strict=True))
            observed = self.graph.evaluate(roots, values)
            assert len(set(observed)) == 1, "Integer reset aliases differ"
            if not values.get("top.rst_n", 0):
                assert observed[0] == 0, (
                    "Top reset assertion does not dominate array clears"
                )
            cases += 1
        return {
            "array_count": len(rows),
            "arrays": rows,
            "leaves": leaves,
            "reset_roots": len(roots),
            "integer_assignments": cases,
            "all_reset_aliases_equal": True,
            "top_reset_assertion_dominates": True,
            "parent_module_sha256": {
                name: module.sha256 for name, module in self.modules.items()
            },
            "used_library_pins": sorted(self.used_library_pins),
        }


def actual_parent_mutations(checker, top, aliases):
    """Corrupt captured actual bindings in memory; the source file stays intact."""
    failures = []
    for path, names in aliases.items():
        checker.guard()
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        local = path.rsplit("/", 1)[-1]
        parent_master = checker.contexts[parent][0]
        original = checker.body(parent_master)
        (instance,) = (
            m for m in INSTANCE.finditer(original) if identifier(m[2].decode()) == local
        )
        for alias in names:
            changed = 0

            def corrupt(pin):
                nonlocal changed
                if identifier(pin[1].decode()) != alias:
                    return pin[0]
                changed += 1
                return b"." + pin[1] + b"(1'b1)"

            fields = PIN.sub(corrupt, instance[3])
            assert changed == 1, "Mutation did not change exactly one reset binding"
            altered = (
                original[: instance.start(3)] + fields + original[instance.end(3) :]
            )
            assert altered != original
            mutated = ResetHierarchy(
                lambda name: altered if name == parent_master else checker.body(name),
                checker.masters,
                checker.library,
                checker.states,
                guard=checker.guard,
            )
            # Parsed modules are immutable; only the changed parent is re-parsed.
            mutated.modules = checker.modules.copy()
            mutated.modules.pop(parent_master)
            try:
                mutated.prove(top, {path: names})
            except (AssertionError, ValueError) as error:
                reason = str(error)
                assert "alias" in reason.lower() or "constant" in reason.lower(), (
                    "Mutation rejected for an unrelated reason",
                    path,
                    alias,
                    reason,
                )
                failures.append(
                    {
                        "array": checker.contexts[path][0],
                        "pin": alias,
                        "fault": "actual_parent_reset_binding_stuck_high",
                        "rejection": reason,
                    }
                )
            else:
                raise AssertionError(
                    ("Actual disconnected reset was accepted", path, alias)
                )
    return failures


def verify(output):
    import json
    from mmap import mmap, ACCESS_READ
    from pathlib import Path
    import resource
    import time
    from audit_tri_oracle_mapped_redundancy import hierarchy
    from link_tri_oracle_indexed_whole_chip import spans
    from plan_tri_oracle_grouped_reset import read_library
    from prove_tri_oracle_packaged_products import CANDIDATE, ROOT, memory_guard
    from prove_tri_oracle_packaged_valid import inputs

    assert __debug__ and not Path("/.dockerenv").exists()
    assert (
        output.resolve().is_relative_to((ROOT / ".cache").resolve())
        and not output.exists()
    )
    memory_guard(10)
    started = time.monotonic()
    ranges, _, states, evidence, structure, _ = inputs()

    def pin(path, wanted=None):
        from hashlib import file_digest

        with path.open("rb") as stream:
            actual = file_digest(stream, "sha256").hexdigest()
        assert wanted is None or actual == wanted, ("Changed reset proof input", path)
        evidence[str(path.relative_to(ROOT))] = actual
        return path

    qualified = json.loads(
        pin(ROOT / "records/tri_oracle_packaged_valid_next_states.json").read_text()
    )
    assert qualified["state"] == "packaged_local_valid_transitions_and_clears_verified"
    assert qualified["candidate_sha256"] == structure["candidate_sha256"]
    assert set(qualified["arrays"]) == set(ranges)
    for name, checksum in qualified["evidence_sha256"].items():
        pin(ROOT / name, checksum)
    for path in (
        Path(__file__).resolve(),
        ROOT / "syn/test_tri_oracle_parent_reset.py",
        ROOT / "syn/audit_tri_oracle_mapped_redundancy.py",
    ):
        pin(path)

    graph = hierarchy(CANDIDATE)
    targets = {}

    def walk(master, path, active):
        assert master not in active, "Hierarchy cycle"
        if master in ranges:
            names = qualified["arrays"][master]["reset_alias_by_stage"]
            assert path not in targets
            targets[path] = tuple(sorted(set(names) | {"rst_n"}))
            return
        for instance, child in graph[master].items():
            local = instance.removeprefix("\\")
            assert "/" not in local, "Ambiguous hierarchical instance name"
            walk(child, path + "/" + local if path else local, active | {master})

    walk(structure["logical_top"], "", set())
    assert len(targets) == len(ranges) == 20, "Reachable array count differs"
    sources = []
    for suffix in ("tt1v25c", "ssg0p9v125c", "ffg1p05vm40c"):
        filename = f"tcbn28hpcplusbwp12t40p140{suffix}.lib"
        ((name, checksum),) = (
            (name, checksum)
            for name, checksum in structure["evidence_sha256"].items()
            if Path(name).name == filename
        )
        sources.append(pin(ROOT / name, checksum))
    masters = set(re.findall(r"(?m)^cell\s*\(([^)]+)\)\s*\{", sources[0].read_text()))
    library = read_library(sources[0], masters)
    with (
        CANDIDATE.open("rb") as stream,
        mmap(stream.fileno(), 0, access=ACCESS_READ) as source,
    ):
        definitions = spans(source)

        def body(master):
            low, high = definitions[master]
            return source[low:high]

        checker = ResetHierarchy(
            body, set(definitions), library, states, guard=memory_guard
        )
        result = checker.prove(structure["logical_top"], targets)
        for row in result["arrays"]:
            assert (
                checker.module(row["module"]).sha256
                == qualified["arrays"][row["module"]]["array_module_sha256"]
            ), "Captured array differs from qualified local clear proof"
        for path in sources[1:]:
            other = read_library(
                path, {master for master, _ in checker.used_library_pins}
            )
            for key in checker.used_library_pins:
                assert {a: other[key].get(a) for a in ("direction", "function")} == {
                    a: library[key].get(a) for a in ("direction", "function")
                }, ("Corner reset function differs", key)
        result["rejected_actual_parent_mutations"] = actual_parent_mutations(
            checker, structure["logical_top"], targets
        )
        assert len(result["rejected_actual_parent_mutations"]) == result["reset_roots"]
        memory_guard()
    for name, checksum in list(evidence.items()):
        pin(ROOT / name, checksum)
    result.update(
        state="packaged_parent_combinational_reset_distribution_verified",
        candidate_sha256=structure["candidate_sha256"],
        evidence_sha256=evidence,
        wall_seconds=time.monotonic() - started,
        peak_resident_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        advance_to_clock_distribution_or_routing_allowed=False,
        scope="Stable two-state combinational reset aliases and top-reset assertion for all twenty "
        "reachable mapped arrays. Flip-flop outputs are arbitrary state cutpoints. "
        "This does not qualify reset release timing, four-state behavior, reachable controller "
        "states, complete architecture, trained execution, accuracy or physical timing/routing.",
    )
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(
        "PARENT_RESET_DISTRIBUTION_PASS",
        result["array_count"],
        result["reset_roots"],
        result["integer_assignments"],
        flush=True,
    )


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    verify(parser.parse_args().output)

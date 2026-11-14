"""Compare whole-block skip rankings on trained mapped replay inputs."""

import argparse
from array import array
import ctypes as c
import json
from math import sqrt
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from audit_tri_oracle_predictor_parity import CHANNELS, HIDDEN, active_groups, dot, integers, margins, weight_bytes
from check_tri_oracle_paper300_gate import sha
from tri_oracle_model_reference import requantize, silu_code


WIDTH = 8
BLOCKS = CHANNELS // WIDTH
REPLAY = Path("records/tri_oracle_predictor_parity.json")
TARGETS = Path("records/paper_result_targets.json")


def cuda_squares(binary, values, weights, tokens):
    driver = c.CDLL("libcuda.so.1")

    def call(name, *arguments):
        status = getattr(driver, name)(*arguments)
        if status:
            raise RuntimeError(f"{name}: CUDA status {status}")

    device = c.c_int()
    context, module, kernel = c.c_void_p(), c.c_void_p(), c.c_void_p()
    call("cuInit", 0)
    call("cuDeviceGet", c.byref(device), 0)
    call("cuDevicePrimaryCtxRetain", c.byref(context), device)
    allocations = []
    try:
        call("cuCtxSetCurrent", context)
        available, total = c.c_size_t(), c.c_size_t()
        call("cuMemGetInfo_v2", c.byref(available), c.byref(total))
        assert available.value >= 1024**3
        call("cuModuleLoad", c.byref(module), bytes(binary))
        call("cuModuleGetFunction", c.byref(kernel), module, b"block_squared_contribution")
        result = (c.c_uint64 * (tokens * BLOCKS))()
        buffers = ((c.c_int8 * len(values)).from_buffer_copy(values),
                   (c.c_int8 * len(weights)).from_buffer_copy(weights), result)
        for index, buffer in enumerate(buffers):
            pointer = c.c_uint64()
            call("cuMemAlloc_v2", c.byref(pointer), c.c_size_t(c.sizeof(buffer)))
            allocations.append(pointer)
            if index < 2:
                call("cuMemcpyHtoD_v2", pointer, c.byref(buffer), c.c_size_t(c.sizeof(buffer)))
        arguments = (*allocations, c.c_int(CHANNELS), c.c_int(HIDDEN))
        pointers = (c.c_void_p * len(arguments))(*(c.addressof(value) for value in arguments))
        call("cuLaunchKernel", kernel, BLOCKS, tokens, 1, 128, 1, 1, 0, c.c_void_p(), pointers, c.c_void_p())
        call("cuCtxSynchronize")
        call("cuMemcpyDtoH_v2", c.byref(result), allocations[-1], c.c_size_t(c.sizeof(result)))
        return list(result), sum(c.sizeof(buffer) for buffer in buffers)
    finally:
        for pointer in reversed(allocations):
            call("cuMemFree_v2", pointer)
        if module:
            call("cuModuleUnload", module)
        call("cuCtxSetCurrent", c.c_void_p())
        call("cuDevicePrimaryCtxRelease_v2", device)


def packed_bytes(activations, dense, dropped):
    input_groups = active_groups(activations, HIDDEN)
    mask = bytes(block not in dropped for block in range(BLOCKS))
    down = sum(live and any(any(dense[start + block*WIDTH:start + (block+1)*WIDTH])
                            for start in range(0, len(dense), CHANNELS))
               for block, live in enumerate(mask))
    return 64 * (2 * input_groups * sum(mask) + (HIDDEN // WIDTH) * down)


def measure(function, binary, files, norms, prior, savings, native_weight_bytes, sign_bytes):
    tokens = len(prior["tokens"])
    activations = array("b", integers(files["activation"], 8, tokens * HIDDEN))
    gate, up, down = (weight_bytes(files[name]) for name in ("gate", "up", "down"))
    shift = integers(files["shifts"], 8, tokens * 3)
    exact_gate = dot(function, activations, gate, tokens, CHANNELS, HIDDEN)
    exact_up = dot(function, activations, up, tokens, CHANNELS, HIDDEN)
    keep = integers(files["keep"], 8, tokens * CHANNELS)
    intermediate = integers(files["intermediate"], 8, tokens * CHANNELS)
    expected = integers(files["expected"], 32, tokens * HIDDEN)
    dense = array("b")
    estimated = [0] * BLOCKS
    for token, row in enumerate(prior["tokens"]):
        norm = norms[token*HIDDEN:(token+1)*HIDDEN]
        count = sum(abs(value) > 768 for value in norm)
        assert count == row["outliers"]
        gsign, usign = [margins(norm, matrix) for matrix in (gate, up)]
        begin, end = token * CHANNELS, (token + 1) * CHANNELS
        for channel, (g, u) in enumerate(zip(gsign, usign, strict=True)):
            # Rank whole blocks by how many token-channel pairs the native
            # predictor already considers skippable.
            skip = count > 0 and g <= 0 and u == 0
            assert keep[begin + channel] == int(not skip)
            estimated[channel // WIDTH] += not skip
        gs, us, ds = shift[3*token:3*token+3]
        values = [requantize(requantize(silu_code(requantize(g, gs, 16)) * requantize(u, us, 16), 8, 16), ds, 8)
                  for g, u in zip(exact_gate[begin:end], exact_up[begin:end], strict=True)]
        assert values.count(0) == row["exact_zero_down_inputs"]
        assert [value if retain else 0 for value, retain in zip(values, keep[begin:end], strict=True)] == intermediate[begin:end]
        dense.extend(values)
    assert dot(function, array("b", intermediate), down, tokens, HIDDEN, CHANNELS) == expected

    exact = dot(function, dense, down, tokens, HIDDEN, CHANNELS)
    norms_squared = [sum(value * value for value in exact[start:start+HIDDEN]) for start in range(0, len(exact), HIDDEN)]
    squares, device_bytes = cuda_squares(binary, dense, down, tokens)
    for block in (0, 1, BLOCKS // 2, BLOCKS - 1):
        start = block * WIDTH
        for token in range(tokens):
            vector = array("b", [0]) * CHANNELS
            vector[start:start + WIDTH] = dense[token*CHANNELS+start:token*CHANNELS+start+WIDTH]
            assert squares[token*BLOCKS+block] == sum(value**2 for value in dot(function, vector, down, 1, HIDDEN, CHANNELS))
    assert all(value > 0 for value in norms_squared)
    contribution = [sum(squares[token*BLOCKS+block] / norms_squared[token] for token in range(tokens)) for block in range(BLOCKS)]
    dense_bytes = packed_bytes(activations, dense, set())
    assert dense_bytes == native_weight_bytes
    block_bytes = 3 * HIDDEN * WIDTH
    assert dense_bytes == BLOCKS * block_bytes
    baseline = dot(function, array("b", (value if not retain else 0 for value, retain in zip(dense, keep, strict=True))),
                   down, tokens, HIDDEN, CHANNELS)

    def relative_error(output):
        return sum(sqrt(sum(value**2 for value in output[start:start+HIDDEN]) / denom)
                   for start, denom in zip(range(0, len(output), HIDDEN), norms_squared, strict=True)) / tokens

    profiles = {}
    budget = 100 * block_bytes
    target_blocks = (savings * dense_bytes + 100 * sign_bytes + budget - 1) // budget
    assert target_blocks <= BLOCKS
    scenarios = [(str(percent), (percent * BLOCKS + 99) // 100) for percent in (10, 25, savings)]
    scenarios.append((f"{savings}_net", target_blocks))
    for label, count in scenarios:
        choices = {}
        for name, scores in (("native_sign_rank", estimated), ("exact_contribution_rank", contribution)):
            dropped = set(sorted(range(BLOCKS), key=scores.__getitem__)[:count])
            removed = array("b", (value if i % CHANNELS // WIDTH in dropped else 0 for i, value in enumerate(dense)))
            delta = dot(function, removed, down, tokens, HIDDEN, CHANNELS)
            transferred = packed_bytes(activations, dense, dropped)
            choices[name] = dict(saved_weight_bytes=dense_bytes-transferred, ordered_blocks_removed=count,
                                 output_relative_error=relative_error(delta),
                                 reduction_percent_at_native_sign_cost=100 * (dense_bytes-transferred-sign_bytes) / dense_bytes)
        profiles[label] = choices
    assert all(item["reduction_percent_at_native_sign_cost"] >= savings
               for item in profiles[f"{savings}_net"].values())
    return dict(tokens=tokens, dense_weight_bytes=dense_bytes, native_sign_bytes=sign_bytes,
                cuda_buffer_bytes=device_bytes,
                native_mask_relative_error=relative_error(baseline), profiles=profiles)


def run(binary):
    assert __debug__ and Path("/.dockerenv").is_file()
    source = json.loads(REPLAY.read_text())
    evidence = {str(path): sha(path) for path in (REPLAY, TARGETS, Path(__file__).relative_to(Path.cwd()), binary,
                                                Path("syn/tri_oracle_block_contribution.cu"))}

    def bind(path):
        digest = source["evidence_sha256"][str(path)]
        assert sha(path) == digest, path
        evidence[str(path)] = digest
        return path

    names = ("gate", "up", "down", "keep", "shifts")
    old = {name: bind(Path(f".cache/model_reference/batch389/{name}.hex")) for name in names}
    old.update({name: bind(Path(f".cache/model_reference/batch403/{name}.hex")) for name in ("expected", "activation")})
    old["intermediate"] = bind(Path(".cache/model_reference/batch407/intermediate.hex"))
    norm0 = integers(bind(Path(".cache/model_reference/batch403/norm.hex")), 16, 16 * HIDDEN)
    packet, = (bind(Path(path)) for path in source["evidence_sha256"] if path.endswith("/layer10_normalization/norm_expected.hex"))
    parent = packet.parent.with_name("layer10_mapped_feedforward") / "fixture"
    new = {name: bind(parent / (name + ".hex")) for name in (*names, "intermediate")}
    new.update({name: bind(packet.parent / (name + ".hex")) for name in ("activation", "expected")})
    norm10 = []
    for word in packet.read_text().splitlines():
        value = int(word, 16)
        for lane in range(8):
            code = (value >> (72 + 16*lane)) & 65535
            norm10.append(code - 65536 if code >= 32768 else code)
    assert len(norm10) == len(source["layer_ten"]["tokens"]) * HIDDEN
    c_source = bind(Path("syn/tri_oracle_fixture_dot.c"))
    bind(Path("syn/audit_tri_oracle_predictor_parity.py"))
    bind(Path("syn/tri_oracle_model_reference.py"))
    native_paths = (Path("records/tri_oracle_concurrent_mapped_feedforward_replay.json"),
                    Path("records/tri_oracle_layer10_mapped_feedforward.json"))
    native_zero, native_ten = (json.loads(path.read_text()) for path in native_paths)
    evidence.update({str(path): sha(path) for path in native_paths})
    assert native_zero["xcelium_exit_status"] == 0
    assert native_zero["candidate_sha256"] == native_ten["candidate_sha256"]
    assert native_zero["traffic"]["exact_outputs"] == source["layer_zero"]["baseline_outputs_reproduced"]
    assert native_ten["exact_feedforward_outputs"] == source["layer_ten"]["baseline_outputs_reproduced"]
    traffic_zero, traffic_ten = native_zero["traffic"], native_ten["memory_traffic"]
    reduction = json.loads(TARGETS.read_text())["disclosed_method_gains"]["feed_forward_external_memory_access_reduction_percent"]
    with TemporaryDirectory(dir=".cache", prefix="packed_prediction_") as directory:
        library = Path(directory).resolve() / "dot.so"
        subprocess.run(["gcc", "-O3", "-Wall", "-Wextra", "-Werror", "-fopenmp", "-shared", "-fPIC",
                        str(c_source), "-o", str(library)], check=True)
        function = c.CDLL(str(library)).tri_oracle_fixture_dot
        function.argtypes = (c.POINTER(c.c_int8), c.POINTER(c.c_int8), c.POINTER(c.c_int32), c.c_int, c.c_int, c.c_int)
        function.restype = None
        layer_zero = measure(function, binary, old, norm0, source["layer_zero"], reduction,
                             traffic_zero["weight_bytes"], traffic_zero["sign_bytes"])
        layer_ten = measure(function, binary, new, norm10, source["layer_ten"], reduction,
                            traffic_ten["packed_weight_bytes"], traffic_ten["added_sign_bytes"])
    assert all(sha(path) == digest for path, digest in evidence.items())
    return dict(state="packed_block_predictor_ranking_compared_on_mapped_fixtures", layer_zero=layer_zero, layer_ten=layer_ten,
                candidate_sha256=native_zero["candidate_sha256"],
                paper_external_memory_reduction_percent=reduction, evidence_sha256=evidence,
                scope="Two mapped fixtures, scored with uniform integer down weights and current packed transfers. "
                      "Exact contributions are a diagnostic heuristic. Net savings charge the observed sign bytes. "
                      "The new masks were evaluated in software and answer accuracy was not measured.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cuda_binary", type=Path)
    print(json.dumps(run(parser.parse_args().cuda_binary), indent=2, sort_keys=True))

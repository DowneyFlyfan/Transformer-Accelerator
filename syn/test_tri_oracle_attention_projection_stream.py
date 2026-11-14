"""Replay all trained grouped attention rows through the projection word stream."""

import argparse
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from run_tri_oracle_batch396_masks import GIB, check_memory
from test_tri_oracle_attention_projection_scale import ROOT, trained_vectors, sha
from tri_oracle_process_guard import terminate_process_group


MODULE = "tri_oracle_attention_projection_stream"
STORE = "tri_oracle_projection_activation_store"
SRAM = (ROOT / ".cache/physical/sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a"
        / "VERILOG/ts5n28hpcpsvta512x64m4f_130a_tt1v25c.v")


def run(source, log, cell_model, mutate, storage=False, shared_bank=False):
    assert Path("/.dockerenv").is_file()
    check_memory(8 * GIB)
    vectors, pins = trained_vectors()
    assert len(vectors) == 64 * 64
    top = f"{STORE if storage else MODULE}_tb"
    bench = ROOT / "verilog" / f"{top}.sv"
    scaler = ROOT / "verilog/tri_oracle_attention_projection_scale.sv"
    dependencies = [cell_model] if cell_model else [scaler]
    if storage:
        dependencies.append(SRAM)
        if cell_model is None:
            dependencies.append(ROOT / "verilog" / f"{MODULE}.sv")
            if shared_bank:
                dependencies.append(ROOT / "verilog" / f"{STORE}.sv")
    pins.update({path: sha(path) for path in (source, bench, *dependencies, Path(__file__).resolve())})
    operands, outputs = [], []
    for start in range(0, len(vectors), 64):
        row = [int(word, 16) for word in vectors[start:start + 64]]
        shift = (row[0] >> 8) & 31
        assert all(((value >> 8) & 31) == shift for value in row)
        payload = sum((value >> 13) << (32 * lane) for lane, value in enumerate(row))
        result = sum((value & 255) << (8 * lane) for lane, value in enumerate(row))
        operands.append(f"{(shift << 2048) | payload:0514x}")
        outputs.append(f"{result:0128x}")
    if mutate:
        outputs[63] = f"{int(outputs[63], 16) ^ 1:0128x}"
    with TemporaryDirectory(prefix="projection_stream_xcelium_", dir=ROOT / ".cache") as temporary:
        directory = Path(temporary)
        input_file, output_file = directory / "operands.hex", directory / "expected.hex"
        input_file.write_text("\n".join(operands) + "\n")
        output_file.write_text("\n".join(outputs) + "\n")
        native_log = directory / "xrun.log"
        command = ["/usr/bin/prlimit", "--as=4294967296", "--", "/opt/cadence/bin/xrun", "-64bit",
                   "-sv", "-top", top, "-l", str(native_log), "-history_file", str(directory / "xrun.history")]
        if storage:
            command.append("+define+UNIT_DELAY")
        if shared_bank:
            command.extend(["-defparam", f"{top}.SHARED_BANK=1"])
        if storage or cell_model:
            command.extend(["-nospecify", "-notimingchecks"])
        command.extend([*map(str, (*dependencies, source, bench)),
                        f"+OPERANDS={input_file}", f"+EXPECTED={output_file}"])
        with log.open("x") as stream:
            child = subprocess.Popen(command, cwd=directory, stdout=stream, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                status = child.wait(timeout=60)
            finally:
                terminate_process_group(child, log_argument=str(native_log))
    assert all(sha(path) == digest for path, digest in pins.items())
    text = log.read_text()
    for line in text.splitlines():
        if line.startswith(("PROJECTION_STREAM_", "ACTIVATION_STORE_")) or re.search(r"\*[EF],", line):
            print(line, flush=True)
    if mutate:
        mismatch = "ACTIVATION_STORE_HELD_RESPONSE first=496 beat=8" if storage else (
            "PROJECTION_STREAM_MISMATCH row=63 word=0 ready=1")
        assert status and mismatch in text
        assert not re.search(r"(?m)^(?:PROJECTION_STREAM|ACTIVATION_STORE)_PASS", text)
        return 0
    if status == 0:
        marker = (r"ACTIVATION_STORE_PASS rows=64 beats=516 errors=3 stalls=\d+"
                  if storage else r"PROJECTION_STREAM_PASS rows=64 words=512 stalls=768 resets=1")
        assert len(re.findall(rf"(?m)^{marker}$", text)) == 1
        if shared_bank:
            assert text.splitlines().count("ACTIVATION_STORE_SHARED_BANK_PASS") == 1
        assert not re.search(r"\*[EF],", text)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--cell-model", type=Path)
    parser.add_argument("--storage", action="store_true")
    parser.add_argument("--shared-bank", action="store_true")
    parser.add_argument("--mutate", action="store_true")
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    module = STORE if args.storage else MODULE
    if args.shared_bank:
        module = "tri_oracle_projection_shared_bank"
    source = args.source or ROOT / "verilog" / f"{module}.sv"
    raise SystemExit(run(source.resolve(), args.log.resolve(),
                         args.cell_model.resolve() if args.cell_model else None, args.mutate,
                         args.storage or args.shared_bank, args.shared_bank))

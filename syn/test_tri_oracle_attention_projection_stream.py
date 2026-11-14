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
TOP = f"{MODULE}_tb"


def run(source, log, cell_model, mutate):
    assert Path("/.dockerenv").is_file()
    check_memory(8 * GIB)
    vectors, pins = trained_vectors()
    assert len(vectors) == 64 * 64
    bench = ROOT / "verilog" / f"{TOP}.sv"
    scaler = ROOT / "verilog/tri_oracle_attention_projection_scale.sv"
    dependencies = [cell_model] if cell_model else [scaler]
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
                   "-sv", "-top", TOP, "-l", str(native_log), "-history_file", str(directory / "xrun.history")]
        if cell_model:
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
        if line.startswith("PROJECTION_STREAM_") or re.search(r"\*[EF],", line):
            print(line, flush=True)
    if mutate:
        assert status and "PROJECTION_STREAM_MISMATCH row=63 word=0 ready=1" in text
        assert "PROJECTION_STREAM_PASS" not in text
        return 0
    if status == 0:
        assert text.splitlines().count("PROJECTION_STREAM_PASS rows=64 words=512 stalls=768 resets=1") == 1
        assert not re.search(r"\*[EF],", text)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "verilog" / f"{MODULE}.sv")
    parser.add_argument("--cell-model", type=Path)
    parser.add_argument("--mutate", action="store_true")
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.source.resolve(), args.log.resolve(),
                         args.cell_model.resolve() if args.cell_model else None, args.mutate))

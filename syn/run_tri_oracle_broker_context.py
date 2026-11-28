"""Run the trained and boundary broker-to-context testbench inside cadence-ddi."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_broker_context_spool_tb"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True, help="New run directory under .cache")
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    run = args.work.resolve()
    fixture = args.fixture.resolve(strict=True)
    if run.exists() or not run.is_relative_to(ROOT / ".cache"):
        raise SystemExit("Use a new run directory under the project cache")
    reference = json.loads((fixture / "reference.json").read_text())
    for name, expected in reference["artifact_sha256"].items():
        assert hashlib.sha256((fixture / name).read_bytes()).hexdigest() == expected, name

    # Share the existing 20-core hierarchy, six memory models and compiler defines.
    # Stop before the all-query frame adds its own stimulus and top-level instance.
    source_list = ROOT / "verilog/live_native_all_query_attention_frame/shared_sources.sv"
    lines = source_list.read_text().splitlines()
    last = lines.index('`include "verilog/tri_oracle_attention_projection_scale_quotient_first.sv"')
    lines = lines[:last+1]
    for name in ("tri_oracle_context_spool.sv", "tri_oracle_broker_context_spool.sv", "broker_context_spool_tb.sv"):
        lines.append(f'`include "verilog/attention_post/{name}"')
    bundle = "\n".join(lines) + "\n"
    names = re.findall(r'^`include "([^"]+)"$', bundle, re.M)
    files = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    assert "verilog/tri_oracle_complete_head_broker.sv" in files
    run.mkdir(parents=True)
    scratch = run / "scratch"
    scratch.mkdir()
    (run / "sources.sv").write_text(bundle)
    env = os.environ.copy()
    for key in ("TMPDIR", "TMP", "TEMP", "CDS_TMP_DIR", "XDG_CACHE_HOME"):
        env[key] = str(scratch)
    argv = ["/opt/cadence/bin/xrun", "-64bit", "-sv", "-notimingchecks", "-xmerror", "RECOME",
            "-incdir", str(ROOT), "-top", TOP, str(run/"sources.sv"), f"+TRAINED={fixture}"]
    (run/"command.json").write_text(json.dumps(dict(argv=argv, sources=files, fixture_sha256=reference["artifact_sha256"]), indent=2)+"\n")
    start = time.monotonic()
    with (run / "console.log").open("x") as log:
        result = subprocess.run(argv, cwd=run, env=env, stdout=log, stderr=subprocess.STDOUT)
    (run / "result.json").write_text(json.dumps(dict(exit=result.returncode, seconds=time.monotonic()-start))+"\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

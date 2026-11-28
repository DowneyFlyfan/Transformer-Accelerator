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


def verified_files(directory, expected):
    for name, digest in expected.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Fixture checksum mismatch for {directory / name}")
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True, help="New run directory under .cache")
    parser.add_argument("--fixture", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--late", type=Path, help="Additional 281-key trained query fixture")
    mode.add_argument("--qkv-fixture", type=Path, help="Two-slot trained projection and committed cache inputs")
    parser.add_argument("--sizes", type=Path, help="Retained token sizes for the committed cache test")
    args = parser.parse_args()
    if bool(args.qkv_fixture) != bool(args.sizes):
        parser.error("--qkv-fixture and --sizes must be used together")
    run = args.work.resolve()
    fixture = args.fixture.resolve(strict=True)
    if run.exists() or not run.is_relative_to(ROOT / ".cache"):
        raise SystemExit("Use a new run directory under the project cache")
    def verify_fixture(directory):
        reference = json.loads((directory / "reference.json").read_text())
        return verified_files(directory, reference["artifact_sha256"])

    fixture_digests = verify_fixture(fixture)
    late = args.late.resolve(strict=True) if args.late else None
    late_digests = verify_fixture(late) if late else None
    top = TOP
    extra_sources = []
    extra_args = []
    cache_inputs = {}
    if args.qkv_fixture:
        qkv = args.qkv_fixture.resolve(strict=True)
        sizes = args.sizes.resolve(strict=True)
        manifest = qkv / "fixture.json"
        projection = json.loads(manifest.read_bytes())
        required = {"raw32.hex", "expected.hex", "cos.hex", "sin.hex", "config.hex"}
        if (projection["schema"] != "trained_two_slot_qkv_cache_fixture_v1"
                or set(projection["artifact_records"]) != required):
            raise ValueError(f"Invalid two-slot fixture at {manifest}")
        projection_digests = {name: row["sha256"] for name, row in projection["artifact_records"].items()}
        size_reference = json.loads((sizes.parent / "reference.json").read_bytes())
        size_digest = size_reference["artifact_sha256"][sizes.name]
        verified_files(sizes.parent, {sizes.name: size_digest})
        cache_inputs = dict(qkv_sha256=verified_files(qkv, projection_digests),
                            qkv_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                            sizes_sha256=size_digest)
        extra_sources = ["tri_oracle_committed_qkv_cache_v1.sv", "tri_oracle_attention_post_qkv_path_v1.sv",
                         "tri_oracle_broker_qkv_reader.sv", "qkv_cache_path_tb.sv", "trained_cache_broker_peer.sv"]
        extra_args = [f"+QKV_FIXTURE_DIR={qkv}", f"+SIZES={sizes}"]
        top = "tri_oracle_joined_qkv_broker_tb"

    # Share the existing 20-core hierarchy, six memory models and compiler defines.
    # Stop before the all-query frame adds its own stimulus and top-level instance.
    source_list = ROOT / "verilog/live_native_all_query_attention_frame/shared_sources.sv"
    lines = source_list.read_text().splitlines()
    last = lines.index('`include "verilog/tri_oracle_attention_projection_scale_quotient_first.sv"')
    lines = lines[:last+1]
    for name in ("tri_oracle_context_spool.sv", "tri_oracle_broker_context_spool.sv", "broker_context_spool_tb.sv"):
        lines.append(f'`include "verilog/attention_post/{name}"')
    lines.extend(f'`include "verilog/attention_post/{name}"' for name in extra_sources)
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
            "-incdir", str(ROOT), "-top", top, str(run/"sources.sv"), f"+TRAINED={fixture}", *extra_args]
    command = dict(argv=argv, sources=files, fixture_sha256=fixture_digests, **cache_inputs)
    if late:
        argv.append(f"+LATE={late}")
        command["late_fixture_sha256"] = late_digests
    (run/"command.json").write_text(json.dumps(command, indent=2)+"\n")
    start = time.monotonic()
    with (run / "console.log").open("x") as log:
        result = subprocess.run(argv, cwd=run, env=env, stdout=log, stderr=subprocess.STDOUT)
    if args.qkv_fixture:
        required_markers = ["COMMITTED_BROKER_READS_PASS Q=32 K=64 V=64 cache_reads=160 size_reads=64",
                            "JOINED_QKV_BROKER_SPOOL_PASS checked_codes=2048 raw_lanes=2048"]
    elif late:
        required_markers = ["BROKER_CONTEXT_SPOOL_PASS cases=5 trained_rows=2 alias_rows=2 rejected=1 late_rows=1"]
    else:
        required_markers = ["BROKER_CONTEXT_SPOOL_PASS cases=4 trained_rows=1 alias_rows=2 rejected=1"]
    # External process diagnostics may interleave with stdout mid-transaction.
    transcript = run / "xrun.log"
    log_lines = set(transcript.read_text().splitlines()) if transcript.is_file() else set()
    missing = [marker for marker in required_markers if marker not in log_lines]
    status = dict(exit=result.returncode, seconds=time.monotonic()-start, missing_markers=missing)
    (run / "result.json").write_text(json.dumps(status)+"\n")
    return result.returncode or int(bool(missing))


if __name__ == "__main__":
    raise SystemExit(main())

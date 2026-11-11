"""Check every head's softmax destination in the elaborated twenty-core fabric."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile

from prepare_tri_oracle_wac_softmax_layer import ROOT, RTL, edit, read, sha, verify

TOP = "tri_oracle_wac_softmax_routes_tb"
MARKER = "WAC_ROUTES_PASS heads=32 probabilities=528 invalid_destinations=12"
TRANSFER = re.compile(
    rf"WAC_ROUTE_TRANSFER {TOP}\.fabric\.clusters\[([0-4])\]\.unit\.selected_bank([0-4])\.block_instance"
    r"\.source_cluster\.implementation\.cores\[([0-3])\]\.compute\.simd\.route_witness length=(\d+)"
)


def destinations(log):
    observed = {}
    for line in log.splitlines():
        if not line.startswith("WAC_ROUTE_TRANSFER "):
            continue
        match = TRANSFER.fullmatch(line)
        assert match, line
        cluster, selected, core, length = map(int, match.groups())
        head = length - 1
        assert cluster == selected and head not in observed
        observed[head] = (cluster, core)
    assert set(observed) == set(range(32))
    return observed


def run(case, wrong_owner, log_path):
    prepared = read(case / "receipt.json")
    assert prepared["softmax"] == "head_owned_core_input_memory" and prepared["memory_models"] == "vendor"
    inputs = prepared["input_sha256"].copy()
    verify(inputs)
    bench = RTL / f"{TOP}.sv"
    bundle = Path(prepared["bundle"])
    assert bundle == case / "bundle.sv" and str(bundle) in inputs
    inputs[str(bench)] = sha(bench)
    available = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines()
                     if line.startswith("MemAvailable:"))
    assert available >= 16 * 2**30, "Need memory headroom to elaborate the complete fabric"
    with tempfile.TemporaryDirectory(dir=ROOT / ".cache", prefix="wac_softmax_routes_") as directory:
        work = Path(directory)
        if wrong_owner:
            original = case / "tri_oracle_sram_compute_cluster.sv"
            changed = work / original.name
            changed.write_text(edit(original.read_text(), "softmax_request.owner[1:0]",
                                    "(softmax_request.owner[1:0] ^ 2'b01)", 2))
            temporary_bundle = work / "bundle.sv"
            temporary_bundle.write_text(edit(bundle.read_text(), str(original), str(changed)))
            bundle = temporary_bundle
        result = subprocess.run([
            "/usr/bin/prlimit", "--as=1342177280", "--", "/opt/cadence/bin/xrun", "-64bit", "-sv", "-nospecify",
            "-notimingchecks", "-sequdp_nba_delay", "-xmerror", "RECOME", "-top", TOP, str(bundle), str(bench),
        ], cwd=work, capture_output=True, text=True, timeout=180)
    log = result.stdout + result.stderr
    if log_path is not None:
        with log_path.open("x") as stream:
            stream.write(log)
    assert result.returncode == 0 and not re.search(r"\*[EF],", log), log[-4500:]
    assert log.splitlines().count(MARKER) == 1
    observed = destinations(log)
    expected = {head: divmod(head % 20, 4) for head in range(32)}
    if wrong_owner:
        assert all(observed[head] == (cluster, core ^ 1) for head, (cluster, core) in expected.items()), observed
        print("WAC_ROUTES_WRONG_OWNER_REJECTED mismatches=32")
    else:
        assert observed == expected, (observed, expected)
        assert len(set(observed.values())) == 20
        print(MARKER, "physical_cores=20")
    verify(inputs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--wrong-owner", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    run(args.case.resolve(), args.wrong_owner, args.log)

"""Check all trained learned-normalization codes with the existing Xcelium RTL."""

import gzip
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_process_guard import terminate_process_group


ROOT = Path(__file__).resolve().parents[1]
TOP = "tri_oracle_batched403_activation_tb"


def main():
    audit_path = ROOT / "records/batch403_activation_precision.json"
    audit = json.loads(audit_path.read_text())
    residual_path = ROOT / "records/batch396_mask_fixture.json"
    residual = json.loads(residual_path.read_text())
    assert audit["state"] == "trained_fixed_normalization_and_output_effect_characterized"
    assert audit["source_sha256"][str(residual_path)] == sha256(residual_path)
    assert audit["scalar_and_cuda_activations_equal"] and audit["epsilon_q16"] == 43980465
    sources = [ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_rmsnorm", "tri_oracle_affine_quantizer", "tri_oracle_rms_activation", TOP,
    )]
    raw = str(Path(residual["fixture"]) / "raw.hex")
    hashes = audit["files_sha256"] | {raw: residual["files_sha256"][raw]} | {
        str(path): sha256(path) for path in (audit_path, residual_path, Path(__file__), *sources,
            ROOT / "syn/run_tri_oracle_batch396_masks.py", ROOT / "syn/tri_oracle_process_guard.py")
    }
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    check_memory(12 * GIB)
    log = ROOT / ".cache/batch403_native_activation.log"
    output = ROOT / "records/batch403_native_activation.json"
    archive = ROOT / "records/batch403_native_activation.log.gz"
    assert not any(path.exists() for path in (log, output, archive))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="batch403_activation_", dir=ROOT / ".cache") as folder:
        work = Path(folder)
        command = [
            "taskset", "-c", "9", "/opt/cadence/bin/xrun", "-64bit", "-sv", "-top", TOP,
            "-xmlibdirname", str(work / "xcelium.d"), "-l", str(work / "native.log"),
            "-history_file", str(work / "history"), *map(str, sources),
            f"+INPUT={residual['fixture']}", f"+EXPECTED={audit['fixture']}",
        ]
        with log.open("x") as stream:
            child = subprocess.Popen(command, cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                child.wait(timeout=90)
            finally:
                terminate_process_group(child)
    content = log.read_text()
    assert child.returncode == 0, content
    marker = "BATCH403_NATIVE_PASS tokens=16 activation_codes=32768 norm_codes=32768 outliers=159"
    assert content.splitlines().count(marker) == 1
    assert not re.search(r"\*(?:E|F),|\*ERROR|Simulation terminated via \$fatal", content)
    assert all(sha256(Path(path)) == digest for path, digest in hashes.items())
    archive.write_bytes(gzip.compress(log.read_bytes(), mtime=0))
    assert gzip.decompress(archive.read_bytes()) == log.read_bytes()
    report = {
        "state": "trained_native_learned_activation_matches_fixed_point_reference",
        "scope": __doc__,
        "native_exit_status": child.returncode,
        "native_process_group": child.pid,
        "elapsed_seconds": time.monotonic() - started,
        "tokens": 16,
        "exact_activation_codes": 32768,
        "exact_normalized_codes": 32768,
        "outliers": 159,
        "source_sha256": hashes,
        "log_sha256": sha256(log),
        "log_archive_sha256": sha256(archive),
        "temporary_build_removed": not work.exists(),
        "joined_compute_frame_verified": False,
        "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(marker)


if __name__ == "__main__":
    main()

"""Retry the trained replay after its host-memory guard stopped it."""

import argparse
from pathlib import Path
import re
import shutil
import time

from replay_tri_oracle_parallel_chip import pin, read, replay_trained, verify
from run_tri_oracle_parallel_chip_synthesis import proc_identity


def run(trial, elaboration_worker):
    import replay_fully_mapped_layer as native

    original = trial / "full_native"
    canonical = original / "trained_receipt.json"
    assert not canonical.exists()
    attention = original / "attention_receipt.json"
    proved = read(attention)
    assert proved["state"] == "parallel_chip_preserved_archived_attention"
    assert proved["native"]["native_exit_status"] == 0
    assert proved["counters"]["rows"] == 4
    pins = proved["input_sha256"].copy()
    verify(pins)
    failure = trial / "full_native.log"
    console = original / "trained/console.log"
    stopped, = re.findall(r"(?m)^SHARED_MAPPED_ATTENTION_STARTED trained (\d+)$", failure.read_text())
    assert proc_identity(int(stopped)) is None
    assert "assert available >= reserve_gib * GIB" in failure.read_text()
    assert "Simulation received SIGTERM" in console.read_text()
    assert not (original / "trained/xcelium.d").is_dir()
    pin(pins, attention, failure, console, Path(__file__).resolve())

    # The prior concurrent runs crossed the guard together. Let the admitted
    # Genus interface check release its memory before retrying simulation.
    started = proc_identity(elaboration_worker)
    if started:
        argv = Path(f"/proc/{elaboration_worker}/cmdline").read_bytes().split(b"\0")
        assert any(item.endswith(b"/retry_genus_elaboration.py") for item in argv)
        deadline = time.monotonic() + 5 * 3600
        print("Waiting for Genus interface elaboration to release memory", elaboration_worker, flush=True)
        while proc_identity(elaboration_worker) == started:
            assert time.monotonic() < deadline
            time.sleep(5)

    output = trial / "full_native_retry"
    output.mkdir()
    native.OUTPUT = output

    def guarded_stage(name, command, start_gib, reserve_gib, address_gib, wall):
        return native.stage(name, command, max(start_gib, 18), reserve_gib, address_gib, wall)

    try:
        replay_trained(trial, output, pins, guarded_stage)
        receipt = output / "trained_receipt.json"
        result = read(receipt)
        assert result["state"] == "parallel_chip_replayed_exact_trained_frame_from_both_packed_images"
        assert result["native"]["native_exit_status"] == 0 and result["counters"]["exact_outputs"] == 32768
        verify(result["input_sha256"])
        canonical.hardlink_to(receipt)
        print("Published verified dual-lane trained replay", canonical, flush=True)
    finally:
        snapshot = output / "trained/xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=lambda value: Path(value).resolve())
    parser.add_argument("elaboration_worker", type=int)
    args = parser.parse_args()
    run(args.candidate, args.elaboration_worker)

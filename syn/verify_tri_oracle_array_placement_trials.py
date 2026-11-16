"""Check both native compute-array placement trials against their inputs."""

from collections import Counter
import json
from pathlib import Path
import re

from verify_tri_oracle_gated_array_placement import (
    ARRAY,
    LEF,
    ROOT,
    WORK,
    components,
    digest,
    dimensions,
    gates_script,
    geometry,
    read,
    sorted_entries,
)

ORIGINAL = Path("records/tri_oracle_gated_array_placement.json")
BUFFERED = Path("records/tri_oracle_array_control_buffers.json")


def check_digests(receipt, inputs):
    expected = read(receipt)["evidence_sha256"]
    for path in inputs:
        assert digest(path) == expected[str(path)], path


def pin_and_blockage_identity(layout):
    return {
        k: sorted_entries(data, k, count)
        for k, (count, data) in geometry(layout).items()
    }


def early_congestion(log):
    horizontal, vertical = re.search(
        r"Overflow after Early Global Route ([0-9.]+)% H \+ ([0-9.]+)% V", log
    ).groups()
    length = re.search(r"Total length: (\d+)um, number of vias:", log)[1]
    return {
        "horizontal_overflow_percent": float(horizontal),
        "vertical_overflow_percent": float(vertical),
        "estimated_wire_length_um": int(length),
    }


def verify_trial(folder, prior_layout, prior_netlist, prior_sdc, count):
    candidate = WORK / folder
    log = (candidate / "console.log").read_text()
    assert re.search(
        rf"(?m)^TRI_ORACLE_GATED_ARRAY_PLACED {count} [0-9]+\.[0-9]+$", log
    )
    assert re.search(r"(?m)^TRI_ORACLE_MAPPED_ARRAY_TIMING_FINISHED$", log)
    assert re.search(r"Message Summary:\s+\d+ warning\(s\), 0 error\(s\)", log)
    assert (candidate / "place.tcl").read_text() == gates_script().replace(
        "$count != 53622", f"$count != {count}"
    )
    for name, expected in (("netlist.v", prior_netlist), ("emitted.sdc", prior_sdc)):
        assert (candidate / name).resolve(strict=True) == expected.resolve(strict=True)
    saved = dict(components(candidate / "placed.def"))
    requested = dict(components(candidate / "seed.def"))
    assert saved == requested and len(saved) == count
    assert pin_and_blockage_identity(
        (candidate / "placed.def").read_text()
    ) == pin_and_blockage_identity(prior_layout.read_text())
    prior = dict(components(prior_layout))
    assert {name: pose[0] for name, pose in prior.items()} == {
        name: pose[0] for name, pose in saved.items()
    }
    reports = [
        candidate / f"native_{name}.rpt"
        for name in ("setup", "hold", "gate_setup", "gate_hold")
    ]
    timing = {
        p.stem.removeprefix("native_"): min(
            map(float, re.findall(r"Slack:=\s+(-?\d+\.\d+)", p.read_text()))
        )
        for p in reports
    }
    files = ["seed.def", "placed.def", "place.tcl", "console.log", "placement.rpt"]
    artefacts = [
        prior_layout,
        prior_netlist,
        prior_sdc,
        *reports,
        *(candidate / name for name in files),
    ]
    return saved, prior, timing, artefacts


def verify():
    original, buffered = WORK, WORK / "control_buffers"
    for record, parent in ((ORIGINAL, original), (BUFFERED, buffered)):
        check_digests(
            record,
            [
                parent / "placed.def",
                parent / "console.log",
                *(
                    parent / f"native_{name}.rpt"
                    for name in ("setup", "hold", "gate_setup", "gate_hold")
                ),
            ],
        )
    check_digests(ORIGINAL, [original / "attempt.def", original / "region.def", LEF])
    check_digests(ARRAY, [(original / "netlist.v").resolve().relative_to(Path.cwd())])
    check_digests(BUFFERED, [buffered / "netlist.v", buffered / "seed.def"])
    exact, _, local_timing, a = verify_trial(
        "local_seed",
        original / "placed.def",
        original / "netlist.v",
        original / "emitted.sdc",
        53622,
    )
    swap, base, swap_timing, b = verify_trial(
        "gpu_swaps",
        buffered / "placed.def",
        buffered / "netlist.v",
        buffered / "emitted.sdc",
        53797,
    )
    sizes = dimensions([LEF], 2000)

    def slots(layout):
        return Counter(
            (sizes[entry[0]], entry[2], entry[3], entry[4]) for entry in layout.values()
        )

    assert slots(swap) == slots(base)
    trial_a = original / "local_seed/seed.json"
    trial_b = original / "gpu_swaps/assignment.json"
    local, gpu = read(trial_a), read(trial_b)
    assert local["seed_sha256"] == digest(original / "local_seed/seed.def")
    assert gpu["seed_sha256"] == digest(original / "gpu_swaps/seed.def")
    assert gpu["input_seed_sha256"] == digest(buffered / "seed.def")
    local_poses = dict(components(original / "attempt.def"))
    assert local_poses.keys() == exact.keys()
    preserved = sum(pose[2:5] == local_poses[name][2:5] for name, pose in exact.items())
    assert preserved >= local["exact"]
    assert (
        sum(pose[2:5] != base[name][2:5] for name, pose in swap.items())
        == gpu["moved_cells"]
    )
    local_base = read(ORIGINAL)["placed_preroute_timing_ps"]
    gpu_base = read(BUFFERED)["placement_timing_after_ps"]
    return dict(
        state="two_regional_compute_array_placement_trials_measured",
        original_location_trial=dict(
            preserved=preserved,
            slack_ns=local_timing,
            baseline_slack_ns={
                mode: slack / 1000 for mode, slack in local_base.items()
            },
        ),
        gpu_swap_trial=dict(
            slack_ns=swap_timing,
            baseline_slack_ns={mode: slack / 1000 for mode, slack in gpu_base.items()},
            baseline_early_congestion=early_congestion(
                (buffered / "console.log").read_text()
            ),
            early_congestion=early_congestion(
                (WORK / "gpu_swaps/console.log").read_text()
            ),
            **{
                key: gpu[key]
                for key in (
                    "edges",
                    "measured_critical_edges",
                    "moved_cells",
                    "graph_score_before",
                    "graph_score_after",
                    "peak_gpu_bytes",
                )
            },
        ),
        scope="Compute array placement with the same physical reservations and 580 MHz constraints. "
        "The source netlists are identical within each trial. Native timing uses early wire estimates.",
        evidence_sha256={
            str(path): digest(path)
            for path in [
                *a,
                *b,
                ORIGINAL,
                BUFFERED,
                ARRAY,
                LEF,
                original / "attempt.def",
                buffered / "console.log",
                trial_a,
                trial_b,
                Path("syn/prepare_tri_oracle_local_array_placement.py"),
                Path("syn/prepare_tri_oracle_gpu_array_placement.py"),
                Path(__file__).resolve().relative_to(Path.cwd()),
            ]
        },
    )


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(), indent=2, sort_keys=True))

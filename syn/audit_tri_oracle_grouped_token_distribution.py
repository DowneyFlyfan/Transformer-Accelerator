"""Check the old grouped-token bottleneck against current mapped leaf pins."""

from collections import Counter, defaultdict
import json
import mmap
from pathlib import Path
import re
import sys

from audit_tri_oracle_physical_io_budget import ROOT, PROBE_REDUCED as STAGE

MODEL = (
    ROOT / ".cache/model_reference/lossless_weight_burst_probe/streaming_probe"
    / "aligned/partial_retention/indexed_down/wide_values/fused_request/score_packet"
    / "partition/registered_load/token_merge_pipeline"
)
sys.path[:0] = [str(path) for path in (
    STAGE.parents[1], MODEL, MODEL.parents[1],
    ROOT / ".cache/physical/nonlinear_rounding_trial/joined_variant_verification",
    ROOT / ".cache/physical/wac_budgeted_parent_boundary",
)]

from verify_command_drive import (
    MappedFanout, TOP, bits, bounds, coordinates, input_pf, liberty_pins, output_pf, read, sha, walk,
)
from verify_linked_placed_topology import pin_fields

SIGNALS = (
    "grouped_active",
    *(f"grouped_count[{bit}]" for bit in range(10)),
    *(f"{name}[{cluster}]" for name in ("size_out_valid", "size_out_ready", "size_query_valid", "size_query_ready")
      for cluster in range(5)),
)


def mapped_top_pins(design, directions):
    with design.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        model = MappedFanout(data, directions)
        _, nets, children, _ = model.view(TOP)
        arbiter, raw = children["grouped_sizes"]
        connections = pin_fields(raw)
        assert (connections["size_count"], connections["native_size_count"]) == (
            "grouped_count", "grouped_size_out_count",
        )
        _, arbiter_nets, _, assignments = model.view(arbiter)
        forwarded = {
            (tuple(bits(left, arbiter_nets)), tuple(bits(right, arbiter_nets)))
            for left, right in assignments
            if left.startswith("size_count[")
        }
        assert len(forwarded) == 10 and forwarded == {
            (bits(f"size_count[{index}]", arbiter_nets), bits(f"native_size_count[{index}]", arbiter_nets))
            for index in range(10)
        }
        result = {}
        try:
            for signal in SIGNALS:
                bit, = bits(signal, nets)
                pins = set(walk(model, TOP, bit, ""))
                if signal.startswith("grouped_count["):
                    upstream, = bits(signal.replace("grouped_count", "grouped_size_out_count"), nets)
                    feed = set(walk(model, TOP, upstream, ""))
                    assert not (pins & feed), signal
                    pins.update(feed)
                drivers = [pin for pin in pins if directions[pin[1]][pin[2]] == "output"]
                loads = [pin for pin in pins if directions[pin[1]][pin[2]] == "input"]
                assert len(drivers) == 1 and loads and len(drivers) + len(loads) == len(pins), (signal, drivers)
                driver, = drivers
                result[signal] = driver, sorted(loads)
        finally:
            for helper in (model.view, model.aliases, model.census):
                helper.cache_clear()
    return result


def main():
    assert __debug__ and Path("/.dockerenv").is_file()
    out = {}
    evidence = {}

    def pin(path, expected=None):
        digest = sha(path)
        assert expected is None or digest == expected, path
        evidence[str(path.relative_to(ROOT))] = digest
        return path

    design = STAGE / "candidate.v"
    seed = STAGE.parent / "seed.def"
    record = read(pin(ROOT / "records/tri_oracle_current_mapped_architecture.json"))
    prior = read(pin(ROOT / "records/tri_oracle_placed_fanout.json"))
    libraries = read(pin(ROOT / "records/tri_oracle_residual_bank_grant_drive_screen.json"))
    pin(design, record["candidate_sha256"])
    pin(seed, record["placement_seed_sha256"])
    catalogs = {
        Path(name).name.split("140", 1)[1].removesuffix(".lib"): liberty_pins(pin(ROOT / name, digest))
        for name, digest in libraries["evidence_sha256"].items() if name.endswith(".lib")
    }
    assert len(catalogs) == 3
    directions = defaultdict(dict)
    for (master, terminal), properties in catalogs["ssg0p9v125c"].items():
        directions[master][terminal] = properties["direction"]

    nodes = mapped_top_pins(design, directions)
    locations = coordinates(seed, {
        name.removeprefix("/"): cell for driver, loads in nodes.values() for name, cell, _ in (driver, *loads)
    })
    old = {row["net"]: row for row in prior["worst"]}
    for signal, (driver, loads) in nodes.items():
        dx, dy = locations[driver[0].removeprefix("/")]
        measurement = {
            "driver": driver,
            "driver_origin_um": [dx, dy],
            "loads": len(loads),
            "load_masters": dict(Counter(f"{master}/{pin_name}" for _, master, pin_name in loads)),
            "max_origin_manhattan_span_um": round(max(
                abs(dx - locations[name.lstrip("/")][0]) + abs(dy - locations[name.lstrip("/")][1])
                for name, _, _ in loads
            ), 3),
            "pin_load_by_corner": {
                corner: bounds(driver, loads, catalog, None) for corner, catalog in catalogs.items()
            },
        }
        if signal in old:
            measurement["previous_design_loads"] = int(old[signal]["loads"])
        if signal.startswith("grouped_count["):
            clusters = Counter()
            for name, _, _ in loads:
                match = re.match(r"^/grouped_([0-4])/sizes/", name)
                assert match, name
                clusters[match[1]] += 1
            assert clusters == dict.fromkeys("01234", 1025), (signal, clusters)
            measurement["loads_by_cluster"] = dict(sorted(clusters.items()))
        out[signal] = measurement
    for fn in (MappedFanout.__init__, MappedFanout.matching_terminals, bits, pin_fields, walk,
               bounds, coordinates, liberty_pins, input_pf, output_pf, main):
        pin(Path(fn.__code__.co_filename))
    return dict(
        state="grouped_token_path_loads_measured_on_current_mapped_chip",
        candidate_sha256=record["candidate_sha256"],
        seed_sha256=record["placement_seed_sha256"],
        by_signal=out,
        evidence_sha256=evidence,
        scope=("Grouped token count and arbitration control. Exact mapped leaf pins and installed cell-library "
               "load limits. Distances are between origins in the placement seed. Wire load, slew and path "
               "timing still require native analysis."),
    )


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))

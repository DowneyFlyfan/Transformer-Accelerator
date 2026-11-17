"""Prepare the repaired-chip attention replay with a pinned reference projection cache."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import ROOT, WORK as PACKET, digest, include, replace_once
from verify_tri_oracle_booth_clock_boundary import PLACEMENT


BASE = ROOT / PACKET.parent
SCOPE = "repaired_chip_attention_rows_prepared_with_reference_projections"
PROMPT_ROW = "7'(shift), 11'd408, 11'(position), 5'(head)"
DECODE_ROW = "7'(shift), 11'(rank == Slots - 1 ? Slots : Slots - 1), 11'(position), 5'(head)"
CACHE_LOAD = """    for (int index = 0; index < Groups * Slots; index++) begin
      if ($isunknown(golden_projection[index])) $fatal(1, "REFERENCE_PROJECTION_CACHE_UNKNOWN");
      projected_cache[index] = golden_projection[index];
      committed[index] = 1;
    end
    $display("REFERENCE_PROJECTION_CACHE_LOADED vectors=%0d", Groups * Slots);
    $fflush();
"""


def read(path):
    return json.loads(path.read_text())


def pinned(path, proof):
    assert digest(path) == proof["evidence_sha256"][str(path.relative_to(ROOT))], path


def replace_block(text, start, stop, replacement):
    assert text.count(start) == text.count(stop) == 1, (start, stop)
    first = text.index(start)
    last = text.index(stop, first)
    return text[:first] + replacement + text[last:]


def render_bench(text):
    text = replace_block(text, "    for (int batch = 0; batch < ProjectionCommands; batch++) begin",
                         "    command(5, 32'h43010001", CACHE_LOAD)
    text = replace_block(text, '    $readmemh({fixture, "/activation.hex"}, activations);',
                         "    for (int index = 0; index < ImageTokens; index++) packed_map", "")
    # Head prediction observes the prompt. The final row can also see its own
    # key, which was emitted for the first decode token after the prompt.
    text = replace_once(text, PROMPT_ROW, DECODE_ROW)
    text = replace_once(text, "UNSEEDED_PACKET_ATTENTION_ROW_PASS", "REFERENCE_PROJECTION_ATTENTION_ROW_PASS")
    return replace_once(text, "UNSEEDED_PACKET_LAYER_PASS", "REFERENCE_PROJECTION_ATTENTION_PASS")


def render_runner(text):
    text = replace_once(text, "streaming_packet.lock", "reference_projection_attention.lock")
    text = replace_once(text, "trained_packet_attention_fixture_bound_to_corrected_full_chip", SCOPE)
    text = replace_once(text, "> 5400:", "> 21600:")
    return text.replace("BOOTH_STREAMING_PACKET_", "REFERENCE_PROJECTION_ATTENTION_")


def prepare(*, check):
    source = BASE / "unseeded_packet_layer"
    previous, schedule = source / "native/prepared_native.json", source / "prepared_schedule.json"
    setup, plan = read(previous), read(schedule)
    assert setup["schedule_receipt_sha256"] == digest(schedule)
    assert plan["attention_heads"] == 32 and plan["attention_rows"] == 128
    assert plan["projection_cache_vectors"] == 16360 and plan["streaming_heads"] == 0
    placement_path = ROOT / PLACEMENT
    logic_path = ROOT / "records/tri_oracle_corrected_booth_buffered_logic.json"
    gpu_path = ROOT / "records/tri_oracle_trained_attention_gpu_reference.json"
    placement, logic, gpu = (read(path) for path in (placement_path, logic_path, gpu_path))
    assert gpu["state"] == "physical_attention_fixture_recomputed_on_host_gpu"
    assert gpu["attended_rows"] == 128 and gpu["exact_signed32_values"] == 8192
    original_cold = BASE / "cold/cold.v"
    assert digest(original_cold) == setup["cold_netlist_sha256"] == logic["original_cold_netlist_sha256"]
    stage = ROOT / Path(placement["database"]).parents[1]
    cold = stage / "cold/cold.v"
    pinned(cold, placement)
    assert placement["evidence_sha256"][str(cold.relative_to(ROOT))] == logic["repaired_cold_netlist_sha256"]
    output = stage / "reference_projection_attention_key_count"
    bench, source_bundle = source / "layer_tb.sv", source / "bundle.sv"
    for path in (bench, source_bundle):
        pinned(path, setup)
    fixture = ROOT / plan["prepared_fixture"]
    stimuli = [fixture / name for name in ("expected.hex", "map.hex", "rows.txt", "signs.hex")]
    for path in stimuli:
        pinned(path, plan)
        if str(path.relative_to(ROOT)) in gpu["evidence_sha256"]:
            pinned(path, gpu)
    vectors = (fixture / "expected.hex").read_text().splitlines()
    assert len(vectors) == 16360 and all(re.fullmatch(r"[0-9a-f]{128}", line) for line in vectors)

    new_bench = output / "attention_tb.sv"
    bundle = replace_once(source_bundle.read_text(), include(original_cold), include(cold))
    bundle = replace_once(bundle, include(bench), include(new_bench))
    generated = {new_bench: render_bench(bench.read_text()), output / "bundle.sv": bundle,
                 output / "run.py": render_runner((stage / "streaming_packet/run.py").read_text())}
    if not check:
        output.mkdir()
        (output / "reference_projection_attention.lock").touch()
    for path, expected in generated.items():
        if check:
            assert path.read_text() == expected, path
        else:
            path.write_text(expected)
    inputs = [previous, schedule, placement_path, logic_path, gpu_path, bench, source_bundle, *generated, *stimuli]
    sources = set(map(Path, re.findall(r'(?m)^`include "([^"]+)"$', bundle)))
    assert {new_bench, cold} <= sources
    inputs.extend(sources)
    manifest = {
        "state": SCOPE, "cold_netlist_sha256": logic["repaired_cold_netlist_sha256"],
        "testbench_top": "tri_oracle_chip_packet_io_tb",
        "testbench_fixture": str(fixture.relative_to(ROOT)),
        "reference_cache_vectors": 16360, "attention_heads": 32, "attention_rows": 128,
        "expected_external_value_requests": 32736,
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in set(inputs)},
    }
    prepared = output / "prepared.json"
    if check:
        assert read(prepared) == manifest, prepared
    else:
        prepared.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return output, len(manifest["evidence_sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Regenerate and compare against the current files")
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    output, pinned_inputs = prepare(check=args.check)
    print(output, pinned_inputs)

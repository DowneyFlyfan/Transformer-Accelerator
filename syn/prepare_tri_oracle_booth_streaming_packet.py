"""Adapt the verified physical-port peer for the trained streaming workload."""

import json
from pathlib import Path
import re

from prepare_tri_oracle_booth_packet_replay import ROOT, WORK as BASE_PACKET, digest

PLACEMENT = Path("records/tri_oracle_corrected_booth_buffered_placement_roundtrip.json")
REFERENCE = Path("records/tri_oracle_booth_trained_streaming_fixture.json")
BASE_RESULT = Path("records/tri_oracle_corrected_booth_packet_attention.json")
TOP = "tri_oracle_chip_packet_io_tb"


def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


def streaming_bench(text):
    for before, after in (
        ("int Slots = 409, ImageTokens = 576;",
         "int Slots = 409, ImageTokens = 576, Layers = 11, ValueRequests = 128;"),
        ("int sign_reads, sign_vectors, sign_errors;",
         "int sign_reads, sign_vectors, sign_errors, merge_layer = 0;"),
        ("signs[ImageTokens];", "signs[Layers * ImageTokens];"),
        ("golden_map[ImageTokens];", "golden_map[Layers * ImageTokens];"),
        ("packed_map[18];", "packed_map[Layers * 18];"),
        ("stored_context[90];", """stored_context[Layers * 90];
  logic [9:0] expected_signs[Layers], expected_value_rank[ValueRequests];"""),
        ("slot, start_bit;", "slot, start_bit, frame, frame_vector;"),
        ("""    if (address >= SignBase)
      return signs[int'((address - SignBase) >> 8)][int'(address[7:6]) * 512 +: 512];""",
         """    if (address >= SignBase) begin
      frame = int'((address - SignBase) >> 18);
      frame_vector = int'(((address - SignBase) & 64'h3ffff) >> 8);
      return signs[frame * ImageTokens + frame_vector][int'(address[7:6]) * 512 +: 512];
    end"""),
        ("address < ContextBase + 720", "address < ContextBase + Layers * 720"),
        ("read_address[lane] < ContextBase + 720", "read_address[lane] < ContextBase + Layers * 720"),
        ("address !== SignBase + 64'(sign_vectors * 256)",
         "sign_vectors > int'(expected_signs[merge_layer]) ||\n"
         "              address !== SignBase + 64'(merge_layer * 262144 + sign_vectors * 256)"),
        ("sign_fault <= sign_reads == 0;", "sign_fault <= merge_layer == 0 && sign_reads == 0;"),
        ("address !== ContextBase + 64'(restored_bursts * 40)",
         "address !== ContextBase + 64'((Layers - 1) * 720 + restored_bursts * 40)"),
        ("            value_reads++;", """            if (value_reads >= ValueRequests ||
                address !== ValueBase + 64'(int'(expected_value_rank[value_reads]) * 64))
              $fatal(1, "STREAMING_VALUE_ADDRESS index=%0d address=%h", value_reads, address);
            $display("STREAMING_VALUE_READ index=%0d rank=%0d", value_reads, expected_value_rank[value_reads]);
            value_reads++;"""),
        ("if (context_bursts >= 18 ||", "if (context_bursts >= Layers * 18 ||"),
        ("int rank, position, expected_reads, prior_reads;", "int rank, position, expected_reads, prior_reads, last_prefill;"),
        ("    $readmemh({fixture, \"/expected.hex\"}, projected_cache);", """    $readmemh({fixture, "/expected.hex"}, projected_cache);
    $readmemh({fixture, "/sign_counts.hex"}, expected_signs);
    $readmemh({fixture, "/value_order.hex"}, expected_value_rank);"""),
        ("for (int index = 0; index < ImageTokens; index++) packed_map",
         "for (int index = 0; index < Layers * ImageTokens; index++) packed_map"),
        ('$fscanf(refs, "%d %d %d %d %d %d %d", image_start, head, alpha, shift, inner, recent, streaming) != 7 || head != 0',
         '$fscanf(refs, "%d %d %d %d %d %d %d %d", image_start, head, alpha, shift,\n'
         '                          inner, recent, streaming, last_prefill) != 8 || head != 2 || streaming != 1'),
        ("command(3, 32'h43030010, 1, '0);", "command(3, 32'h43030010, 1, 192'(Layers - 1));"),
        ("11'd408, 32'(alpha), 5'd0", "11'(last_prefill + 1), 32'(alpha), 5'(head)"),
        ("{6'd0, 5'd0, 18'(inner)", "{6'd0, 5'(head), 18'(inner)"),
        ("7'(shift), 11'd408, 11'(position), 5'd0", "7'(shift), 11'(last_prefill + 1), 11'(position), 5'(head)"),
        ("host_words != 289 || value_reads != 206",
         "host_words != 289 + (Layers - 1) * 3 || value_reads != ValueRequests"),
        ("#10000000;", "#15000000;"),
    ):
        text = replace_once(text, before, after)

    merge_sequence = """    for (int layer = 0; layer < Layers; layer++) begin
      logic [63:0] frame_sign_base;
      merge_layer = layer;
      sign_reads = 0;
      sign_vectors = 0;
      frame_sign_base = SignBase + 64'(layer * 262144);
      tag = 32'h43020000 + 32'(layer);
      command(2, tag, 1, 192'({frame_sign_base[41:6], 12'd1536, 10'(image_start), 5'(layer), layer == 0}));
      response(2, tag, 0);
      while (reading[1] || response_pending[1]) @(negedge clk);
      if (maps != (layer + 1) * ImageTokens || context_bursts != (layer + 1) * 18 ||
          context_words != (layer + 1) * 90 || context_acks != (layer + 1) * 18)
        $fatal(1, "STREAMING_CONTEXT_COUNTS layer=%0d", layer);
      if (sign_vectors < int'(expected_signs[layer]) || sign_vectors > int'(expected_signs[layer])+1 ||
          sign_reads != sign_vectors + int'(layer == 0) || sign_errors != 1)
        $fatal(1, "STREAMING_SIGN_INVENTORY layer=%0d vectors=%0d reads=%0d faults=%0d",
               layer, sign_vectors, sign_reads, sign_errors);
      $display("STREAMING_MERGE_FRAME_PASS layer=%0d maps=%0d vectors=%0d", layer, ImageTokens, sign_vectors);
      $fflush();
    end

"""
    text, modified = re.subn(r"(?ms)^    command\(2, 32'h43020000,.*?(?=^    command\(3,)",
                             lambda _: merge_sequence, text)
    assert modified == 1
    text, modified = re.subn(r"(?ms)^  initial begin\n    #1000000;.*?^  end\n\n", "", text)
    assert modified == 1
    return text


def prepare():
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    base = ROOT / BASE_PACKET
    original_result = json.loads(BASE_RESULT.read_text())
    base_receipt = base / "prepared.json"
    assert digest(base_receipt) == original_result["evidence_sha256"][str(base_receipt.relative_to(ROOT))]
    base_inputs = json.loads(base_receipt.read_text())
    reference = json.loads(REFERENCE.read_text())
    placement = json.loads(PLACEMENT.read_text())
    after = ROOT / Path(placement["database"]).parents[1]
    output, fixture = after / "streaming_packet", after / "streaming_fixture"
    for name, checksum in reference["evidence_sha256"].items():
        assert digest(ROOT / name) == checksum, name
    cold = after / "cold/cold.v"
    assert digest(cold) == reference["cold_netlist_sha256"]
    template, bundle = (base / name for name in ("attention_tb.sv", "bundle.sv"))
    for path in (template, bundle):
        assert digest(path) == base_inputs["evidence_sha256"][str(path.relative_to(ROOT))]
    for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle.read_text()):
        path = Path(name)
        assert digest(path) == base_inputs["evidence_sha256"][str(path.relative_to(ROOT))]

    bench = output / "attention_tb.sv"
    bench_text = streaming_bench(template.read_text())
    text = replace_once(bundle.read_text(), str(ROOT / base_inputs["die_netlist"]), str(cold))
    bundle_text = replace_once(text, str(template), str(bench))
    output.mkdir()
    bench.write_text(bench_text)
    (output / "bundle.sv").write_text(bundle_text)
    evidence = (base_receipt, template, bundle, ROOT / REFERENCE, ROOT / PLACEMENT,
                cold, output / "bundle.sv", bench, Path(__file__).resolve())
    facts = {
        "state": "trained_packet_attention_fixture_bound_to_corrected_full_chip",
        "testbench_top": TOP,
        "testbench_fixture": str(fixture.relative_to(ROOT)),
        "cold_netlist_sha256": reference["cold_netlist_sha256"],
        "merge_frames": 11,
        "expected_streaming_value_requests": 128,
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in evidence},
    }
    (output / "prepared.json").write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n")
    print(output)


if __name__ == "__main__":
    assert __debug__
    prepare()

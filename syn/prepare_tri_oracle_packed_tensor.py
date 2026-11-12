"""Derive a packed down-projection candidate from the pinned compact tensor."""

import argparse
import json
from pathlib import Path
import re

from verify_tri_oracle_packed_down_weights import FIRST_ROW, TILE_ROWS, sha256, signed


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / ".cache/physical/wac_budgeted_parent_boundary/compact_load_transport/integrated"
RESTORED = ROOT / ".cache/physical/context_external/local_restore/layer_replay_v2"


def rewrite(source, changes):
    for before, after in changes:
        assert source.count(before) == 1, before
        source = source.replace(before, after, 1)
    return source


def tensor(source):
    return rewrite(source, (
        ("input logic clk,rst_n,cfg_valid,cfg_paired,",
         "input logic clk,rst_n,cfg_valid,cfg_paired,cfg_packed_weights,"),
        ("  input logic [63:0] rsp_data,\n", """  input logic [63:0] rsp_data,
  output logic wide_req_valid,
  input logic wide_req_ready,
  output logic [63:0] wide_req_address,
  output logic [5:0] wide_req_length,
  input logic wide_rsp_valid,
  output logic wide_rsp_ready,
  input logic wide_rsp_last,wide_rsp_error,
  input logic [511:0] wide_rsp_data,
"""),
        ("FLUSH,DONE,CLEAR_WEIGHTS,WEIGHT_CHUNK\n", "FLUSH,DONE,CLEAR_WEIGHTS,WEIGHT_CHUNK,PACK_START,PACK_WAIT\n"),
        ("  logic [5119:0] sequence_data;\n", """  logic [5119:0] sequence_data;
  logic packed_weights,packed_error,packed_ready,packed_done,packed_done_error;
  logic [159:0] packed_keep;
  logic packed_cfg_valid,packed_cfg_ready,packed_load_done,packed_load_done_ready,packed_load_error;
  logic [63:0] packed_cfg_address;
  logic [4:0] packed_cfg_core,packed_cfg_first_word,wide_load_core;
  logic [1:0] packed_cfg_group,wide_load_group;
  logic [7:0] packed_cfg_enable;
  logic [5:0] packed_cfg_words;
  logic wide_load_valid;
  logic [9:0] wide_load_addr;
  logic [31:0] wide_load_enable;

  tri_oracle_packed_weight_schedule packed_schedule (
    .clk,.rst_n(owner_rst_n),.cfg_valid(state==PACK_START),.cfg_ready(packed_ready),
    .cfg_base(weight_base),.cfg_first_row(channels[15:0]),.cfg_dense_rows(dense_rows),
    .cfg_feature_words(feature_words),.cfg_count(count),.cfg_tile_start(tile_start),
    .cfg_keep(packed_keep),.cfg_active_words(active_words),
    .load_cfg_valid(packed_cfg_valid),.load_cfg_ready(packed_cfg_ready),
    .load_cfg_address(packed_cfg_address),.load_cfg_core(packed_cfg_core),
    .load_cfg_first_word(packed_cfg_first_word),.load_cfg_row_group(packed_cfg_group),
    .load_cfg_row_enable(packed_cfg_enable),.load_cfg_words(packed_cfg_words),
    .load_done_valid(packed_load_done),.load_done_error(packed_load_error),
    .load_done_ready(packed_load_done_ready),.done_valid(packed_done),
    .done_ready(state==PACK_WAIT),.done_error(packed_done_error)
  );

  assign wide_load_group = {(|wide_load_enable[31:16]),
                            (|wide_load_enable[31:24]) || (|wide_load_enable[15:8])};

  tri_oracle_wide_weight_loader packed_loader (
    .clk,.rst_n(owner_rst_n),.cfg_valid(packed_cfg_valid),.cfg_ready(packed_cfg_ready),
    .cfg_address(packed_cfg_address),.cfg_core(packed_cfg_core),.cfg_first_word(packed_cfg_first_word),
    .cfg_row_group(packed_cfg_group),.cfg_row_enable(packed_cfg_enable),.cfg_words(packed_cfg_words),
    .done_valid(packed_load_done),.done_ready(packed_load_done_ready),.done_error(packed_load_error),
    .req_valid(wide_req_valid),.req_ready(wide_req_ready),.req_address(wide_req_address),
    .req_length(wide_req_length),.rsp_valid(wide_rsp_valid),.rsp_ready(wide_rsp_ready),
    .rsp_last(wide_rsp_last),.rsp_error(wide_rsp_error),.rsp_data(wide_rsp_data),
    .load_valid(wide_load_valid),.load_ready(1'b1),.load_core(wide_load_core),
    .load_addr(wide_load_addr),.load_row_enable(wide_load_enable),.load_data()
  );
"""),
        ("""    .clk(clk),.rst_n(backend_rst_n),.load_valid(load_valid),.load_core(load_core),
    .load_kind(load_kind),.load_addr(load_addr),.load_payload(load_payload),
    .load_row_enable(load_row_enable),.load_error(load_error),""",
         """    .clk(clk),.rst_n(backend_rst_n),.load_valid(load_valid || wide_load_valid),
    .load_core(wide_load_valid ? wide_load_core : load_core),
    .load_kind(wide_load_valid ? 2'b00 : load_kind),
    .load_addr(wide_load_valid ? wide_load_addr : load_addr),.load_payload(load_payload),
    .load_row_enable(wide_load_valid ? wide_load_enable : load_row_enable),.load_error(load_error),
    .wide_load_valid,.wide_load_group,.wide_load_payload(wide_rsp_data),"""),
        ("    tile_words=9'(part_words)", """    invalid_config=invalid_config || (cfg_packed_weights &&
      (cfg_paired || softmax_request.score_tile || cfg_weight_base[5:0]!=0 ||
       cfg_channels[2:0]!=0 || cfg_dense_rows[2:0]!=0));
    tile_words=9'(part_words)"""),
        ("    logical_row=paired ?", """    logical_row=packed_weights && state==VALIDATE ? int'(validate_column) : paired ?"""),
        ("      weight_core<=0;weight_row<=0;tile_start<=0;chunk_word<=0;selected_channel<=0;\n",
         """      weight_core<=0;weight_row<=0;tile_start<=0;chunk_word<=0;selected_channel<=0;
      packed_weights<=0;packed_keep<=0;packed_error<=0;
"""),
        ("          activation_stride<=cfg_activation_stride;paired<=cfg_paired;\n",
         """          activation_stride<=cfg_activation_stride;paired<=cfg_paired;
          packed_weights<=cfg_packed_weights;packed_keep<=0;packed_error<=0;
"""),
        ("          if(17'(channels[int'(validate_column)*16+:16])>=dense_rows)begin",
         """          if(packed_weights) packed_keep[validate_column]<=selected_row_kept;
          if(17'(channels[int'(validate_column)*16+:16])>=dense_rows ||
             (packed_weights && 17'(channels[int'(validate_column)*16+:16])!=
              17'(channels[15:0])+17'(validate_column)))begin"""),
        ("state<=WEIGHT_SELECT;end\n            else weight_core",
         "state<=packed_weights ? PACK_START : WEIGHT_SELECT;end\n            else weight_core"),
        ("        EXECUTE:if(sequence_ready)state<=WAIT_EXECUTE;\n", """        PACK_START:if(packed_ready)begin packed_error<=0;state<=PACK_WAIT;end
        PACK_WAIT:begin
          if(load_error) packed_error<=1;
          if(packed_done)begin
            if(packed_done_error || packed_error || load_error)begin
              done_error<=1;flush_second<=0;state<=FLUSH;
            end else state<=EXECUTE;
          end
        end
        EXECUTE:if(sequence_ready)state<=WAIT_EXECUTE;
"""),
        ("if(load_error && state!=IDLE && state!=DONE && state!=FLUSH)begin",
         "if(load_error && state!=IDLE && state!=DONE && state!=FLUSH && state!=PACK_WAIT)begin"),
    ))


def fabric(source):
    return rewrite(source, (
        ("    input wire [63:0] load_payload,\n", """    input wire [63:0] load_payload,
    input wire wide_load_valid,
    input wire [1:0] wide_load_group,
    input wire [511:0] wide_load_payload,
"""),
        ("            .load_error(load_errors[cluster]),", """            .load_error(load_errors[cluster]),
            .wide_load_valid(wide_load_valid && load_core[4:2]==3'(cluster)),
            .wide_load_group,.wide_load_payload,"""),
    ))


def adapter(source):
    return rewrite(source, (
        ("  input logic [63:0] load_payload,\n", """  input logic [63:0] load_payload,
  input logic wide_load_valid,
  input logic [1:0] wide_load_group,
  input logic [511:0] wide_load_payload,
"""),
        ("""  logic [2047:0] load_data;
  tri_oracle_load_payload_decode decode_load_payload (
    .load_valid, .load_kind, .load_payload, .load_row_enable, .load_data
  );
""", """  logic [2047:0] load_data, scalar_load_data;
  tri_oracle_load_payload_decode decode_load_payload (
    .load_valid(load_valid && !wide_load_valid), .load_kind, .load_payload, .load_row_enable,
    .load_data(scalar_load_data)
  );
  always_comb begin
    load_data = scalar_load_data;
    if (wide_load_valid) begin
      load_data = '0;
      load_data[{wide_load_group, 9'b0} +: 512] = wide_load_payload;
    end
  end
"""),
    ))


def trained_fixture(output):
    record = ROOT / "records/wac_packed_trained_down_fabric_result.json"
    packed = json.loads(record.read_text())
    assert packed["state"] == "packed_trained_down_weights_checked_on_twenty_compiled_memory_cores"
    evidence = packed["evidence_sha256"]
    weights_record = ROOT / "records/batch389_fixture_preparation.json"
    input_record = ROOT / "records/batch407_learned_fixture.json"
    weights = json.loads(weights_record.read_text())
    inputs = json.loads(input_record.read_text())
    output_record, = [Path(name) for name in inputs["source_sha256"]
                      if name.endswith("/batch403_activation_precision.json")]
    expected_path = Path(json.loads(output_record.read_text())["fixture"]) / "expected.hex"
    assert all(inputs["source_sha256"][str(path)] == sha256(path)
               for path in (output_record, expected_path))
    down = Path(weights["fixture"]) / "down.hex"
    activation_path = Path(inputs["fixture"]) / "intermediate.hex"
    binary, = [ROOT / name for name in evidence if name.endswith("/packed_down_fabric/packed.bin")]
    pinned = (weights_record, input_record, down, activation_path, binary)
    assert all(evidence[str(path.relative_to(ROOT))] == sha256(path) for path in pinned)
    features = weights["intermediate_features"]
    assert features == 5632 and inputs["intermediate"] == features
    assert weights["original_layer"] == inputs["original_checkpoint_layer"] == 0

    with down.open() as data:
        data.seek(FIRST_ROW * features * 3)
        scalar = bytes.fromhex(data.read(TILE_ROWS * features * 3))
    with binary.open("rb") as data:
        data.seek(FIRST_ROW * features)
        wide = data.read(TILE_ROWS * features)
    with activation_path.open() as data:
        activation = bytes.fromhex(data.read(features * 3))
    expected = expected_path.read_text().splitlines()[FIRST_ROW:FIRST_ROW + TILE_ROWS]
    assert len(scalar) == len(wide) == TILE_ROWS * features
    assert len(activation) == features and len(expected) == TILE_ROWS

    signed_activation = list(map(signed, activation))
    for row, result in enumerate(expected):
        actual = sum(signed(weight) * value for weight, value in
                     zip(scalar[row * features:(row + 1) * features], signed_activation, strict=True))
        assert actual & 0xffffffff == int(result, 16), row + FIRST_ROW

    output.mkdir()
    for name, data, width in (("scalar", scalar, 8), ("packed", wide, 64), ("activation", activation, 8)):
        with (output / (name + ".hex")).open("x") as stream:
            stream.writelines(data[index:index + width][::-1].hex() + "\n"
                              for index in range(0, len(data), width))
    (output / "expected.hex").write_text("\n".join(expected) + "\n")
    return (record, *pinned, output_record, expected_path, *sorted(output.iterdir()))


def prepare(output):
    candidates = {
        BASE / "tri_oracle_batched_tensor390.sv": (BASE / "tri_oracle_batched_tensor390.sv", tensor),
        BASE / "tri_oracle_compute_fabric.sv": (RESTORED / "tri_oracle_compute_fabric.sv", fabric),
        BASE / "cluster_adapter.sv": (BASE / "cluster_adapter.sv", adapter),
    }
    baseline = BASE / "receipt.json"
    receipt = json.loads(baseline.read_text())
    assert receipt["state"] == "compact_bank_load_transport_preserved_exact_source_transactions"
    baseline_bundle = BASE / "bundle.sv"
    pins = receipt["input_sha256"]
    bundle = baseline_bundle.read_text()
    includes = tuple(Path(path) for path in re.findall(r'(?m)^`include "([^"]+)"$', bundle))
    for source in (*includes, baseline_bundle):
        assert pins[str(source)] == sha256(source), source
    assert candidates.keys() <= set(includes)

    restored_fabric = RESTORED / "tri_oracle_compute_fabric.sv"
    restored_receipt = ROOT / "records/wac_local_context_restore_result.json"
    restored = json.loads(restored_receipt.read_text())
    assert restored["state"] == "compact_attention_restores_compiled_local_merge_tables"
    assert restored["evidence_sha256"][str(restored_fabric.relative_to(ROOT))] == sha256(restored_fabric)
    output.mkdir()
    for original, (source, transform) in candidates.items():
        target = output / original.name
        target.write_text(transform(source.read_text()))
        bundle = rewrite(bundle, ((f'`include "{original}"', f'`include "{target}"'),))
    support = [ROOT / "verilog" / (name + ".sv") for name in (
        "tri_oracle_wide_weight_loader", "tri_oracle_packed_weight_schedule", "tri_oracle_packed_tensor_tb",
    )]
    candidate_bundle = output / "bundle.sv"
    candidate_bundle.write_text(bundle + "".join(f'`include "{source}"\n' for source in support))
    generated = tuple(output.iterdir())
    fixture = trained_fixture(output / "fixture")
    evidence = (baseline, baseline_bundle, *includes, restored_receipt, restored_fabric,
                *support, *generated, *fixture, Path(__file__),
                Path(__file__).with_name("verify_tri_oracle_packed_down_weights.py"))
    (output / "prepared.json").write_text(json.dumps({
        "state": "compact_context_tensor_packed_weight_path_prepared",
        "input_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in evidence},
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())

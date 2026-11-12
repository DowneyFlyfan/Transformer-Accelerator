"""Enable packed gate, up, and down weight reads on the unified chip."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_packed_tensor import rewrite
from verify_tri_oracle_packed_down_weights import ROOT, sha256


BASE = ROOT / ".cache/physical/wide_weight_loader/unified_chip"


def tensor(source):
    return rewrite(source, (
        ("tri_oracle_packed_weight_schedule packed_schedule (",
         "tri_oracle_paired_weight_schedule packed_schedule ("),
        ("    .cfg_base(weight_base),.cfg_first_row(channels[15:0]),",
         "    .cfg_paired(paired),.cfg_base(weight_base),.cfg_up_base(up_weight_base),.cfg_first_row(channels[15:0]),"),
        ("(cfg_paired || softmax_request.score_tile || cfg_weight_base[5:0]!=0 ||",
         "(softmax_request.score_tile || cfg_weight_base[5:0]!=0 ||\n       (cfg_paired && cfg_up_weight_base[5:0]!=0) ||"),
    ))


def frame(source):
    return rewrite(source, (
        ("cfg_output_features[2:0]!=0 || cfg_down_base[5:0]!=0",
         "cfg_output_features[2:0]!=0 || cfg_down_base[5:0]!=0 ||\n                              cfg_gate_base[5:0]!=0 || cfg_up_base[5:0]!=0"),
        ("PACKED_FEEDFORWARD_WEIGHTS && !attention_selected && state==DOWN_LAUNCH",
         "PACKED_FEEDFORWARD_WEIGHTS && !attention_selected && (state==GATE_LAUNCH || state==DOWN_LAUNCH)"),
    ))


def learned(source):
    return rewrite(source, (
        ("cfg_output_features[2:0]!=0 || cfg_down_base[5:0]!=0",
         "cfg_output_features[2:0]!=0 || cfg_down_base[5:0]!=0 ||\n                                     cfg_gate_base[5:0]!=0 || cfg_up_base[5:0]!=0"),
    ))


def bench(source):
    return rewrite(source, (
        ("  logic [511:0] wide_rsp_data;\n", """  logic [511:0] wide_rsp_data;
  int wide_branch_beats[3], narrow_branch_beats[3];

  function automatic int weight_branch(input logic [63:0] address);
    if(address>=GATE_BASE && address<GATE_BASE+64'(INTERMEDIATE*HIDDEN))return 0;
    if(address>=UP_BASE && address<UP_BASE+64'(INTERMEDIATE*HIDDEN))return 1;
    if(address>=DOWN_BASE && address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))return 2;
    return -1;
  endfunction

  function automatic logic [63:0] weight_base(input int branch);
    case(branch)
      0:return GATE_BASE;
      1:return UP_BASE;
      default:return DOWN_BASE;
    endcase
  endfunction

  function automatic int weight_value(input int branch,row,feature);
    case(branch)
      0:return gate_weight(row,feature);
      1:return up_weight(row,feature);
      default:return down_weight(row,feature);
    endcase
  endfunction
"""),
        ("""    int offset,first_row,feature;
    wide_rsp_data='0;
    if(wide_active)begin
      offset=int'(wide_address-DOWN_BASE)+wide_beat*64;
      first_row=8*(offset/(8*INTERMEDIATE));
      feature=(offset%(8*INTERMEDIATE))/8;
      for(int row=0;row<8;row++)
        for(int byte_index=0;byte_index<8;byte_index++)
          wide_rsp_data[row*64+byte_index*8+:8]=8'(down_weight(first_row+row,feature+byte_index));
""", """    int offset,first_row,feature,branch,columns;
    wide_rsp_data='0;
    if(wide_active)begin
      branch=weight_branch(wide_address);
      columns=branch==2 ? INTERMEDIATE : HIDDEN;
      offset=int'(wide_address-weight_base(branch))+wide_beat*64;
      first_row=8*(offset/(8*columns));
      feature=(offset%(8*columns))/8;
      for(int row=0;row<8;row++)
        for(int byte_index=0;byte_index<8;byte_index++)
          wide_rsp_data[row*64+byte_index*8+:8]=8'(weight_value(branch,first_row+row,feature+byte_index));
"""),
        ("""    if(wide_req_valid && wide_req_ready)begin
      if(!PACKED || read_active || req_valid || write_active || write_response ||
         write_bytes!=TOKENS*INTERMEDIATE || !committed[TOKENS*INTERMEDIATE-1] ||
         wide_req_length==0 || wide_req_length>32 || wide_req_address[5:0]!=0 ||
         wide_req_address<DOWN_BASE ||
         wide_req_address+64'(wide_req_length)*64>DOWN_BASE+64'(OUTPUTS*INTERMEDIATE) ||
         int'(wide_req_address-DOWN_BASE)%(8*INTERMEDIATE)+int'(wide_req_length)*64>8*INTERMEDIATE)
        $fatal(1,"PACKED_DECODER_REQUEST address=%h",wide_req_address);
""", """    if(wide_req_valid && wide_req_ready)begin
      int branch, columns, rows, offset_bytes;
      branch=weight_branch(wide_req_address);
      columns=branch==2 ? INTERMEDIATE : HIDDEN;
      rows=branch==2 ? OUTPUTS : INTERMEDIATE;
      offset_bytes=int'(wide_req_address-weight_base(branch));
      if(!PACKED || branch<0 || read_active || req_valid || write_active || write_response ||
         activation_acks!=TOKENS*HIDDEN ||
         (branch==2 && (write_bytes!=TOKENS*INTERMEDIATE || !committed[TOKENS*INTERMEDIATE-1])) ||
         wide_req_length==0 || wide_req_length>32 || wide_req_address[5:0]!=0 ||
         offset_bytes+int'(wide_req_length)*64>rows*columns ||
         offset_bytes%(8*columns)+int'(wide_req_length)*64>8*columns)
        $fatal(1,"PACKED_DECODER_REQUEST address=%h",wide_req_address);
"""),
        ("      wide_beats++;", "      wide_beats++;\n      wide_branch_beats[weight_branch(wide_address)]++;"),
        ("      if(wide_active || (PACKED && req_address>=DOWN_BASE &&\n         req_address<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE)))",
         "      if(wide_active || (PACKED && weight_branch(req_address)>=0))"),
        ("      if(current>=DOWN_BASE && current<DOWN_BASE+64'(OUTPUTS*INTERMEDIATE))scalar_down_beats++;",
         """      if(weight_branch(current)>=0)narrow_branch_beats[weight_branch(current)]++;
      if(weight_branch(current)==2)scalar_down_beats++;"""),
        ('    $fdisplay(progress_file,"BATCH408_START");$fflush(progress_file);',
         """    $fdisplay(progress_file,"BATCH408_START");$fflush(progress_file);
    foreach(wide_branch_beats[i])begin wide_branch_beats[i]=0;narrow_branch_beats[i]=0;end"""),
        ("      wide_requests=0;wide_beats=0;scalar_down_beats=0;",
         """      wide_requests=0;wide_beats=0;scalar_down_beats=0;
      foreach(wide_branch_beats[i])begin wide_branch_beats[i]=0;narrow_branch_beats[i]=0;end"""),
        ('    $display("PACKED_DECODER_PASS packed=', """    foreach(wide_branch_beats[i])
      if((PACKED && (wide_branch_beats[i]==0 || narrow_branch_beats[i]!=0)) ||
         (!PACKED && (narrow_branch_beats[i]==0 || wide_branch_beats[i]!=0)))
        $fatal(1,"PACKED_PAIR_BRANCH_INVENTORY branch=%0d",i);
    $display("PACKED_PAIR_BRANCHES gate_wide=%0d up_wide=%0d down_wide=%0d gate_narrow=%0d up_narrow=%0d down_narrow=%0d",
      wide_branch_beats[0],wide_branch_beats[1],wide_branch_beats[2],
      narrow_branch_beats[0],narrow_branch_beats[1],narrow_branch_beats[2]);
    $display("PACKED_DECODER_PASS packed="""),
    ))


def prepare(output):
    reference_path = ROOT / "records/wac_unified_chip_commands_result.json"
    reference = json.loads(reference_path.read_text())
    assert reference["state"] == "mapped_chip_commands_verified_on_unified_read_source_decoder"
    manifest = BASE / "prepared.json"
    bundle_path = BASE / "bundle.sv"
    assert reference["evidence_sha256"][str(manifest.relative_to(ROOT))] == sha256(manifest)
    pins = json.loads(manifest.read_text())["input_sha256"]
    assert all(sha256(ROOT / path) == digest for path, digest in pins.items())
    budget_path = ROOT / "records/wac_unified_decode_read_budget_result.json"
    budget = json.loads(budget_path.read_text())
    assert budget["state"] == "measured_local_decode_weight_demand_exceeds_paper_latency_budget"
    assert budget["gate_up_weight_bytes"] > budget["down_weight_bytes"]

    bundle = bundle_path.read_text()
    sources = tuple(Path(name) for name in re.findall(r'(?m)^`include "([^"]+)"$', bundle))
    modifiers = {
        "tri_oracle_batched_tensor390.sv": tensor,
        "tri_oracle_batched_frame393.sv": frame,
        "tri_oracle_batched_learned406.sv": learned,
        "trained_tb.sv": bench,
    }
    assert all(sum(path.name == name for path in sources) == 1 for name in modifiers)
    output.mkdir()
    for source in (path for path in sources if path.suffix == ".sv"):
        text = source.read_text()
        renamed = text.replace("PACKED_DOWN_WEIGHTS", "PACKED_FEEDFORWARD_WEIGHTS")
        if source.name in modifiers:
            renamed = modifiers[source.name](renamed)
        if renamed != text:
            target = output / source.name
            assert not target.exists(), target
            target.write_text(renamed)
            bundle = rewrite(bundle, ((f'`include "{source}"', f'`include "{target}"'),))
    schedule = ROOT / "verilog/tri_oracle_paired_weight_schedule.sv"
    (output / "bundle.sv").write_text(bundle + f'`include "{schedule}"\n')
    evidence = (manifest, reference_path, budget_path, schedule, Path(__file__), *sorted(output.iterdir()))
    (output / "prepared.json").write_text(json.dumps({
        "state": "unified_chip_packed_gate_up_and_down_source_prepared",
        "controller_sha256": reference["controller_sha256"],
        "input_sha256": pins | {str(path.relative_to(ROOT)): sha256(path) for path in evidence},
    }, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    prepare(parser.parse_args().output.resolve())

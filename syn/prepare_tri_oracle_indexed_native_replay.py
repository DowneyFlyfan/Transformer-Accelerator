"""Bind the indexed images to the existing trained whole-chip scoreboard."""

import argparse
import json
from pathlib import Path
import re

from audit_tri_oracle_placed_chip_boundary import digest
from prepare_tri_oracle_early_weight_pairs import edit
from prepare_tri_oracle_indexed_weight_image import DOWN_PAYLOAD_BASE, PAIR_PAYLOAD_BASE, SLOT_BYTES


def testbench(source, dimensions):
    pair_slots = dimensions["pair"]["index_entries"]
    down_slots = dimensions["down"]["index_entries"]
    assert pair_slots == 2816 and down_slots == 1536
    replacements = [
        ("  int lane_branch_beats[2][3];", f"""  localparam logic [63:0] PAIR_PAYLOAD_BASE=64'h{PAIR_PAYLOAD_BASE:016x};
  localparam logic [63:0] DOWN_PAYLOAD_BASE=64'h{DOWN_PAYLOAD_BASE:016x};
  localparam int PAIR_SLOTS={pair_slots}, DOWN_SLOTS={down_slots}, IMAGE_SLOT_BYTES={SLOT_BYTES};
  byte unsigned pair_index[PAIR_SLOTS*64], down_index[DOWN_SLOTS*64];
  byte unsigned pair_payload[PAIR_SLOTS*IMAGE_SLOT_BYTES], down_payload[DOWN_SLOTS*IMAGE_SLOT_BYTES];
  int indexed_beats[2][4], payload_owed[2], pending_region[2];
  logic [63:0] payload_next[2];

  function automatic int image_region(input logic [63:0] address);
    if (address>=GATE_BASE && address<GATE_BASE+PAIR_SLOTS*64) return 0;
    if (address>=PAIR_PAYLOAD_BASE && address<PAIR_PAYLOAD_BASE+PAIR_SLOTS*IMAGE_SLOT_BYTES) return 1;
    if (address>=DOWN_BASE && address<DOWN_BASE+DOWN_SLOTS*64) return 2;
    if (address>=DOWN_PAYLOAD_BASE && address<DOWN_PAYLOAD_BASE+DOWN_SLOTS*IMAGE_SLOT_BYTES) return 3;
    return -1;
  endfunction

  function automatic logic [63:0] image_base(input int region);
    case (region)
      0: return GATE_BASE;
      1: return PAIR_PAYLOAD_BASE;
      2: return DOWN_BASE;
      3: return DOWN_PAYLOAD_BASE;
      default: return 64'b0;
    endcase
  endfunction

  function automatic byte unsigned index_byte(input int region, offset);
    return region==0 ? pair_index[offset] : down_index[offset];
  endfunction

  task automatic check_indexed_request(input int lane, input logic [63:0] address, input int beats);
    int region, offset, entry, cluster, part, encoded_bytes;
    bit raw;
    logic [63:0] payload_base;
    region=image_region(address);
    if (region<0 || address[5:0]!=0 || beats<1 || beats>63)
      $fatal(1,"INDEXED_NATIVE_REQUEST address=%h length=%0d",address,beats);
    offset=int'(address-image_base(region));
    if (region==0 || region==2) begin
      if (beats!=1 || payload_owed[lane]!=0)
        $fatal(1,"INDEXED_NATIVE_INDEX_BEFORE_PAYLOAD_RETIRED lane=%0d",lane);
      entry=offset/64;
      cluster=region==0 ? (entry/8)%5 : (entry/24)%5;
      part=region==0 ? (entry/2)%4 : (entry/6)%4;
      if (lane!=int'(cluster>2 || (cluster==2 && part>=2)))
        $fatal(1,"INDEXED_NATIVE_WRONG_LANE lane=%0d cluster=%0d part=%0d",lane,cluster,part);
      payload_base='0;
      for (int b=0; b<8; b++) payload_base[8*b+:8]=index_byte(region,offset+b);
      encoded_bytes=int'((int'(index_byte(region,offset+9)) & 'h3f)*256+int'(index_byte(region,offset+8)));
      raw=(index_byte(region,offset+9) & 8'h40)!=0;
      if (raw || encoded_bytes<2176 || encoded_bytes>IMAGE_SLOT_BYTES ||
          payload_base!=image_base(region+1)+64'(entry)*IMAGE_SLOT_BYTES)
        $fatal(1,"INDEXED_NATIVE_BAD_IMAGE_ENTRY");
      pending_region[lane]=region+1;
      payload_next[lane]=payload_base;
      payload_owed[lane]=(encoded_bytes+63)/64;
    end else begin
      if (region!=pending_region[lane] || address!==payload_next[lane] ||
          beats!=(payload_owed[lane]>63 ? 63 : payload_owed[lane]))
        $fatal(1,"INDEXED_NATIVE_PAYLOAD_SEQUENCE lane=%0d address=%h length=%0d",lane,address,beats);
      payload_next[lane]+=64'(beats)*64;
      payload_owed[lane]-=beats;
    end
  endtask
""".rstrip()),
        ("  int wide_branch_beats[3], narrow_branch_beats[3];", "  int narrow_branch_beats[3];"),
        ("      payload_valid=1;payload_last=(word==14);payload_data=descriptor[word*64+:64];",
         "      payload_valid=1;payload_last=0;payload_data=descriptor[word*64+:64];"),
        ("    payload_valid=0;payload_last=0;payload_data='x;\n    wait_for_lease=0;", """    payload_valid=1;payload_last=1;payload_data=64'h1;
    @(posedge clk);if(payload_ready!==1'b1)$fatal(1,"INDEXED_NATIVE_EXTENSION_READY");
    @(negedge clk);
    payload_valid=0;payload_last=0;payload_data='x;
    wait_for_lease=0;"""),
        ("    if(dut.residual_bank_granted!==1'b1 ||", """    if(dut.indexed_weight_format!==1'b1 ||
       dut.layer.layer.feedforward.compute.compute.tensor.indexed_weight_format!==1'b1)
      $fatal(1,"INDEXED_NATIVE_FORMAT_NOT_AT_TENSOR");
    if(dut.residual_bank_granted!==1'b1 ||"""),
        ('descriptor_words=15 commands=', 'descriptor_words=16 commands='),
        ('FEEDFORWARD_DESCRIPTOR_SLICE_PASS bus_bits=%0d words=15', 'FEEDFORWARD_DESCRIPTOR_SLICE_PASS bus_bits=%0d words=16'),
        ("      if(wide_active[0] || (PACKED && weight_branch(req_address)>=0))",
         "      if(wide_active[0] || (PACKED && (weight_branch(req_address)>=0 || image_region(req_address)>=0)))"),
        ("          lane_branch_beats[lane][branch]++;\n          wide_branch_beats[branch]++;",
         """          region=image_region(wide_address[lane]);
          if (region<0) $fatal(1,"INDEXED_NATIVE_RESPONSE_UNKNOWN_REGION");
          indexed_beats[lane][region]++;"""),
        ("      foreach(lane_branch_beats[lane,branch])lane_branch_beats[lane][branch]=0;\n", ""),
    ]
    result = edit(source, replacements)
    reset = "foreach(wide_branch_beats[i])begin wide_branch_beats[i]=0;narrow_branch_beats[i]=0;end"
    assert result.count(reset) == 2
    result = result.replace(reset, "foreach(narrow_branch_beats[i])narrow_branch_beats[i]=0;")

    start = result.index("    int offset,first_row,feature,branch,columns;")
    end = result.index("\n  end\n  end", start)
    result = result[:start] + """    int offset,region;
    wide_rsp_data[lane]='0;
    if(wide_active[lane] && packed_sign_address(wide_address[lane]))
      wide_rsp_data[lane]=packed_sign_line(wide_address[lane]);
    else if(wide_active[lane])begin
      region=image_region(wide_address[lane]);
      offset=int'(wide_address[lane]-image_base(region))+wide_beat[lane]*64;
      for(int b=0;b<64;b++) begin
        case (region)
          0: wide_rsp_data[lane][8*b+:8]=pair_index[offset+b];
          1: wide_rsp_data[lane][8*b+:8]=pair_payload[offset+b];
          2: wide_rsp_data[lane][8*b+:8]=down_index[offset+b];
          3: wide_rsp_data[lane][8*b+:8]=down_payload[offset+b];
          default: $fatal(1,"INDEXED_NATIVE_RESPONSE_ADDRESS");
        endcase
      end
    end""" + result[end:]

    start = result.index("        int branch, columns, rows, offset_bytes;")
    end = result.index("        if(packed_sign_address(wide_req_address[lane]))", start)
    result = result[:start] + "        int region;\n        region=image_region(wide_req_address[lane]);\n" + result[end:]
    start = result.index("        end else if(!PACKED || branch<0")
    end = result.index("        wide_active[lane]<=1;", start)
    result = result[:start] + """        end else begin
          if(!PACKED || (lane==0 && (read_active || req_valid)) || write_active || write_response ||
             activation_acks!=TOKENS*HIDDEN ||
             (region>=2 && (write_bytes!=TOKENS*INTERMEDIATE || !committed[TOKENS*INTERMEDIATE-1])))
            $fatal(1,"INDEXED_NATIVE_REQUEST_OWNERSHIP");
          check_indexed_request(lane,wide_req_address[lane],int'(wide_req_length[lane]));
        end
""" + result[end:]
    result = edit(result, [("        int branch;\n        branch=weight_branch(wide_address[lane]);\n",
                            "        int region;\n")])

    start = result.index("    foreach(wide_branch_beats[i])\n")
    end = result.index('    $display("PACKED_DECODER_PASS ', start)
    result = result[:start] + """    if (simultaneous_responses==0) $fatal(1,"PARALLEL_CHIP_NO_DUAL_RESPONSE");
    foreach(narrow_branch_beats[i])
      if (narrow_branch_beats[i]!=0) $fatal(1,"INDEXED_NATIVE_SCALAR_WEIGHT_TRANSFER");
    for (int lane=0;lane<2;lane++) begin
      if (payload_owed[lane]!=0) $fatal(1,"INDEXED_NATIVE_UNFINISHED_TILE");
      for (int region=0;region<4;region++)
        if (indexed_beats[lane][region]==0) $fatal(1,"INDEXED_NATIVE_MISSING_REGION");
      $display("INDEXED_NATIVE_READS lane=%0d pair_index=%0d pair_payload=%0d down_index=%0d down_payload=%0d",
        lane,indexed_beats[lane][0],indexed_beats[lane][1],indexed_beats[lane][2],indexed_beats[lane][3]);
    end
    $display("PARALLEL_CHIP_READS simultaneous_responses=%0d",simultaneous_responses);
""" + result[end:]

    start = result.index('    $fdisplay(progress_file,"BATCH408_FIXTURES_LOADED")')
    loading = """    begin
      int fd;
      string directory;
      if (!$value$plusargs("INDEXED_DIR=%s",directory)) $fatal(1,"INDEXED_NATIVE_IMAGE_DIR");
"""
    for name in ("pair_index", "pair_payload", "down_index", "down_payload"):
        loading += f"""      fd=$fopen({{directory,"/{name}.bin"}},"rb");
      if (!fd || $fread({name},fd)!=$size({name})) $fatal(1,"INDEXED_NATIVE_IMAGE_LENGTH {name}");
      $fclose(fd);
"""
    return result[:start] + loading + "    end\n" + result[start:]


def prepare(raw_stage, images, output):
    assert __debug__, "Use Python assertions"
    raw = json.loads((raw_stage / "inputs.json").read_text())
    image_receipt = images / "image.json"
    image = json.loads(image_receipt.read_text())
    for name, expected in image["sha256"].items():
        assert digest(Path(name)) == expected, name
        if name.endswith(("/pair.bin", "/down.bin")):
            assert raw["inputs"][name] == expected
    raw_bundle = raw_stage / "bundle.sv"
    bundle_text = raw_bundle.read_text()
    source_name, = re.findall(r'(?m)^`include "([^"]+/trained_writeback_tb\.sv)"$', bundle_text)
    original = Path(source_name)
    assert digest(original) == raw["inputs"][str(original)]
    assert digest(raw_bundle) == raw["inputs"][str(raw_bundle)]
    output.mkdir(parents=True)
    bench, bundle = output / "indexed_tb.sv", output / "bundle.sv"
    bench.write_text(testbench(original.read_text(), image))
    bundle.write_text(edit(bundle_text, [(str(original), str(bench))]))
    manifest = raw.copy()
    manifest["inputs"] = {name: value for name, value in raw["inputs"].items()
                          if name not in {str(original), str(raw_bundle)}}
    for path in (bench, bundle, image_receipt, original, Path(__file__).resolve()):
        manifest["inputs"][str(path)] = digest(path)
    for name, value in image["sha256"].items():
        if Path(name).parent == images:
            manifest["inputs"][name] = value
    manifest["args"] = [arg.replace(str(raw_stage), str(output)) for arg in raw["args"]]
    manifest["args"].append(f"+INDEXED_DIR={images}")
    manifest["raw_replay_stage"] = str(raw_stage)
    assert manifest["args"].count(str(bundle)) == 1
    (output / "inputs.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_stage", type=Path)
    parser.add_argument("images", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.raw_stage.resolve(), args.images.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()

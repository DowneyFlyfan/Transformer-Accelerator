"""Connect the archived indexed weight regression to the repaired write-stage cut."""

import argparse
import mmap
from pathlib import Path

from audit_tri_oracle_packed_weight_path import STAGE, module_body
from audit_tri_oracle_placed_chip_boundary import digest


def prepare_testbench(source):
    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError(f"Expected one archived testbench occurrence of {old!r}")
        source = source.replace(old, new)

    replace("  always #5 clk=~clk;", r"""
  logic [1:0] offered, granted, request_grant, staged_valid;
  logic stage_done, stage_error, stage_ready;
  logic [1:0][31:0] segment_rows, staged_rows;
  logic [1:0][511:0] segment_payload, staged_payload;
  logic [1:0][4:0] staged_core;
  logic [1:0][9:0] staged_addr;
  int concurrent_writes, same_cluster_conflicts;

  always #5 clk=~clk;
  weight_stream_write_arbiter arbiter (
    .clk,.rst_n,.offered,.core(load_core),.memory_ready(request_grant),.granted
  );
  tri_oracle_packed_write_stage_mapped stage (
    .clk,.rst_n,.load_valid(offered & granted),
    .\load_core[0] (load_core[0]),.\load_core[1] (load_core[1]),
    .\load_addr[0] (load_addr[0]),.\load_addr[1] (load_addr[1]),
    .\load_row_enable[0] (segment_rows[0]),.\load_row_enable[1] (segment_rows[1]),
    .\load_payload[0] (segment_payload[0]),.\load_payload[1] (segment_payload[1]),
    .write_valid(staged_valid),
    .\write_core[0] (staged_core[0]),.\write_core[1] (staged_core[1]),
    .\write_addr[0] (staged_addr[0]),.\write_addr[1] (staged_addr[1]),
    .\write_row_enable[0] (staged_rows[0]),.\write_row_enable[1] (staged_rows[1]),
    .\write_payload[0] (staged_payload[0]),.\write_payload[1] (staged_payload[1]),
    .loader_done_valid(&done_valid),.loader_done_error(|done_error),
    .done_ready(&done_ready),.loader_done_ready(stage_ready),
    .done_valid(stage_done),.done_error(stage_error)
  );
  always @(posedge clk) if (rst_n) begin
    if (&offered && load_core[0][4:2]==load_core[1][4:2]) same_cluster_conflicts++;
    if (&staged_valid) begin
      if (staged_core[0][4:2]==staged_core[1][4:2]) $fatal(1,"SAME_CLUSTER_WRITE_COLLISION");
      concurrent_writes++;
    end
    if (stage_done && |staged_valid) $fatal(1,"STAGED_DONE_EARLY");
  end
""".strip("\n"))

    replace(".done_ready(done_ready[lane])", ".done_ready(stage_ready && (&done_valid))")
    replace("    assign load_ready[lane]=cycle%7!=lane && cycle%7!=lane+2;", """
    assign request_grant[lane]=cycle%7!=lane && cycle%7!=lane+2;
    tri_oracle_weight_write_segments split (
      .clk,.rst_n,.decoded_valid(load_valid[lane]),.decoded_ready(load_ready[lane]),
      .decoded_rows(load_row_enable[lane]),.decoded_payload(load_data[lane]),
      .segment_valid(offered[lane]),.segment_ready(granted[lane]),
      .segment_rows(segment_rows[lane]),.segment_payload(segment_payload[lane])
    );
""".strip("\n"))

    start = source.index("      if(load_valid[lane] && load_ready[lane]) begin")
    end = source.index("\n    end\n  end\n", start)
    source = source[:start] + """      if (staged_valid[lane]) begin
        int core, word, part, sub, group, offset;
        core=int'(staged_core[lane]); word=int'(staged_addr[lane]); part=core%4; sub=-1;
        if (core<10*lane || core>=10*(lane+1) || word>=(tile_start==160 ? 16 : 32) ||
            !active_words[32*part+word]) $fatal(1,"STAGED_WRITE_ADDRESS");
        for (int i=0; i<4; i++) begin
          if (staged_rows[lane][8*i+:8]!='0) begin
            if (sub!=-1) $fatal(1,"STAGED_MULTIPLE_ROW_GROUPS");
            sub=i;
          end
        end
        if (sub<0 || (seen[lane][core][word] & (1<<sub))) $fatal(1,"STAGED_EMPTY_OR_DUPLICATE_GROUP");
        for (int i=0; i<8; i++) begin
          if (staged_rows[lane][8*sub+i] !== (32*(core/4)+8*sub+i<row_count && keep[32*(core/4)+8*sub+i]))
            $fatal(1,"STAGED_WRITE_ROW_MASK");
        end
        group=int'(first_row)/8+4*(core/4)+sub;
        offset=64*(group*704+part*176+int'(tile_start)+word);
        for (int i=0; i<64; i++) begin
          if (staged_payload[lane][8*i+:8]!==raw[offset+i])
            $fatal(1,"STAGED_WEIGHT_BYTE lane=%0d core=%0d word=%0d group=%0d byte=%0d",
                   lane,core,word,sub,i);
        end
        writes[lane]++;
        seen[lane][core][word] |= 1<<sub;
      end""" + source[end:]
    replace("logic [127:0] mask);", "logic [127:0] mask, bit shared_bank_only=0);")
    replace("keep='1;active_words=mask;", """keep=shared_bank_only ? 160'h00000000_00000000_ffffffff_00000000_00000000 : '1;
    active_words=mask;""")
    replace("32*(core/4)<count) begin", "32*(core/4)<count && |keep[32*(core/4)+:32]) begin")
    replace("expected[lane]+=words;", """begin
            int enabled_rows;
            enabled_rows=count-32*(core/4);
            expected[lane]+=words*(enabled_rows>=32 ? 4 : (enabled_rows+7)/8);
          end""")
    replace("wait(done_valid===2'b11);", "wait(stage_done===1'b1);")
    replace("if(done_error!==0)", "if(stage_error!==1'b0)")
    replace("256*(total_writes[0]+total_writes[1])!=2048*5632", "64*(total_writes[0]+total_writes[1])!=2048*5632")
    replace("256*(total_writes[0]+total_writes[1])!=237056", "64*(total_writes[0]+total_writes[1])!=237056")
    replace("256*(total_writes[0]+total_writes[1]),total_indices", "64*(total_writes[0]+total_writes[1]),total_indices")
    replace("INDEXED_DOWN_MATRIX_PASS", "STAGED_INDEXED_DOWN_MATRIX_PASS")
    replace('      $display("STAGED_INDEXED_DOWN_MATRIX_PASS', '''      $display("STAGED_MATRIX_CYCLES cycles=%0d",cycle);
      $display("STAGED_INDEXED_DOWN_MATRIX_PASS''')
    replace("    $finish;", """    begin
      int dense_segments, previous_conflicts;
      dense_segments=total_writes[0]+total_writes[1];
      previous_conflicts=same_cluster_conflicts;
      test_tile(0,160,0,'1,1);
      if (concurrent_writes==0 || same_cluster_conflicts<=previous_conflicts)
        $fatal(1,"WRITE_ARBITRATION_COVERAGE concurrent=%0d conflicts=%0d",
               concurrent_writes,same_cluster_conflicts);
      $display("STAGED_WRITES_PASS segments=%0d concurrent=%0d directed_conflicts=%0d",
               dense_segments,concurrent_writes,same_cluster_conflicts-previous_conflicts);
    end
    $finish;""")
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netlist", type=Path)
    parser.add_argument("testbench", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    if digest(args.netlist) != args.sha256:
        raise ValueError("Unexpected candidate netlist digest")
    with args.netlist.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        stage = b"module " + STAGE.encode() + b" (" + module_body(source, STAGE) + b"endmodule\n"
    testbench = prepare_testbench(args.testbench.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "write_stage.v").write_bytes(stage)
    (args.output / "indexed_down_staged_tb.sv").write_text(testbench)


if __name__ == "__main__":
    main()

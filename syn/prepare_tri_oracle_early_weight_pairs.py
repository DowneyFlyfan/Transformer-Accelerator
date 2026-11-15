"""Prepare a 512-bit output candidate from the existing indexed weight parser."""

import sys
from pathlib import Path

from prepare_tri_oracle_weight_segments_replay import prepare_testbench


def edit(text, changes):
    for original, replacement in changes:
        if text.count(original) != 1:
            raise ValueError(f"Expected one occurrence of {original!r}")
        text = text.replace(original, replacement)
    return text


def tile(source):
    return edit(source, [
        ("module weight_stream_tile  (", "module tri_oracle_early_pair_tile ("),
        ("  output logic [2047:0] write_data,",
         "  output logic [1:0] write_group,\n  output logic [511:0] write_data,"),
        ("  wire [4:0] LAST_WRITE=short_tile ? 5'd15 : 5'd31;\n", ""),
        ("logic raw, ended, next_pair, pop, push, pair_ready, pair_out;",
         "logic raw, ended, pair_half, pop, push, pair_ready, output_pair_valid;"),
        ("  logic [4:0] produced_word;\n  logic [1023:0] first_pair;",
         "  logic [5:0] produced_pairs;"),
        ("""  assign pair_ready = state == Run && (!next_pair || !write_valid || write_ready);
  assign pair_out = pair_ready && (&decoder_out_valid);
  assign decode_error = pair_out && (|decoder_out_error);""",
         """  // Both decoder outputs hold the pair until the second group is accepted.
  assign output_pair_valid = state == Run && (&decoder_out_valid);
  assign decode_error = output_pair_valid && (|decoder_out_error);
  assign pair_ready = state == Run && (decode_error || (pair_half && write_ready));
  assign write_valid = output_pair_valid && !decode_error;
  assign write_word = produced_pairs[5:1];
  assign write_group = {produced_pairs[0],pair_half};
  assign write_data = decoded[pair_half];"""),
        ("""      next_pair <= 0;
      produced_word <= 0;
      first_pair <= '0;
      write_valid <= 0;
      write_word <= 0;
      write_data <= '0;""", """      pair_half <= 0;
      produced_pairs <= 0;"""),
        ("""          next_pair <= 0;
          produced_word <= 0;
          write_valid <= 0;""", """          pair_half <= 0;
          produced_pairs <= 0;"""),
        ("""          if (write_valid && write_ready) begin
            write_valid <= 0;
            if (write_word == LAST_WRITE) state <= Done;
          end
          if (pair_out && !decode_error) begin
            next_pair <= !next_pair;
            if (!next_pair) first_pair <= {decoded[1], decoded[0]};
            else begin
              write_data <= {decoded[1], decoded[0], first_pair};
              write_word <= produced_word;
              write_valid <= 1;
              produced_word <= produced_word + 1'b1;
            end
          end""",
         """          if (write_valid && write_ready) begin
            pair_half <= !pair_half;
            if (pair_half) begin
              produced_pairs <= produced_pairs + 1'b1;
              if ({1'b0,produced_pairs} == PAIR_COUNT - 7'd1) state <= Done;
            end
          end"""),
        ("            status_error <= 1;\n            write_valid <= 0;",
         "            status_error <= 1;"),
    ])


def loader(source):
    return edit(source, [
        ("module weight_stream_loader  (", "module tri_oracle_early_pair_loader ("),
        ("[2047:0] load_data", "[511:0] load_data"),
        ("  logic [2047:0] decoded_data;",
         """  logic [511:0] decoded_data;
  logic [1:0] decoded_group;
  logic [31:0] tile_rows;"""),
        ("  assign load_addr = {5'b0,decoded_word};",
         "  assign load_addr = {5'b0,decoded_word};\n"
         "  assign load_row_enable = tile_rows & (32'hff << {decoded_group,3'b0});"),
        ("""    for (genvar group=0; group<4; group++) begin : rows
      assign load_data[512*group+8*byte_id +: 8] = decoded_data[512*group+511-8*byte_id -: 8];
    end""",
         "    assign load_data[8*byte_id+:8] = decoded_data[511-8*byte_id-:8];"),
        ("  weight_stream_tile decoder (", "  tri_oracle_early_pair_tile decoder ("),
        (".write_word(decoded_word), .write_data(decoded_data)",
         ".write_word(decoded_word), .write_group(decoded_group), .write_data(decoded_data)"),
        ("load_row_enable <= 0", "tile_rows <= 0"),
        ("load_row_enable <= cfg_row_enable", "tile_rows <= cfg_row_enable"),
    ])


def lane(source):
    return edit(source, [
        ("module weight_stream_indexed_lane #(", "module tri_oracle_early_pair_lane #("),
        ("[2047:0] load_data", "[511:0] load_data"),
        ("  assign load_valid = loader_write_valid && words[load_addr[4:0]];",
         """  wire group_kept = words[load_addr[4:0]] && (|load_row_enable);
  assign load_valid = loader_write_valid && group_kept;"""),
        ("  weight_stream_loader loader (", "  tri_oracle_early_pair_loader loader ("),
        (".load_ready(!words[load_addr[4:0]] || load_ready)", ".load_ready(!group_kept || load_ready)"),
    ])


def testbench(source):
    result = prepare_testbench(source)
    start = result.index("    tri_oracle_weight_write_segments split (")
    end = result.index("\n    );", start) + len("\n    );")
    result = result[:start] + """    assign offered[lane]=load_valid[lane];
    assign load_ready[lane]=granted[lane];
    assign segment_rows[lane]=load_row_enable[lane];
    assign segment_payload[lane]=load_data[lane];""" + result[end:]
    return edit(result, [
        ("weight_stream_indexed_lane #(", "tri_oracle_early_pair_lane #("),
        ("[2047:0] load_data;", "[511:0] load_data;"),
        ("bit shared_bank_only=0", "bit shared_bank_only=0, bit sparse_rows=0"),
        ("    active_words=mask;", """    if (sparse_rows) keep=160'h40000080_00000000_00800900_80000001_00000000;
    active_words=mask;"""),
        ("""            int enabled_rows;
            enabled_rows=count-32*(core/4);
            expected[lane]+=words*(enabled_rows>=32 ? 4 : (enabled_rows+7)/8);""",
         """            for (int g=0; g<4; g++) begin
              int enabled_rows;
              enabled_rows=0;
              for (int row=0; row<8; row++)
                if (32*(core/4)+8*g+row<count && keep[32*(core/4)+8*g+row])
                  enabled_rows++;
              if (enabled_rows>0) expected[lane]+=words;
            end"""),
        ("    $finish;", """    test_tile(0,160,0,'1,0,1);
    if (writes[0]!=384 || writes[1]!=384) $fatal(1,"SPARSE_SEGMENT_WRITE_CENSUS");
    $display("EARLY_PAIR_SPARSE_ROWS_PASS writes=%0d,%0d",writes[0],writes[1]);
    $finish;"""),
    ])


def stalled_header_testbench(source):
    start = source.index("    weight_stream_tile dut")
    end = source.index("\n\n    task automatic encode_body", start)
    original = source[start:end]
    ports = ".write_valid, .write_ready, .write_word, .write_data,"
    direct = original.replace("weight_stream_tile dut", "tri_oracle_early_pair_tile dut").replace(
        ports, ".write_valid, .write_ready, .write_word, .write_group, .write_data,")
    wide = original.replace(ports, ".write_valid(wide_valid), .write_ready(wide_ready), .write_word, .write_data(wide_data),")
    before = """`ifdef HOLD_WHOLE_WORD
    logic wide_valid, wide_ready;
    logic [2047:0] wide_data;
    logic [31:0] selected_rows;
    tri_oracle_weight_write_segments adapter (
        .clk,.rst_n,.decoded_valid(wide_valid),.decoded_ready(wide_ready),
        .decoded_rows(32'hffff_ffff),.decoded_payload(wide_data),
        .segment_valid(write_valid),.segment_ready(write_ready),
        .segment_rows(selected_rows),.segment_payload(write_data)
    );
    assign write_group = {(|selected_rows[31:16]),
                         ((|selected_rows[31:24]) || (|selected_rows[15:8]))};
"""
    return edit(source, [
        ("module weight_stream_tile_tb;", "module early_pair_tb;"),
        ("logic [2047:0] write_data;", "logic [511:0] write_data;\n    logic [1:0] write_group;"),
        (original, before + wide + "\n`else\n" + direct + "\n`endif"),
        ("writes >= 32 || write_word !== 5'(writes) || write_data !== expected[writes]",
         "writes >= 128 || write_word !== 5'(writes/4) || write_group !== 2'(writes%4) ||\n"
         "            write_data !== expected[writes/4][512*(writes%4)+:512]"),
        ("if (writes != 32)", "if (writes != 128)"),
        ("            if (beat == 68)", """            if (beat == 3) begin
                repeat (12) @(negedge clk);
                if (writes != 2) $fatal(1,"EARLY_PAIR_WAITED_FOR_SECOND_PAIR writes=%0d",writes);
            end
            if (beat == 68)"""),
        ("WEIGHT_TILE_STALLED_HEADER_PASS", "EARLY_PAIR_STALLED_HEADER_PASS"),
    ])


def stalled_loader_testbench(source):
    start = source.index("      if (writes>=32)")
    end = source.index("      writes++;", start)
    return edit(source, [
        ("logic [2047:0] load_data, expected[32];", "logic [511:0] load_data;\n  logic [2047:0] expected[32];"),
        ("weight_stream_loader dut", "tri_oracle_early_pair_loader dut"),
        (source[start:end], """      int group;
      group=writes%4;
      if (writes>=128) $fatal(1,"EXTRA_WRITE");
      if (load_core!==cfg_core ||
          load_row_enable!==(cfg_row_enable & (32'hff<<(8*group))) ||
          load_addr!==10'(writes/4))
        $fatal(1,"WRONG_WRITE_METADATA tile_core=%0d segment=%0d",cfg_core,writes);
      if (check_writes) begin
        for (int byte_id=0; byte_id<64; byte_id++)
          if (load_data[8*byte_id+:8] !== expected[writes/4][512*group+511-8*byte_id-:8])
            $fatal(1,"WRONG_WRITE_DATA word=%0d group=%0d byte=%0d",writes/4,group,byte_id);
      end
"""),
        ("writes!=32", "writes!=128"),
        ("fault==2 && writes>=32", "fault==2 && writes>=128"),
        ("LOADER_STREAM_PASS stall=", "EARLY_LOADER_STREAM_PASS stall="),
        (" writes=896 ", " writes=3584 "),
        ("#150us;", "#350us;"),
    ])


def main():
    indexed, out = map(Path, sys.argv[1:])
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "tile.sv": (tile, Path("verilog/weight_stream_tile.sv")),
        "loader.sv": (loader, indexed / "weight_stream_loader.sv"),
        "lane.sv": (lane, indexed / "weight_stream_indexed_lane.sv"),
        "indexed_tb.sv": (testbench, indexed / "parser_repair/indexed_down_tb.sv"),
        "early_pair_tb.sv": (stalled_header_testbench, Path("verilog/weight_stream_tile_tb.sv")),
        "early_loader_tb.sv": (stalled_loader_testbench, indexed / "compact_decoder/full_loader_tb.sv"),
        "malformed_tb.sv": (lambda text: edit(text, [
            ("weight_stream_tile dut", "tri_oracle_early_pair_tile dut"),
            (".write_word(), .write_data()", ".write_word(), .write_group(), .write_data()"),
        ]), indexed / "parser_repair/malformed_tile_tb.sv"),
    }
    for name, (transform, path) in paths.items():
        (out / name).write_text(transform(path.read_text()))


if __name__ == "__main__":
    main()

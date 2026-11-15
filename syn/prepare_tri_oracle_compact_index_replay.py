"""Insert the compact index link into the existing archived mapped weight replay."""
import argparse
import json
import mmap
from pathlib import Path
import re

from audit_tri_oracle_placed_fanout import sha
from check_tri_oracle_paper300_gate import BOUNDED_STAGE, BOUNDED_TOKEN_MAP_PLACEMENT

COLD = BOUNDED_STAGE / "native_token_map_buffer_candidate/cold/cold.v"
REFERENCE = BOUNDED_STAGE / "gate_full/test.sv"
ROOTS = ("tri_oracle_dual_group_weight_transport", "tri_oracle_packed_write_stage_mapped")
MODULE = re.compile(rb"(?m)^module\s+(\w+)\s*\(")
INSTANCE = re.compile(rb"(?m)^[ \t]+(\w+)\s+(?:\\\S+|[\w$]+)\s*\(\s*\.")


def extract(source, output):
    with source.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as raw:
        modules = {}
        for definition in MODULE.finditer(raw):
            name = definition[1].decode()
            end = raw.find(b"\nendmodule", definition.end())
            assert end >= definition.end() and name not in modules
            modules[name] = definition.start(), end + len(b"\nendmodule")
        used = set()
        pending = list(ROOTS)
        while pending:
            name = pending.pop()
            if name in used:
                continue
            begin,end = modules[name]
            used.add(name)
            for match in INSTANCE.finditer(raw,begin,end):
                kind = match[1].decode()
                if kind in modules and kind not in used:
                    pending.append(kind)
        with output.open("xb") as destination:
            for name in sorted(used,key=lambda label:modules[label][0]):
                begin,end = modules[name]
                destination.write(raw[begin:end]+b"\n\n")
    return sorted(used)


def transform(text):
    def replace(old,new):
        nonlocal text
        assert text.count(old) == 1, old
        text = text.replace(old,new,1)

    replace("module indexed_down_tb;", "module compact_index_replay_tb;")
    replace("  bit active[2];", """  bit active[2];
  logic [1:0] rsp_error;
  logic [1:0] link_valid, link_ready, link_compact, link_last, link_error;
  logic [1:0][2:0] link_words;
  logic [1:0][447:0] link_data;
  bit held[2];
  int fragment_word[2], compact_chunks[2], full_chunks[2];
  bit bad_index;
  initial bad_index=$test$plusargs("BAD_COMPACT_INDEX");""")
    replace(".rsp_error(2'b00),",".rsp_error(rsp_error),")

    start = text.index("    assign rsp_valid[lane]=active[lane]")
    end = text.index("    always @(posedge clk) if (rst_n) begin",start)
    replace(text[start:end], """    tri_oracle_compact_index_ingress ingress (
      .clk, .rst_n,
      .in_valid(link_valid[lane]), .in_ready(link_ready[lane]), .in_compact(link_compact[lane]),
      .in_data(link_data[lane]), .in_words(link_words[lane]), .in_last(link_last[lane]),
      .in_error(link_error[lane]), .out_valid(rsp_valid[lane]), .out_ready(rsp_ready[lane]),
      .out_data(rsp_data[lane]), .out_last(rsp_last[lane]), .out_error(rsp_error[lane])
    );
    always @(active[lane] or address[lane] or fragment_word[lane] or length[lane]
             or held[lane] or cycle or bad_index) begin
      int offset, words, left;
      offset=0;
      words=0;
      left=0;
      link_valid[lane]=0;
      link_data[lane]='0;
      link_last[lane]=0;
      link_compact[lane]=0;
      link_error[lane]=0;
      link_words[lane]=0;
      if (active[lane] && address[lane]<PAYLOAD && fragment_word[lane]==0) begin
        offset=int'(address[lane]-INDEX);
        link_compact[lane]=1;
        link_words[lane]=2;
        link_last[lane]=1;
        link_valid[lane]=held[lane] || cycle%4!=lane;
        for(int i=0;i<16;i++) link_data[lane][8*i+:8]=indices[offset+i];
        for(int i=16;i<64;i++) link_error[lane] |= |indices[offset+i];
        if(bad_index) link_data[lane][79]=1;
      end else if(active[lane] && address[lane]>=PAYLOAD &&
                  fragment_word[lane]<length[lane]*8) begin
        offset=int'(address[lane]-PAYLOAD)+8*fragment_word[lane];
        left=length[lane]*8-fragment_word[lane];
        words=left<7 ? left : 7;
        link_words[lane]=3'(words);
        link_last[lane]=words==left;
        link_valid[lane]=held[lane] || cycle%4!=lane;
        for(int i=0;i<56;i++)
          if(i<8*words) link_data[lane][8*i+:8]=payload[offset+i];
      end
    end
""")
    replace("      if (req_valid[lane] && req_ready[lane]) begin", """      held[lane]<=link_valid[lane] && !link_ready[lane];
      if (link_valid[lane] && link_ready[lane]) begin
        fragment_word[lane]<=fragment_word[lane]+int'(link_words[lane]);
        if(link_compact[lane]) compact_chunks[lane]++;
        else full_chunks[lane]++;
      end
      if (req_valid[lane] && req_ready[lane]) begin
        fragment_word[lane]<=0;""")
    replace("    if ($test$plusargs(\"FULL_MATRIX\")) begin", """    if (bad_index) begin
      first_row=0;row_count=160;tile_start=0;keep='1;active_words='1;
      cfg_indexed=1;
      cfg_valid=1;
      @(negedge clk);
      cfg_valid=0;
      cfg_indexed=0;
      wait(stage_done===1'b1);
      @(negedge clk);
      if(stage_error!==1 || compact_chunks[0]==0 || compact_chunks[1]==0 ||
         data_beats[0]!=0 || data_beats[1]!=0 || wide_writes[0]!=0 || wide_writes[1]!=0)
        $fatal(1,"COMPACT_INDEX_RESERVED_BIT_WAS_NOT_REJECTED");
      $display("COMPACT_INDEX_BAD_RESERVED_REJECTED compact0=%0d compact1=%0d",compact_chunks[0],compact_chunks[1]);
      $finish;
    end else if ($test$plusargs("FULL_MATRIX")) begin""")
    replace('      $display("DUAL_GROUP_MATRIX_WRITES', '''      if(compact_chunks[0]!=780 || compact_chunks[1]!=756 || full_chunks[0]==0 || full_chunks[1]==0)
        $fatal(1,"COMPACT_INDEX_MAPPED_INVENTORY");
      $display("COMPACT_INDEX_MATRIX_PASS compact0=%0d compact1=%0d payload_chunks0=%0d payload_chunks1=%0d",
               compact_chunks[0],compact_chunks[1],full_chunks[0],full_chunks[1]);
      $display("DUAL_GROUP_MATRIX_WRITES''')
    return text


def prepare(out):
    assert Path("/.dockerenv").is_file()
    placement = json.loads(BOUNDED_TOKEN_MAP_PLACEMENT.read_text())
    assert sha(COLD) == placement["cold_netlist_sha256"]
    out.mkdir(exist_ok=True)
    mapped, bench = (out/name for name in ("current_weight_cut.v","compact_index_replay_tb.sv"))
    reachable = extract(COLD,mapped)
    bench.write_text(transform(REFERENCE.read_text()))
    sources = (mapped,bench,REFERENCE,BOUNDED_TOKEN_MAP_PLACEMENT,Path(__file__))
    receipt = dict(state="compact_index_xcelium_input_prepared",
                   cold_netlist_sha256=placement["cold_netlist_sha256"], native_modules=reachable,
                   evidence_sha256={str(path):sha(path) for path in sources})
    (out/"prepared.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n")
    print("COMPACT_INDEX_REPLAY_PREPARED",len(reachable),mapped.stat().st_size)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    prepare(parser.parse_args().output)

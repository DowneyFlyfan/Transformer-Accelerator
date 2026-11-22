"""Integrate captured command ownership into the qualified cluster source.

The source must expose the existing four-core score selector, compiled aggregate
memory and ordered output queue. All external ports and other module bodies are
preserved. The generated composition also needs tri_oracle_cluster_return_owner.sv.
"""
import argparse
import hashlib
import json
from pathlib import Path

def edit(text,old,new):
    if text.count(old)!=1:raise ValueError(f'Expected exactly one source anchor: {old}')
    return text.replace(old,new)

def corrected_cluster(original):
    text=edit(original,'  logic [1:0] selected_core;', '''  logic [1:0] selected_core;
  logic [3:0] read_head, required_read_cores, response_cores;
  logic [2:0] response_owner;
  logic read_inflight;
  tri_oracle_cluster_return_owner return_owner (
    .clk,.rst_n,.issue,.issue_slot(cmd_output),.issue_owner(core_score_select),
    .reserved,.done,.done_slots,.next_slot(done_slot),.read_head,
    .read_valid(done_aligned),.read_cores(required_read_cores),
    .response_pending(read_inflight),.response_slot(read_slot),
    .response_owner,.response_cores
  );''')
    text=edit(text,'  assign core_read = active_cores & {4{done_aligned}};',
              '  assign core_read = required_read_cores & {4{done_aligned}};')
    text=edit(text,"  assign done_slot = done_slots[4*int'(core_score_select[2] ? selected_core : 2'd0)+:4];",
              '  assign done_slot = tag_queue[read_head];')
    text=edit(text,'''    done_aligned = core_score_select[2] ? done[selected_core] : (&done) && done_slots[7:4] == done_slots[3:0]
                   && done_slots[11:8] == done_slots[3:0]
                   && done_slots[15:12] == done_slots[3:0];
    aggregate_write = rst_n && (&(result_valid | ~active_cores));''',
              '    aggregate_write = rst_n && read_inflight && ((result_valid & response_cores)==response_cores);')
    text=edit(text,"      reduced_words[row*32+:32] = core_score_select[2] ? result_words[1024*int'(selected_core)+row*32+:32] : reduce_four(",
              "      reduced_words[row*32+:32] = response_owner[2] ? result_words[1024*int'(response_owner[1:0])+row*32+:32] : reduce_four(")
    text=edit(text,'      read_slot <= 0;\n','')
    text=edit(text,'      if (done_aligned) read_slot <= done_slot;\n','')
    if text.split('\n);',1)[0]!=original.split('\n);',1)[0]:raise ValueError('External interface changed')
    if text.split('endmodule',1)[1]!=original.split('endmodule',1)[1]:raise ValueError('Another module changed')
    return text

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.source.resolve()==args.output.resolve():raise ValueError('Preserve the original source')
    result=corrected_cluster(args.source.read_text())
    with args.output.open('x') as stream:stream.write(result)
    print(json.dumps(dict(source_sha256=sha(args.source),output_sha256=sha(args.output),
        external_ports_unchanged=True,other_modules_unchanged=True,
        additional_control_state_bits=125,additional_arrays=0,additional_memory_macros=0,
        paper_matching=False)))

if __name__=='__main__':main()

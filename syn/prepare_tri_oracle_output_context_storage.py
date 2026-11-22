"""Expose existing core output slots through the existing load/command ports.

Load kind3 writes slots14/15; addresses16/17 release their compute reservation.
Reduce3 reads previously written outputs without array execution: one selected
core or the sum of all four. Owned context slots14/15 require unicast; four-core
reads of those slots are rejected while any core owns a context there.
The caller keeps head/query/epoch ownership until
the ordered cluster result retires. No data-memory or array instance is added.
"""
import argparse
import hashlib
import json
from pathlib import Path

def edit(text,old,new):
    if text.count(old)!=1:raise ValueError(f'Expected exactly one source anchor: {old}')
    return text.replace(old,new)

def core_with_context(original):
    text=edit(original,'  logic accepted_load, compute_enabled, softmax_configure, softmax_owns_input;',
'''  // Output slots share the existing macro ports; no context data flops.
  logic [2:0] context_outstanding;
  logic [1:0] context_owned;
  logic matrix_load_ready, context_load_ready, context_write, context_release;
  logic [3:0] output_write_address;
  logic [1023:0] output_write_data;
  logic accepted_load, compute_enabled, softmax_configure, softmax_owns_input;''')
    text=edit(text,'  assign accepted_load = load_valid && load_ready;',
'''  assign context_load_ready = rst_n && context_outstanding==0 && !read_valid
                              && !result_valid && !writeback_valid;
  assign load_ready = load_kind==3 ? context_load_ready : matrix_load_ready;
  assign accepted_load = load_valid && load_ready;
  assign context_write = accepted_load && load_kind==3 && load_addr>=14 && load_addr<=15;
  assign context_release = accepted_load && load_kind==3 && load_addr>=16 && load_addr<=17;
  assign output_write_address = context_write ? load_addr[3:0] : writeback_slot;
  assign output_write_data = context_write ? load_data[1023:0] : writeback_data;''')
    text=edit(text,'    .clk, .rst_n, .load_ready, .activation_reloaded, .activation_reload_required,',
              '    .clk, .rst_n, .load_ready(matrix_load_ready), .activation_reloaded, .activation_reload_required,')
    text=edit(text,'    cmd_ready = compute_enabled && array_ready && !accepted_load;',
'''    cmd_ready = compute_enabled && array_ready && !accepted_load
                && !(cmd_output>=14 && context_owned[cmd_output[0]]);''')
    text=edit(text,'    output_web = !(rst_n && writeback_valid);',
              '    output_web = !(rst_n && (writeback_valid || context_write));')
    text=edit(text,'    .AA(writeback_slot), .AB(memory_read_address), .D(writeback_data), .Q(output_q)',
              '    .AA(output_write_address), .AB(memory_read_address), .D(output_write_data), .Q(output_q)')
    text=edit(text,'      command_pending <= 0;',
              '      context_outstanding <= 0;\n      context_owned <= 0;\n      command_pending <= 0;')
    text=edit(text,'''      load_error <= accepted_load && (load_kind == 3
                                  || ((load_kind == 0 || load_kind == 2) && load_addr >= 32));''',
'''      case ({accept_command,done_valid})
        2'b10: context_outstanding <= context_outstanding+3'd1;
        2'b01: context_outstanding <= context_outstanding-3'd1;
        default: ;
      endcase
      if (context_write) context_owned[load_addr[0]] <= 1;
      if (context_release) context_owned[load_addr[0]] <= 0;
      if (context_write && recent_valid && recent_slot==load_addr[3:0]) recent_valid <= 0;
      load_error <= accepted_load && (((load_kind == 0 || load_kind == 2) && load_addr >= 32)
                                  || (load_kind==3 && (load_addr<14 || load_addr>17)));''')
    if text.split('\n);',1)[0]!=original.split('\n);',1)[0]:raise ValueError('Core interface changed')
    return text

def cluster_with_context(original):
    text=edit(original,'  logic [3:0] ready, done, result_valid, load_errors, core_load;',
'''  logic [3:0] compute_done, context_done;
  logic [15:0] compute_done_slots;
  logic [3:0] context_done_slot;
  logic [3:0][1:0] context_owned;
  logic [3:0][15:0] stored_valid;
  logic context_read, context_load_blocked, stored_read_valid;
  logic [3:0] ready, done, result_valid, load_errors, core_load;''')
    text=edit(text,'  assign core_issue = active_cores & {4{issue}};',
              '  assign core_issue = active_cores & {4{issue && !context_read}};')
    text=edit(text,'''    load_error = (|load_errors) || (load_valid && !core_load_ready[load_core]);
    cmd_ready = (&(ready | ~active_cores)) && !load_valid && count < 16
                && !reserved[cmd_output] && cmd_reduce != 3;''',
'''    context_read = cmd_reduce==3;
    context_load_blocked = load_valid && load_kind==3 && count!=0;
    load_error = (|load_errors) || (load_valid && !core_load_ready[load_core]) || context_load_blocked;
    stored_read_valid = 1;
    done = compute_done | context_done;
    for (integer c=0;c<4;c++) begin
      done_slots[c*4+:4] = context_done[c] ? context_done_slot : compute_done_slots[c*4+:4];
      if (active_cores[c] && !stored_valid[c][cmd_output]) stored_read_valid=0;
      if (!core_score_select[2] && cmd_output>=14 && context_owned[c][cmd_output[0]]) stored_read_valid=0;
    end
    cmd_ready = !load_valid && !reserved[cmd_output] &&
        (context_read ? count==0 && stored_read_valid && !cmd_accumulate :
         (&(ready | ~active_cores)) && count<16);''')
    text=edit(text,'    for (integer c = 0; c < 4; c++) core_load[c] = load_valid && load_core == 2\'(c);',
              '    for (integer c = 0; c < 4; c++) core_load[c] = load_valid && load_core == 2\'(c) && !context_load_blocked;')
    text=edit(text,'    .done_valid(done), .done_output(done_slots),',
              '    .done_valid(compute_done), .done_output(compute_done_slots),')
    text=edit(text,'      reserved <= 0;',
'''      context_done <= 0;
      context_done_slot <= 0;
      context_owned <= 0;
      stored_valid <= 0;
      reserved <= 0;''')
    text=edit(text,'''      case ({issue, retire})''',
'''      context_done <= issue && context_read ? active_cores : 4'b0;
      if (issue && context_read) context_done_slot <= cmd_output;
      if (issue && !context_read)
        for (integer c=0;c<4;c++) if (active_cores[c]) stored_valid[c][cmd_output] <= 1;
      if (load_valid && load_kind==3 && !context_load_blocked && core_load_ready[load_core]) begin
        if (load_addr>=14 && load_addr<=15) begin
          context_owned[load_core][load_addr[0]] <= 1;
          stored_valid[load_core][load_addr[3:0]] <= 1;
        end
        if (load_addr>=16 && load_addr<=17) begin
          context_owned[load_core][load_addr[0]] <= 0;
          stored_valid[load_core][4'd14+4'(load_addr[0])] <= 0;
        end
      end
      case ({issue, retire})''')
    if text.split('\n);',1)[0]!=original.split('\n);',1)[0]:raise ValueError('Cluster interface changed')
    if text.split('endmodule',1)[1]!=original.split('endmodule',1)[1]:raise ValueError('Other cluster modules changed')
    return text

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['core_source','cluster_source','output_core','output_cluster']:parser.add_argument(name,type=Path)
    args=parser.parse_args();sources=[args.core_source,args.cluster_source];outputs=[args.output_core,args.output_cluster]
    if len({p.resolve() for p in [*sources,*outputs]})!=4:raise ValueError('Keep every input and output path distinct')
    if any(p.exists() or p.is_symlink() for p in outputs):raise ValueError('Preserve existing outputs')
    core=core_with_context(sources[0].read_text());cluster=cluster_with_context(sources[1].read_text())
    with outputs[0].open('x') as stream:stream.write(core)
    try:
        with outputs[1].open('x') as stream:stream.write(cluster)
    except BaseException:
        outputs[0].unlink();raise
    print(json.dumps(dict(source_sha256={str(p):sha(p) for p in sources},output_sha256={str(p):sha(p) for p in outputs},
        external_ports_unchanged=True,additional_control_state_bits_per_cluster=100,
        additional_arrays=0,additional_data_register_bits=0,additional_memory_macros=0,paper_matching=False)))
if __name__=='__main__':main()

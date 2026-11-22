"""Extend existing output-memory leases for complete-head packed score storage.

Kind3 writes0..15 lease that slot. Legacy16/17 release14/15. Generic32..47
release0..15. All other kind3addresses are rejected. External ports, memory
instances, array instances and stored data widths remain unchanged.
"""
from pathlib import Path
import argparse,hashlib,json

def edit(text,before,after):
    if text.count(before)!=1:raise ValueError('Expected one source anchor: '+before)
    return text.replace(before,after)

def core(source):
    text=edit(source,'  logic [1:0] context_owned;', '  logic [15:0] context_owned;\n  logic [3:0] context_release_slot;')
    text=edit(text,'  assign context_write = accepted_load && load_kind==3 && load_addr>=14 && load_addr<=15;',
        '  assign context_write = accepted_load && load_kind==3 && load_addr<16;')
    text=edit(text,'  assign context_release = accepted_load && load_kind==3 && load_addr>=16 && load_addr<=17;',
        '  assign context_release = accepted_load && load_kind==3 && ((load_addr>=16 && load_addr<=17) || (load_addr>=32 && load_addr<=47));\n  assign context_release_slot = load_addr>=32 ? load_addr[3:0] : 4\'d14+4\'(load_addr[0]);')
    text=edit(text,'&& !(cmd_output>=14 && context_owned[cmd_output[0]]);','&& !context_owned[cmd_output];')
    text=edit(text,'if (context_write) context_owned[load_addr[0]] <= 1;','if (context_write) context_owned[load_addr[3:0]] <= 1;')
    text=edit(text,'if (context_release) context_owned[load_addr[0]] <= 0;','if (context_release) context_owned[context_release_slot] <= 0;')
    text=edit(text,'(load_kind==3 && (load_addr<14 || load_addr>17))','(load_kind==3 && !((load_addr<=17) || (load_addr>=32 && load_addr<=47)))')
    assert text.split('\n);',1)[0]==source.split('\n);',1)[0]
    return text

def cluster(source):
    text=edit(source,'  logic [3:0][1:0] context_owned;', '  logic [3:0][15:0] context_owned;\n  logic [3:0] context_release_slot;')
    text=edit(text,'    context_read = cmd_reduce==3;', "    context_read = cmd_reduce==3;\n    context_release_slot = load_addr>=32 ? load_addr[3:0] : 4'd14+4'(load_addr[0]);")
    text=edit(text,'if (!core_score_select[2] && cmd_output>=14 && context_owned[c][cmd_output[0]]) stored_read_valid=0;',
        'if (!core_score_select[2] && context_owned[c][cmd_output]) stored_read_valid=0;')
    text=edit(text,'if (load_addr>=14 && load_addr<=15) begin', 'if (load_addr<16) begin')
    text=edit(text,'context_owned[load_core][load_addr[0]] <= 1;', 'context_owned[load_core][load_addr[3:0]] <= 1;')
    text=edit(text,'if (load_addr>=16 && load_addr<=17) begin', 'if ((load_addr>=16 && load_addr<=17) || (load_addr>=32 && load_addr<=47)) begin')
    text=edit(text,'context_owned[load_core][load_addr[0]] <= 0;', 'context_owned[load_core][context_release_slot] <= 0;')
    text=edit(text,"stored_valid[load_core][4'd14+4'(load_addr[0])] <= 0;", 'stored_valid[load_core][context_release_slot] <= 0;')
    assert text.split('\n);',1)[0]==source.split('\n);',1)[0]
    assert text.split('endmodule',1)[1]==source.split('endmodule',1)[1]
    return text

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['input_core','input_cluster','output_core','output_cluster']:parser.add_argument(name,type=Path)
    args=parser.parse_args();inputs=[args.input_core,args.input_cluster];outputs=[args.output_core,args.output_cluster]
    if len({p.resolve() for p in [*inputs,*outputs]})!=4:raise ValueError('Input and output paths must be distinct')
    if any(p.exists() or p.is_symlink() for p in outputs):raise FileExistsError('Preserve existing outputs')
    generated=[core(inputs[0].read_text()),cluster(inputs[1].read_text())]
    with outputs[0].open('x') as stream:stream.write(generated[0])
    try:
        with outputs[1].open('x') as stream:stream.write(generated[1])
    except BaseException:outputs[0].unlink();raise
    print(json.dumps(dict(state='full_output_slot_leases_generated_not_native_verified',
        input_sha256={str(p):sha(p) for p in inputs},output_sha256={str(p):sha(p) for p in outputs},
        added_control_state_bits_per_cluster=112,new_data_register_bits=0,new_memory_macros=0,new_arrays=0,
        external_ports_unchanged=True,legacy_value_context_addresses_preserved=True,native_verified=False,paper_matching=False)))
if __name__=='__main__':main()

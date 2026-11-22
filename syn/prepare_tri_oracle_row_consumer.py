"""Recreate scalar row-consumer fixtures and native simulator source bundles.

This is a local numeric-format reconstruction, not the paper's undisclosed
quantization recipe or a trained layer. Two tiny metadata slices come from the
frozen checkpoint export; every raw projection input is synthetic. Generated
vectors and simulator builds belong under this project's .cache directory.

Example: python3 -B syn/prepare_tri_oracle_row_consumer.py --output-directory
.cache/row_consumer_replay
Run the emitted bundles with Xcelium using the printed fixture directory.
"""
import argparse
import hashlib
import json
from pathlib import Path

from tri_oracle_model_reference import requantize, silu_code

ROOT = Path(__file__).resolve().parents[1]
# count, tokens, packed units, gate shifts, up shifts, down shifts, metadata layer.
CASES = [(80, 3, '000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000', '000000000000000000008040', '00000000000000000000c100', '000000000000000000003040', None), (80, 3, 'dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848', '000000000000000000008040', '00000000000000000000c100', '000000000000000000003040', None), (32, 1, '000000000000000000000000000000000000000000000000000000000000000000000000dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848', '000000000000000000000000', '000000000000000000000000', '000000000000000000000000', None), (80, 16, 'dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848dde16c4fa848', '040e30818201038c20608040', '80c100e3080c100e3080c100', '2030407d02030407d0203040', None), (80, 3, '28a4932ca4ca4d228a0ca48a28a28a48a29228b2d328a2cb28b48b4524ca28a28a48a48a4cb4d248a4c949348a2d229348a29348a28a29228a48a292', '000000000000000000008040', '00000000000000000000c100', '000000000000000000003040', 0), (32, 3, '00000000000000000000000000000000000000000000000000000000000000000000000089b8db6db6db6dc89b8db6db6e38a38db6da6e36e26db6db', '000000000000000000008040', '00000000000000000000c100', '000000000000000000003040', 21)]

RAW_VALUES = (512,-512,256,-256,1024,-1024,4096,-4096,2147483647,-2147483648,1,-1,32767,-32768)


def prepare(output):
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT/'.cache') or output==ROOT/'.cache':
        raise ValueError('Output must be below the project .cache directory')
    output.mkdir(parents=True,exist_ok=False)
    words={name:[] for name in ['raw','gated','wide','coarse','correction','row_units','gate_shifts','up_shifts','down_shifts']}
    packet_count=0;active_count=0;shared_shift_differences=0
    for count,tokens,unit_hex,gate_hex,up_hex,down_hex,metadata_layer in CASES:
        units=int(unit_hex,16);gate_shifts=int(gate_hex,16);up_shifts=int(up_hex,16);down_shifts=int(down_hex,16)
        for name,value in [('row_units',units),('gate_shifts',gate_shifts),('up_shifts',up_shifts),('down_shifts',down_shifts)]:
            words[name].append(value)
        for token in range(tokens):
            raw=gated=wide=coarse=correction=0
            gate_base=(gate_shifts>>(token*6))&63;up_base=(up_shifts>>(token*6))&63;down_shift=(down_shifts>>(token*6))&63
            for lane in range(count):
                gate_value=512 if lane==0 else RAW_VALUES[(lane+token)%len(RAW_VALUES)]
                up_value=512 if lane==0 else RAW_VALUES[(5*lane+token+2)%len(RAW_VALUES)]
                paired_lane=(lane//16)*32+lane%16
                raw|=(gate_value&0xffffffff)<<(paired_lane*32)
                raw|=(up_value&0xffffffff)<<((paired_lane+16)*32)
                gate_offset=(units>>(lane*6))&7;up_offset=(units>>(lane*6+3))&7
                g=requantize(gate_value,gate_base+gate_offset,16);u=requantize(up_value,up_base+up_offset,16)
                value=requantize(silu_code(g)*u,8,16)
                wide_value=requantize(value,down_shift,16);coarse_value=requantize(value,down_shift,8)
                correction_value=max(-128,min(127,wide_value-coarse_value))
                old=requantize(silu_code(requantize(gate_value,gate_base,16))*requantize(up_value,up_base,16),8,16)
                shared_shift_differences+=value!=old
                gated|=(value&65535)<<(lane*16);wide|=(wide_value&65535)<<(lane*16)
                coarse|=(coarse_value&255)<<(lane*8);correction|=(correction_value&255)<<(lane*8)
                active_count+=1
            for name,value in [('raw',raw),('gated',gated),('wide',wide),('coarse',coarse),('correction',correction)]:words[name].append(value)
            packet_count+=1
    widths=dict(raw=5120,gated=1280,wide=1280,coarse=640,correction=640,row_units=480,gate_shifts=96,up_shifts=96,down_shifts=96)
    for name,values in words.items():
        (output/(name+'.hex')).write_text(''.join(f'{value:0{widths[name]//4}x}\n' for value in values))
    assert (packet_count,active_count,shared_shift_differences)==(29,2128,573)
    bundles={}
    for name,testbench,define in [('row_unit_bundle.sv','tri_oracle_row_weight_consumer_tb.sv',True),('row_boundary_bundle.sv','tri_oracle_row_boundary_tb.sv',False)]:
        paths=[ROOT/'verilog/tri_oracle_silu_gate.sv',ROOT/'verilog/tri_oracle_row_nonlinear.sv',ROOT/'verilog'/testbench]
        content=('`define ROW_UNIT_CONSUMER\n' if define else '')+''.join(f'`include "{path}"\n' for path in paths)
        (output/name).write_text(content);bundles[name]=[str(p.relative_to(ROOT)) for p in paths]
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    receipt=dict(state='scalar_row_consumer_fixtures_prepared_not_executed',cases=6,packets=packet_count,active_channel_values=active_count,shared_shift_counterfactual_differences=shared_shift_differences,fixture_sha256={p.name:sha(p) for p in sorted(output.glob('*.hex'))},bundle_sha256={name:sha(output/name) for name in bundles},source_sha256={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/'syn/tri_oracle_model_reference.py',ROOT/'verilog/tri_oracle_silu_gate.sv',ROOT/'verilog/tri_oracle_row_nonlinear.sv',ROOT/'verilog/tri_oracle_row_weight_consumer_tb.sv',ROOT/'verilog/tri_oracle_row_boundary_tb.sv']},whole_trained_layer_verified=False,paper_matching=False)
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',required=True,type=Path)
    arguments=parser.parse_args();receipt=prepare(arguments.output_directory)
    print(json.dumps(dict(fixture_directory=str(arguments.output_directory.resolve()),cases=receipt['cases'],packets=receipt['packets'],native_execution_verified=False)))


if __name__=='__main__':main()

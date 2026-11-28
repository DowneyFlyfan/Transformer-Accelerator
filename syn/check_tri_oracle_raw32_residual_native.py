"""Independent closed-log residual/native-C checker; standard library only.

The checker never launches RTL, Tensor libraries, native binaries or a compiler.
All reference arithmetic follows capture of every actual packet/ACK/C output.
Input metadata and original raw/gamma bytes must be explicitly SHA-bound.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import struct
import time

resource.setrlimit(resource.RLIMIT_AS,(2<<30,2<<30))
resource.setrlimit(resource.RLIMIT_CPU,(120,120))
READS={}

def need(condition,reason):
    if not condition:raise ValueError(reason)

def identity(s):return[s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

def read(path,sha=None):
    path=Path(path).resolve(strict=True);before=identity(path.stat());need(before[5]<=64<<20,'bounded actual log/input required')
    with path.open('rb')as stream:
        need(identity(os.fstat(stream.fileno()))==before,'opened identity');raw=stream.read(before[5]+1)
        need(len(raw)==before[5]and stream.read(1)==b''and identity(os.fstat(stream.fileno()))==before,'complete FD/EOF')
    need(identity(path.stat())==before,'final path identity');h=hashlib.sha256(raw).hexdigest();need(sha is None or h==sha,'input SHA mismatch')
    READS[str(path)]=dict(path=str(path),sha256=h,bytes=len(raw),identity_before=before,identity_after_fd=before,identity_after_path=before,complete_EOF=True)
    return raw

def power(unit):return Fraction(1<<unit)if unit>=0 else Fraction(1,1<<(-unit))
def nearest(value):
    absolute=abs(value);word=(2*absolute.numerator+absolute.denominator)//(2*absolute.denominator)
    return -word if value<0 else word

def select_and_recode(old,down,old_unit,down_unit):
    need(len(old)==len(down)and old,'complete residual operands')
    physical=[a*power(old_unit)+b*power(down_unit)for a,b in zip(old,down)]
    maximum=max(map(abs,physical));selected=0
    if maximum:
        for selected in range(-32,98):
            if maximum<=((1<<31)-1)*power(selected):break
        else:raise ValueError('residual unit exceeds97')
    words=[nearest(value/power(selected))for value in physical]
    need(all(abs(v)<1<<31 for v in words),'residual symmetric signed32 range')
    epsilon=nearest(power(16-2*selected)/100000)if selected<=0 else 0
    return words,selected,epsilon

def normalize(raw,gain,epsilon,gamma_unit):
    need(len(raw)==len(gain)==2048,'complete native C feature/gain vectors')
    need(all(-(1<<23)<=v<(1<<23)for v in gain),'original signed24 gamma')
    n=len(raw);denominator=(sum(v*v for v in raw)<<16)+epsilon*n;need(denominator>0,'positive C denominator')
    products=[a*b for a,b in zip(raw,gain)];maximum=max(map(abs,products));shift=0
    while maximum*maximum*n*(1<<16)>16129*denominator*(1<<(2*shift)):
        shift+=1;need(shift<=23,'C scale domain')
    d=denominator*(1<<(2*shift));codes=[]
    for product in products:
        numerator=product*product*n*(1<<16);floor=math.isqrt(numerator//d)
        rounded=floor+int(4*numerator>=(2*floor+1)**2*d)
        signed=-rounded if product<0 else rounded;codes.append(max(-128,min(127,signed)))
    return dict(codes=codes,activation_exponent=gamma_unit+shift if maximum else 0,
        outlier_mask=[v*v*n*(1<<16)>9*denominator for v in raw],
        normalized_negative=[v<0 for v in products],
        outlier_negative=[v<0 and v*v*n*(1<<16)>9*denominator for v in raw])

def records(console,marker,pattern,count):
    lines=[line for line in console.splitlines()if line.startswith(marker+' ')]
    need(len(lines)==count,'exact record count '+marker)
    out=[]
    for line in lines:
        match=re.fullmatch(pattern,line);need(match is not None,'malformed record '+marker);out.append(match.groups())
    return out

def check(args):
    started=time.monotonic();raw_bytes=read(args.original_raw,args.original_raw_sha256)
    metadata=read(args.original_metadata,args.original_metadata_sha256);gamma_bytes=read(args.gamma,args.gamma_sha256)
    need(len(raw_bytes)==8192 and len(metadata)==16 and len(gamma_bytes)==6144,'original row/metadata/gamma exact extents')
    console=read(args.console,args.console_sha256).decode('utf-8');need('RAW32_RESIDUAL_COMPLETE_NATIVE_PASS 'in console,'closed native complete marker missing')
    need(not any(token in console for token in ('$fatal','*F,','Fatal:','RAW32_RESIDUAL_FIRST_SCRATCH_PROGRESS_ONLY_PASS')),'native failure or superseded partial marker')
    old=list(struct.unpack('<2048i',raw_bytes));need(all(v!=-(1<<31)for v in old),'symmetric original raw domain')
    meta=int.from_bytes(metadata,'little');old_unit=int.from_bytes(metadata[8:9],'little',signed=True);old_epsilon=meta&((1<<64)-1)
    root=(meta>>72)&1023;rank=(meta>>82)&1023;position=(meta>>92)&1023;layer=(meta>>102)&31;epoch=(meta>>107)&65535
    need((meta>>123)==0 and root==rank==layer==0 and position==5 and epoch==1,'bound original first-row metadata')
    need(-32<=old_unit<=97 and old_epsilon==(nearest(power(16-2*old_unit)/100000)if old_unit<=0 else 0),'bound original physical epsilon')
    raw_records=records(console,'FULL_FF_RAW',r'FULL_FF_RAW cycle=(\d+) tag=([0-9a-fA-F]{8}) start=(\d+) count=(\d+) last=([01]) eOut=(-?\d+) data=([0-9a-fA-F]{1280})',13)
    down=[];down_units=set();packet_cycles=[]
    for number,(cycle,tag,start,count,last,unit,hexdata)in enumerate(raw_records):
        expected=128 if number==12 else 160
        need(int(tag,16)==0x504f0000 and int(start)==number*160 and int(count)==expected and int(last)==(number==12),'real native DOWN packet association')
        words=list(struct.unpack('<160i',int(hexdata,16).to_bytes(640,'little')))
        need(all(v==0 for v in words[expected:]),'actual final DOWN padding');need(all(abs(v)<=92274688 for v in words[:expected]),'native DOWN bound')
        down.extend(words[:expected]);down_units.add(int(unit));packet_cycles.append(int(cycle))
    need(len(down)==2048 and down_units=={-17},'complete bound actual native DOWN operands/unit')
    expected_raw,unit,epsilon=select_and_recode(old,down,old_unit,-17)
    raw_ack=records(console,'RAW32_RESIDUAL_RAW_ACK_DATA',r'RAW32_RESIDUAL_RAW_ACK_DATA cycle=(\d+) line=(\d+) beat=(\d+) address=([0-9a-fA-F]{16}) data=([0-9a-fA-F]{16})',1024)
    acknowledged=bytearray();raw_ack_cycles=[]
    for number,(cycle,line,beat,address,hexdata)in enumerate(raw_ack):
        need(int(line)==number//8 and int(beat)==number%8 and int(address,16)==0x83000000+5*8192+number*8,'acknowledged residual raw address/line/beat association')
        acknowledged.extend(int(hexdata,16).to_bytes(8,'little'));raw_ack_cycles.append(int(cycle))
    need(bytes(acknowledged)==struct.pack('<2048i',*expected_raw),'all2048 actual committed residual words differ from exact physical sum/direct rounding')
    scratch=records(console,'RAW32_RESIDUAL_SCRATCH_ACK',r'RAW32_RESIDUAL_SCRATCH_ACK cycle=(\d+) line=(\d+) address=([0-9a-fA-F]{16}) bytes=64',128)
    for number,(cycle,line,address)in enumerate(scratch):need(int(line)==number and int(address,16)==0x82000000+number*64,'scratch ACK order/address')
    # The producer's public terminal handshake must be observed independently
    # of this consumer's later scratch drain. Never infer or delay the pulse.
    native_done=records(console,'FULL_FF_NATIVE_DONE',r'FULL_FF_NATIVE_DONE cycle=(\d+) tag=([0-9a-fA-F]{8}) error=([01]) scratch_ACKs=(\d+) native_input_drained=([01])',1)[0]
    done_cycle,done_tag,done_error,done_scratch,done_drained=native_done
    done_cycle=int(done_cycle);scratch_cycles=[int(row[0])for row in scratch]
    need(all(a<b for a,b in zip(packet_cycles,packet_cycles[1:])),'strict native packet acceptance cycles')
    need(all(a<b for a,b in zip(scratch_cycles,scratch_cycles[1:])),'strict actual scratch ACK cycles')
    need(int(done_tag,16)==0x504f0000 and done_error=='0'and done_scratch=='120'and done_drained=='0','actual matching native Done at120scratch before drain')
    need(done_cycle==packet_cycles[-1]+3,'actual producer Done exactly three cycles after accepted final packet')
    need(sum(cycle<done_cycle for cycle in scratch_cycles)==120 and scratch_cycles[119]<done_cycle<scratch_cycles[120],'actual final eight scratch ACKs follow producer completion')
    metadata_ack=records(console,'RAW32_RESIDUAL_METADATA_ACK',r'RAW32_RESIDUAL_METADATA_ACK cycle=(\d+) address=([0-9a-fA-F]{16}) unit=(-?\d+) epsilon=(\d+) bytes=([0-9a-fA-F]{32})',1)[0]
    meta_cycle,address,actual_unit,actual_epsilon,actual_meta=metadata_ack
    expected_meta=epsilon|((unit&255)<<64)|(root<<72)|(0<<82)|(position<<92)|((layer+1)<<102)|((epoch+1)<<107)
    need(int(address,16)==0x84000000 and int(actual_unit)==unit and int(actual_epsilon)==epsilon and int(actual_meta,16)==expected_meta,'publication metadata/regenerated epsilon/target identity')
    need(max(int(v[0])for v in scratch)<min(raw_ack_cycles)and max(raw_ack_cycles)<int(meta_cycle),'scratch/raw/metadata actual ACK order')
    configs=records(console,'RAW32_RESIDUAL_C_CFG',r'RAW32_RESIDUAL_C_CFG cycle=(\d+) count=(\d+)',1)
    demands=records(console,'RAW32_RESIDUAL_C_DEMAND',r'RAW32_RESIDUAL_C_DEMAND cycle=(\d+) rank=(\d+) root=(\d+)',1)
    need(int(configs[0][1])==264 and demands[0][1:]==('0','0')and int(meta_cycle)<int(configs[0][0])<int(demands[0][0]),'real native C admission before/after publication')
    gains=[int.from_bytes(gamma_bytes[index:index+3],'little',signed=True)for index in range(0,6144,3)]
    expected_c=normalize(expected_raw,gains,epsilon,-23)
    strips=records(console,'RAW32_RESIDUAL_C_STRIP',r'RAW32_RESIDUAL_C_STRIP cycle=(\d+) tag=([0-9a-fA-F]{8}) index=(\d+) count=(\d+) last=([01]) eA=(-?\d+) code=([0-9a-fA-F]{16}) mask=([0-9a-fA-F]{2}) negative=([0-9a-fA-F]{2}) outlier_negative=([0-9a-fA-F]{2})',256)
    for number,(cycle,tag,index,count,last,exponent,code,mask,negative,outlier_negative)in enumerate(strips):
        need(int(tag,16)==0x50520000 and int(index)==number and int(count)==8 and int(last)==(number==255)and int(exponent)==expected_c['activation_exponent'],'actual native C output association/exponent')
        need(int(cycle)>int(demands[0][0]),'C output before actual demand')
        need(int(code,16).to_bytes(8,'little')==struct.pack('<8b',*expected_c['codes'][number*8:(number+1)*8]),'all2048 actual native C normalized codes')
        for key,actual in [('outlier_mask',mask),('normalized_negative',negative),('outlier_negative',outlier_negative)]:
            bits=sum(int(expected_c[key][number*8+lane])<<lane for lane in range(8));need(int(actual,16)==bits,'all2048 native C '+key)
    intermediate=records(console,'FULL_FF_INTERMEDIATE_ACK',r'FULL_FF_INTERMEDIATE_ACK cycle=(\d+) address=([0-9a-fA-F]{16}) length=(\d+)',71)
    for number,(_,address,length)in enumerate(intermediate):need(int(address,16)==0x74000000+number*80 and int(length)==(4 if number==70 else 10),'distinct71 native intermediate ACKs')
    complete=[line for line in console.splitlines()if line.startswith('RAW32_RESIDUAL_COMPLETE_NATIVE_PASS ')]
    need(len(complete)==1,'one native terminal record');fields=dict(token.split('=',1)for token in complete[0].split()[1:])
    wanted=dict(packets=13,lanes=2048,native_intermediate_ACKs=71,native_intermediate_bytes=5632,scratch_ACKs=128,raw_ACKs=128,metadata_ACKs=1,total_commit_ACKs=257,commit_bytes=16400,Cstrips=256,Caccepted=1,Ccompleted=1,frame_count=264,AwaitDemand=1,owner_held=1,retire=0,done_held=1,unit=unit,epsilon=epsilon,RAMs=621,PEarrays=20,full_model=0,paper_matching=0,physical_advancement_allowed=0)
    need(all(fields.get(key)==str(value)for key,value in wanted.items()),'complete native terminal fields')
    result=dict(schema='raw32_residual_complete_native_postcheck_v2',post_checks_passed=True,actual_review_accepted=False,original_runtime_execution_not_performed_by_checker=True,observed_producer_completion=dict(cycle=done_cycle,tag=int(done_tag,16),error=0,scratch_ACKs=120,native_input_drained=False,cycles_after_final_packet=3,remaining_scratch_ACKs=8),independent_exact_residual2048=True,independent_epsilon_and_metadata=True,independent_native_C2048_codes_and_all3_planes=True,selected_raw_unit=unit,selected_epsilon=epsilon,C_activation_exponent=expected_c['activation_exponent'],actual_ACKs=dict(native_intermediate=71,scratch=128,raw=128,metadata=1,commit_total=257),actual_native_packets=13,actual_native_lanes=2048,actual_native_C_strips=256,frame_count_retained=264,completed_rows=1,retired=False,owner_held=True,read_bindings=READS,checker_elapsed_seconds=time.monotonic()-started,checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),model_or_GPU_or_compiler_or_simulator_invocations=0,full_model_verified=False,paper_matching=False,physical_advancement_allowed=False,paper300_gate='HOLD')
    output=Path(args.output);need(output.is_absolute()and output.resolve().is_relative_to(Path(__file__).resolve().parents[1]/'.cache'),'owned absolute cache result path')
    with output.open('x')as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(dict(post_checks_passed=True,result_path=str(output),result_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),selected_raw_unit=unit,C_activation_exponent=expected_c['activation_exponent'])))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('console','console-sha256','original-raw','original-raw-sha256','original-metadata','original-metadata-sha256','gamma','gamma-sha256','output'):parser.add_argument('--'+name,required=True)
    check(parser.parse_args())

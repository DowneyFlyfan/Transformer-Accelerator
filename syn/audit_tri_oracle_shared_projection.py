"""Check actual shared-array operands, context origin and full trained dots."""
if not __debug__:
    raise RuntimeError('Verification requires Python assertions; run without -O.')
from collections import Counter,defaultdict,deque
from pathlib import Path
import hashlib,json,re,sys
J=Path(__file__).resolve().parents[1]/'.cache/late_clipping_20261121/frame_integration/shared_attention_projection_v1'
C=J.parent/'autonomous_attention_commit_v1/trained_v2/native'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def fields(line):return dict(re.findall(r'(\w+)=(\S+)',line))
def signed(value,width):return value-(1<<width) if value>>(width-1) else value

def check(log,mode):
    assert mode in ('positive','error')
    assert not re.search(r'\*[EWF],',log),'Native diagnostic present'
    marker='SHARED_ATTENTION_PROJECTION_PASS' if mode=='positive' else 'SHARED_PROJECTION_ERROR_DRAIN_PASS'
    assert len(re.findall(r'^'+marker+r' .*$',log,re.M))==1,'Missing unique terminal'
    arrays=re.findall(r'^SCORE_BATCH_ARRAY path=(\S+)$',log,re.M)
    memories=re.findall(r'^SCORE_BATCH_MEMORY path=(\S+)$',log,re.M)
    assert len(arrays)==len(set(arrays))==20
    assert len(memories)==len(set(memories))==606
    previous=(C/'xrun.log').read_text().replace('tri_oracle_complete_head_handoff_tb.',arrays[0].split('.')[0]+'.')
    for prefix in ['BROKER_TENSOR_REQUEST ','BROKER_NORMALIZER_CONFIG ','BROKER_NORMALIZER_INPUT ','BROKER_PROBABILITY ','BROKER_CONTEXT ']:
        key='owner' if 'NORMALIZER' in prefix or 'PROBABILITY' in prefix else 'head'
        actual=defaultdict(list);wanted=defaultdict(list)
        for text,target in [(log,actual),(previous,wanted)]:
            for line in text.splitlines():
                if line.startswith(prefix):target[fields(line)[key]].append(line)
        assert actual==wanted,('Attention event mismatch',prefix)
    context_words=[int(line,16) for line in (J.parent/'complete_head_handoff_v1/projection_words.hex').read_text().splitlines()]
    matrix_raw=(J.parent/'current_integer_attention_fixed_scales_v2/data/output_weights.bin').read_bytes()
    activity=defaultdict(Counter);projection_group=None
    pending=defaultdict(deque);transactions=0;row_dots=0
    for line in log.splitlines():
        if line.startswith('SHARED_CONTEXT_READ '):projection_group=int(fields(line)['group'])
        elif line.startswith('SCORE_BATCH_ARRAY_INPUT '):
            d=fields(line);mask=int(d['mask'],16);values=[]
            # Never demand initialized payload in disabled physical lanes.
            # Enabled lanes must still contain actual known signed bytes.
            for name in ['a','b']:
                if re.search('[xz]',d[name]):
                    for index in range(256):
                        if (mask>>index)&1:
                            start=len(d[name])-2*(index+1)
                            assert re.fullmatch('[0-9a-f]{2}',d[name][start:start+2]),'Unknown enabled operand'
            a=int(d['a'].replace('x','0').replace('z','0'),16)
            b=int(d['b'].replace('x','0').replace('z','0'),16)
            path=d['path'];ordinal=activity[projection_group][path];activity[projection_group][path]+=1
            if projection_group is not None:
                cluster=int(re.search(r'clusters\[(\d+)\]',path)[1]);core=int(re.search(r'cores\[(\d+)\]',path)[1])
                assert 0<=ordinal<64 and 0<=projection_group<13
                feature_word=64*core+ordinal
                for row in range(32):
                    channel=160*projection_group+32*cluster+row
                    expected_mask=255 if channel<2048 else 0
                    assert (mask>>(8*row))&255==expected_mask,'Projection row mask differs'
                    if expected_mask:
                        assert (a>>(64*row))&((1<<64)-1)==context_words[feature_word],'Array activation is not native context'
                        offset=channel*2048+feature_word*8
                        assert (b>>(64*row))&((1<<64)-1)==int.from_bytes(matrix_raw[offset:offset+8],'little'),'Array weight is not trained weight'
            for row in range(32):
                total=0
                for lane in range(8):
                    index=row*8+lane
                    if (mask>>index)&1:
                        total+=signed((a>>(8*index))&255,8)*signed((b>>(8*index))&255,8)
                values.append(total)
            pending[d['path']].append(values);transactions+=1;row_dots+=32
        elif line.startswith('SCORE_BATCH_ARRAY_OUTPUT '):
            d=fields(line);assert pending[d['path']],'Unowned array result'
            actual=int(d['sums'],16)
            assert [signed((actual>>(19*row))&((1<<19)-1),19) for row in range(32)]==pending[d['path']].popleft()
    assert not any(pending.values()),'Array work not drained'
    expected_attention=Counter(fields(x)['path'] for x in previous.splitlines() if x.startswith('SCORE_BATCH_ARRAY_INPUT '))
    assert activity[None]==expected_attention,'Attention array activity differs'
    if mode=='positive':
        assert set(activity)=={None,*range(13)}
        assert all(activity[group]==Counter({path:64 for path in arrays}) for group in range(13)),'Projection array work missing'
        assert transactions==17768 and row_dots==568576
    else:
        assert all(not counts for group,counts in activity.items() if group is not None),'Projection executed after early weight error'
        assert transactions==1128 and row_dots==36096
    reference=json.loads((J/'output_reference.json').read_text())
    assert all(sha(path)==want for path,want in reference['evidence_sha256'].items())
    reads=defaultdict(list);weights=Counter();dots={};groups=[]
    for line in log.splitlines():
        if line.startswith('SHARED_CONTEXT_READ '):
            d=fields(line);group=int(d['group']);word=int(d['word']);assert 0<=word<256
            assert int(d['data'],16)==context_words[word],'Wrong native context word'
            reads[group].append(word)
        elif line.startswith('SHARED_WEIGHT_REQUEST '):
            d=fields(line);address=int(d['address'],16);length=int(d['length'])
            assert address>=0x200000 and address%8==0 and 1<=length<=16
            begin=(address-0x200000)//8;assert begin+length<=524288
            weights.update(range(begin,begin+length))
        elif line.startswith('SHARED_PROJECTION_DOT '):
            d=fields(line);channel=int(d['channel']);assert channel not in dots,'Duplicate channel'
            dots[channel]=int(d['raw'])
        elif line.startswith('SHARED_PROJECTION_GROUP_PASS '):
            d=fields(line);groups.append((int(d['group']),int(d['values'])))
    if mode=='positive':
        assert groups==[(g,128 if g==12 else 160) for g in range(13)]
        assert set(reads)==set(range(13)) and all(sorted(x)==list(range(256)) for x in reads.values())
        assert weights==Counter({i:1 for i in range(524288)}),'Weight word coverage differs'
        assert set(dots)==set(range(2048)),'Missing projection channels'
        codes=memoryview(b''.join(v.to_bytes(8,'little') for v in context_words)).cast('b')
        matrix=memoryview((J.parent/'current_integer_attention_fixed_scales_v2/data/output_weights.bin').read_bytes()).cast('b')
        for channel in range(2048):
            total=sum(int(code)*int(weight) for code,weight in zip(codes,matrix[channel*2048:(channel+1)*2048]))
            assert dots[channel]==total,('Raw trained projection mismatch',channel)
        assert log.splitlines().count('SHARED_MASKED_OFFER_FINISH_PASS')==1
        assert log.splitlines().count('COMMIT_QUERY_DONE error=0')==1
    else:
        assert not dots and not groups
        assert weights==Counter({i:1 for i in range(16)}) and sum(map(len,reads.values()))==128
        assert 'SHARED_PROJECTION_ERROR_DRAIN_PASS accepted_weight_beats=16 output_values=0 reset_required=1 held_offer=1' in log
        assert 'COMMIT_QUERY_DONE error=0' not in log
        events=[(i,x) for i,x in enumerate(log.splitlines()) if x.startswith(('SHARED_ERROR_RESPONSE ','SHARED_ERROR_ACCEPTED_LAST ','SHARED_ERROR_TENSOR_COMPLETION '))]
        assert [x for i,x in events[:16]]==[f'SHARED_ERROR_RESPONSE beat={beat} last={int(beat==16)} error={int(beat==1)}' for beat in range(1,17)]
        assert len(events)==18 and events[16][1]=='SHARED_ERROR_ACCEPTED_LAST address=0000000000200000 length=16'
        assert events[17][1]=='SHARED_ERROR_TENSOR_COMPLETION drained_beats=16 error=1'
        terminal=next(i for i,x in enumerate(log.splitlines()) if x.startswith(marker+' '))
        assert events[-1][0]<terminal
    return dict(actual_arrays=20,actual_compiled_memory_witnesses=606,
        exact_array_transactions=transactions,exact_physical_row_dots=row_dots,
        attention_context_values=2048,projection_output_values=len(dots),
        context_word_reads=sum(map(len,reads.values())),requested_weight_words=sum(weights.values()),
        held_offer_verified=True,accepted_weight_error_drain_verified=mode=='error',
        whole_chip_integration_verified=False,current_mapped_candidate_verified=False,
        quantized_projection_output_verified=False,full_accuracy_verified=False,paper_matching=False)

def qualify(mode):
    out=J/('native_positive_v2' if mode=='positive' else 'native_error_v1')
    status=json.loads((out/'status.json').read_text());inv=json.loads((out/'invocation.json').read_text())
    assert status['exit_status']==0 and status['owned_group_terminal'] and status['stop_reason'] is None and status['supervisor_error'] is None
    assert all(sha(path)==want for path,want in inv['source_sha256'].items())
    log=(out/'xrun.log').read_text();result=check(log,mode)
    result.update(state='actual_shared_attention_projection_verified' if mode=='positive' else 'actual_shared_projection_error_drain_verified',native_wall_seconds=status['wall_seconds'],
        evidence_sha256={str(p):sha(p) for p in [Path(__file__).resolve(),out/'xrun.log',out/'console.log',out/'status.json',out/'invocation.json',J/'shared_inputs.json',J/'output_reference.json']})
    print(json.dumps({k:v for k,v in result.items() if k!='evidence_sha256'},indent=2))

if __name__=='__main__':qualify(sys.argv[1])

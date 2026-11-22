"""Mutate actual completed native traces; incomplete runs never form fixtures."""
from pathlib import Path
import importlib.util,json,re,sys
J=Path(__file__).resolve().parents[1]/'.cache/late_clipping_20261121/frame_integration/shared_attention_projection_v1'
path=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().with_name('audit_tri_oracle_shared_projection.py')
spec=importlib.util.spec_from_file_location('tested_shared_audit',path)
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
mode=sys.argv[2] if len(sys.argv)>2 else 'positive'
out=J/('native_positive_v2' if mode=='positive' else 'native_error_v1')
status=json.loads((out/'status.json').read_text());assert status['exit_status']==0 and status['owned_group_terminal']
log=(out/'xrun.log').read_text();M.check(log,mode)
lines=log.splitlines();mutants={}
if mode=='positive':
    start=next(i for i,line in enumerate(lines) if line.startswith('SHARED_CONTEXT_READ '))
    mutants['projection_array_activity_removed']='\n'.join(line for i,line in enumerate(lines) if i<start or not line.startswith(('SCORE_BATCH_ARRAY_INPUT ','SCORE_BATCH_ARRAY_OUTPUT ')))
    changed=lines.copy();owner=next(M.fields(x)['owner'] for x in lines if x.startswith('BROKER_PROBABILITY '))
    indices=[i for i,x in enumerate(lines) if x.startswith('BROKER_PROBABILITY ') and M.fields(x)['owner']==owner]
    a=indices[0];b=next(i for i in indices[1:] if M.fields(lines[i])['probability']!=M.fields(lines[a])['probability'])
    changed[a],changed[b]=changed[b],changed[a];mutants['same_owner_probability_reordered']='\n'.join(changed)
    i=next(i for i,x in enumerate(lines) if x.startswith('SHARED_PROJECTION_DOT '));changed=lines.copy()
    value=int(M.fields(changed[i])['raw']);changed[i]=re.sub(r'raw=-?\d+',f'raw={value+1}',changed[i]);mutants['wrong_projection_dot']='\n'.join(changed)
    changed=lines.copy();del changed[i];mutants['missing_projection_channel']='\n'.join(changed)
    i=next(i for i,x in enumerate(lines) if x.startswith('SHARED_CONTEXT_READ '));changed=lines.copy();d=M.fields(changed[i]);wrong=int(d['data'],16)^1
    changed[i]=re.sub(r'data=[0-9a-f]+',f'data={wrong:016x}',changed[i]);mutants['wrong_native_context_word']='\n'.join(changed)
else:
    mutants['independent_error_probe_removed']='\n'.join(x for x in lines if not x.startswith(('SHARED_ERROR_RESPONSE ','SHARED_ERROR_ACCEPTED_LAST ','SHARED_ERROR_TENSOR_COMPLETION ')))
    changed=lines.copy();i=next(i for i,x in enumerate(lines) if x.startswith('SHARED_ERROR_RESPONSE beat=16 '));del changed[i];mutants['accepted_last_beat_removed']='\n'.join(changed)
    i=next(i for i,x in enumerate(lines) if x.startswith('SHARED_ERROR_TENSOR_COMPLETION '));last=next(i for i,x in enumerate(lines) if x.startswith('SHARED_ERROR_ACCEPTED_LAST '));changed=lines.copy();value=changed.pop(i);changed.insert(last,value);mutants['completion_before_last']='\n'.join(changed)
accepted=[];rejected=[]
for label,mutant in mutants.items():
    try:M.check(mutant,mode)
    except AssertionError:rejected.append(label)
    else:accepted.append(label)
result=dict(mode=mode,rejected=rejected,incorrectly_accepted=accepted)
print(json.dumps(result,indent=2))
assert not accepted,'Verifier accepted corrupt native evidence'

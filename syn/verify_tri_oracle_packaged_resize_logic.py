"""Verify exact mapped substitutions and identical foundry simulation models."""
from collections import Counter,defaultdict
from hashlib import file_digest,sha256
import json
from mmap import ACCESS_READ,mmap
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'.cache/wide_packaged_host_link/drive_repair'
sys.path.insert(0,str(ROOT/'syn'))
from link_tri_oracle_indexed_whole_chip import spans
from verify_tri_oracle_serialized_placement_transfer import INSTANCE


def digest(path):
    with path.open('rb') as stream:return file_digest(stream,'sha256').hexdigest()


def read(path):return json.loads(path.read_text())


def models(path):
    text=path.read_bytes()
    result={}
    for match in re.finditer(rb'(?m)^module\s+(\w+)\b',text):
        stop=text.find(b'endmodule',match.end())
        assert stop!=-1
        name=match[1].decode()
        assert name not in result
        result[name]=text[match.end():stop+len(b'endmodule')]
    return result


def edited_digest(text,edits):
    result=sha256();start=0
    for first,last,value in (*sorted(edits),(len(text),len(text),b'')):
        assert start<=first<=last<=len(text)
        for offset in range(start,first,4*1024**2):
            result.update(text[offset:min(first,offset+4*1024**2)])
        result.update(value);start=last
    return result.hexdigest()


def verify():
    plan=read(WORK/'prepared.json');hierarchy=read(WORK/'hierarchy.json')
    seed=read(WORK/'host_legalized/prepared.json')
    for record in (plan,hierarchy):
        for name,want in record['evidence_sha256'].items():assert digest(ROOT/name)==want,name
    assert not hierarchy['partial_shared_slots']
    source=ROOT/'.cache/wide_packaged_host_link/placement/native/cold.v'
    candidate=WORK/'host_legalized/candidate.v'
    library=ROOT/'.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'
    assert digest(source)==plan['source_cold_netlist_sha256']==hierarchy['source_cold_netlist_sha256']
    assert digest(candidate)==seed['candidate_sha256']
    pairs=Counter((row['old_master'],row['new_master']) for row in plan['replacements'])
    behavior=models(library)
    signatures={}
    for (old,new),count in sorted(pairs.items()):
        assert behavior[old]==behavior[new],(old,new)
        assert old.encode() not in behavior[old] and new.encode() not in behavior[new]
        signatures[old+' -> '+new]={'instances':count,'common_model_body_sha256':sha256(behavior[old]).hexdigest(),
                                    'common_model_body_bytes':len(behavior[old])}
    changes=defaultdict(dict)
    for row in hierarchy['logical_changes']:
        assert row['leaf'] not in changes[row['module']]
        changes[row['module']][row['leaf']]=row
    edits=[];selected=[]
    with source.open('rb') as stream,mmap(stream.fileno(),0,access=ACCESS_READ) as text:
        modules=spans(text)
        for name,rows in changes.items():
            seen=set()
            for match in INSTANCE.finditer(text,*modules[name]):
                leaf=match[2].removeprefix(b'\\').decode()
                if leaf not in rows:continue
                row=rows[leaf]
                assert match[1].decode()==row['old']
                edits.append((*match.span(1),row['new'].encode()));seen.add(leaf)
            assert seen==rows.keys()
        assert len(edits)==sum(pairs.values())==620
        expected=edited_digest(text,edits)
        assert expected==digest(candidate)
        # A changed cell type outside the approved mapping must be rejected.
        wrong=list(edits)
        first,last,value=wrong[0]
        wrong[0]=(first,last,b'INVD0BWP12T40P140')
        assert edited_digest(text,wrong)!=expected
    with candidate.open('rb') as stream,mmap(stream.fileno(),0,access=ACCESS_READ) as text:
        assert spans(text).keys()==modules.keys() and len(modules)==771
    evidence={str(p.relative_to(ROOT)):digest(p) for p in
              (source,candidate,library,WORK/'prepared.json',WORK/'hierarchy.json',
               WORK/'host_legalized/prepared.json',Path(__file__).resolve(),
               ROOT/'syn/link_tri_oracle_indexed_whole_chip.py',
               ROOT/'syn/verify_tri_oracle_serialized_placement_transfer.py')}
    result={'state':'exact_620_mapped_cell_substitutions_with_identical_foundry_verilog_bodies',
            'source_cold_netlist_sha256':digest(source),'candidate_sha256':expected,
            'cell_identifier_substitutions':620,'distinct_cell_type_pairs':len(pairs),
            'module_count':len(modules),'model_body_comparisons':signatures,
            'rejected_mutations':['unapproved_replacement_cell_type'],
            'scope':'Whole candidate bytes equal the original cold export with exactly the 620 mapped '
                    'cell identifiers replaced. Every old/new foundry Verilog module has an identical '
                    'body, including ports, state primitives, notifier logic and preprocessor branches. '
                    'Cell declarations do not contain self-name references. This establishes preservation '
                    'of modeled digital behavior under the same elaboration settings and initial states. '
                    'Physical library delay, placement, wire timing, complete trained execution and '
                    'model accuracy remain separate checks.',
            'evidence_sha256':evidence}
    (WORK/'verified_logic.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print('EXACT_EQUIVALENT_RESIZE_LOGIC_VERIFIED',620,len(pairs),len(modules),flush=True)
    return result


if __name__=='__main__':
    assert __debug__ and Path.cwd()==ROOT and not Path('/.dockerenv').exists()
    verify()

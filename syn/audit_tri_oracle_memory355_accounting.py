"""Inventory-bound capacity audit of the preserved placed candidate.

Count actual native cold-export instances and derive capacity from vendor
module parameters, not part-number spellings. The paper's405KB label does not
specify its byte convention here: compare both405000 and414720bytes. Never add
uninstantiated memories to make a total fit. This diagnoses capacity only; it
does not release the paper300 hold or claim current physical/functional signoff.
"""
from collections import Counter
import csv
import datetime
import hashlib
import itertools
import json
from pathlib import Path
import re


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def capacity_bytes(source,master):
    source=re.sub(r'/\*.*?\*/|//[^\n]*','',source,flags=re.S)
    modules=re.findall(r'\bmodule\s+'+re.escape(master)+r'\b(.*?)\bendmodule\b',source,re.S)
    if len(modules)!=1:raise ValueError('One exact vendor module definition required')
    parameters={}
    for name,value in re.findall(r'\bparameter\s+(?:integer\s+)?(\w+)\s*=\s*(\d+)\s*;',modules[0]):
        if name in parameters:raise ValueError('Ambiguous vendor parameter')
        parameters[name]=int(value)
    if 'numWord' in parameters and 'numBit' in parameters:
        depth,width=parameters['numWord'],parameters['numBit']
    elif 'W' in parameters and 'N' in parameters:
        depth,width=parameters['W'],parameters['N']
    else:raise ValueError('Unsupported or missing literal storage dimensions')
    if depth<=0 or width<=0 or (depth*width)%8:raise ValueError('Invalid byte-addressable storage dimensions')
    return depth*width//8


def memory_counts(rows):
    counts=Counter();seen=set()
    for row in rows:
        master=row['master'];instance=row['instance']
        if not master.startswith(('TS5N28','TS6N28')):continue
        if instance in seen:raise ValueError('Duplicate native memory instance '+instance)
        seen.add(instance);counts[master]+=1
    return dict(sorted(counts.items()))


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'records/memory355_candidate_capacity.json';assert not output.exists()
    qualified_path=root/'records/restore304_preservation_qualification.json'
    producer_path=root/'records/restore295_full_result.json'
    qualified=json.loads(qualified_path.read_text());producer=json.loads(producer_path.read_text())
    assert qualified['state']=='placed_parent_and_original_full_models_preserved_timing_unqualified'
    assert qualified['evidence_sha256'][str(producer_path)]==sha(producer_path)
    assert qualified['native_full_and_cold_restoration_verified'] and qualified['original_memory_models']==600
    base=Path(producer['output_directory'])
    core=base/'cold/core_cells.tsv';parent=base/'cold/restored_cells.tsv';netlist=base/'full/restored_parent.v'
    inputs={str(path):sha(path) for path in [Path(__file__).resolve(),root/'syn/test_tri_oracle_memory355_accounting.py',
                                           qualified_path,producer_path,core,parent,netlist]}
    for path in [core,parent,netlist]:assert inputs[str(path)]==producer['native_evidence_sha256'][str(path)]
    paper=root/'Paper/Tri-Oracle - A 17.78μJ per Token Vision-Language Model Accelerator with Token-Attention-Weight Redundancy Prediction.pdf'
    assert sha(paper)=='6d6b998c459ade605e082d723374462e1d14b53d6a6b13063ca0f8d1180b1d9f'
    inputs[str(paper)]=sha(paper)
    model_source=json.loads((root/'records/real190_full_result.json').read_text())
    inputs[str(root/'records/real190_full_result.json')]=sha(root/'records/real190_full_result.json')
    capacities={};models={}
    for name,expected in model_source['source_sha256'].items():
        path=Path(name)
        if '/VERILOG/' not in name or path.suffix!='.v':continue
        path=path.resolve()
        if str(path) in inputs:continue
        assert sha(path)==expected;inputs[str(path)]=expected
        text=path.read_text()
        master=re.search(r'\bmodule\s+(TS[56]N28\w+)\b',text).group(1)
        capacities[master]=capacity_bytes(text,master);models[master]=str(path)
    with core.open() as a,parent.open() as b:
        counts=memory_counts(itertools.chain(csv.DictReader(a,delimiter='\t'),csv.DictReader(b,delimiter='\t')))
    assert sum(counts.values())==600
    assert set(counts).issubset(capacities),'Unaccounted vendor memory type'
    entries={master:dict(instances=count,bytes_per_instance=capacities[master],
                         total_bytes=count*capacities[master],vendor_model=models[master]) for master,count in counts.items()}
    total=sum(entry['total_bytes'] for entry in entries.values())
    comparisons={name:dict(published_bytes=size,shortfall_bytes=size-total,exact_match=total==size)
                 for name,size in [('decimal_KB',405000),('binary_KiB',405*1024)]}
    matches_any=any(item['exact_match'] for item in comparisons.values())
    # The undisclosed convention is itself unresolved; equal capacity under one
    # possible convention alone would not qualify physical memory partitioning.
    assert all(sha(path)==digest for path,digest in inputs.items()),'Capacity evidence changed'
    report=dict(state='observed_native_memory_capacity_unreconciled',
        verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=inputs,
        restored_checkpoint=qualified['recovered_saved_checkpoint'],
        restored_checkpoint_fingerprint_sha256=qualified['recovered_checkpoint_fingerprint_sha256'],
        native_instances=sum(counts.values()),by_master=entries,total_bytes=total,total_binary_KiB=total/1024,
        paper_figure='31.6.7',paper_published_label='405KB',paper_byte_convention_confirmed=False,
        comparisons=comparisons,capacity_matches_any_proposed_convention=matches_any,memory_capacity_reconciled=False,
        uninstantiated_storage_added=False,paper300_release_authorized=False,scope=__doc__)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print('MEMORY355_NATIVE_CAPACITY',total,'bytes',total/1024,'KiB',sum(counts.values()),'instances')
    print('MEMORY355_PAPER_MEMORY_UNQUALIFIED',json.dumps(comparisons))
    return 1


if __name__=='__main__':raise SystemExit(main())

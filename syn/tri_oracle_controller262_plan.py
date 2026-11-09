"""Plan trees for high-fanout protected enables from bound native inventories."""
from collections import Counter
import csv
import datetime
import hashlib
import json
from pathlib import Path
import re

from tri_oracle_controller255_tree import plan_buffers


def pin_names(text):
    # Native list serialization restricted to whitespace-free physical names.
    # Reject unsupported Tcl quoting rather than reinterpret an ambiguous pin.
    names=[];position=0
    for match in re.finditer(r'\{([A-Za-z0-9_/$:.[\]-]+)\}|([A-Za-z0-9_/$:.[\]-]+)',text):
        if text[position:match.start()].strip():raise ValueError('Unsupported native pin list')
        names.append(match[1] or match[2]);position=match.end()
    if text[position:].strip():raise ValueError('Unsupported native pin list')
    return names


def read_native_nets(stream):
    fields=['constant','power','ground','driver_pins','driver_ports','load_pins','load_ports']
    if stream.readline().rstrip('\n').split('\t')!=fields:raise ValueError('Wrong native net header')
    for line in stream:
        values=line.rstrip('\n').split('\t')
        if len(values)!=len(fields):raise ValueError('Wrong native net row width')
        yield dict(zip(fields,values))


def select_enable_nets(rows, controllers):
    selected=[];seen_drivers=set();seen_pins=set()
    for row in rows:
        if row['constant']!='no_constant' or row['power']!='false' or row['ground']!='false' or row['driver_ports'] or row['load_ports']:continue
        drivers=pin_names(row['driver_pins'])
        if len(drivers)!=1:continue
        driver=drivers[0];controller=driver.rsplit('/',2)[0]
        if controller not in controllers:continue
        pins=pin_names(row['load_pins'])
        if len(pins)!=len(set(pins)):raise ValueError('Duplicate native sink')
        if len(pins)<128 or sum(pin.rsplit('/',1)[-1]=='E' for pin in pins)<64:continue
        if any(pin.rsplit('/',2)[0]!=controller or not re.fullmatch(r'[ABCDEIS][0-4]?',pin.rsplit('/',1)[-1]) for pin in pins):continue
        if driver in seen_drivers or seen_pins.intersection(pins):raise ValueError('Ambiguous candidate connectivity')
        seen_drivers.add(driver);seen_pins.update(pins)
        selected.append(dict(controller=controller,driver=driver,pins=sorted(pins)))
    return sorted(selected,key=lambda row:row['driver'])


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'.cache/physical/pnr/tri_oracle_controller262_plan'
    result=root/'records/controller262_plan_result.json'
    assert not output.exists() and not result.exists()
    producer_path=root/'records/controller260_tree_result.json'
    producer=json.loads(producer_path.read_text())
    assert producer['state']=='noninverting_controller_tree_cold_preserved_and_three_corners_completed'
    physical=Path(producer['output_directory'])/'warm'
    paths=[physical/'after_nets.tsv',physical/'after_cells.tsv',physical/'after_preservation.tsv']
    identities={str(path):sha(path) for path in paths}
    assert all(producer['native_evidence_sha256'][name]==digest for name,digest in identities.items())
    for path in [producer_path,Path(__file__).resolve(),root/'syn/test_tri_oracle_controller262_plan.py',root/'syn/tri_oracle_controller255_tree.py']:
        identities[str(path)]=sha(path)
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    assert available>8*1024**3
    with paths[2].open() as stream:
        policies=list(csv.DictReader(stream,delimiter='\t'))
    assert len(policies)==86 and all(row['expected_object']==row['actual_object'] and row['dont_touch']=='true' for row in policies)
    controllers={row['actual_object'] for row in policies if row['actual_object'].endswith('/implementation')}
    assert len(controllers)==26
    with paths[0].open() as stream:candidates=select_enable_nets(read_native_nets(stream),controllers)
    assert candidates
    wanted={pin.rsplit('/',1)[0] for candidate in candidates for pin in [candidate['driver'],*candidate['pins']]}
    cells={}
    with paths[1].open() as stream:
        for row in csv.DictReader(stream,delimiter='\t'):
            if row['instance'] in wanted:
                assert row['instance'] not in cells
                cells[row['instance']]=row
    assert set(cells)==wanted
    output.mkdir()
    summary=[]
    with (output/'trees.tsv').open('w') as trees,(output/'plan.tsv').open('w') as plans,(output/'sinks.tsv').open('w') as sinks:
        trees.write('tree\tcontroller\tdriver\tdriver_master\tloads\tbuffers\troot\n')
        plans.write('tree\tid\tlevel\tmaster\tx\ty\tkind\ttargets\n')
        sinks.write('tree\tpin\tlocation\n')
        for index,candidate in enumerate(candidates):
            driver_cell=cells[candidate['driver'].rsplit('/',1)[0]]
            # Native execution must independently check driver library semantics.
            points=[]
            for pin in candidate['pins']:
                location=cells[pin.rsplit('/',1)[0]]['location']
                x,y=map(float,location.strip('{}').split())
                points.append((pin,x,y));sinks.write(f'{index}\t{pin}\t{location}\n')
            nodes=plan_buffers(points)
            trees.write(f"{index}\t{candidate['controller']}\t{candidate['driver']}\t{driver_cell['master']}\t{len(points)}\t{len(nodes)}\t{len(nodes)-1}\n")
            for node in nodes:
                kind='leaf' if node['pins'] else 'parent'
                targets=node['pins'] or list(map(str,node['children']))
                plans.write(f"{index}\t{node['id']}\t{node['level']}\t{node['master']}\t{node['x']:.6f}\t{node['y']:.6f}\t{kind}\t{' '.join(targets)}\n")
            summary.append(dict(tree=index,controller=candidate['controller'],driver=candidate['driver'],driver_master=driver_cell['master'],loads=len(points),buffers=len(nodes),stages=nodes[-1]['level']+1,pin_kinds=dict(Counter(pin.rsplit('/',1)[-1] for pin in candidate['pins']))))
    assert all(sha(name)==digest for name,digest in identities.items())
    record=dict(state='protected_enable_batch_plan_prepared_native_execution_pending',
        prepared_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=identities,
        generated_sha256={str(path):sha(path) for path in output.iterdir()},output_directory=str(output),
        total_trees=len(summary),total_buffers=sum(row['buffers'] for row in summary),
        total_original_loads=sum(row['loads'] for row in summary),trees=summary,
        placement_executed=False,timing_executed=False,functional_verification_executed=False,native_driver_library_eligibility_pending=True,
        scope='Read-only geometry plan from exact physical260 inventories. Single-driver internal enables with at least128 loads including64 E pins. Ports, constants, power, ground, asynchronous and clock pin names, and hierarchy-crossing loads excluded. No native edit or repair is inferred.')
    result.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({key:value for key,value in record.items() if key not in ['source_sha256','generated_sha256','trees']},indent=2))


if __name__=='__main__':main()

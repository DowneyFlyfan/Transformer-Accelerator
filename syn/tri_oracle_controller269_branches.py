"""Plan internal signal branches while preserving all original external loads."""
from collections import Counter
import csv
import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from tri_oracle_controller255_tree import plan_buffers
from tri_oracle_controller262_plan import pin_names, read_native_nets


def select_local_branches(rows, controllers):
    selected=[];seen_drivers=set();seen_pins=set()
    clock_reset={'CP','CPN','CK','CKN','CLK','CDN','SDN','RN','SN','RESET','RESETN','RST','RSTN','SETN','PREN','G','GN'}
    for row in rows:
        if row['constant']!='no_constant' or row['power']!='false' or row['ground']!='false' or row['driver_ports'] or row['load_ports']:continue
        drivers=pin_names(row['driver_pins'])
        if len(drivers)!=1:continue
        driver=drivers[0];controller=driver.rsplit('/',2)[0]
        if controller not in controllers:continue
        original=pin_names(row['load_pins'])
        if len(original)!=len(set(original)):raise ValueError('Duplicate original sink')
        if any(pin.rsplit('/',1)[-1] in clock_reset for pin in original):continue
        pins=sorted(pin for pin in original if pin.rsplit('/',2)[0]==controller and re.fullmatch(r'E|[ABCDIS][0-4]?|SE|SI',pin.rsplit('/',1)[-1]))
        if len(pins)<128:continue
        if driver in seen_drivers or seen_pins.intersection(pins):raise ValueError('Ambiguous candidate connectivity')
        seen_drivers.add(driver);seen_pins.update(pins)
        selected.append(dict(controller=controller,driver=driver,pins=pins,remaining=sorted(set(original)-set(pins)),original_loads=len(original)))
    return sorted(selected,key=lambda row:row['driver'])


def plan_at_driver(points, location):
    try:x,y=map(float,location)
    except (ValueError,TypeError) as error:raise ValueError('Two finite driver coordinates required') from error
    if not math.isfinite(x) or not math.isfinite(y):raise ValueError('Finite driver coordinates required')
    nodes=plan_buffers(points)
    nodes[-1]['x']=x;nodes[-1]['y']=y
    return nodes


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'.cache/physical/pnr/tri_oracle_controller269_plan'
    result=root/'records/controller269_plan_result.json'
    assert not output.exists() and not result.exists()
    producer_path=root/'records/controller266_tree_result.json'
    producer=json.loads(producer_path.read_text())
    assert producer['state']=='noninverting_controller_batch_cold_preserved_and_three_corners_completed'
    physical=Path(producer['output_directory'])/'warm'
    paths=[physical/'after_nets.tsv',physical/'after_cells.tsv',physical/'after_preservation.tsv']
    identities={str(path):sha(path) for path in paths}
    assert all(producer['native_evidence_sha256'][name]==digest for name,digest in identities.items())
    for path in [producer_path,Path(__file__).resolve(),root/'syn/test_tri_oracle_controller269_branches.py',root/'syn/tri_oracle_controller262_plan.py',root/'syn/tri_oracle_controller255_tree.py']:
        identities[str(path)]=sha(path)
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    assert available>8*1024**3
    with paths[2].open() as stream:
        policies=list(csv.DictReader(stream,delimiter='\t'))
    assert len(policies)==86 and all(row['expected_object']==row['actual_object'] and row['dont_touch']=='true' for row in policies)
    controllers={row['actual_object'] for row in policies if row['actual_object'].endswith('/implementation')}
    assert len(controllers)==26
    with paths[0].open() as stream:candidates=select_local_branches(read_native_nets(stream),controllers)
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
    with (output/'trees.tsv').open('w') as trees,(output/'plan.tsv').open('w') as plans,(output/'sinks.tsv').open('w') as sinks,(output/'drivers.tsv').open('w') as drivers:
        trees.write('tree\tcontroller\tdriver\tdriver_master\toriginal_loads\tselected_loads\tbuffers\troot\tremaining\n')
        plans.write('tree\tid\tlevel\tmaster\tx\ty\tkind\ttargets\n')
        sinks.write('tree\tpin\tlocation\n')
        drivers.write('tree\tlocation\n')
        for index,candidate in enumerate(candidates):
            driver_cell=cells[candidate['driver'].rsplit('/',1)[0]]
            # Native execution must independently check driver library semantics.
            points=[]
            for pin in candidate['pins']:
                location=cells[pin.rsplit('/',1)[0]]['location']
                x,y=map(float,location.strip('{}').split())
                points.append((pin,x,y));sinks.write(f'{index}\t{pin}\t{location}\n')
            driver_location=tuple(map(float,driver_cell['location'].strip('{}').split()))
            nodes=plan_at_driver(points,driver_location)
            drivers.write(f"{index}\t{driver_cell['location']}\n")
            trees.write(f"{index}\t{candidate['controller']}\t{candidate['driver']}\t{driver_cell['master']}\t{candidate['original_loads']}\t{len(points)}\t{len(nodes)}\t{len(nodes)-1}\t{' '.join(candidate['remaining'])}\n")
            for node in nodes:
                kind='leaf' if node['pins'] else 'parent'
                targets=node['pins'] or list(map(str,node['children']))
                plans.write(f"{index}\t{node['id']}\t{node['level']}\t{node['master']}\t{node['x']:.6f}\t{node['y']:.6f}\t{kind}\t{' '.join(targets)}\n")
            summary.append(dict(tree=index,controller=candidate['controller'],driver=candidate['driver'],driver_master=driver_cell['master'],original_loads=candidate['original_loads'],selected_loads=len(points),remaining_loads=len(candidate['remaining']),buffers=len(nodes),stages=nodes[-1]['level']+1,pin_kinds=dict(Counter(pin.rsplit('/',1)[-1] for pin in candidate['pins']))))
    assert all(sha(name)==digest for name,digest in identities.items())
    record=dict(state='protected_local_signal_branch_plan_prepared_native_execution_pending',
        prepared_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=identities,
        generated_sha256={str(path):sha(path) for path in output.iterdir()},output_directory=str(output),
        total_trees=len(summary),total_buffers=sum(row['buffers'] for row in summary),
        total_original_loads=sum(row['original_loads'] for row in summary),total_buffered_loads=sum(row['selected_loads'] for row in summary),trees=summary,
        placement_executed=False,timing_executed=False,functional_verification_executed=False,native_driver_library_eligibility_pending=True,
        scope='Read-only geometry plan from exact physical266 inventories. At least128 local ordinary signal loads per protected-controller driver. All unselected external loads stay on the original root net. Clock/reset roots, ports, constants, power and ground are excluded. The root buffer is anchored at the original driver. Native library eligibility, placement, connectivity, timing and function remain pending.')
    result.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({key:value for key,value in record.items() if key not in ['source_sha256','generated_sha256','trees']},indent=2))


if __name__=='__main__':main()

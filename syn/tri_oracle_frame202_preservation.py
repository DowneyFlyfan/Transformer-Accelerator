"""Bind physical changes to the actual new-parent macro/reset import baseline."""
import csv
import math
from pathlib import Path

from tri_oracle_parent_candidate_acceptance import read_topology, digest


PREFIX = 'numeric/engine/backend'
CORES = {f'{PREFIX}/clusters[{cluster}].cluster/cores[{core}]' for cluster in range(5) for core in range(4)}
BANKS = {f'{PREFIX}/clusters[{cluster}].cluster/aggregate_memory[{bank}]' for cluster in range(5) for bank in range(8)}


def read_ready_prerequisite(read_record, identity_for_pid, owners, label, state):
    def complete(record):
        return record['state']==state and (not label.startswith('mapped208') or record.get('temporary_build_removed') is True)
    record=read_record()
    if record['state']=='failed':raise ValueError(label+' failed')
    if complete(record):return record
    identity=identity_for_pid(record['supervisor_pid'])
    if not identity or identity[0] in ['Z','X'] or (label in owners and owners[label]!=identity[1]):
        # The producer may have atomically published cleanup completion and
        # exited after our first read. Its final record takes precedence.
        fresh=read_record()
        if complete(fresh):return fresh
        raise ValueError(label+' owner disappeared or changed before completion')
    owners.setdefault(label,identity[1])
    return None


def require_macro_poses(import_inventory, before, after):
    def read(path, location_key):
        result = {}
        with Path(path).open() as stream:
            for row in csv.DictReader(stream, delimiter='\t'):
                name = row['instance']
                if name in result or name not in CORES | BANKS:
                    raise ValueError('Duplicate or unknown physical macro: '+name)
                location = tuple(float(x) for x in row[location_key].strip('{}').split())
                if len(location)!=2 or not all(math.isfinite(value) for value in location) or row['orientation']!='r0' or row['status']!='fixed':
                    raise ValueError('Wrong macro geometry/status: '+name)
                expected = 'tri_oracle_sram_memory_compute' if name in CORES else 'TS6N28HPCPSVTA16X128M2F'
                if row['master']!=expected:
                    raise ValueError('Wrong physical macro master: '+name)
                result[name] = (expected, location, row['orientation'], row['status'])
        if set(result)!=CORES | BANKS:
            raise ValueError('Incomplete20-core/40-bank physical macro set')
        return result
    original = read(import_inventory,'actual_location')
    if read(before,'location')!=original or read(after,'location')!=original:
        raise ValueError('Original imported macro pose changed')
    return dict(preserved_macros=60,preserved_core_footprints=20,preserved_aggregate_banks=40,
        evidence_sha256={str(p):digest(p) for p in [import_inventory,before,after]},
        scope='Exact names, masters, reported locations, orientations and fixed status only.')


def require_reset_topology(baseline, candidate):
    original, observed = read_topology(baseline), read_topology(candidate)
    expected = {name+'/rst_n' for name in CORES}
    cores = {name for name in original if not name.startswith('prediction/')}
    prediction = {name for name in original if name.startswith('prediction/')}
    if cores!=expected or not prediction:
        raise ValueError('Actual imported reset endpoint set incomplete')
    if original!=observed:
        raise ValueError('Imported reset endpoint/ancestor/master/clock topology changed')
    return dict(core_reset_endpoints=20,prediction_reset_endpoints=len(prediction),
        baseline_sha256=digest(baseline),candidate_sha256=digest(candidate),
        all_imported_reset_endpoint_chains_preserved=True,
        scope='Exact native imported registered reset ancestry; recovery/removal and reset inverter parity remain unqualified.')

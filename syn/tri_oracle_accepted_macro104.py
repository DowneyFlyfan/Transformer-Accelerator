"""Anchor all60 macro poses to the digest of an accepted parent inventory."""
import csv
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def require_accepted_macro_poses(inventory,accepted_digest,macros,temporary_parent):
    inventory=Path(inventory);macros=Path(macros)
    with tempfile.TemporaryDirectory(prefix='macro104_sort_',dir=temporary_parent) as folder:
        canonical=Path(folder)/'canonical.tsv'
        subprocess.run(['sort','-S','64M','-T',folder,'-o',str(canonical),str(inventory)],
                       env=dict(os.environ,LC_ALL='C'),check=True,timeout=300)
        assert sha(canonical)==accepted_digest,'Changed accepted inventory digest'
    actual={}
    with macros.open(newline='') as stream:
        for row in csv.reader(stream,delimiter='\t'):
            assert len(row)==6,'Malformed macro row'
            name,master,location,orientation,status,pins=row
            assert name not in actual,'Duplicate macro'
            match=re.fullmatch(r'fabric/clusters\[([0-4])\]\.unit/cluster/implementation/(cores\[([0-3])\]|aggregate_memory\[([0-7])\])',name)
            assert match,'Unknown macro identity'
            core=match[3] is not None
            expected_master='tri_oracle_sram_memory_compute' if core else 'TS6N28HPCPSVTA16X128M2F'
            assert master==expected_master and status=='fixed' and pins==('3158' if core else '268'),'Changed fixed interface'
            actual[name]=(master,location,orientation)
    assert len(actual)==60,'Wrong macro count'
    seen=set()
    with inventory.open(newline='') as stream:
        reader=csv.DictReader(stream,delimiter='\t')
        assert reader.fieldnames==['instance','master','location','orientation'],'Malformed accepted inventory'
        for row in reader:
            name=row['instance']
            if name in actual:
                assert name not in seen,'Duplicate accepted macro'
                seen.add(name)
                assert actual[name]==(row['master'],row['location'],row['orientation']),'Changed accepted macro geometry: '+name
    assert seen==set(actual),'Missing accepted macro geometry'
    return dict(accepted_macros=60,accepted_parent_inventory_sha256=accepted_digest,
                macro_baseline_sha256=sha(macros),all20_core_and40_aggregate_macro_poses_bound=True)

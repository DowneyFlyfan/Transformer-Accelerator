"""Expand legal fixed-format search using immutable320 captured rows.

No new model inference, labels, weights, arithmetic or neural architecture.
The first8 images fit formats; the same8 held images are reused diagnostics,
not a fresh unseen test. An external task evaluation remains mandatory.
M=128 rows/split; H=2048 hidden features; K=5632 intermediate channels.
Negative gain caps attenuate up values via additional nonnegative right shifts;
they never place a negative value in a hardware shift field.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('HF_HUB_OFFLINE','1')
os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import torch
from safetensors import safe_open
from tri_oracle_integer_reference import IntegerFeedForwardReference
from audit_tri_oracle_format320_ranges import relative_error


def sha(path):
    """path: scalar input file name; stream/digest: file handle/scalar SHA256."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


@torch.inference_mode()
def main():
    """Paths, receipts, grid and result entries are Python metadata/scalars.
    captured:22 dicts containing CPU activation/residual/target[256,H], generated
    by qualified320 original floating inference. weights gate/up[K,H],down[H,K]
    load directly from pinned float32 safetensors to CUDA. reference initializes
    the unchanged signed8/signed16 arithmetic from those weights and scalar norm
    epsilon. a/r/y[M,H],ha/hr/hy[M,H] are disjoint fitting/held CUDA row slices.
    raw/values[M,H] and stats norm_codes[M,H], counters[M] come from evaluate.
    gain/down/quantum[M] derive from stats; errors and range extrema are scalar.
    No training loss, optimizer or model parameter updates are used.
    """
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    result=root/'records/format322_extended_calibration.json'
    out=root/'.cache/model_reference/format322'
    assert not result.exists() and not out.exists()
    prior_path=root/'records/format320_multi_image_range_audit.json'
    guard_path=root/'records/format321_gpu_guard_result.json'
    prior=json.loads(prior_path.read_text());guard=json.loads(guard_path.read_text())
    assert guard['state']=='completed' and guard['native_exit_status']==0
    assert sha(prior_path)==guard['summary_sha256']
    assert prior['state']=='multi_image_fixed_format_and_range_diagnostic_completed'
    assert len(prior['inputs'])==16 and len(prior['layers'])==22
    assert all(row['split']==('calibration' if i<8 else 'held') for i,row in enumerate(prior['inputs']))
    assert prior['image_pixels_disjoint_from_evaluation'] is True and prior['evaluation_images_excluded']==64
    identities={**prior['source_sha256'],str(prior_path):sha(prior_path),str(guard_path):sha(guard_path),
                str(Path(__file__)):sha(__file__)}
    for path,digest in prior['generated_sha256'].items():
        assert sha(path)==digest;identities[path]=digest
    assert all(sha(path)==digest for path,digest in identities.items())
    model_directory=root/'.cache/model_reference/tiny_llava_v1'
    loader=json.loads((root/'records/format320_loader_metadata.json').read_text())
    assert {p.name for p in model_directory.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    index=json.loads((model_directory/'model.safetensors.index.json').read_text())
    config=json.loads((model_directory/'config.json').read_text())
    captured=torch.load(root/'.cache/model_reference/format320/captured_rows.pt',map_location='cpu',weights_only=True)
    assert len(captured)==22
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0]>10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84);torch.cuda.reset_peak_memory_stats()
    old_grid=[(g,d) for g in [0,2,4,6,7] for d in [-6,-4,-2,-1,0,1,2,3,4,6]]
    extra_grid=[(g,d) for g in [-8,-6,-4,-2,-1,0,2,4,6,7]
                for d in [-6,-4,-2,-1,0,1,2,3,4,6,7,8,9,10,12,14,16] if (g,d) not in old_grid]
    grid=old_grid+extra_grid;assert len(grid)==len(set(grid))==170
    out.mkdir();started=time.monotonic()
    record=dict(state='running',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=identities,checkpoint_revision=prior['checkpoint_revision'],
        calibration_images=8,reused_diagnostic_images=8,rows_per_split=128,
        candidate_count_per_layer=len(grid),layers=[],numerical_reference_changed=False,
        labels_used=False,dataset_accuracy_verified=False,hardware_configuration_mapping_verified=False,
        full_paper_results_matched=False,scope=__doc__)
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    save()
    for layer,row_data in enumerate(captured):
        weights={}
        for kind in ['gate','up','down']:
            suffix=f'.layers.{layer}.mlp.{kind}_proj.weight'
            names=[name for name in index['weight_map'] if name.endswith(suffix)]
            assert len(names)==1
            with safe_open(model_directory/index['weight_map'][names[0]],framework='pt',device='cpu') as shard:
                weights[kind]=shard.get_tensor(names[0]).to('cuda')
            assert weights[kind].dtype==torch.float32
        assert weights['gate'].shape==weights['up'].shape==(5632,2048) and weights['down'].shape==(2048,5632)
        assert all(row_data[name].shape==(256,2048) for name in ['activation','residual','target'])
        a=row_data['activation'][:128].to('cuda');r=row_data['residual'][:128].to('cuda');y=row_data['target'][:128].to('cuda')
        ha=row_data['activation'][128:].to('cuda');hr=row_data['residual'][128:].to('cuda');hy=row_data['target'][128:].to('cuda')
        reference=IntegerFeedForwardReference(weights['gate'],weights['up'],weights['down'],config['text_config']['rms_norm_eps'])
        candidates=[]
        for number,(gain_cap,offset) in enumerate(grid):
            raw,values,stats=reference.evaluate(a,r,prune=False,maximum_up_gain_bits=gain_cap,down_shift_offset=offset)
            error=relative_error(values,y)
            if number<50:
                previous=prior['layers'][layer]['candidate_grid'][number]
                assert (gain_cap,offset)==(previous['maximum_up_gain_bits'],previous['down_shift_offset'])
                assert abs(error-previous['relative_error'])<.000001,'Frozen50-choice baseline failed to reproduce'
            candidates.append(dict(maximum_up_gain_bits=gain_cap,down_shift_offset=offset,relative_error=error))
        best=min(candidates,key=lambda x:x['relative_error'])
        policy={key:best[key] for key in ['maximum_up_gain_bits','down_shift_offset']}
        raw,values,stats=reference.evaluate(ha,hr,prune=False,**policy)
        assert bool(((stats['up_shift']>=0)&(stats['up_shift']<=63)&(stats['down_shift']>=0)&(stats['down_shift']<=63)).all())
        gain=stats['up_gain_bits'];down=stats['down_shift']
        quantum=torch.exp2((down-8-gain).float())
        item=dict(layer=layer,policy=policy,candidate_grid=candidates,
            prior_calibration_error=prior['layers'][layer]['new_calibration_error'],
            new_calibration_error=best['relative_error'],
            prior_held_error=prior['layers'][layer]['new_held_error'],
            new_reused_diagnostic_error=relative_error(values,hy),
            applied_gain_min=int(gain.min()),applied_gain_max=int(gain.max()),
            actual_up_shift_min=int(stats['up_shift'].min()),actual_up_shift_max=int(stats['up_shift'].max()),
            actual_down_shift_min=int(down.min()),actual_down_shift_max=int(down.max()),
            down_input_positive_physical_limit_min=float((127*quantum).min()),
            down_input_positive_physical_limit_max=float((127*quantum).max()),
            gated_endpoint_codes=int(stats['gated_endpoint_codes'].sum()))
        assert item['new_calibration_error']<=item['prior_calibration_error']+.000001
        record['layers'].append(item);save()
        print('FORMAT322_LAYER',layer,'policy',policy,'oldheld',item['prior_held_error'],'newheld',item['new_reused_diagnostic_error'],flush=True)
        del reference,weights
    policy_path=out/'layer_policy.json'
    policy_path.write_text(json.dumps(dict(state='extended_local_fixed_layer_policy',checkpoint_revision=prior['checkpoint_revision'],
        layers=[dict(layer=x['layer'],**x['policy']) for x in record['layers']],
        calibration_images=8,reused_diagnostic_images=8,external_task_evaluation_required=True,
        hardware_configuration_mapping_verified=False),indent=2)+'\n')
    assert all(sha(path)==digest for path,digest in identities.items())
    assert {p.name for p in model_directory.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    save(state='extended_legal_format_search_completed_baseline_reproduced',
        all1100_original_candidate_errors_reproduced=True,
        generated_sha256={str(policy_path):sha(policy_path)},graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated())
    print('FORMAT322_COMPLETED layers=22 candidates=170',flush=True)


if __name__=='__main__':
    main()

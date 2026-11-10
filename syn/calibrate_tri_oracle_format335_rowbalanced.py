"""Fit row-balanced exponent policies using only the original eight fit images.

The old aggregate norm can hide zero outputs on ordinary tokens behind one
large token. Minimize mean per-token relative output error instead. Fit a
fallback pair and independent input-exponent buckets containing at least eight
fit rows. Keep all170 legal candidates, weights and integer arithmetic fixed.
The same eight held images are reused diagnostics, not fresh validation.
No task answers, new model forward, training, task score or chip claim.
M=128 rows per split,H=2048 hidden features,D=5632 intermediate channels.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import torch
from safetensors import safe_open
from tri_oracle_integer_reference import IntegerFeedForwardReference,_quantize
from tri_oracle_format335_policy import evaluate_policy


def sha(path):
    """Caller file path,streamed input bytes -> scalar digest; no tensor allocation."""
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def row_errors(values,target):
    """Caller output/target[M,H], original captured target. delta[M,H] is derived;
    scalar row norms[M] give relative errors[M], keeping each token equally weighted.
    """
    return (values-target).norm(dim=-1)/target.norm(dim=-1).clamp_min(1e-20)


def metrics(raw,values,target):
    """raw[M,H] exact integer output,values/target[M,H] from reference/capture.
    Return scalar aggregate/mean errors and zero-row count; no policy selection.
    """
    return dict(frobenius_relative_error=float((values-target).norm()/target.norm().clamp_min(1e-20)),
                mean_row_relative_error=float(row_errors(values,target).mean()),
                zero_output_rows=int((raw==0).all(dim=-1).sum()))


@torch.inference_mode()
def main():
    """Read frozen metadata and22 captured CPU dicts of activation/residual/target[256,H].
    For each layer gate/up[D,H],down[H,D] float32 trained matrices load from pinned
    safetensors to one graphics processor. The unchanged reference quantizes them.
    a/r/y[M,H] take fit rows0..127; ha/hr/hy[M,H] take reused rows128..255.

    For every frozen candidate raw/values[M,H],stats and errors[M] come from
    unchanged arithmetic and row_errors. error_matrix[170,M] is collected on CPU.
    Exponents[M] derive only from fit activation magnitudes. buckets map scalar
    exponent to the lowest mean row error candidate,with at least8 fit rows.
    Indices[B] select CPU error columns,not model inputs. Policies freeze before
    any held-output metrics are computed. Original3740 fitting Frobenius errors
    must reproduce; no task labels or held rows enter candidate selection.
    """
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/'records/format335_rowbalanced_calibration.json'
    directory=root/'.cache/model_reference/format335'
    assert not output.exists() and not directory.exists()
    qualification=root/'records/format327_qualification.json'
    assert sha(qualification)=='750d9451f8fe8c83a2c517bc91a41f1e30c17cfade13a41678bb92d7f0ab6a81'
    qualified=json.loads(qualification.read_text())
    scoring_path=root/'records/format326_official_scoring.json'
    assert sha(scoring_path)==qualified['scoring_sha256']
    scoring=json.loads(scoring_path.read_text())
    fitted_path=root/'records/format322_extended_calibration.json'
    fitted=json.loads(fitted_path.read_text())
    prior_policy=json.loads((root/'.cache/model_reference/format322/layer_policy.json').read_text())
    assert fitted['state']=='extended_legal_format_search_completed_baseline_reproduced'
    assert prior_policy['state']=='extended_local_fixed_layer_policy'
    inputs=dict(scoring['source_sha256'])
    for path in [Path(__file__),qualification,scoring_path,root/'syn/tri_oracle_format335_policy.py',
                 root/'syn/test_tri_oracle_format335_policy.py',root/'records/format334_row_sensitivity.json',
                 root/'records/format332_failure_diagnosis.json']:
        inputs[str(path)]=sha(path)
    assert all(sha(path)==digest for path,digest in inputs.items())
    model=root/'.cache/model_reference/tiny_llava_v1'
    loader=json.loads((root/'records/format320_loader_metadata.json').read_text())
    assert {p.name for p in model.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    index=json.loads((model/'model.safetensors.index.json').read_text())
    config=json.loads((model/'config.json').read_text())
    captured=torch.load(root/'.cache/model_reference/format320/captured_rows.pt',map_location='cpu',weights_only=True)
    assert len(captured)==22
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0]>10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84);torch.cuda.reset_peak_memory_stats()
    directory.mkdir();started=time.monotonic()
    policies=[]  #22 frozen layer dictionaries; fallback and sufficiently supported exponent buckets.
    grids=[]  #22 CPU error matrices[170,M], fit rows only, stored privately.
    maximum_baseline_difference=0.
    record=dict(state='fitting',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        source_sha256=inputs,checkpoint_revision=fitted['checkpoint_revision'],
        fit_images=8,reused_diagnostic_images=8,fit_rows_per_layer=128,minimum_bucket_fit_rows=8,
        candidates_per_layer=170,layers=[],held_rows_used_for_selection=False,labels_used=False,
        numerical_reference_changed=False,hardware_configuration_mapping_verified=False,
        dataset_accuracy_verified=False,full_paper_results_matched=False,scope=__doc__)
    def save():
        record['elapsed_seconds']=time.monotonic()-started
        temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(output)
    save()
    for layer,data in enumerate(captured):
        assert all(data[key].shape==(256,2048) for key in ['activation','residual','target'])
        weights={}
        for kind in ['gate','up','down']:
            names=[name for name in index['weight_map'] if name.endswith(f'.layers.{layer}.mlp.{kind}_proj.weight')]
            assert len(names)==1
            with safe_open(model/index['weight_map'][names[0]],framework='pt',device='cpu') as shard:
                weights[kind]=shard.get_tensor(names[0]).to('cuda')
        assert weights['gate'].shape==weights['up'].shape==(5632,2048) and weights['down'].shape==(2048,5632)
        reference=IntegerFeedForwardReference(weights['gate'],weights['up'],weights['down'],config['text_config']['rms_norm_eps'])
        a=data['activation'][:128].to('cuda');r=data['residual'][:128].to('cuda');y=data['target'][:128].to('cuda')
        candidate_grid=fitted['layers'][layer]['candidate_grid']
        assert len(candidate_grid)==170
        errors=[]  #170 CPU vectors[M], each from unchanged full-shape integer arithmetic.
        pairs=[]  #170 ordered scalar parameter pairs,exactly the previous frozen grid.
        for candidate in candidate_grid:
            pair={key:candidate[key] for key in ['maximum_up_gain_bits','down_shift_offset']}
            raw,values,_=reference.evaluate(a,r,prune=False,**pair)
            old_metric=float((values-y).norm()/y.norm().clamp_min(1e-20))
            difference=abs(old_metric-candidate['relative_error'])
            maximum_baseline_difference=max(maximum_baseline_difference,difference)
            assert difference<1e-6,(layer,pair,old_metric,candidate['relative_error'])
            errors.append(row_errors(values,y).cpu());pairs.append(pair)
        error_matrix=torch.stack(errors)  # [170,M] CPU,fit rows only.
        assert torch.isfinite(error_matrix).all()
        grids.append(error_matrix)
        global_best=int(error_matrix.mean(dim=1).argmin())
        exponents=_quantize(a,per_row=True)[1][:,0].cpu()  # [M] input-only scale exponent.
        buckets=[]
        selected_errors=error_matrix[global_best].clone()  # [M] expected fit errors for fixed dispatch.
        for exponent in sorted(set(exponents.tolist())):
            positions=torch.nonzero(exponents==exponent,as_tuple=True)[0]  # [B] CPU fit-row indices.
            if positions.numel()<8:continue
            best=int(error_matrix.index_select(1,positions).mean(dim=1).argmin())
            buckets.append(dict(activation_exponent=exponent,fit_rows=int(positions.numel()),**pairs[best]))
            selected_errors.index_copy_(0,positions,error_matrix[best].index_select(0,positions))
        policy=dict(layer=layer,fallback=pairs[global_best],buckets=buckets)
        policies.append(policy)  #Freeze both selectors before evaluating diagnostic rows.
        fit_raw,fit_values,_=evaluate_policy(reference,a,r,policy,prune=False)
        assert float((row_errors(fit_values,y).cpu()-selected_errors).abs().max())<1e-6
        ha=data['activation'][128:].to('cuda');hr=data['residual'][128:].to('cuda');hy=data['target'][128:].to('cuda')
        old_raw,old_values,_=reference.evaluate(ha,hr,prune=False,
            maximum_up_gain_bits=prior_policy['layers'][layer]['maximum_up_gain_bits'],
            down_shift_offset=prior_policy['layers'][layer]['down_shift_offset'])
        uniform_raw,uniform_values,_=reference.evaluate(ha,hr,prune=False,**pairs[global_best])
        new_raw,new_values,new_stats=evaluate_policy(reference,ha,hr,policy,prune=False)
        entry=dict(layer=layer,policy=policy,
            fit_exponent_counts={str(exponent):int((exponents==exponent).sum()) for exponent in sorted(set(exponents.tolist()))},
            fit_bucketed=metrics(fit_raw,fit_values,y),old_reused_diagnostic=metrics(old_raw,old_values,hy),
            uniform_rowbalanced_reused_diagnostic=metrics(uniform_raw,uniform_values,hy),
            bucketed_reused_diagnostic=metrics(new_raw,new_values,hy),
            minimum_hardware_shift=min(int(new_stats[key].min()) for key in ['gate_shift','up_shift','down_shift']),
            maximum_hardware_shift=max(int(new_stats[key].max()) for key in ['gate_shift','up_shift','down_shift']))
        record['layers'].append(entry);save()
        print('FORMAT335_LAYER_FIT',layer,'old_mean',entry['old_reused_diagnostic']['mean_row_relative_error'],
              'new_mean',entry['bucketed_reused_diagnostic']['mean_row_relative_error'],
              'old_zero_rows',entry['old_reused_diagnostic']['zero_output_rows'],
              'new_zero_rows',entry['bucketed_reused_diagnostic']['zero_output_rows'],flush=True)
        del weights,reference,raw,values,fit_raw,fit_values,old_raw,old_values,uniform_raw,uniform_values,new_raw,new_values,new_stats
    policy_path=directory/'layer_policy.json'
    policy_path.write_text(json.dumps(dict(state='row_balanced_exponent_bucket_policy',
        checkpoint_revision=fitted['checkpoint_revision'],minimum_bucket_fit_rows=8,layers=policies),indent=2)+'\n')
    grid_path=directory/'fit_row_errors.pt';torch.save(grids,grid_path)
    assert all(sha(path)==digest for path,digest in inputs.items())
    assert {p.name for p in model.iterdir() if p.is_file()}==set(loader['snapshot_file_names'])
    assert len(record['layers'])==22
    record.update(state='row_balanced_input_exponent_policies_fitted',all3740_prior_fitting_errors_reproduced=True,
        maximum_baseline_error_difference=maximum_baseline_difference,
        generated_sha256={str(path):sha(path) for path in [policy_path,grid_path]},
        graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),graphics_peak_reserved_bytes=torch.cuda.max_memory_reserved())
    save();print('FORMAT335_CALIBRATION_COMPLETED',flush=True)


if __name__=='__main__':main()

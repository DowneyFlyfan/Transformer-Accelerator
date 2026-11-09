"""Paired learned-scale folding diagnostic; no hardware or dataset-accuracy claim.

M=2 archived tokens, H=2048 hidden features, K=5632 intermediate channels,
O=2048 outputs. The original trained first layer remains frozen. This is
inference only; no training loss or optimizer is used.
"""
import hashlib
import json
from pathlib import Path
import time

import torch
from safetensors import safe_open
from tri_oracle_integer_reference import IntegerFeedForwardReference


def sha(path):
    """path: scalar local filename; streaming digest initializes a scalar string."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


@torch.inference_mode()
def main():
    """All non-tensor variables below are scalar paths, labels, metadata or timers.

    Trained gate/up[K,H], down[O,K], gamma[H] come directly from the pinned
    checkpoint. Archived activation/residual[M,H] come from saved model tokens.
    rho[M,H] is residual normalized without gamma; denominator[M,1] is its
    positive root-mean-square norm. Oracle/folded_oracle[M,O] use float64.
    Each reference returns raw[M,O], values[M,O], stats norm_codes[M,H], and
    scalar-per-token[M] shift, outlier and saturation counts. Floating and
    integer_error[M] store one relative error per token, never a task score.
    """
    root=Path(__file__).resolve().parents[1]
    result=root/'records/folded_scale191_gpu_result.json';assert not result.exists()
    started=time.monotonic()
    folder=root/'.cache/model_reference/tiny_llava_v1'
    candidate_path=root/'records/model_reference_candidate.json'
    candidate=json.loads(candidate_path.read_text())
    index_path=folder/'model.safetensors.index.json'
    index=json.loads(index_path.read_text())['weight_map']
    fixtures=[root/'.cache/model_reference'/name for name in ['full_layer_fixture','feedforward_pruning_fixture']]
    sources=[json.loads((path/'prediction_source.json').read_text()) for path in fixtures]
    for path in fixtures:
        manifest=json.loads((path/'manifest.json').read_text())
        assert sha(path/'prediction_source.json')==manifest['files']['prediction_source.json']
    inputs=[Path(__file__).resolve(),candidate_path,index_path,folder/'config.json',
            root/'syn/tri_oracle_integer_reference.py',root/'syn/tri_oracle_model_reference.py',
            *[path/'prediction_source.json' for path in fixtures],*[path/'manifest.json' for path in fixtures],
            fixtures[0]/'expected.hex']
    identities={str(path):sha(path) for path in inputs}
    for item in candidate['verified_weights']:
        path=root/item['path'];assert sha(path)==item['sha256'];identities[str(path)]=item['sha256']
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32=False
    assert torch.cuda.is_available()
    free,total=torch.cuda.mem_get_info();assert free>3*1024**3
    torch.cuda.reset_peak_memory_stats()
    def load(suffix,shape):
        """suffix: scalar checkpoint key; shape: expected dimension tuple.
        loaded[shape] is the trained memory-mapped CPU tensor; the returned
        float32 CUDA tensor has the same explicit gate/up/down/gamma axes.
        """
        name='language_model.model.layers.0.'+suffix
        with safe_open(folder/index[name],framework='pt',device='cpu') as archive:
            loaded=archive.get_tensor(name)
            assert tuple(loaded.shape)==shape
            return loaded.to(device='cuda',dtype=torch.float32)
    gate=load('mlp.gate_proj.weight',(5632,2048))  # [K,H], trained gate matrix.
    up=load('mlp.up_proj.weight',(5632,2048))  # [K,H], trained up matrix.
    down=load('mlp.down_proj.weight',(2048,5632))  # [O,K], trained down matrix.
    gamma=load('post_attention_layernorm.weight',(2048,))  # [H], trained learned scale.
    activation=torch.tensor([s['ffn_activation'] for s in sources],device='cuda',dtype=torch.float32)  # [M,H], archived normalized activations.
    residual=torch.tensor([s['residual_before_rms'] for s in sources],device='cuda',dtype=torch.float32)  # [M,H], archived pre-scale residuals.
    archived_gamma=torch.tensor(sources[0]['learned_normalization_scale'],device='cuda',dtype=torch.float32)  # [H], archive scale witness.
    assert torch.equal(gamma,archived_gamma)
    assert all(s['learned_normalization_scale']==sources[0]['learned_normalization_scale'] for s in sources)
    epsilon=float(json.loads((folder/'config.json').read_text())['text_config']['rms_norm_eps'])
    assert all(s['rms_epsilon']==epsilon for s in sources)
    denominator=(residual.double().square().mean(dim=1,keepdim=True)+epsilon).sqrt()  # [M,1], direct norm calculation.
    rho=residual.double()/denominator  # [M,H], gamma-free normalization.
    reconstruction=rho*gamma.double()[None,:]  # [M,H], float64 learned-scale reconstruction.
    norm_error=(reconstruction-activation.double()).norm(dim=1)/activation.double().norm(dim=1)  # [M], archived-input consistency.
    assert bool((norm_error<1e-6).all())
    gate_float=activation.double()@gate.double().t()  # [M,K], trained gate projection.
    up_float=activation.double()@up.double().t()  # [M,K], trained up projection.
    oracle=(torch.nn.functional.silu(gate_float)*up_float)@down.double().t()  # [M,O], original float64 feed-forward output.
    folded_gate=gate*gamma[None,:]  # [K,H], static float32 coefficient folding for integer quantization.
    folded_up=up*gamma[None,:]  # [K,H], static float32 coefficient folding.
    exact_folded_gate=gate.double()*gamma.double()[None,:]  # [K,H], float64 identity witness.
    exact_folded_up=up.double()*gamma.double()[None,:]  # [K,H], float64 identity witness.
    folded_oracle=(torch.nn.functional.silu(rho@exact_folded_gate.t())*(rho@exact_folded_up.t()))@down.double().t()  # [M,O], reassociated float64 path.
    identity_error=(folded_oracle-oracle).norm(dim=1)/oracle.norm(dim=1)  # [M], paired floating equivalence error.
    assert bool((identity_error<1e-6).all())
    cases=[]
    baseline_norm_codes=None  # [M,H], initialized from the first original-format evaluation.
    for policy,gate_weight,up_weight,input_values in [
        ('original',gate,up,activation),('folded_learned_scale',folded_gate,folded_up,rho.float())]:
        # gate_weight/up_weight[K,H] and input_values[M,H] alias the tensors above.
        reference=IntegerFeedForwardReference(gate_weight,up_weight,down,epsilon)
        for prune in [False,True]:
            raw,values,stats=reference.evaluate(input_values,residual,prune=prune,
                maximum_up_gain_bits=7,down_shift_offset=-1,gate_threshold=0,up_window=0)
            # raw/values[M,O] and norm_codes[M,H] are returned by the frozen reference.
            if baseline_norm_codes is None:baseline_norm_codes=stats['norm_codes'].clone()
            assert torch.equal(baseline_norm_codes,stats['norm_codes'])
            integer_error=(values.double()-oracle).norm(dim=1)/oracle.norm(dim=1)  # [M], local output error only.
            archived_match=None
            if policy=='original' and not prune:
                expected=[int(s,16) for s in (fixtures[0]/'expected.hex').read_text().splitlines()]
                archived_match=[int(v)&0xffffffff for v in raw[0].tolist()]==expected
                assert archived_match,'Original integer reference no longer matches archived2048-word fixture'
            cases.append(dict(policy=policy,prune=prune,relative_l2_per_token=integer_error.tolist(),
                gate_shift=stats['gate_shift'].tolist(),up_shift=stats['up_shift'].tolist(),down_shift=stats['down_shift'].tolist(),
                predicted_skips=stats['skip_count'].tolist(),outliers=stats['outlier_count'].tolist(),
                up_endpoint_codes=stats['up_endpoint_codes'].tolist(),gated_endpoint_codes=stats['gated_endpoint_codes'].tolist(),
                original_archived_2048_output_words_match=archived_match))
    torch.cuda.synchronize()
    assert torch.cuda.max_memory_allocated()<2*1024**3
    assert all(sha(path)==digest for path,digest in identities.items())
    result.write_text(json.dumps(dict(state='paired_folded_scale_diagnostic_completed',source_sha256=identities,
        checkpoint_revision=candidate['revision'],token_positions=[11,0],token_count=2,layer_index=0,
        floating_reconstruction_relative_l2=norm_error.tolist(),floating_identity_relative_l2=identity_error.tolist(),
        cases=cases,elapsed_seconds=time.monotonic()-started,
        gpu_name=torch.cuda.get_device_name(0),graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
        graphics_peak_reserved_bytes=torch.cuda.max_memory_reserved(),
        policy='Same fixed gain cap7 and down-offset-1; only learned-scale placement changes. Local builder policy, not recovered paper parameters.',
        source_hardware_changed=False,full_model_accuracy_qualified=False,paper_results_matched=False,
        scope=__doc__),indent=2)+'\n')
    print('FOLDED_SCALE191_DIAGNOSTIC_COMPLETE',json.dumps(cases),flush=True)


if __name__=='__main__':main()

"""Export fit-selected Gate/Up codebooks without modifying current weights.

F=120 fit rows, E=120 reused diagnostic rows, H=2048 input features,
K=5632 intermediate outputs. Exported codebooks are alternative signed8
weights for ordinary prefill only; hardware transport is not qualified here.
"""
if not __debug__:raise RuntimeError('Code export requires assertions')
from hashlib import file_digest,sha256
import json,time
from pathlib import Path
import torch
from safetensors import safe_open
from tri_oracle_integer_reference import _quantize
from measure_tri_oracle_gate_up_code_calibration import fit_projection_codes,projection_error


def tensor_sha(value):
    """Caller signed8 matrix[K,H]; fresh contiguous CPU bytes define its hash."""
    return sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def validate_payload(payload,gate,up,gate_exponent,up_exponent):
    """Caller original signed8 Gate/Up[K,H] and scalar original exponents.
    payload contains loaded signed8 candidate tensors of the same shapes.
    Difference[K,H] is evaluated in signed16 on each original's device.
    Reject malformed keys, shapes, types, exponents and any code step>1.
    """
    if not isinstance(payload,dict) or set(payload)!={'gate','up','gate_exponent','up_exponent'}:
        raise ValueError('Invalid codebook fields')
    for role,original,exponent in (('gate',gate,gate_exponent),('up',up,up_exponent)):
        value=payload[role]
        if not isinstance(value,torch.Tensor) or value.dtype!=torch.int8 or value.shape!=original.shape or original.dtype!=torch.int8:
            raise ValueError('Invalid exported code shape or dtype')
        if type(payload[role+'_exponent']) is not int or payload[role+'_exponent']!=exponent:
            raise ValueError('Exported weight exponent differs')
        difference=value.to(device=original.device,dtype=torch.int16)-original.to(torch.int16)  # [K,H].
        if not bool((difference.abs()<=1).all()):raise ValueError('Exported code step exceeds one')


@torch.inference_mode()
def run(stage):
    """Scalar paths/hashes/records determine the published selected layers.
    Captures are CPU-mapped22 dictionaries of activation[256,H]; selected
    activation[F+E,H] excludes token0. Per branch checkpoint W[K,H] float32,
    original/candidate/repeated codes[K,H] signed8 are on the graphics device.
    Payload copies candidate codes to CPU; records contain scalar hashes only.
    """
    root=Path.cwd();cache=root/'.cache/model_reference';started=time.monotonic()
    assert not Path('/.dockerenv').exists() and stage.resolve().is_relative_to(cache.resolve())
    assert stage.is_dir() and not (stage/'export.json').exists()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision('highest');torch.cuda.set_per_process_memory_fraction(.15)
    torch.cuda.reset_peak_memory_stats();pins={}
    def read(path):return json.loads(path.read_text())
    def pin(path,wanted=None):
        with path.open('rb') as f:digest=file_digest(f,'sha256').hexdigest()
        assert wanted is None or digest==wanted,('Changed export input',path)
        assert pins.setdefault(str(path.resolve()),digest)==digest
        return path
    published=read(pin(root/'records/tri_oracle_gate_up_code_calibration_diagnostic.json'))
    assert published['state']=='bounded_discrete_gate_up_code_calibration_diagnostic_improved_without_promotion'
    for name,digest in published['evidence_sha256'].items():pin(root/name,digest)
    name,=[name for name in published['evidence_sha256'] if name.endswith('/receipt.json')]
    diagnostic=read(root/name)
    for name,digest in diagnostic['input_sha256'].items():pin(Path(name),digest)
    for path in (Path(__file__).resolve(),root/'syn/test_tri_oracle_gate_up_code_export.py',
                 stage/'export_guard.py',stage/'export_architecture.pdf',stage/'export_architecture.dot'):
        pin(path)
    assert diagnostic['checkpoint_revision']==published['checkpoint_revision']
    selected=published['selected_layers'];assert selected==[3,6,12,15,17,18,19,20]
    model=cache/'tiny_llava_v1';mapping=read(model/'model.safetensors.index.json')['weight_map']
    captures=torch.load(cache/'format320/captured_rows.pt',map_location='cpu',weights_only=True,mmap=True)
    rows=[row for row in range(256) if row%16];assert len(rows)==240
    records=[]
    for layer in selected:
        expected=diagnostic['layers'][layer];assert expected['layer']==layer and expected['choice']=='calibrated'
        activation=captures[layer]['activation'][rows].to('cuda')  # [F+E,H], fixed archived ordinary rows.
        assert activation.shape==(240,2048)
        payload={};originals={};original_hashes={};numeric_hashes={}
        for role in ('gate','up'):
            key,=(name for name in mapping if name.endswith(f'.layers.{layer}.mlp.{role}_proj.weight'))
            with safe_open(model/mapping[key],framework='pt',device='cpu') as shard:
                weight=shard.get_tensor(key).to(device='cuda',dtype=torch.float32)  # [K,H], pinned checkpoint.
            assert weight.shape==(5632,2048)
            original,power=_quantize(weight);exponent=int(power)  # [K,H], scalar, existing global format.
            candidate=fit_projection_codes(activation[:120],weight,original,exponent)  # [K,H], fit-only codes.
            repeated=fit_projection_codes(activation[:120],weight,original,exponent)  # [K,H], independent repeat.
            assert torch.equal(candidate,repeated),('Nonreproducible code fit',layer,role)
            assert int(candidate.ne(original).sum())==expected['changed_codes'][role]
            assert int((candidate<0).ne(original<0).sum())==expected['changed_signs'][role]
            assert exponent==expected['scalar_weight_exponents'][role]
            for split,indices in (('fit',slice(0,120)),('diagnostic',slice(120,None))):
                assert abs(projection_error(activation[indices],weight,candidate,exponent)-expected['projections'][role][split]['calibrated'])<1e-12
            payload[role]=candidate.cpu();payload[role+'_exponent']=exponent
            originals[role]=original  # [K,H], retained until full payload validation.
            original_hashes[role]=tensor_sha(original);numeric_hashes[role]=tensor_sha(candidate)
            # Validate each branch before releasing the original GPU matrix.
            assert bool(((candidate.to(torch.int16)-original.to(torch.int16)).abs()<=1).all())
            del weight,original,candidate,repeated
        validate_payload(payload,originals['gate'],originals['up'],payload['gate_exponent'],payload['up_exponent'])
        path=stage/f'gate_up_{layer:02d}.pt';assert not path.exists()
        with path.open('xb') as f:torch.save(payload,f)
        loaded=torch.load(path,map_location='cpu',weights_only=True)
        validate_payload(loaded,originals['gate'],originals['up'],payload['gate_exponent'],payload['up_exponent'])
        assert set(loaded)==set(payload)
        for role in ('gate','up'):
            assert torch.equal(loaded[role],payload[role]) and tensor_sha(loaded[role])==numeric_hashes[role]
            assert loaded[role+'_exponent']==payload[role+'_exponent']
        pin(path)
        records.append(dict(layer=layer,path=str(path.resolve()),sha256=pins[str(path.resolve())],
            bytes=path.stat().st_size,original_numeric_sha256=original_hashes,candidate_numeric_sha256=numeric_hashes,
            scalar_exponents={role:payload[role+'_exponent'] for role in ('gate','up')},shape=[5632,2048]))
        print('GATE_UP_CODEBOOK_EXPORTED',layer,path.stat().st_size,flush=True)
        del activation,payload,loaded,originals
    for name,wanted in pins.items():
        with Path(name).open('rb') as f:assert file_digest(f,'sha256').hexdigest()==wanted,('Changed final export input',name)
    report=dict(state='selected_gate_up_codebooks_reproduced_and_exported',checkpoint_revision=published['checkpoint_revision'],
        selected_layers=selected,layers=records,exact_repeat_projection_matrices=16,codebooks_disk_roundtrip_verified=8,
        maximum_code_step=1,input_sha256=pins,elapsed_seconds=time.monotonic()-started,
        device=torch.cuda.get_device_name(),peak_device_bytes=torch.cuda.max_memory_allocated(),
        new_weight_transport_verified=False,task_accuracy_verified=False,mapped_execution_verified=False,
        scope='Exact repeated fit and disk roundtrip of8selected alternative Gate/Up matrices; current baseline files unchanged. Numeric images alone do not qualify packed hardware transport, scheduling, task accuracy or mapped execution.')
    with (stage/'export.json').open('x') as f:f.write(json.dumps(report,indent=2)+'\n')
    print('GATE_UP_EXPORT_COMPLETE',len(records),report['elapsed_seconds'],flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',type=Path)
    run(parser.parse_args().stage.resolve())

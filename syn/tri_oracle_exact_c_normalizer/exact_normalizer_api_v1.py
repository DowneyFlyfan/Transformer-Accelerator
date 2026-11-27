"""Exact encoded current-C normalization with explicit CPU/CUDA backends.

Module import loads no Torch/Triton/model/compiler, creates no file/device and
builds no extension. Original inert5198 is preserved in inert_api_snapshot_v1.py.
Axes: M independent rows; N octet features8..4096. Inputs are encoded integers,
not FLOAT/model inputs. No loss, optimizer, policy dispatch or residual add.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import types

_HERE=Path(__file__).resolve().parent
_CPU_SHA256='e9e4a1eb776e4283d321ad89d81bc48d0c288c97f2ff4616fb57ca6cf643f29e'
_EXTENSION_NAME='exact_c_normalizer_cuda_v1'
_OUTPUT_KEYS=('codes','activation_exponent','outlier_mask','normalized_negative','outlier_negative','error_codes')
_CPU_MODULE=None
_CUDA_MODULE=None
_CUDA_IDENTITY=None


def _load_cpu_module():
    global _CPU_MODULE
    if _CPU_MODULE is None:
        path=_HERE/'cpu_fixedwords_v1.py';source=path.read_bytes()
        if hashlib.sha256(source).hexdigest()!=_CPU_SHA256:
            raise ValueError('Authenticated fixed-word CPU source changed')
        module=types.ModuleType('exact_c_cpu_fixedwords_v1');module.__file__=str(path)
        exec(compile(source,str(path),'exec'),module.__dict__)
        _CPU_MODULE=module
    return _CPU_MODULE


def normalize24_cpu(raw,gain,epsilon_q16,gamma_exponent):
    """Explicit fixed-word CPU path, never evidence of GPU execution.

    Caller/init/axes: raw integer lists[M,N] signed32; gain lists[N] broadcast
    or[M,N] carrying signed24; epsilon exact uint64-valued lists[M]; gamma
    signed8-valued lists[M]. Newly initialized outputs: codes[M,N], eA[M],
    threeBoolean planes[M,N], errors[M]. M rows,N features; no oracle/floats.
    """
    return _load_cpu_module().normalize24_cpu_fixedwords(raw,gain,epsilon_q16,gamma_exponent)


def load_cuda_backend(shared_object,expected_sha256):
    """Explicit Root-built .so path/hash identity join, never a JIT/approval.

    Scalar metadata only: exact existing artifact under the project's .cache
    directory and lowerhex SHA256. No replacement of a loaded module in-process.
    """
    global _CUDA_MODULE,_CUDA_IDENTITY
    if type(expected_sha256)is not str or re.fullmatch('[0-9a-f]{64}',expected_sha256)is None:
        raise ValueError('Exact lowerhex extension digest required')
    path=Path(shared_object).resolve(strict=True);build=(_HERE.parents[1]/'.cache').resolve()
    if not path.is_relative_to(build) or not path.is_file() or path.suffix!='.so' or not path.name.startswith(_EXTENSION_NAME):
        raise ValueError('Explicit project .cache CUDA extension path required')
    identity=(str(path),expected_sha256)
    if _CUDA_MODULE is not None:
        if _CUDA_IDENTITY!=identity:raise ValueError('CUDA extension identity cannot change in a process')
        return
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha256:
        raise ValueError('CUDA extension digest mismatch')
    # Explicit CUDA loading only: PyTorch must expose its shared libraries.
    import torch
    spec=importlib.util.spec_from_file_location(_EXTENSION_NAME,path)
    if spec is None or spec.loader is None:raise RuntimeError('Cannot construct selected CUDA extension loader')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if not callable(getattr(module,'normalize24',None)):
        raise RuntimeError('Selected CUDA extension lacks exact normalization API')
    _CUDA_MODULE=module;_CUDA_IDENTITY=identity


def _selected_cuda_module():
    if _CUDA_MODULE is None:
        path=os.environ.get('EXACT_C_CUDA_EXTENSION_PATH');digest=os.environ.get('EXACT_C_CUDA_EXTENSION_SHA256')
        if path is None or digest is None:
            raise RuntimeError('Root must separately build/select the reviewed CUDA extension; no automatic JIT/fallback')
        load_cuda_backend(path,digest)
    return _CUDA_MODULE


def normalize24_cuda(raw,gain,epsilon_q16,gamma_exponent):
    """Two integer kernels on caller's explicit current CUDA stream.

    Caller/init/axes: contiguous CUDA raw int32[M,N]; gain int32[N] or[M,N]
    signed24; epsilon uint64[M]; gamma exponent int8[M]. All same device and
    immutable until completion. New outputs codes int8[M,N], eA int16[M]
    signed9, threebool[M,N] planes, errors int32[M]. No CPU value transfer,
    hidden dtype/stride/device copy, oracle, FLOAT norm or extension build.
    """
    import torch
    values=(raw,gain,epsilon_q16,gamma_exponent)
    if not all(isinstance(value,torch.Tensor)for value in values):raise ValueError('Four explicitly encoded tensors required')
    if not all(value.layout==torch.strided and value.is_cuda and value.is_contiguous()for value in values):
        raise ValueError('Contiguous CUDA tensors required; no hidden copies')
    if any(value.device!=raw.device for value in values):raise ValueError('Inputs must share the same explicitly selected CUDA device')
    if raw.dtype!=torch.int32 or gain.dtype!=torch.int32 or epsilon_q16.dtype!=torch.uint64 or gamma_exponent.dtype!=torch.int8:
        raise ValueError('Exact signed32/gain32/unsigned64/signed8 tensor dtypes required')
    if raw.ndim!=2 or raw.shape[0]<1 or not 8<=raw.shape[1]<=4096 or raw.shape[1]%8:
        raise ValueError('Complete positive batch of octet feature rows required')
    rows,features=raw.shape
    if tuple(gain.shape)not in((features,),(rows,features))or tuple(epsilon_q16.shape)!=(rows,)or tuple(gamma_exponent.shape)!=(rows,):
        raise ValueError('Gain[N] or[M,N], epsilon/exponent[M] required')
    backend=_selected_cuda_module();results=backend.normalize24(raw,gain,epsilon_q16,gamma_exponent)
    if type(results)not in(tuple,list)or len(results)!=len(_OUTPUT_KEYS):raise RuntimeError('Selected CUDA backend output schema mismatch')
    # Output metadata only, never transfer/recompute values on CPU.
    expected_dtypes=(torch.int8,torch.int16,torch.bool,torch.bool,torch.bool,torch.int32);output={}
    for key,value,dtype in zip(_OUTPUT_KEYS,results,expected_dtypes):
        wanted=(rows,)if key in('activation_exponent','error_codes')else(rows,features)
        if not isinstance(value,torch.Tensor)or value.device!=raw.device or value.dtype!=dtype or tuple(value.shape)!=wanted or not value.is_contiguous():
            raise RuntimeError('Selected CUDA backend output metadata mismatch: '+key)
        output[key]=value
    return output

"""Explicit Compute Unified Device Architecture (CUDA) input bit encoder.

Caller/source: raw float32[M,N] and gamma float32[N] or[M,N] are original
binary32 values, never normalized/reference targets. N=8..4096 in octets.
The selected native backend bit-interprets these CUDA inputs. New outputs:
raw int32[M,N], gain int32[gamma.shape] carrying signed24, raw/gamma units
int8[M], and epsilon uint64[M]. No model/loss/optimizer or CPU encoding exists.
Only one internal validation flag scalar crosses to the host to raise errors.
The caller selects a separately built library from the project cache.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import re

_HERE = Path(__file__).resolve().parent
_PROJECT_CACHE = _HERE.parent.parent / '.cache'
_NAME = 'exact_c_input_encoder_cuda_v1'
_OUTPUT_KEYS = ('raw', 'gain', 'raw_unit_exponent', 'gamma_exponent', 'epsilon_q16')
_BACKEND = None
_IDENTITY = None


def load_cuda_backend(shared_object, expected_sha256):
    """Admit one explicitly built artifact by existing project-cache path/hash.

    Metadata only; this function never compiles, builds, selects a CPU encoder,
    or replaces a previously loaded identity. Root separately admits the build.
    """
    global _BACKEND, _IDENTITY
    if type(expected_sha256) is not str or re.fullmatch('[0-9a-f]{64}', expected_sha256) is None:
        raise ValueError('Exact lowercase extension SHA256 required')
    path = Path(shared_object).resolve(strict=True)
    if not path.is_relative_to(_PROJECT_CACHE.resolve()) or not path.is_file() or path.suffix != '.so' or not path.name.startswith(_NAME):
        raise ValueError('Explicit project-cache build artifact required')
    identity = (str(path), expected_sha256)
    if _BACKEND is not None:
        if _IDENTITY != identity:
            raise ValueError('Loaded CUDA encoder identity cannot change')
        return
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError('CUDA encoder artifact SHA256 mismatch')
    # Explicit loading needs PyTorch's shared libraries; no extension builder
    # is imported here or anywhere in the arithmetic invocation path.
    import torch
    spec = importlib.util.spec_from_file_location(_NAME, path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot construct admitted CUDA encoder loader')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, 'encode_physical', None)):
        raise RuntimeError('Admitted encoder binary lacks the selected entrypoint')
    _BACKEND, _IDENTITY = module, identity


def _selected_backend():
    if _BACKEND is None:
        path = os.environ.get('EXACT_C_INPUT_ENCODER_CUDA_EXTENSION_PATH')
        digest = os.environ.get('EXACT_C_INPUT_ENCODER_CUDA_EXTENSION_SHA256')
        if path is None or digest is None:
            raise RuntimeError('Root must explicitly build/select the reviewed CUDA encoder; no JIT/fallback')
        load_cuda_backend(path, digest)
    return _BACKEND


def encode_physical_input_cuda(raw, gamma):
    """Original CUDA binary32 inputs -> five fresh encoded integer tensors.

    raw[M,N], gamma[N] or[M,N]: caller-owned contiguous float32 tensors on
    the same explicit device. Native outputs[M,N]/[gamma.shape]/[M] originate
    from separate allocations and preserve original axes. The native unit
    scan/recode kernels use that device's current stream. Input values remain
    unchanged, including signed zero and rejected nonfinite payload bits.
    Only validation[1] int32 is read on the host; no input/code value is read
    or encoded by Python. A nonzero flag rejects the entire operation.
    """
    import torch
    if not all(isinstance(value, torch.Tensor) for value in (raw, gamma)):
        raise ValueError('Explicit raw/gamma tensors required')
    if not all(value.layout == torch.strided and value.is_cuda and value.is_contiguous() for value in (raw, gamma)):
        raise ValueError('Contiguous strided CUDA inputs required; no hidden copies')
    if raw.device != gamma.device or raw.dtype != torch.float32 or gamma.dtype != torch.float32:
        raise ValueError('Same-device original float32 inputs required')
    if raw.ndim != 2 or raw.shape[0] < 1 or not 8 <= raw.shape[1] <= 4096 or raw.shape[1] % 8:
        raise ValueError('Positive matrix of complete feature octets required')
    rows, features = raw.shape
    if tuple(gamma.shape) not in ((features,), (rows, features)):
        raise ValueError('Gamma[N] or gamma[M,N] required')
    values = _selected_backend().encode_physical(raw, gamma)
    if type(values) not in (list, tuple) or len(values) != 6:
        raise RuntimeError('Admitted CUDA encoder result schema changed')
    validation = values[5]  # New native int32[1], one whole-operation flag.
    if (not isinstance(validation, torch.Tensor) or validation.device != raw.device
            or validation.layout != torch.strided or validation.dtype != torch.int32
            or tuple(validation.shape) != (1,) or not validation.is_contiguous()):
        raise RuntimeError('Admitted CUDA encoder validation flag metadata changed')
    if validation.item() != 0:
        raise ValueError('Nonfinite original input or unrepresentable signed8 gamma unit')
    dtypes = (torch.int32, torch.int32, torch.int8, torch.int8, torch.uint64)
    result = {}
    for index, (key, dtype) in enumerate(zip(_OUTPUT_KEYS, dtypes)):
        value = values[index]
        shape = tuple(raw.shape) if key == 'raw' else tuple(gamma.shape) if key == 'gain' else (rows,)
        if (not isinstance(value, torch.Tensor) or value.device != raw.device
                or value.layout != torch.strided or value.dtype != dtype
                or tuple(value.shape) != shape or not value.is_contiguous()):
            raise RuntimeError('Admitted CUDA encoder output metadata changed: ' + key)
        result[key] = value
    return result

#include <torch/extension.h>
#include <c10/cuda/CUDAGuard.h>
#include <cstdint>
#include <limits>
#include <vector>

std::vector<at::Tensor> input_encoder_cuda_launch(
    const at::Tensor& raw, const at::Tensor& gamma);

// Metadata defenses only. All value validation and encoding stay on CUDA;
// Python reads only the returned one-element device error flag to raise ValueError.
std::vector<at::Tensor> encode_physical(
    const at::Tensor& raw, const at::Tensor& gamma) {
  TORCH_CHECK(raw.is_cuda() && gamma.is_cuda(), "CUDA inputs required");
  TORCH_CHECK(raw.layout() == at::kStrided && gamma.layout() == at::kStrided, "Strided inputs required");
  TORCH_CHECK(raw.device() == gamma.device(), "One explicit CUDA device required");
  TORCH_CHECK(raw.scalar_type() == at::kFloat && gamma.scalar_type() == at::kFloat, "Original float32 inputs required");
  TORCH_CHECK(raw.is_contiguous() && gamma.is_contiguous(), "Contiguous inputs required; no hidden copies");
  TORCH_CHECK(raw.dim() == 2 && raw.size(0) > 0 && raw.size(1) >= 8 &&
      raw.size(1) <= 4096 && raw.size(1) % 8 == 0, "Complete positive octet matrix required");
  const int64_t rows = raw.size(0);
  const int64_t features = raw.size(1);
  const bool broadcast = gamma.dim() == 1;
  TORCH_CHECK((broadcast && gamma.size(0) == features) ||
      (gamma.dim() == 2 && gamma.sizes() == raw.sizes()), "Gamma[N] or gamma[M,N] required");
  const int64_t gain_rows = broadcast ? 1 : rows;
  TORCH_CHECK(rows <= std::numeric_limits<int>::max() - gain_rows,
      "Unit-scan CUDA grid bound exceeded");
  TORCH_CHECK(1 + (raw.numel() - 1) / 128 <= std::numeric_limits<int>::max(),
      "Recode CUDA grid bound exceeded");
  const c10::cuda::CUDAGuard device_guard(raw.device());
  return input_encoder_cuda_launch(raw, gamma);
}

PYBIND11_MODULE(TORCH_EXTENSION_NAME, module) {
  module.def("encode_physical", &encode_physical,
      "Exact original-bit physical input encoding on the caller current CUDA stream");
}

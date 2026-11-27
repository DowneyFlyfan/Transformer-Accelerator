#include <torch/extension.h>
#include <c10/cuda/CUDAGuard.h>
#include <cstdint>
#include <limits>
#include <vector>

std::vector<torch::Tensor> exact_normalizer_cuda_launch(
    const torch::Tensor& raw, const torch::Tensor& gain,
    const torch::Tensor& epsilon, const torch::Tensor& gamma);

// Defensive metadata checks repeat the Python ValueError boundary. There is no
// host value read or fallback. All tensors remain on the same current device.
std::vector<torch::Tensor> normalize24(
    const torch::Tensor& raw, const torch::Tensor& gain,
    const torch::Tensor& epsilon, const torch::Tensor& gamma) {
  TORCH_CHECK(raw.is_cuda() && gain.is_cuda() && epsilon.is_cuda() && gamma.is_cuda(), "CUDA tensors required");
  TORCH_CHECK(raw.device() == gain.device() && raw.device() == epsilon.device() && raw.device() == gamma.device(), "One CUDA device required");
  TORCH_CHECK(raw.is_contiguous() && gain.is_contiguous() && epsilon.is_contiguous() && gamma.is_contiguous(), "Contiguous inputs required; no hidden copies");
  TORCH_CHECK(raw.scalar_type() == at::kInt && gain.scalar_type() == at::kInt, "Raw/gain int32 required");
  TORCH_CHECK(epsilon.scalar_type() == at::ScalarType::UInt64 && gamma.scalar_type() == at::kChar, "Unsigned64 epsilon and signed8 exponent required");
  TORCH_CHECK(raw.dim() == 2 && raw.size(0) > 0 && raw.size(1) >= 8 && raw.size(1) <= 4096 && raw.size(1) % 8 == 0, "Legal complete octet rows required");
  const int64_t rows = raw.size(0);
  const int64_t features = raw.size(1);
  TORCH_CHECK((gain.dim() == 1 && gain.size(0) == features) ||
      (gain.dim() == 2 && gain.sizes() == raw.sizes()), "Gain[N] or gain[M,N] required");
  TORCH_CHECK(epsilon.dim() == 1 && gamma.dim() == 1 && epsilon.size(0) == rows && gamma.size(0) == rows, "One epsilon/exponent per row required");
  TORCH_CHECK(1 + (raw.numel() - 1) / 128 <= std::numeric_limits<int>::max(), "CUDA grid bound exceeded");
  const c10::cuda::CUDAGuard device_guard(raw.device());
  return exact_normalizer_cuda_launch(raw, gain, epsilon, gamma);
}

PYBIND11_MODULE(TORCH_EXTENSION_NAME, module) {
  module.def("normalize24", &normalize24, "Exact current-C integer normalization on the caller current CUDA stream");
}

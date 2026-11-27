// Original binary32 bit encoding only: no numeric floating arithmetic or CPU path.
#include <ATen/core/Tensor.h>
#include <ATen/ops/empty.h>
#include <ATen/ops/zeros.h>
#include <c10/cuda/CUDAException.h>
#include <c10/cuda/CUDAStream.h>
#include <cuda_runtime.h>
#include <cstdint>
#include <vector>

namespace {
constexpr int kThreads = 128;

// Index i corresponds to raw unit i-32. All33 constants are checked against
// the frozen rational scalar oracle outside this implementation.
__device__ __constant__ uint64_t kEpsilon[33] = {
    12089258196146291747ULL, 3022314549036572937ULL, 755578637259143234ULL,
    188894659314785809ULL, 47223664828696452ULL, 11805916207174113ULL,
    2951479051793528ULL, 737869762948382ULL, 184467440737096ULL,
    46116860184274ULL, 11529215046068ULL, 2882303761517ULL, 720575940379ULL,
    180143985095ULL, 45035996274ULL, 11258999068ULL, 2814749767ULL, 703687442ULL,
    175921860ULL, 43980465ULL, 10995116ULL, 2748779ULL, 687195ULL, 171799ULL,
    42950ULL, 10737ULL, 2684ULL, 671ULL, 168ULL, 42ULL, 10ULL, 3ULL, 1ULL};

// For a finite magnitude word: significand<=24bits, power -149..104.
// The seed ratio lies[2^(width-2),2^(width-1)), so one increment at most
// meets the symmetric POSITIVE limit and the preceding unit cannot fit.
// Seed alignment is<=31bits(raw32) or<=24bits(gain24); never asymmetric.
__device__ __forceinline__ int minimal_unit(uint32_t absolute_word, int width) {
  if (absolute_word == 0) return 0;
  const int encoded_exponent = int(absolute_word >> 23);
  const uint32_t fraction = absolute_word & 0x7fffffu;
  const uint32_t significand = encoded_exponent ? fraction | 0x800000u : fraction;
  const int power = encoded_exponent ? encoded_exponent - 150 : -149;
  const int unit = power + (31 - __clz(significand)) - (width - 2);
  const int shift = power - unit;
  const uint64_t limit = (uint64_t(1) << (width - 1)) - 1;
  const bool exceeds = shift >= 0 ? (uint64_t(significand) << shift) > limit
      : uint64_t(significand) > (limit << -shift);
  return unit + int(exceeds);
}

// Round ORIGINAL bits directly at the final selected unit. A rightshift>24
// is belowhalf for every24-bit significand; otherwise rounding add<=25bits.
// A nonnegative shift is bounded by the selected positive-limit unit, so
// magnitude<=INT32_MAX(raw) or2^23-1(gain), and negation stays representable.
__device__ __forceinline__ int32_t encode_word(uint32_t word, int unit) {
  const int encoded_exponent = int((word >> 23) & 255u);
  const uint32_t fraction = word & 0x7fffffu;
  const uint32_t significand = encoded_exponent ? fraction | 0x800000u : fraction;
  if (significand == 0) return 0;
  const int power = encoded_exponent ? encoded_exponent - 150 : -149;
  const int shift = power - unit;
  uint32_t magnitude;
  if (shift >= 0) magnitude = significand << shift;
  else {
    const int right = -shift;
    magnitude = right > 24 ? 0u : (significand + (uint32_t(1) << (right - 1))) >> right;
  }
  return word >> 31 ? -int32_t(magnitude) : int32_t(magnitude);
}

// One block per raw row or gain row: original source arrays[M,N]/[G,N],
// G=1 broadcast or M rowwise. Each thread visits disjoint source features;
// shared max/invalid reduction is deterministic, using only uint32 words.
// raw_units[M]/epsilon[M] and gain_units[G] are written once per row.
// error[1] is a newly zeroed whole-operation flag: bit0nonfinite,bit1badgainunit.
__global__ void unit_scan_kernel(
    const float* raw, const float* gamma, int64_t rows, int features,
    int8_t* raw_units, int32_t* gain_units, uint64_t* epsilon, int32_t* error) {
  const int64_t unit_row = int64_t(blockIdx.x);
  const bool is_gain = unit_row >= rows;
  const int64_t row = is_gain ? unit_row - rows : unit_row;
  const float* source = is_gain ? gamma : raw;
  __shared__ uint32_t maximum[kThreads];
  __shared__ uint32_t invalid[kThreads];
  uint32_t local_maximum = 0, local_invalid = 0;
  for (int feature = int(threadIdx.x); feature < features; feature += kThreads) {
    // Bit reinterpretation intrinsic, not an integer-to-float conversion or
    // floating arithmetic. Loads preserve signedzero/subnormal/NaN payloads.
    const uint32_t word = __float_as_uint(source[row * features + feature]);
    const uint32_t absolute_word = word & 0x7fffffffu;
    if ((absolute_word >> 23) == 255u) local_invalid = 1;
    else if (absolute_word > local_maximum) local_maximum = absolute_word;
  }
  maximum[threadIdx.x] = local_maximum;
  invalid[threadIdx.x] = local_invalid;
  __syncthreads();
  for (int stride = kThreads / 2; stride > 0; stride >>= 1) {
    if (int(threadIdx.x) < stride) {
      if (maximum[threadIdx.x + stride] > maximum[threadIdx.x])
        maximum[threadIdx.x] = maximum[threadIdx.x + stride];
      invalid[threadIdx.x] |= invalid[threadIdx.x + stride];
    }
    __syncthreads();
  }
  if (threadIdx.x != 0) return;
  if (invalid[0]) atomicOr(error, 1);
  int unit = minimal_unit(maximum[0], is_gain ? 24 : 32);
  if (is_gain) {
    if (unit < -128 || unit > 127) {
      atomicOr(error, 2);
      gain_units[row] = 0;  // Safe internal value; the entire API call rejects.
    } else gain_units[row] = unit;
  } else {
    if (unit < -32) unit = -32;  // Physical raw-unit choice, no role inference.
    raw_units[row] = int8_t(unit);  // Finite binary32 gives -32..97 inclusive.
    epsilon[row] = unit >= 1 ? uint64_t(0) : kEpsilon[unit + 32];
  }
}

// Parallel original-bit recode. raw output[M,N], gain output[G,N], and gamma
// exponents[M] all have separate owning allocations. Broadcast gain is encoded
// exactly once. Unit-scan completion on this same stream precedes all reads.
// Invalid calls initialize safe values, then Python raises using only error[1].
__global__ void recode_kernel(
    const float* raw, const float* gamma, int64_t raw_count, int64_t gain_count,
    int features, bool broadcast, const int8_t* raw_units,
    const int32_t* gain_units, const int32_t* error,
    int32_t* out_raw, int32_t* out_gain, int8_t* gamma_exponents) {
  const int64_t index = int64_t(blockIdx.x) * blockDim.x + threadIdx.x;
  if (index >= raw_count) return;
  const bool bad = error[0] != 0;
  const int64_t row = index / features;
  out_raw[index] = bad ? 0 : encode_word(__float_as_uint(raw[index]), int(raw_units[row]));
  if (index % features == 0)
    gamma_exponents[row] = bad ? int8_t(0) : int8_t(gain_units[broadcast ? 0 : row]);
  if (index < gain_count) {
    const int64_t gain_row = index / features;
    out_gain[index] = bad ? 0 : encode_word(__float_as_uint(gamma[index]), gain_units[gain_row]);
  }
}
}  // namespace

std::vector<at::Tensor> input_encoder_cuda_launch(
    const at::Tensor& raw, const at::Tensor& gamma) {
  const int64_t rows = raw.size(0);
  const int features = int(raw.size(1));
  const bool broadcast = gamma.dim() == 1;
  const int gain_rows = broadcast ? 1 : int(rows);
  // Five distinct public allocations, preserving original source axes.
  auto out_raw = at::empty(raw.sizes(), raw.options().dtype(at::kInt));
  auto out_gain = at::empty(gamma.sizes(), raw.options().dtype(at::kInt));
  auto raw_units = at::empty({rows}, raw.options().dtype(at::kChar));
  auto gamma_units = at::empty({rows}, raw.options().dtype(at::kChar));
  auto epsilon = at::empty({rows}, raw.options().dtype(at::ScalarType::UInt64));
  auto gain_units = at::empty({gain_rows}, raw.options().dtype(at::kInt));
  auto error = at::zeros({1}, raw.options().dtype(at::kInt));
  const cudaStream_t stream = c10::cuda::getCurrentCUDAStream(raw.get_device()).stream();
  unit_scan_kernel<<<unsigned(rows + gain_rows), kThreads, 0, stream>>>(
      raw.data_ptr<float>(), gamma.data_ptr<float>(), rows, features,
      raw_units.data_ptr<int8_t>(), gain_units.data_ptr<int32_t>(),
      epsilon.data_ptr<uint64_t>(), error.data_ptr<int32_t>());
  C10_CUDA_KERNEL_LAUNCH_CHECK();
  recode_kernel<<<unsigned(1 + (raw.numel() - 1) / kThreads), kThreads, 0, stream>>>(
      raw.data_ptr<float>(), gamma.data_ptr<float>(), raw.numel(), gamma.numel(),
      features, broadcast, raw_units.data_ptr<int8_t>(), gain_units.data_ptr<int32_t>(),
      error.data_ptr<int32_t>(), out_raw.data_ptr<int32_t>(), out_gain.data_ptr<int32_t>(),
      gamma_units.data_ptr<int8_t>());
  C10_CUDA_KERNEL_LAUNCH_CHECK();
  return {out_raw, out_gain, raw_units, gamma_units, epsilon, error};
}

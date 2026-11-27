// Exact current-C arithmetic. No floating arithmetic, model, or CPU callback.
#include <ATen/core/Tensor.h>
#include <ATen/ops/empty.h>
#include <ATen/ops/empty_like.h>
#include <c10/cuda/CUDAException.h>
#include <c10/cuda/CUDAStream.h>
#include <cuda_runtime.h>
#include <cstdint>
#include <vector>

namespace {
constexpr int kLimbs = 5;
struct U160 { uint32_t w[kLimbs]; };  // little-endian unsigned32 limbs

__device__ __forceinline__ U160 zero160() {
  U160 out{};
  return out;
}

__device__ __forceinline__ U160 from64(uint64_t value) {
  U160 out{};
  out.w[0] = static_cast<uint32_t>(value);
  out.w[1] = static_cast<uint32_t>(value >> 32);
  return out;
}

__device__ __forceinline__ int compare160(const U160& a, const U160& b) {
  for (int i = kLimbs - 1; i >= 0; --i) {
    if (a.w[i] < b.w[i]) return -1;
    if (a.w[i] > b.w[i]) return 1;
  }
  return 0;
}

__device__ __forceinline__ U160 add160(const U160& a, const U160& b) {
  U160 out{};
  uint64_t carry = 0;
  for (int i = 0; i < kLimbs; ++i) {
    // At most 2*(2^32-1)+1 <2^33, never unsigned64 overflow.
    const uint64_t total = uint64_t(a.w[i]) + uint64_t(b.w[i]) + carry;
    out.w[i] = static_cast<uint32_t>(total);
    carry = total >> 32;
  }
  // Every call below is bounded below2^160 by the valid-domain proof.
  return out;
}

__device__ __forceinline__ U160 subtract160(const U160& a, const U160& b) {
  U160 out{};
  uint64_t borrow = 0;
  for (int i = 0; i < kLimbs; ++i) {
    const uint64_t subtrahend = uint64_t(b.w[i]) + borrow;  // <=2^32
    const uint64_t minuend = a.w[i];
    // Unsigned subtraction/wrap followed by low32 is defined; borrow is
    // separately retained. Caller first proves a>=b across allfive limbs.
    out.w[i] = static_cast<uint32_t>(minuend - subtrahend);
    borrow = minuend < subtrahend;
  }
  return out;
}

__device__ __forceinline__ U160 left160(const U160& a, unsigned shift) {
  U160 out{};
  if (shift >= 160) return out;
  const unsigned words = shift / 32;
  const unsigned bits = shift % 32;
  for (int i = kLimbs - 1; i >= 0; --i) {
    if (unsigned(i) < words) continue;
    const int source = i - int(words);
    out.w[i] = a.w[source] << bits;
    // Do not evaluate a shift-by32 when bits==0.
    if (bits && source > 0) out.w[i] |= a.w[source - 1] >> (32 - bits);
  }
  return out;
}

__device__ __forceinline__ U160 right160(const U160& a, unsigned shift) {
  U160 out{};
  if (shift >= 160) return out;
  const unsigned words = shift / 32;
  const unsigned bits = shift % 32;
  for (int i = 0; i < kLimbs; ++i) {
    const unsigned source = unsigned(i) + words;
    if (source >= unsigned(kLimbs)) continue;
    out.w[i] = a.w[source] >> bits;
    if (bits && source + 1 < unsigned(kLimbs))
      out.w[i] |= a.w[source + 1] << (32 - bits);
  }
  return out;
}

__device__ __forceinline__ U160 multiply32(const U160& a, uint32_t factor) {
  U160 out{};
  uint64_t carry = 0;
  for (int i = 0; i < kLimbs; ++i) {
    // (2^32-1)^2+(2^32-1) <2^64.
    const uint64_t total = uint64_t(a.w[i]) * factor + carry;
    out.w[i] = static_cast<uint32_t>(total);
    carry = total >> 32;
  }
  return out;
}

__device__ __forceinline__ U160 multiply160(const U160& a, const U160& b) {
  U160 out{};
  for (int i = 0; i < kLimbs; ++i) {
    uint64_t carry = 0;
    for (int j = 0; j + i < kLimbs; ++j) {
      // A single schoolbook term is at most
      // (2^32-1)^2+(2^32-1)+(2^32-1)=2^64-1.
      const uint64_t total = uint64_t(a.w[i]) * b.w[j] + out.w[i+j] + carry;
      out.w[i+j] = static_cast<uint32_t>(total);
      carry = total >> 32;
    }
  }
  // Used only for squared magnitudes<=2^108; full products fit160.
  return out;
}

__device__ __forceinline__ uint32_t magnitude32(int32_t value) {
  // Widen BEFORE negating INT32_MIN. This signed64 operation is bounded2^31.
  return value < 0 ? static_cast<uint32_t>(-int64_t(value)) : uint32_t(value);
}

__device__ __forceinline__ U160 load_words(const uint32_t* words) {
  U160 out{};
  for (int i = 0; i < kLimbs; ++i) out.w[i] = words[i];
  return out;
}

__device__ __forceinline__ void store_words(uint32_t* words, const U160& value) {
  for (int i = 0; i < kLimbs; ++i) words[i] = value.w[i];
}

// Inputs: raw [M,N] int32; gain [N] or[M,N] int32 carrying signed24;
// epsilon [M] uint64; gamma [M] int8. row_words [M,10] uint32 is newly
// initialized D[5] and B[5]; exponents[M]/errors[M] are written on every row.
// A deterministic thread per row avoids atomic/reduction carry races.
__global__ void statistics_kernel(
    const int32_t* raw, const int32_t* gain, const uint64_t* epsilon,
    const int8_t* gamma, int64_t rows, int features, bool broadcast_gain,
    uint32_t* row_words, int16_t* exponents, int32_t* errors) {
  const int64_t row = int64_t(blockIdx.x) * blockDim.x + threadIdx.x;
  if (row >= rows) return;
  uint32_t* destination = row_words + row * 10;
  store_words(destination, zero160());
  store_words(destination + 5, zero160());
  exponents[row] = 0;
  errors[row] = 0;
  U160 energy{};
  uint64_t maximum = 0;
  bool gain_bad = false;
  for (int feature = 0; feature < features; ++feature) {
    const int64_t index = row * features + feature;
    const int32_t x = raw[index];
    const int32_t g = gain[broadcast_gain ? feature : index];
    const uint32_t ax = magnitude32(x);
    const uint64_t square = uint64_t(ax) * ax;  // <=2^62, inclusive
    energy = add160(energy, from64(square));
    if (g < -8388608 || g > 8388607) {
      gain_bad = true;
    } else {
      const uint64_t product = uint64_t(ax) * magnitude32(g);  // <=2^54
      if (product > maximum) maximum = product;
    }
  }
  // Error precedence matches the CPU ABI; malformed gain wins over zeroD.
  if (gain_bad) { errors[row] = 2; return; }
  const U160 denominator = add160(left160(energy, 16),
      multiply32(from64(epsilon[row]), uint32_t(features)));
  if (compare160(denominator, zero160()) == 0) { errors[row] = 1; return; }
  const U160 max_word = from64(maximum);
  const U160 numerator = left160(multiply32(multiply160(max_word, max_word),
      uint32_t(features)), 16);
  U160 budget = multiply32(denominator, 16129);
  unsigned shift = 0;
  while (compare160(numerator, budget) > 0) {
    if (shift == 23) { errors[row] = 3; return; }
    ++shift;
    budget = left160(budget, 2);
  }
  const U160 unit_denominator = left160(denominator, 2 * shift);
  store_words(destination, denominator);
  store_words(destination + 5, unit_denominator);
  exponents[row] = maximum ? int16_t(int(gamma[row]) + int(shift)) : int16_t(0);
  // maximum==0 is NOT an error and does NOT suppress raw outlier features.
}

// Feature replay initializes every output, including errors. The caller keeps
// input arrays immutable between the ordered statistics and replay launches.
__global__ void replay_kernel(
    const int32_t* raw, const int32_t* gain, const uint32_t* row_words,
    const int32_t* errors, int64_t total, int features, bool broadcast_gain,
    int8_t* codes, bool* outliers, bool* normalized_negative, bool* outlier_negative) {
  const int64_t index = int64_t(blockIdx.x) * blockDim.x + threadIdx.x;
  if (index >= total) return;
  codes[index] = 0;
  outliers[index] = false;
  normalized_negative[index] = false;
  outlier_negative[index] = false;
  const int64_t row = index / features;
  if (errors[row]) return;
  const int feature = int(index % features);
  const int32_t x = raw[index];
  const int32_t g = gain[broadcast_gain ? feature : index];
  const uint32_t ax = magnitude32(x);
  const uint64_t square = uint64_t(ax) * ax;
  const uint64_t product = uint64_t(ax) * magnitude32(g);
  const U160 denominator = load_words(row_words + row * 10);
  const U160 unit_denominator = load_words(row_words + row * 10 + 5);
  const U160 raw_numerator = left160(multiply32(from64(square), uint32_t(features)), 16);
  const bool is_outlier = compare160(raw_numerator, multiply32(denominator, 9)) > 0;
  const bool negative = x != 0 && g != 0 && ((x < 0) != (g < 0));
  outliers[index] = is_outlier;
  outlier_negative[index] = is_outlier && x < 0;
  normalized_negative[index] = negative;
  const U160 product_word = from64(product);
  U160 remainder = left160(multiply32(multiply160(product_word, product_word),
      uint32_t(features)), 18);  // 4*A, <=2^138 inclusive
  U160 root_term{};
  U160 delta = left160(unit_denominator, 14);
  uint32_t root_code = 0;
  for (int iteration = 0; iteration < 8; ++iteration) {
    const U160 trial = add160(root_term, delta);
    const bool accept = compare160(remainder, trial) >= 0;
    if (accept) remainder = subtract160(remainder, trial);
    root_term = add160(right160(root_term, 1), accept ? delta : zero160());
    delta = right160(delta, 2);
    root_code = (root_code << 1) | uint32_t(accept);
  }
  const int magnitude = int((root_code + 1) >> 1);
  const int signed_value = negative ? -magnitude : magnitude;
  codes[index] = int8_t(signed_value < -128 ? -128 : (signed_value > 127 ? 127 : signed_value));
}
}  // namespace

std::vector<at::Tensor> exact_normalizer_cuda_launch(
    const at::Tensor& raw, const at::Tensor& gain,
    const at::Tensor& epsilon, const at::Tensor& gamma) {
  const int64_t rows = raw.size(0);
  const int features = int(raw.size(1));
  const int64_t total = raw.numel();
  // Origins: newly allocated outputs match the documented [M,N]/[M] axes.
  auto codes = at::empty_like(raw, raw.options().dtype(at::kChar));
  auto exponents = at::empty({rows}, raw.options().dtype(at::kShort));
  auto outliers = at::empty_like(raw, raw.options().dtype(at::kBool));
  auto normalized_negative = at::empty_like(raw, raw.options().dtype(at::kBool));
  auto outlier_negative = at::empty_like(raw, raw.options().dtype(at::kBool));
  auto errors = at::empty({rows}, raw.options().dtype(at::kInt));
  auto row_words = at::empty({rows, 10}, raw.options().dtype(at::ScalarType::UInt32));
  const cudaStream_t stream = c10::cuda::getCurrentCUDAStream(raw.get_device()).stream();
  constexpr int threads = 128;
  statistics_kernel<<<unsigned(1 + (rows - 1) / threads), threads, 0, stream>>>(
      raw.data_ptr<int32_t>(), gain.data_ptr<int32_t>(), epsilon.data_ptr<uint64_t>(),
      gamma.data_ptr<int8_t>(), rows, features, gain.dim() == 1,
      row_words.data_ptr<uint32_t>(), exponents.data_ptr<int16_t>(), errors.data_ptr<int32_t>());
  C10_CUDA_KERNEL_LAUNCH_CHECK();
  replay_kernel<<<unsigned(1 + (total - 1) / threads), threads, 0, stream>>>(
      raw.data_ptr<int32_t>(), gain.data_ptr<int32_t>(), row_words.data_ptr<uint32_t>(),
      errors.data_ptr<int32_t>(), total, features, gain.dim() == 1,
      codes.data_ptr<int8_t>(), outliers.data_ptr<bool>(), normalized_negative.data_ptr<bool>(), outlier_negative.data_ptr<bool>());
  C10_CUDA_KERNEL_LAUNCH_CHECK();
  return {codes, exponents, outliers, normalized_negative, outlier_negative, errors};
}

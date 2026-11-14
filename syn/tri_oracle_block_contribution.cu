// Score eight consecutive down-projection inputs against every output row.
extern "C" __global__ void block_squared_contribution(
    const signed char *input, const signed char *weights,
    unsigned long long *squares, int channels, int outputs)
{
    constexpr int width = 8;
    constexpr int workers = 128;
    __shared__ unsigned long long partial[workers];
    const int block = blockIdx.x;
    const int token = blockIdx.y;
    const int lane = threadIdx.x;
    const int channel = block * width;
    unsigned long long sum = 0;
    for (int output = lane; output < outputs; output += workers) {
        int dot = 0;
        for (int term = 0; term < width; ++term)
            dot += input[token * channels + channel + term] * weights[output * channels + channel + term];
        sum += static_cast<long long>(dot) * dot;
    }
    partial[lane] = sum;
    __syncthreads();
    for (int stride = workers / 2; stride > 0; stride /= 2) {
        if (lane < stride)
            partial[lane] += partial[lane + stride];
        __syncthreads();
    }
    if (lane == 0)
        squares[token * (channels / width) + block] = partial[0];
}

#include <stdint.h>

/* Rows of activations and rows of weights, each with `terms` signed bytes. */
void tri_oracle_fixture_dot(const int8_t *activations, const int8_t *weights,
                            int32_t *output, int rows, int channels, int terms)
{
    #pragma omp parallel for collapse(2) schedule(static)
    for (int row = 0; row < rows; ++row) {
        for (int channel = 0; channel < channels; ++channel) {
            const int8_t *activation = activations + row * terms;
            const int8_t *weight = weights + channel * terms;
            int32_t sum = 0;
            #pragma omp simd reduction(+:sum)
            for (int term = 0; term < terms; ++term)
                sum += activation[term] * weight[term];
            output[row * channels + channel] = sum;
        }
    }
}

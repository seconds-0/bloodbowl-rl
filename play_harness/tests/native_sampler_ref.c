// Host fp32 transliteration of the discrete per-head branch of sample_logits
// (vendor/PufferLib src/pufferlib.cu with training/puffer_exact_joint_actions.patch),
// used by test_parity_metrics.py as the reference for parity.native_fp32_head.
// The only change from the CUDA kernel: the loop keeps accumulating after the
// sampled action so every cumulative value can be reported.
#include <math.h>

static float safe_logit(float l) {
    if (isnan(l)) l = 0.0f;
    if (isinf(l)) l = (l > 0) ? 3.4028e+38f : -3.4028e+38f;
    return l;
}

// Returns the sampled index for the uniform draw u, or -1 for an empty mask.
int head_sample(const float* logits, const unsigned char* mask, int A, float u,
                float* lse_out, float* cum_out, float* logp_out) {
    float max_val = -INFINITY;
    float sum_exp = 0.0f;
    int enabled_count = 0;
    for (int a = 0; a < A; ++a) {
        if (!mask[a]) continue;
        float l = safe_logit(logits[a]);
        if (l > max_val) {
            sum_exp *= expf(max_val - l);
            max_val = l;
        }
        sum_exp += expf(l - max_val);
        enabled_count += 1;
    }
    if (enabled_count == 0) return -1;
    float logsumexp = max_val + logf(sum_exp);
    float cumsum = 0.0f;
    int sampled_action = -1;
    for (int a = 0; a < A; ++a) {
        cum_out[a] = 0.0f;
        if (!mask[a]) continue;
        float l = safe_logit(logits[a]);
        float prob = expf(l - logsumexp);
        cumsum += prob;
        cum_out[a] = cumsum;
        if (sampled_action < 0 && u < cumsum) sampled_action = a;
    }
    if (sampled_action < 0) {
        sampled_action = A - 1;
        for (int a = A - 1; a >= 0; --a) {
            if (mask[a]) { sampled_action = a; break; }
        }
    }
    *lse_out = logsumexp;
    *logp_out = safe_logit(logits[sampled_action]) - logsumexp;
    return sampled_action;
}

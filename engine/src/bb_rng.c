#include "bb/bb_rng.h"

// PCG32 (Melissa O'Neill, pcg-random.org; Apache-2.0 reference algorithm).
static uint32_t pcg32_next(bb_rng* rng) {
    uint64_t old = rng->state;
    rng->state = old * 6364136223846793005ULL + rng->inc;
    uint32_t xorshifted = (uint32_t)(((old >> 18u) ^ old) >> 27u);
    uint32_t rot = (uint32_t)(old >> 59u);
    return (xorshifted >> rot) | (xorshifted << ((-rot) & 31));
}

void bb_rng_seed(bb_rng* rng, uint64_t seed, uint64_t stream) {
    rng->mode = BB_RNG_PRNG;
    rng->error = 0;
    rng->script = 0;
    rng->script_len = rng->script_pos = 0;
    rng->sink = 0;
    rng->sink_user = 0;
    rng->state = 0u;
    rng->inc = (stream << 1u) | 1u;
    pcg32_next(rng);
    rng->state += seed;
    pcg32_next(rng);
}

void bb_rng_script(bb_rng* rng, const uint8_t* values, int len) {
    rng->mode = BB_RNG_SCRIPT;
    rng->error = 0;
    rng->script = values;
    rng->script_len = len;
    rng->script_pos = 0;
    rng->sink = 0;
    rng->sink_user = 0;
    rng->state = rng->inc = 0;
}

void bb_rng_set_sink(bb_rng* rng, bb_dice_sink sink, void* user) {
    rng->sink = sink;
    rng->sink_user = user;
}

uint32_t bb_rng_next(bb_rng* rng) {
    return pcg32_next(rng);
}

int bb_roll(bb_rng* rng, int sides) {
    int value;
    if (rng->mode == BB_RNG_SCRIPT) {
        if (rng->script_pos >= rng->script_len) {
            rng->error = 1;
            return 1; // keep the engine well-defined; caller checks bb_rng_error
        }
        value = rng->script[rng->script_pos++];
        if (value < 1 || value > sides) {
            rng->error = 1;
            return 1;
        }
    } else {
        // Rejection sampling for an unbiased 1..sides.
        uint32_t bound = (uint32_t)sides;
        uint32_t threshold = -bound % bound; // (2^32 - bound) % bound
        uint32_t r;
        do {
            r = pcg32_next(rng);
        } while (r < threshold);
        value = (int)(r % bound) + 1;
    }
    if (rng->sink) rng->sink(rng->sink_user, sides, value);
    return value;
}

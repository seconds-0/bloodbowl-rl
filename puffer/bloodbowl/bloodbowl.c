// bloodbowl.c — standalone driver for the PufferLib env (build.sh --local /
// --fast, or direct clang on Mac). Plays random-policy matches end-to-end
// through the exact c_reset/c_step path training uses, then reports
// aggregate stats + steps/sec. Heads are sampled from the legality mask
// (like the CUDA masked sampler); pass --unmasked to sample uniformly over
// each head instead, stress-testing the decode snap-to-legal path the
// maskless torch backend relies on.
#include "bloodbowl.h"
#include <stdio.h>
#include <time.h>

// Sample a uniformly random set bit in mask[0..len); -1 if none.
static int sample_masked(const unsigned char* mask, int len, bb_rng* rng) {
    int n = 0;
    for (int i = 0; i < len; i++) n += mask[i];
    if (n == 0) return -1;
    int k = (int)(bb_rng_next(rng) % (uint32_t)n);
    for (int i = 0; i < len; i++) {
        if (mask[i] && k-- == 0) return i;
    }
    return -1;
}

int main(int argc, char** argv) {
    int episodes = 64;
    int unmasked = 0;
    uint64_t seed = 42;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--unmasked") == 0) unmasked = 1;
        else if (strcmp(argv[i], "--seed") == 0 && i + 1 < argc) seed = strtoull(argv[++i], 0, 10);
        else episodes = atoi(argv[i]);
    }

    static Bloodbowl env; // ~20KB of legal-action buffer; keep off the stack
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    env.num_agents = BBE_AGENTS;
    env.seed = seed;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env.obs_ptr[a] = obs + a * BBE_OBS_SIZE;
        env.action_ptr[a] = actions + a * 3;
        env.action_mask_ptr[a] = mask + a * BBE_MASK_SIZE;
        env.reward_ptr[a] = rewards + a;
        env.terminal_ptr[a] = terminals + a;
    }
    c_reset(&env);

    bb_rng pol;
    bb_rng_seed(&pol, seed ^ 0xBADC0DE, 3);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    long steps = 0;
    int done = 0;
    while (done < episodes) {
        for (int a = 0; a < BBE_AGENTS; a++) {
            const unsigned char* m = env.action_mask_ptr[a];
            if (unmasked) {
                env.action_ptr[a][0] = (float)(bb_rng_next(&pol) % BBE_HEAD_TYPE);
                env.action_ptr[a][1] = (float)(bb_rng_next(&pol) % BBE_HEAD_ARG);
                env.action_ptr[a][2] = (float)(bb_rng_next(&pol) % BBE_HEAD_SQ);
            } else {
                env.action_ptr[a][0] = (float)sample_masked(m, BBE_HEAD_TYPE, &pol);
                env.action_ptr[a][1] = (float)sample_masked(m + BBE_HEAD_TYPE, BBE_HEAD_ARG, &pol);
                env.action_ptr[a][2] = (float)sample_masked(
                    m + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ, &pol);
            }
        }
        c_step(&env);
        steps++;
        if (terminals[0] != 0.0f) done++;
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double secs = (double)(t1.tv_sec - t0.tv_sec) + (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;

    Log* lg = &env.log;
    float n = lg->n > 0 ? lg->n : 1;
    printf("bloodbowl standalone: %d episodes, %ld steps in %.2fs (%s)\n",
           done, steps, secs, unmasked ? "unmasked" : "masked");
    printf("  steps/sec        %.0f (x2 agent-obs per step)\n", (double)steps / secs);
    printf("  perf             %.3f\n", lg->perf / n);
    printf("  score_diff       %+.2f\n", lg->score_diff / n);
    printf("  tds/match        %.2f\n", lg->tds / n);
    printf("  episode_length   %.0f\n", lg->episode_length / n);
    printf("  episode_return   %+.2f\n", lg->episode_return / n);
    printf("  illegal_frac     %.4f\n", lg->illegal_frac / n);
    c_close(&env);
    return 0;
}

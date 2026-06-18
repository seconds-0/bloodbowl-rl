// bbe_microstats_probe.c — empirical baseline for the behavioral micro-stat
// counters under masked-random play. Answers "what should blocks/pickups/etc
// read on the dashboard for a policy with NO preferences?" so a 0.000 on a
// trained run can be classified as a real behavioral finding vs a broken
// counter. (Motivating case: synthesis run showed blocks 0.000 at bc_acc
// 0.80 — is the instrument lying?)
//
// Build: clang -O2 -Ipuffer/bloodbowl puffer/bloodbowl/bbe_microstats_probe.c -o /tmp/bbe_microstats_probe
// Run:   /tmp/bbe_microstats_probe [seed] [episodes]
#include "bloodbowl.h"
#include <stdio.h>
#include <stdlib.h>

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
    uint64_t seed = argc > 1 ? strtoull(argv[1], 0, 10) : 7;
    int episodes = argc > 2 ? atoi(argv[2]) : 200;

    static Bloodbowl env;
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
    bb_rng_seed(&pol, seed ^ 0x5E1F7E57, 5);
    // Accumulate the same per-episode sums the Log sees, sampled at episode
    // end (the counters reset on episode boundary inside c_step).
    long blocks = 0, blitzes = 0, dodges = 0, gfis = 0, pickups = 0,
         passes = 0, kd_inflicted = 0, kd_own = 0, decisions = 0;
    int done = 0;
    int prev[8] = {0};
    while (done < episodes) {
        for (int a = 0; a < BBE_AGENTS; a++) {
            const unsigned char* mk = env.action_mask_ptr[a];
            env.action_ptr[a][0] = (float)sample_masked(mk, BBE_HEAD_TYPE, &pol);
            env.action_ptr[a][1] =
                (float)sample_masked(mk + BBE_HEAD_TYPE, BBE_HEAD_ARG, &pol);
            env.action_ptr[a][2] = (float)sample_masked(
                mk + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ, &pol);
        }
        prev[0] = env.ep_blocks;
        prev[1] = env.ep_blitzes;
        prev[2] = env.ep_dodge_att[0] + env.ep_dodge_att[1];
        prev[3] = env.ep_gfi_att[0] + env.ep_gfi_att[1];
        prev[4] = env.ep_pickup_att[0] + env.ep_pickup_att[1];
        prev[5] = env.ep_pass_att[0] + env.ep_pass_att[1];
        prev[6] = env.ep_knockdowns_inflicted;
        prev[7] = env.ep_knockdowns_own;
        c_step(&env);
        decisions++;
        if (terminals[0] != 0.0f) {
            // Counters were zeroed by the in-step reset; prev holds the
            // pre-reset values minus the final action — close enough for a
            // baseline (the final action is END_TURN/score resolution).
            blocks += prev[0];
            blitzes += prev[1];
            dodges += prev[2];
            gfis += prev[3];
            pickups += prev[4];
            passes += prev[5];
            kd_inflicted += prev[6];
            kd_own += prev[7];
            done++;
        }
    }
    double n = (double)episodes;
    printf("masked-random baseline over %d episodes (seed %llu, %ld decisions):\n",
           episodes, (unsigned long long)seed, decisions);
    printf("  blocks/ep          %.3f\n", blocks / n);
    printf("  blitzes/ep         %.3f\n", blitzes / n);
    printf("  dodge_attempts/ep  %.3f\n", dodges / n);
    printf("  gfi_attempts/ep    %.3f\n", gfis / n);
    printf("  pickup_attempts/ep %.3f\n", pickups / n);
    printf("  pass_attempts/ep   %.3f\n", passes / n);
    printf("  kd_inflicted/ep    %.3f\n", kd_inflicted / n);
    printf("  kd_own/ep          %.3f\n", kd_own / n);
    return 0;
}

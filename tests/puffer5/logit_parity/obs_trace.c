// obs_trace.c -- record one Blood Bowl env's observation sequence for the
// PufferLib 5.0 logit-parity check (tests/puffer5/logit_parity/run.sh).
//
// Steps ONE standalone Bloodbowl env through the exact c_reset/c_step path
// training uses, with uniform exact-joint actions (bbe_sample_joint_uniform,
// as puffer/bloodbowl/bloodbowl.c does). Per step it writes, for both agents,
// the obs bytes BEFORE the step plus the terminal flag emitted together with
// that obs (terminals[a] from the previous c_step; 0 for the first obs). The
// policy contract: zero a row's recurrent state before encoding an obs whose
// terminal flag is set.
//
// Usage: obs_trace OUT.bin STEPS SEED MAX_DECISIONS   (MAX_DECISIONS 0 = default)
//
// Trace format (little-endian):
//   char magic[8] = "BBOBSTR1"
//   uint32 steps, uint32 obs_size, uint32 agents, uint32 terminal_obs_count
//   per step: uint8 obs[agents * obs_size]; float32 term[agents]
#include "bloodbowl.h"
#include <stdio.h>

int main(int argc, char** argv) {
    if (argc != 5) {
        fprintf(stderr, "usage: %s OUT.bin STEPS SEED MAX_DECISIONS\n", argv[0]);
        return 2;
    }
    const char* out_path = argv[1];
    int steps = atoi(argv[2]);
    uint64_t seed = strtoull(argv[3], NULL, 10);
    int max_decisions = atoi(argv[4]);
    if (steps <= 0) {
        fprintf(stderr, "steps must be positive\n");
        return 2;
    }

    static Bloodbowl env;
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    env.num_agents = BBE_AGENTS;
    env.seed = seed;
    if (max_decisions > 0) env.max_decisions = max_decisions;
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

    FILE* fp = fopen(out_path, "wb");
    if (!fp) {
        perror(out_path);
        return 1;
    }
    uint32_t header[4] = {(uint32_t)steps, (uint32_t)BBE_OBS_SIZE,
                          (uint32_t)BBE_AGENTS, 0};
    fwrite("BBOBSTR1", 1, 8, fp);
    fwrite(header, sizeof(uint32_t), 4, fp);

    float term_prev[BBE_AGENTS] = {0.0f, 0.0f};
    uint32_t terminal_obs = 0;
    for (int t = 0; t < steps; t++) {
        if (fwrite(obs, 1, sizeof obs, fp) != sizeof obs ||
            fwrite(term_prev, sizeof(float), BBE_AGENTS, fp) != BBE_AGENTS) {
            perror("write");
            return 1;
        }
        if (term_prev[0] != 0.0f) terminal_obs++;
        for (int a = 0; a < BBE_AGENTS; a++) {
            bbe_sample_joint_uniform(&env, a, env.action_ptr[a], &pol);
        }
        c_step(&env);
        for (int a = 0; a < BBE_AGENTS; a++) term_prev[a] = terminals[a];
    }
    header[3] = terminal_obs;
    fseek(fp, 8, SEEK_SET);
    fwrite(header, sizeof(uint32_t), 4, fp);
    fclose(fp);
    c_close(&env);
    printf("obs_trace steps=%d seed=%llu max_decisions=%d terminal_obs=%u\n",
           steps, (unsigned long long)seed, env.max_decisions, terminal_obs);
    return 0;
}

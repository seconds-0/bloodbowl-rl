// 5.0 adapter driver: the installed ocean/bloodbowl/bloodbowl.h adapter (C++,
// the header src/pufferl.cu compiles) plus the bloodbowl5_env.c env object,
// stepped the way 5.0's CPU vec worker does it: my_vec_init, Agent pointers
// laid out like env_setup's identity layout (no frozen policies), puf_reset,
// then memset rewards/terminals, puf_step per env, puf_pack_joint_actions.
//
// Build (see run_parity.sh):
//   clang++ -std=c++17 -O2 -I<tree>/src -I<tree>/ocean/bloodbowl -I<raylib inc> \
//     p5_driver.cpp build/bloodbowl_env.o -o p5_driver -lm -fopenmp
#include "bloodbowl.h"
#include "trace_format.h"

int main(int argc, char** argv) {
    if (argc < 6) {
        fprintf(stderr, "usage: p5_driver AGENTS STEPS SEED MAX_DECISIONS OUT\n");
        return 1;
    }
    int agents = atoi(argv[1]);
    int steps = atoi(argv[2]);
    uint64_t seed = strtoull(argv[3], NULL, 10);
    int max_decisions = atoi(argv[4]);
    Dict vk = {0};
    dict_set(&vk, "total_agents", agents);
    dict_set(&vk, "num_buffers", 1);
    dict_set(&vk, "num_policies", 1);
    dict_set(&vk, "hist_policy_percent", 0);
    Dict ek = {0};
    dict_set(&ek, "seed", (double)seed);
    if (max_decisions > 0) {
        dict_set(&ek, "max_decisions", max_decisions);
    }
    int num_envs = 0;
    int starts[1] = {0};
    int counts_buf[1] = {0};
    Env* envs = my_vec_init(&num_envs, starts, counts_buf, &vk, &ek);
    if (num_envs * 2 != agents) {
        fprintf(stderr, "unexpected env count %d\n", num_envs);
        return 2;
    }
    const int mask_size = 30 + 33 + 391;
    uint8_t* obs = (uint8_t*)calloc((size_t)agents * OBS_SIZE, 1);
    float* actions = (float*)calloc((size_t)agents * NUM_ATNS, sizeof(float));
    float* rewards = (float*)calloc((size_t)agents, sizeof(float));
    float* terminals = (float*)calloc((size_t)agents, sizeof(float));
    unsigned char* mask = (unsigned char*)malloc((size_t)agents * mask_size);
    memset(mask, 1, (size_t)agents * mask_size);
    for (int e = 0; e < num_envs; e++) {
        for (int s = 0; s < 2; s++) {
            int row = e * 2 + s;
            Agent* a = &envs[e].agents[s];
            a->observations = obs + (size_t)row * OBS_SIZE;
            a->actions = actions + (size_t)row * NUM_ATNS;
            a->rewards = rewards + row;
            a->terminals = terminals + row;
            a->action_mask = mask + (size_t)row * mask_size;
        }
        envs[e].tag = 0;
    }
    uint32_t* joint = (uint32_t*)calloc((size_t)agents * PUF_JOINT_ACTION_MAX, sizeof(uint32_t));
    int* offsets = (int*)calloc((size_t)agents, sizeof(int));
    int* counts = (int*)calloc((size_t)agents, sizeof(int));
    int buffer_counts[1] = {0};
    for (int e = 0; e < num_envs; e++) {
        puf_reset(&envs[e]);
    }
    puf_pack_joint_actions(envs, 0, num_envs, 0, agents, actions, joint, offsets,
        counts, buffer_counts);
    FILE* fp = fopen(argv[5], "wb");
    if (!fp) {
        perror("open trace");
        return 2;
    }
    pt_header(fp, (uint32_t)agents, (uint32_t)steps, OBS_SIZE);
    for (int t = 0; t < steps; t++) {
        uint64_t h = pt_step(fp, (uint32_t)t, seed, agents, OBS_SIZE, obs, rewards,
            terminals, joint, offsets, counts, actions);
        printf("%d %016llx\n", t, (unsigned long long)h);
        memset(rewards, 0, (size_t)agents * sizeof(float));
        memset(terminals, 0, (size_t)agents * sizeof(float));
        for (int e = 0; e < num_envs; e++) {
            puf_step(&envs[e]);
        }
        puf_pack_joint_actions(envs, 0, num_envs, 0, agents, actions, joint,
            offsets, counts, buffer_counts);
    }
    uint32_t nf = (uint32_t)(sizeof(Log) / sizeof(float));
    float* sum = (float*)calloc(nf, sizeof(float));
    for (int e = 0; e < num_envs; e++) {
        float* src = (float*)&envs[e].log;
        for (uint32_t j = 0; j < nf; j++) {
            sum[j] += src[j];
        }
    }
    pt_write(fp, &nf, sizeof nf);
    pt_write(fp, sum, nf * sizeof(float));
    fclose(fp);
    printf("log_n %.1f\n", sum[nf - 1]);
    my_vec_close(envs);
    return 0;
}

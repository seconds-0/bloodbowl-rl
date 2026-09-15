// Prints the 5.0 physical row layout for a league configuration: the adapter's
// real seat routing (bbe5_assign_policies in training/puffer5/adapter/bloodbowl.h)
// followed by the policy-layout and Agent row assignment of src/pufferl.cu
// env_setup at 6ffa5b1 (copied verbatim below, CPU backend branch).
//
// Output: one line per env: "env <i> tag <t> rows <seat0 row> <seat1 row>",
// then "layout <policy_layout...>".
#include <cassert>
#include "bloodbowl.h"

int main(int argc, char** argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: p5_layout TOTAL_AGENTS NUM_BUFFERS NUM_POLICIES HIST_PCT\n");
        return 1;
    }
    int total_agents = atoi(argv[1]);
    int num_buffers = atoi(argv[2]);
    int num_policies = atoi(argv[3]);
    float frozen_pct = (float)atof(argv[4]);
    int apb = total_agents / num_buffers;
    int num_envs = total_agents / 2;
    int* env_starts = (int*)calloc(num_buffers, sizeof(int));
    int* env_counts = (int*)calloc(num_buffers, sizeof(int));
    // 4.0 binding.c my_vec_init buffer split (2 agents per env).
    int buf = 0, buf_agents = 0;
    for (int i = 0; i < num_envs; i++) {
        buf_agents += 2;
        env_counts[buf]++;
        if (buf_agents >= apb && buf < num_buffers - 1) {
            buf++;
            env_starts[buf] = i + 1;
            buf_agents = 0;
        }
    }
    Env* envs = (Env*)calloc(num_envs, sizeof(Env));
    for (int i = 0; i < num_envs; i++) envs[i].num_agents = 2;
    Dict vk = {0};
    dict_set(&vk, "num_policies", num_policies);
    dict_set(&vk, "hist_policy_percent", frozen_pct);
    bbe5_assign_policies(envs, num_buffers, env_starts, env_counts, &vk);

    // --- verbatim logic from src/pufferl.cu env_setup (CPU backend) ---
    int* policy_layout = (int*)calloc(num_policies + 1, sizeof(int));
    int* rows = (int*)calloc(total_agents, sizeof(int));
    for (int buf = 0; buf < num_buffers; buf++) {
        int buf_start = buf * apb;
        int env_start = env_starts[buf];
        int env_count = env_counts[buf];
        int frozen_start = env_count;
        if (num_policies > 1 && frozen_pct > 0.0f) {
            frozen_start = env_count - (int)(frozen_pct * env_count);
        }
        int* counts = (int*)calloc(num_policies, sizeof(int));
        for (int e = 0; e < env_count; e++) {
            Env* eptr = &envs[env_start + e];
            for (int s = 0; s < eptr->num_agents; s++) {
                int policy = e < frozen_start ? 0 : eptr->agents[s].policy;
                assert(policy >= 0 && policy < num_policies);
                counts[policy]++;
            }
        }
        int offset = 0;
        for (int b = 0; b <= num_policies; b++) {
            if (buf == 0) {
                policy_layout[b] = offset;
            } else {
                assert(policy_layout[b] == offset);
            }
            if (b < num_policies) {
                offset += counts[b];
            }
        }
        assert(offset == apb);
        int* cursors = (int*)calloc(num_policies, sizeof(int));
        for (int b = 0; b < num_policies; b++) {
            cursors[b] = buf_start + policy_layout[b];
        }
        for (int e = 0; e < env_count; e++) {
            Env* eptr = &envs[env_start + e];
            int tag = 0;
            for (int s = 0; s < eptr->num_agents; s++) {
                int policy = e < frozen_start ? 0 : eptr->agents[s].policy;
                if (policy > tag) {
                    tag = policy;
                }
                int phys = cursors[policy]++;
                rows[(env_start + e) * 2 + s] = phys;
            }
            eptr->tag = tag;
        }
        free(cursors);
        free(counts);
    }
    // --- end verbatim ---
    for (int i = 0; i < num_envs; i++) {
        printf("env %d tag %d rows %d %d\n", i, envs[i].tag, rows[i * 2], rows[i * 2 + 1]);
    }
    printf("layout");
    for (int b = 0; b <= num_policies; b++) printf(" %d", policy_layout[b]);
    printf("\n");
    return 0;
}

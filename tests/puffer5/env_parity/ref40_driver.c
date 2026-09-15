// 4.0 reference driver: the unmodified puffer/bloodbowl/binding.c compiled
// against the live 4.0 patched src/vecenv.h (exact-joint transport, perm,
// tags), stepped through create_static_vec / static_vec_reset / cpu_vec_step
// exactly as the 4.0 CPU vec path does.
//
// Build (rig, same flags as the 4.0 static-library compile):
//   clang -O2 -DNDEBUG -mavx2 -mfma -fopenmp -I<ref40 src dir> -I/usr/include \
//     -I<env dir> ref40_driver.c -o ref40_driver -lm -lcudart
#include "binding.c"
#include "trace_format.h"

int main(int argc, char** argv) {
    if (argc < 6) {
        fprintf(stderr, "usage: ref40_driver AGENTS STEPS SEED MAX_DECISIONS OUT\n");
        return 1;
    }
    int agents = atoi(argv[1]);
    int steps = atoi(argv[2]);
    uint64_t seed = strtoull(argv[3], NULL, 10);
    int max_decisions = atoi(argv[4]);
    Dict* vk = create_dict(8);
    dict_set(vk, "total_agents", agents);
    dict_set(vk, "num_buffers", 1);
    Dict* ek = create_dict(8);
    dict_set(ek, "seed", (double)seed);
    if (max_decisions > 0) {
        dict_set(ek, "max_decisions", max_decisions);
    }
    StaticVec* vec = create_static_vec(agents, 1, 0, vk, ek);
    static_vec_reset(vec);
    FILE* fp = fopen(argv[5], "wb");
    if (!fp) {
        perror("open trace");
        return 2;
    }
    pt_header(fp, (uint32_t)agents, (uint32_t)steps, OBS_SIZE);
    for (int t = 0; t < steps; t++) {
        uint64_t h = pt_step(fp, (uint32_t)t, seed, agents, OBS_SIZE,
            (const uint8_t*)vec->observations, vec->rewards, vec->terminals,
            vec->joint_actions, vec->joint_action_offsets,
            vec->joint_action_counts, vec->actions);
        printf("%d %016llx\n", t, (unsigned long long)h);
        cpu_vec_step(vec);
    }
    Env* envs = (Env*)vec->envs;
    uint32_t nf = (uint32_t)(sizeof(Log) / sizeof(float));
    float* sum = (float*)calloc(nf, sizeof(float));
    for (int i = 0; i < vec->size; i++) {
        float* src = (float*)&envs[i].log;
        for (uint32_t j = 0; j < nf; j++) {
            sum[j] += src[j];
        }
    }
    pt_write(fp, &nf, sizeof nf);
    pt_write(fp, sum, nf * sizeof(float));
    fclose(fp);
    printf("log_n %.1f\n", sum[nf - 1]);
    return 0;
}

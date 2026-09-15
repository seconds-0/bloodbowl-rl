// PufferLib 5.0 environment header for the Blood Bowl env (bloodbowl-rl).
//
// This is the ENV_HEADER that 5.0's build.sh hands to src/pufferl.cu (C++17,
// nvcc) and src/puffercpu.c (C, clang). It deliberately does NOT include the
// real env: puffer/bloodbowl/bloodbowl.h is C11 engine code that is not C++
// clean, and it must stay byte-identical to the 4.0 source (hash 3ed6899e).
// The real env compiles as its own C translation unit (bloodbowl5_env.c,
// which includes the unmodified 4.0 binding.c through a 4.0-API shim) and is
// reached through the small extern "C" bbe5_* API below.
//
// Installed by tools/install_puffer5_env.sh as ocean/bloodbowl/bloodbowl.h;
// the env source itself is installed under ocean/bloodbowl/env/.
#pragma once

#include <stdint.h>
#include <stdlib.h>

typedef uint8_t obs_t;
#include "pufferenv.h"
#include "bloodbowl5_generated.h" // BBE5_LOG_FLOATS, BBE5_ENV_SOURCE_HASH

#define OBS_SIZE 2782
#define NUM_ATNS 3
#define ACT_SIZES {30, 33, 391}
// Exact joint support transport (training/puffer5/patches/0002). Matches
// MY_JOINT_ACTION_MAX in puffer/bloodbowl/binding.c: BB_LEGAL_MAX + 391.
#define PUF_JOINT_ACTION_MAX 4487
#define MY_VEC_INIT
#define MY_VEC_CLOSE

// Mirror of bloodbowl.h's Log: floats only, n last. The installer derives
// BBE5_LOG_FLOATS from the compiled env and my_vec_init re-checks it.
struct Log {
    float fields[BBE5_LOG_FLOATS - 1];
    float n;
};

struct Env {
    Log log;            // trainer-visible accumulator; bbe5_step moves env deltas here
    int num_agents;
    unsigned int rng;
    Agent agents[2];    // slot 0 = HOME, slot 1 = AWAY (bank seat in tagged envs)
    int tag;            // 5.0 env_setup: max policy index of the env's seats
    int boundary_reached;
    void* bb;           // Bloodbowl* owned by the env TU
    int bb_owner;       // 1 when puf_init allocated a standalone env
};

#ifdef __cplusplus
extern "C" {
#endif
int bbe5_log_float_count(void);
int bbe5_obs_size(void);
int bbe5_mask_size(void);
int bbe5_joint_action_max(void);
void* bbe5_vec_init(int* num_envs_out, int* buffer_env_starts,
                    int* buffer_env_counts, Dict* vec_kwargs, Dict* env_kwargs);
void* bbe5_env_at(void* envs, int i);
void* bbe5_init_one(Dict* env_kwargs);
void bbe5_bind(void* bb, int tag, obs_t* obs0, obs_t* obs1,
               unsigned char* mask0, unsigned char* mask1,
               float* act0, float* act1, float* rew0, float* rew1,
               float* term0, float* term1);
void bbe5_reset(void* bb);
void bbe5_step(void* bb, float* log_accumulator);
void bbe5_pack_joint(void* first_env, int env_count, int buf,
                     int agents_per_buffer, float* actions_base,
                     uint32_t* joint_actions, int* joint_offsets,
                     int* joint_counts, int* joint_buffer_counts);
void bbe5_log(float* log, Dict* out);
void bbe5_render(void* bb);
void bbe5_free_one(void* bb);
void bbe5_free_vec(void* envs);
int bbe5_scripted_bank_tag(void* bb);
#ifdef __cplusplus
}
#endif

static inline void bbe5_check_abi(void) {
    if (bbe5_log_float_count() != BBE5_LOG_FLOATS || bbe5_obs_size() != OBS_SIZE ||
            bbe5_mask_size() != 30 + 33 + 391 ||
            bbe5_joint_action_max() != PUF_JOINT_ACTION_MAX) {
        fprintf(stderr,
            "bloodbowl5: adapter ABI mismatch (log floats %d/%d, obs %d/%d, "
            "mask %d, joint max %d/%d); rerun tools/install_puffer5_env.sh\n",
            bbe5_log_float_count(), BBE5_LOG_FLOATS, bbe5_obs_size(), OBS_SIZE,
            bbe5_mask_size(), bbe5_joint_action_max(), PUF_JOINT_ACTION_MAX);
        exit(1);
    }
}

static inline void bbe5_bind_env(Env* env) {
    bbe5_bind(env->bb, env->tag,
        env->agents[0].observations, env->agents[1].observations,
        env->agents[0].action_mask, env->agents[1].action_mask,
        env->agents[0].actions, env->agents[1].actions,
        env->agents[0].rewards, env->agents[1].rewards,
        env->agents[0].terminals, env->agents[1].terminals);
}

// Seat routing. 5.0's env_setup gives the trailing hist_policy_percent of each
// buffer's envs to frozen policies, reading agents[s].policy for those envs
// only. Assign seat 1 of those envs to banks in block order, exactly like the
// 4.0 selfplay league (pufferlib/selfplay.py build_perm_tags): with
// num_policies = 1 + N banks and hist_policy_percent = N*int(apb*p)/envs_per_buf,
// bank b's rows are [apb - F + b*int(apb*p), ...), the same physical slice.
static inline void bbe5_assign_policies(Env* envs, int num_buffers,
        const int* starts, const int* counts, Dict* vk) {
    int num_policies = (int)dict_get(vk, "num_policies");
    float pct = (float)dict_get(vk, "hist_policy_percent");
    if (num_policies < 1) {
        num_policies = 1;
    }
    for (int buf = 0; buf < num_buffers; buf++) {
        int env_count = counts[buf];
        int frozen_start = env_count;
        if (num_policies > 1 && pct > 0.0f) {
            frozen_start = env_count - (int)(pct * env_count);
        }
        int hist = env_count - frozen_start;
        int banks = num_policies - 1;
        if (hist > 0 && (banks <= 0 || hist % banks != 0)) {
            fprintf(stderr,
                "bloodbowl5: %d historical envs per buffer do not split evenly "
                "over %d frozen policies (vec.num_policies=%d, "
                "vec.hist_policy_percent=%g)\n",
                hist, banks, num_policies, pct);
            exit(1);
        }
        int per_bank = banks > 0 && hist > 0 ? hist / banks : 1;
        for (int e = 0; e < env_count; e++) {
            Env* env = &envs[starts[buf] + e];
            env->agents[0].policy = 0;
            env->agents[1].policy = e < frozen_start
                ? 0 : 1 + (e - frozen_start) / per_bank;
        }
    }
}

Env* my_vec_init(int* num_envs_out, int* buffer_env_starts, int* buffer_env_counts,
                 Dict* vec_kwargs, Dict* env_kwargs) {
    bbe5_check_abi();
    void* arr = bbe5_vec_init(num_envs_out, buffer_env_starts, buffer_env_counts,
        vec_kwargs, env_kwargs);
    int n = *num_envs_out;
    Env* envs = (Env*)calloc((size_t)n, sizeof(Env));
    if (!envs) {
        perror("bloodbowl5: calloc envs");
        exit(1);
    }
    for (int i = 0; i < n; i++) {
        envs[i].num_agents = 2;
        envs[i].bb = bbe5_env_at(arr, i);
        envs[i].bb_owner = 0;
    }
    int num_buffers = (int)dict_get(vec_kwargs, "num_buffers");
    bbe5_assign_policies(envs, num_buffers, buffer_env_starts,
        buffer_env_counts, vec_kwargs);
    return envs;
}

void my_vec_close(Env* envs) {
    if (envs) {
        bbe5_free_vec(envs[0].bb);
        free(envs);
    }
}

void puf_init(Env* env, Dict* kwargs) {
    bbe5_check_abi();
    env->bb = bbe5_init_one(kwargs);
    env->bb_owner = 1;
    env->num_agents = 2;
    env->agents[0].policy = 0;
    env->agents[1].policy = 0;
}

void puf_reset(Env* env) {
    bbe5_bind_env(env);
    bbe5_reset(env->bb);
}

void puf_step(Env* env) {
    bbe5_step(env->bb, (float*)&env->log);
}

void puf_render(Env* env) {
    bbe5_render(env->bb);
}

void puf_close(Env* env) {
    if (env->bb_owner && env->bb) {
        bbe5_free_one(env->bb);
        env->bb = NULL;
    }
}

void puf_log(Log* log, Dict* out) {
    bbe5_log((float*)log, out);
}

// Trainer hook (patch 0002): compact the exact joint support of one buffer.
static inline void puf_pack_joint_actions(Env* envs, int env_start, int env_count,
        int buf, int agents_per_buffer, float* actions_base,
        uint32_t* joint_actions, int* joint_offsets, int* joint_counts,
        int* joint_buffer_counts) {
    bbe5_pack_joint(envs[env_start].bb, env_count, buf, agents_per_buffer,
        actions_base, joint_actions, joint_offsets, joint_counts,
        joint_buffer_counts);
}

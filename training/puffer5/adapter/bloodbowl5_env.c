// C translation unit for the Blood Bowl env under PufferLib 5.0.
//
// Compiles the unmodified 4.0 binding (puffer/bloodbowl/binding.c, hash
// 3ed6899e with the rest of puffer/bloodbowl) through a 4.0-API shim and
// exports the bbe5_* API declared in the adapter bloodbowl.h. Build flags
// mirror the 4.0 static-library compile (-O2 -DNDEBUG -mavx2 -mfma) so the
// env's floating-point observation planes are produced by the same code
// generation choices.
//
// Include order matters:
//   1. 5.0 ini.h defines Dict / dict_find / dict_set.
//   2. The binding's exported names are renamed so they cannot collide with
//      the 5.0 adapter's C++ definitions.
//   3. binding.c pulls in the real bloodbowl.h (from its own directory) and
//      then "vecenv.h", which resolves to shim/vecenv.h.
#include "ini.h"

#define my_vec_init bbe4_my_vec_init
#define my_init bbe4_my_init
#define my_log bbe4_my_log
#define my_setup_perm bbe4_my_setup_perm
#define my_pack_joint_actions bbe4_my_pack_joint_actions

#include "env/binding.c"

#undef Env
#undef dict_get
#undef dict_get_unsafe

int bbe5_log_float_count(void) {
    return (int)(sizeof(Log) / sizeof(float));
}

int bbe5_obs_size(void) {
    return BBE_OBS_SIZE;
}

int bbe5_mask_size(void) {
    return BBE_MASK_SIZE;
}

int bbe5_joint_action_max(void) {
    return MY_JOINT_ACTION_MAX;
}

void* bbe5_vec_init(int* num_envs_out, int* buffer_env_starts,
                    int* buffer_env_counts, Dict* vec_kwargs, Dict* env_kwargs) {
    return bbe4_my_vec_init(num_envs_out, buffer_env_starts, buffer_env_counts,
        vec_kwargs, env_kwargs);
}

void* bbe5_env_at(void* envs, int i) {
    return &((Bloodbowl*)envs)[i];
}

void* bbe5_init_one(Dict* env_kwargs) {
    Bloodbowl* env = (Bloodbowl*)calloc(1, sizeof(Bloodbowl));
    if (!env) {
        perror("bloodbowl5: calloc env");
        exit(1);
    }
    bbe4_my_init(env, env_kwargs);
    return env;
}

// Point the env's per-slot buffers at 5.0's Agent rows. Mirrors 4.0
// my_setup_perm (including the v4-plane dirty flags for re-pointed rows) and
// carries the trainer's env tag into the env, which c_step reads for the
// scripted bank seat.
void bbe5_bind(void* bb, int tag, uint8_t* obs0, uint8_t* obs1,
               unsigned char* mask0, unsigned char* mask1,
               float* act0, float* act1, float* rew0, float* rew1,
               float* term0, float* term1) {
    Bloodbowl* env = (Bloodbowl*)bb;
    env->v4_dirty[0] = 1;
    env->v4_dirty[1] = 1;
    env->obs_ptr[0] = obs0;
    env->obs_ptr[1] = obs1;
    env->action_mask_ptr[0] = mask0;
    env->action_mask_ptr[1] = mask1;
    env->action_ptr[0] = act0;
    env->action_ptr[1] = act1;
    env->reward_ptr[0] = rew0;
    env->reward_ptr[1] = rew1;
    env->terminal_ptr[0] = term0;
    env->terminal_ptr[1] = term1;
    env->observations = obs0;
    env->actions = act0;
    env->rewards = rew0;
    env->terminals = term0;
    env->action_mask = mask0;
    env->num_agents = BBE_AGENTS;
    env->tag = tag;
}

void bbe5_reset(void* bb) {
    c_reset((Bloodbowl*)bb);
}

// Step, then move this step's Log deltas into the trainer-visible
// accumulator. The env only ever adds to its Log (never reads it back), and
// the 4.0 vecenv cleared it on every log call, so moving the delta each step
// is equivalent and keeps the trainer's Log a plain float struct.
void bbe5_step(void* bb, float* log_accumulator) {
    Bloodbowl* env = (Bloodbowl*)bb;
    c_step(env);
    float* src = (float*)&env->log;
    int nf = (int)(sizeof(Log) / sizeof(float));
    for (int j = 0; j < nf; j++) {
        log_accumulator[j] += src[j];
        src[j] = 0.0f;
    }
}

void bbe5_pack_joint(void* first_env, int env_count, int buf,
                     int agents_per_buffer, float* actions_base,
                     uint32_t* joint_actions, int* joint_offsets,
                     int* joint_counts, int* joint_buffer_counts) {
    StaticVec vec = {0};
    vec.actions = actions_base;
    vec.agents_per_buffer = agents_per_buffer;
    vec.joint_actions = joint_actions;
    vec.joint_action_offsets = joint_offsets;
    vec.joint_action_counts = joint_counts;
    vec.joint_buffer_counts = joint_buffer_counts;
    bbe4_my_pack_joint_actions(&vec, (Bloodbowl*)first_env, 0, env_count, buf);
}

void bbe5_log(float* log, Dict* out) {
    bbe4_my_log((Log*)log, out);
}

void bbe5_render(void* bb) {
    c_render((Bloodbowl*)bb);
}

int bbe5_scripted_bank_tag(void* bb) {
    return ((Bloodbowl*)bb)->scripted_bank_tag;
}

void bbe5_free_one(void* bb) {
    c_close((Bloodbowl*)bb);
    free(bb);
}

void bbe5_free_vec(void* envs) {
    free(envs);
}

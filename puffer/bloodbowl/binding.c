// binding.c — PufferLib 4.0 vecenv glue for the Blood Bowl env.
//
// build.sh compiles this file as the env's single translation unit and
// awk-extracts the literal `#define OBS_TENSOR_T` line below, so keep these
// defines as plain literals.
#include "bloodbowl.h"

#define OBS_SIZE 832
#define NUM_ATNS 3
#define ACT_SIZES {30, 33, 391}
#define OBS_TENSOR_T ByteTensor
#define MY_ACTION_MASK 454

#define MY_VEC_INIT
#define MY_USES_PERM
#define MY_USES_TAGS
#define Env Bloodbowl
#include "vecenv.h"

_Static_assert(OBS_SIZE == BBE_OBS_SIZE, "OBS_SIZE out of sync with bloodbowl.h");
_Static_assert(MY_ACTION_MASK == BBE_MASK_SIZE,
               "MY_ACTION_MASK out of sync with bloodbowl.h");

// dict_get aborts on missing keys; tolerate sparse [env] config sections.
static double kw(Dict* kwargs, const char* key, double fallback) {
    DictItem* item = dict_get_unsafe(kwargs, key);
    return item != NULL ? item->value : fallback;
}

static void apply_kwargs(Env* env, Dict* kwargs) {
    env->reward_td = (float)kw(kwargs, "reward_td", 1.0);
    env->reward_win = (float)kw(kwargs, "reward_win", 3.0);
    env->reward_setup_done = (float)kw(kwargs, "reward_setup_done", 0.0);
    env->reward_setup_autofix = (float)kw(kwargs, "reward_setup_autofix", 0.0);
    env->max_decisions = (int)kw(kwargs, "max_decisions", BBE_MAX_DECISIONS);
    if (env->max_decisions <= 0 || env->max_decisions > BBE_MAX_DECISIONS) {
        env->max_decisions = BBE_MAX_DECISIONS;
    }
    env->render_fps = (int)kw(kwargs, "render_fps", 60.0);
}

void my_setup_perm(StaticVec* vec, Env* env, int slot_base) {
    size_t obs_elem_size = obs_element_size();
    for (int s = 0; s < env->num_agents; s++) {
        int phys = vec->agent_perm ? vec->agent_perm[slot_base + s] : (slot_base + s);
        env->obs_ptr[s]         = (uint8_t*)vec->observations + (size_t)phys * OBS_SIZE * obs_elem_size;
        env->action_mask_ptr[s] = vec->action_mask + (size_t)phys * MY_ACTION_MASK;
        env->action_ptr[s]      = vec->actions + (size_t)phys * NUM_ATNS;
        env->reward_ptr[s]      = vec->rewards + phys;
        env->terminal_ptr[s]    = vec->terminals + phys;
    }
}

Env* my_vec_init(int* num_envs_out, int* buffer_env_starts, int* buffer_env_counts,
                 Dict* vec_kwargs, Dict* env_kwargs) {
    int total_agents = (int)dict_get(vec_kwargs, "total_agents")->value;
    int num_buffers = (int)dict_get(vec_kwargs, "num_buffers")->value;
    int agents_per_buffer = total_agents / num_buffers;

    // create_static_vec assumes buffer b's agent rows start at
    // b * agents_per_buffer; with 2 agents per env any remainder would make
    // buffers overlap agent rows. Fail loudly instead of corrupting training.
    if (total_agents % (num_buffers * BBE_AGENTS) != 0) {
        fprintf(stderr,
                "bloodbowl: total_agents (%d) must be divisible by "
                "num_buffers * %d (= %d)\n",
                total_agents, BBE_AGENTS, num_buffers * BBE_AGENTS);
        exit(1);
    }

    int num_envs = total_agents / BBE_AGENTS;
    Env* envs = (Env*)calloc(num_envs, sizeof(Env));
    uint64_t base_seed = (uint64_t)kw(env_kwargs, "seed", 1.0);
    for (int i = 0; i < num_envs; i++) {
        Env* env = &envs[i];
        apply_kwargs(env, env_kwargs);
        env->num_agents = BBE_AGENTS;
        // Distinct, deterministic per-env stream; episode counter advances it.
        env->seed = base_seed + (uint64_t)i;
    }

    int buf = 0;
    int buf_agents = 0;
    buffer_env_starts[0] = 0;
    buffer_env_counts[0] = 0;
    for (int i = 0; i < num_envs; i++) {
        buf_agents += BBE_AGENTS;
        buffer_env_counts[buf]++;
        if (buf_agents >= agents_per_buffer && buf < num_buffers - 1) {
            buf++;
            buffer_env_starts[buf] = i + 1;
            buffer_env_counts[buf] = 0;
            buf_agents = 0;
        }
    }

    *num_envs_out = num_envs;
    return envs;
}

void my_init(Env* env, Dict* kwargs) {
    apply_kwargs(env, kwargs);
    env->num_agents = BBE_AGENTS;
    if (env->seed == 0) {
        env->seed = (uint64_t)kw(kwargs, "seed", 1.0);
    }
}

void my_log(Log* log, Dict* out) {
    // dict_set stores the key POINTER (vecenv.h), so string literals only.
    dict_set(out, "perf", log->perf);
    dict_set(out, "score_diff", log->score_diff);
    dict_set(out, "tds", log->tds);
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
    dict_set(out, "illegal_frac", log->illegal_frac);
    dict_set(out, "hist_score_bank_0", log->hist_score_bank[0]);
    dict_set(out, "hist_score_bank_1", log->hist_score_bank[1]);
    dict_set(out, "hist_score_bank_2", log->hist_score_bank[2]);
    dict_set(out, "hist_score_bank_3", log->hist_score_bank[3]);
    dict_set(out, "hist_score_bank_4", log->hist_score_bank[4]);
    dict_set(out, "hist_score_bank_5", log->hist_score_bank[5]);
    dict_set(out, "hist_score_bank_6", log->hist_score_bank[6]);
    dict_set(out, "hist_score_bank_7", log->hist_score_bank[7]);
    dict_set(out, "hist_n_bank_0", log->hist_n_bank[0]);
    dict_set(out, "hist_n_bank_1", log->hist_n_bank[1]);
    dict_set(out, "hist_n_bank_2", log->hist_n_bank[2]);
    dict_set(out, "hist_n_bank_3", log->hist_n_bank[3]);
    dict_set(out, "hist_n_bank_4", log->hist_n_bank[4]);
    dict_set(out, "hist_n_bank_5", log->hist_n_bank[5]);
    dict_set(out, "hist_n_bank_6", log->hist_n_bank[6]);
    dict_set(out, "hist_n_bank_7", log->hist_n_bank[7]);
}

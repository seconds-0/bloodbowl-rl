// binding.c — PufferLib 4.0 vecenv glue for the Blood Bowl env.
//
// build.sh compiles this file as the env's single translation unit and
// awk-extracts the literal `#define OBS_TENSOR_T` line below, so keep these
// defines as plain literals.
#include "bloodbowl.h"

#define OBS_SIZE 2782 // obs v4 (mirrors BBE_OBS_SIZE; static-assert below)
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

// ACT_SIZES must stay a plain brace literal (see the header comment above),
// so tie its PARTITION to the BBE_HEAD_* source of truth instead of deriving
// it: the MY_ACTION_MASK assert above only pins the sum, so a sum-preserving
// drift (e.g. type head +1 / square head -1) would ship mis-partitioned masks
// silently. Commas inside braces split macro arguments (only parens protect
// them), which exposes the middle element to a _Static_assert; the outer
// elements carry brace tokens the preprocessor can't strip, so they are
// pinned at startup by bbe_check_act_sizes (called from both init entry
// points).
#define BBE_ACT_SECOND__(a, b, c) b
#define BBE_ACT_SECOND_(...) BBE_ACT_SECOND__(__VA_ARGS__)
#define BBE_ACT_SECOND(x) BBE_ACT_SECOND_(x)
_Static_assert(NUM_ATNS == 3, "ACT_SIZES checks below assume 3 action heads");
_Static_assert(sizeof((const int[])ACT_SIZES) == NUM_ATNS * sizeof(int),
               "ACT_SIZES element count out of sync with NUM_ATNS");
_Static_assert(BBE_ACT_SECOND(ACT_SIZES) == BBE_HEAD_ARG,
               "ACT_SIZES arg head out of sync with BBE_HEAD_ARG");

static const int bbe_act_sizes[] = ACT_SIZES;
static void bbe_check_act_sizes(void) {
    if (bbe_act_sizes[0] != BBE_HEAD_TYPE || bbe_act_sizes[1] != BBE_HEAD_ARG ||
        bbe_act_sizes[2] != BBE_HEAD_SQ) {
        fprintf(stderr,
                "bloodbowl: ACT_SIZES {%d, %d, %d} out of sync with BBE_HEAD_* "
                "{%d, %d, %d}\n",
                bbe_act_sizes[0], bbe_act_sizes[1], bbe_act_sizes[2],
                BBE_HEAD_TYPE, BBE_HEAD_ARG, BBE_HEAD_SQ);
        exit(1);
    }
}

// dict_get aborts on missing keys; tolerate sparse [env] config sections.
static double kw(Dict* kwargs, const char* key, double fallback) {
    DictItem* item = dict_get_unsafe(kwargs, key);
    return item != NULL ? item->value : fallback;
}

static void apply_kwargs(Env* env, Dict* kwargs) {
    env->reward_td = (float)kw(kwargs, "reward_td", 1.0);
    env->reward_win = (float)kw(kwargs, "reward_win", 3.0);
    env->reward_draw = (float)kw(kwargs, "reward_draw", 0.0);
    env->reward_setup_done = (float)kw(kwargs, "reward_setup_done", 0.0);
    env->reward_setup_autofix = (float)kw(kwargs, "reward_setup_autofix", 0.0);
    env->reward_ball_gain = (float)kw(kwargs, "reward_ball_gain", 0.0);
    env->reward_ball_loss = (float)kw(kwargs, "reward_ball_loss", 0.0);
    env->reward_dist_ball = (float)kw(kwargs, "reward_dist_ball", 0.0);
    env->reward_dist_endzone = (float)kw(kwargs, "reward_dist_endzone", 0.0);
    env->reward_injury_inflicted = (float)kw(kwargs, "reward_injury_inflicted", 0.0);
    env->reward_injury_taken = (float)kw(kwargs, "reward_injury_taken", 0.0);
    env->reward_injury_value_scaled = (int)kw(kwargs, "reward_injury_value_scaled", 0.0);
    env->reward_send_off = (float)kw(kwargs, "reward_send_off", 0.0);
    env->reward_kickoff_touchback = (float)kw(kwargs, "reward_kickoff_touchback", 0.0);
    env->reward_surf_taken = (float)kw(kwargs, "reward_surf_taken", 0.0);
    env->reward_surf_inflicted = (float)kw(kwargs, "reward_surf_inflicted", 0.0);
    // Profile C exposure-EV + sequencing knobs (bb_blockev; spec defaults
    // when enabled: k_kd 0.06, k_value 0.5, k_ball 0.3, k_seq ~0.02).
    env->reward_k_kd = (float)kw(kwargs, "reward_k_kd", 0.0);
    env->reward_k_value = (float)kw(kwargs, "reward_k_value", 0.0);
    env->reward_k_ball = (float)kw(kwargs, "reward_k_ball", 0.0);
    env->reward_k_seq = (float)kw(kwargs, "reward_k_seq", 0.0);
    // Possession annuity transfer per own-turn-ended-holding (suggested 0.03)
    env->reward_possession = (float)kw(kwargs, "reward_possession", 0.0);
    // Rush tax per GFI square at declaration (suggested 0.01-0.02)
    env->reward_rush_cost = (float)kw(kwargs, "reward_rush_cost", 0.0);
    // R6v1 carrier-exposure penalties, positive magnitudes charged via -=.
    env->reward_carrier_exposure = (float)kw(kwargs, "reward_carrier_exposure", 0.0);
    env->reward_carrier_exposure_soft =
        (float)kw(kwargs, "reward_carrier_exposure_soft", 0.0);
    // R12v1 defensive scoring-lane threat penalties (D133-A), positive
    // magnitudes charged via -=. 1-turn (hard) + optional 2-turn (soft) tiers.
    env->reward_defensive_threat = (float)kw(kwargs, "reward_defensive_threat", 0.0);
    env->reward_defensive_threat_soft =
        (float)kw(kwargs, "reward_defensive_threat_soft", 0.0);
    // Aggregate-stat-matching pseudo-reward scale (D114). 0 = off (default).
    // When >0, an episode-end -scale*||z||_2 penalty pulls the 7-stat full-game
    // vector toward docs/human-baseline.json. Kickoff-pure only; pair with
    // --env.reward-possession 0. See bloodbowl.h reward_statmatch_scale.
    env->reward_statmatch_scale = (float)kw(kwargs, "reward_statmatch_scale", 0.0);
    // Backplay curriculum: scoring-proximal demo resets (0 = uniform)
    env->demo_endzone_maxdist = (int)kw(kwargs, "demo_endzone_maxdist", 0.0);
    // Pickup curriculum (D64): loose-ball-near-mover demo resets (0 = off)
    env->demo_pickup_maxdist = (int)kw(kwargs, "demo_pickup_maxdist", 0.0);
    // Post-kickoff scoop drill (D68): loose ball at team-turn <= N (0 = off)
    env->demo_postkick_maxturn = (int)kw(kwargs, "demo_postkick_maxturn", 0.0);
    // Passing ladder (D72): held-ball + downfield-receiver demo resets (0=off)
    env->demo_pass_maxrange = (int)kw(kwargs, "demo_pass_maxrange", 0.0);
    env->skillup_max_players = (int)kw(kwargs, "skillup_max_players", 4.0);
    env->skillup_max_each = (int)kw(kwargs, "skillup_max_each", 2.0);
    env->skillup_secondary_pct = (float)kw(kwargs, "skillup_secondary_pct", 0.0);
    // v5 path-actions (D82): STEP head = any reachable destination (0 = v4)
    env->macro_moves = (int)kw(kwargs, "macro_moves", 0.0);
    env->reach_mover = -1;
    env->macro_mover = -1;
    env->demo_reset_pct = (float)kw(kwargs, "demo_reset_pct", 0.0);
    env->exclude_team = (int)kw(kwargs, "exclude_team", -1.0);
    env->force_home_team = (int)kw(kwargs, "force_home_team", -1.0);
    env->force_away_team = (int)kw(kwargs, "force_away_team", -1.0);
    env->scripted_opponent = (int)kw(kwargs, "scripted_opponent", 0.0);
    env->scripted_opponent_team = (int)kw(kwargs, "scripted_opponent_team", 1.0);
    if (env->scripted_opponent_team < 0 || env->scripted_opponent_team > 1) {
        env->scripted_opponent_team = 1;
    }
    env->max_decisions = (int)kw(kwargs, "max_decisions", BBE_MAX_DECISIONS);
    if (env->max_decisions <= 0 || env->max_decisions > BBE_MAX_DECISIONS) {
        env->max_decisions = BBE_MAX_DECISIONS;
    }
    env->render_fps = (int)kw(kwargs, "render_fps", 60.0);
}

void my_setup_perm(StaticVec* vec, Env* env, int slot_base) {
    size_t obs_elem_size = obs_element_size();
    // Re-pointed obs rows may hold another agent's stale v4 plane bytes.
    env->v4_dirty[0] = 1;
    env->v4_dirty[1] = 1;
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
    bbe_check_act_sizes();
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

    // Demo-state curriculum: one shared load BEFORE any stepping thread
    // exists (the chess SHARED_FEN_CURRICULUM pattern) — the lazy reset-time
    // path then never races. Missing file degrades to plain procgen resets.
    if ((float)kw(env_kwargs, "demo_reset_pct", 0.0) > 0.0f) {
        bbe_state_bank_load();
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
    bbe_check_act_sizes();
    apply_kwargs(env, kwargs);
    env->num_agents = BBE_AGENTS;
    if (env->seed == 0) {
        env->seed = (uint64_t)kw(kwargs, "seed", 1.0);
    }
    if (env->demo_reset_pct > 0.0f) {
        bbe_state_bank_load(); // before stepping, mirroring my_vec_init
    }
}

void my_log(Log* log, Dict* out) {
    // dict_set stores the key POINTER (vecenv.h), so string literals only.
    //
    // CAPACITY: vec_log (src/bindings_cpu.cpp / bindings.cu) hands us a
    // create_dict(64) and appends "n" after we return — keep total keys < 64.
    // We emit 56. Growing past the call-site capacity is SILENT HEAP
    // CORRUPTION upstream (assert compiles out under NDEBUG); our vendored
    // dict_set aborts loudly instead (training/puffer_dict_capacity.patch).
    // History: key count hit 37 vs capacity 32 when slot scores + demo
    // counters landed → "free(): corrupted unsorted chunks" at first episode
    // completion (~786K steps), masquerading as a thread-count bug.
    dict_set(out, "perf", log->perf);
    dict_set(out, "score_diff", log->score_diff);
    dict_set(out, "tds", log->tds);
    dict_set(out, "tds_t0", log->tds_t0);
    dict_set(out, "tds_t1", log->tds_t1);
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
    dict_set(out, "statmatch_term", log->statmatch_term);
    dict_set(out, "illegal_frac", log->illegal_frac);
    dict_set(out, "blocks", log->blocks);
    dict_set(out, "blocks_thrown", log->blocks_thrown);
    dict_set(out, "blocks_thrown_t0", log->blocks_thrown_t0);
    dict_set(out, "blocks_thrown_t1", log->blocks_thrown_t1);
    dict_set(out, "block_1d_frac", log->block_1d_frac);
    dict_set(out, "block_2d_frac", log->block_2d_frac);
    dict_set(out, "block_3d_frac", log->block_3d_frac);
    dict_set(out, "block_2dred_frac", log->block_2dred_frac);
    dict_set(out, "block_3dred_frac", log->block_3dred_frac);
    dict_set(out, "pickup_success", log->pickup_success);
    dict_set(out, "possession_rate", log->possession_rate);
    dict_set(out, "blitzes", log->blitzes);
    dict_set(out, "dodge_attempts", log->dodge_attempts);
    dict_set(out, "gfi_attempts", log->gfi_attempts);
    dict_set(out, "pickup_attempts", log->pickup_attempts);
    dict_set(out, "pass_attempts", log->pass_attempts);
    dict_set(out, "handoff_attempts", log->handoff_attempts);
    dict_set(out, "knockdowns_inflicted", log->knockdowns_inflicted);
    dict_set(out, "knockdowns_own", log->knockdowns_own);
    dict_set(out, "ep_send_offs", log->ep_send_offs);
    dict_set(out, "ep_touchbacks", log->ep_touchbacks);
    dict_set(out, "carrier_exposed_full", log->carrier_exposed_full);
    dict_set(out, "carrier_exposed_soft", log->carrier_exposed_soft);
    dict_set(out, "ep_def_threats_1t", log->def_threats_1t);
    dict_set(out, "ep_def_threats_2t", log->def_threats_2t);
    dict_set(out, "error_episodes", log->error_episodes);
    dict_set(out, "demo_episodes", log->demo_episodes);
    dict_set(out, "demo_fallbacks", log->demo_fallbacks);
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
    dict_set(out, "slot_0_score", log->slot_0_score);
    dict_set(out, "slot_1_score", log->slot_1_score);
    dict_set(out, "draw_rate", log->draw_rate);
}

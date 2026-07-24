// binding.c — PufferLib 4.0 vecenv glue for the Blood Bowl env.
//
// build.sh compiles this file as the env's single translation unit and
// awk-extracts the literal `#define OBS_TENSOR_T` line below, so keep these
// defines as plain literals.
#include "bloodbowl.h"

#define OBS_SIZE 2782 // obs v6 semantic ABI; v4/v5 shape retained (see header)
#define NUM_ATNS 3
#define ACT_SIZES {30, 33, 391}
#define OBS_TENSOR_T ByteTensor
#define MY_ACTION_MASK 454
#define MY_JOINT_ACTION_MAX 4487 // BB_LEGAL_MAX + 391 virtual destinations

#define MY_VEC_INIT
#define MY_USES_PERM
#define MY_USES_TAGS
#define Env Bloodbowl
#include "vecenv.h"

_Static_assert(OBS_SIZE == BBE_OBS_SIZE, "OBS_SIZE out of sync with bloodbowl.h");
_Static_assert(MY_ACTION_MASK == BBE_MASK_SIZE,
               "MY_ACTION_MASK out of sync with bloodbowl.h");
_Static_assert(MY_JOINT_ACTION_MAX >= BB_LEGAL_MAX + BBE_HEAD_SQ,
               "joint support capacity cannot hold legal + virtual actions");

static uint32_t bbe_pack_joint(int type, int arg, int square) {
    return (uint32_t)type | ((uint32_t)arg << 10) |
           ((uint32_t)square << 20);
}

// Compact the exact semantic support for one vec buffer. The native sampler
// consumes these tuples sequentially (type -> arg|type -> square|type,arg)
// and stores the three selected conditional masks in the ordinary rollout
// mask, so PPO recomputation needs no ragged history buffer.
void my_pack_joint_actions(StaticVec* vec, Env* envs, int env_start,
                           int env_count, int buf) {
    int agent_start = buf * vec->agents_per_buffer;
    int agent_end = agent_start + vec->agents_per_buffer;
    int joint_start = agent_start * MY_JOINT_ACTION_MAX;
    int cursor = 0;
    for (int ei = env_start; ei < env_start + env_count; ei++) {
        Env* env = &envs[ei];
        for (int slot = 0; slot < env->num_agents; slot++) {
            ptrdiff_t action_off = env->action_ptr[slot] - vec->actions;
            int phys = (int)(action_off / NUM_ATNS);
            if (action_off < 0 || action_off % NUM_ATNS != 0 ||
                phys < agent_start || phys >= agent_end) {
                fprintf(stderr,
                        "bloodbowl: joint-support row escaped vec buffer "
                        "(buf=%d row=%d expected=[%d,%d))\n",
                        buf, phys, agent_start, agent_end);
                abort();
            }
            int off = joint_start + cursor;
            int count = 0;
            if (env->match.status != BB_STATUS_DECISION ||
                env->match.decision_team != slot || env->n_legal <= 0) {
                vec->joint_actions[off] =
                    bbe_pack_joint(BB_A_NONE, 32, 390);
                count = 1;
            } else {
                for (int i = 0; i < env->n_legal; i++) {
                    vec->joint_actions[off + count++] = bbe_pack_joint(
                        env->legal[i].type, env->legal_arg[i],
                        env->legal_sq[i]);
                }
                if (env->macro_moves && env->reach_mover >= 0) {
                    for (int d = 0; d < 390; d++) {
                        if (env->reach_parent[d] < 0) continue;
                        int x = d % BB_PITCH_LEN;
                        int y = d / BB_PITCH_LEN;
                        int sq = bbe_sq_index(slot, x, y);
                        vec->joint_actions[off + count++] =
                            bbe_pack_joint(BB_A_STEP, 32, sq);
                    }
                }
            }
            if (count <= 0 || count > MY_JOINT_ACTION_MAX ||
                cursor + count > vec->agents_per_buffer * MY_JOINT_ACTION_MAX) {
                fprintf(stderr,
                        "bloodbowl: exact joint support overflow "
                        "(row=%d count=%d cursor=%d cap=%d)\n",
                        phys, count, cursor,
                        vec->agents_per_buffer * MY_JOINT_ACTION_MAX);
                abort();
            }
            vec->joint_action_offsets[phys] = off;
            vec->joint_action_counts[phys] = count;
            cursor += count;
        }
    }
    vec->joint_buffer_counts[buf] = cursor;
}

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
    env->reward_td = (float)kw(kwargs, "reward_td", BBE_DEFAULT_REWARD_TD);
    env->reward_win = (float)kw(kwargs, "reward_win", BBE_DEFAULT_REWARD_WIN);
    env->reward_draw = (float)kw(kwargs, "reward_draw", BBE_DEFAULT_REWARD_DRAW);
    env->reward_configured = 1;
    env->reward_setup_done = (float)kw(kwargs, "reward_setup_done", 0.0);
    env->reward_setup_autofix = (float)kw(kwargs, "reward_setup_autofix", 0.0);
    env->reward_ball_gain = (float)kw(kwargs, "reward_ball_gain", 0.0);
    env->reward_ball_loss = (float)kw(kwargs, "reward_ball_loss", 0.0);
    env->reward_dist_ball = (float)kw(kwargs, "reward_dist_ball", 0.0);
    env->reward_dist_endzone = (float)kw(kwargs, "reward_dist_endzone", 0.0);
    env->reward_dist_pbrs_gamma =
        (float)kw(kwargs, "reward_dist_pbrs_gamma", 0.0);
    env->reward_injury_inflicted = (float)kw(kwargs, "reward_injury_inflicted", 0.0);
    env->reward_injury_taken = (float)kw(kwargs, "reward_injury_taken", 0.0);
    env->reward_injury_value_scaled = (int)kw(kwargs, "reward_injury_value_scaled", 0.0);
    env->reward_send_off = (float)kw(kwargs, "reward_send_off", 0.0);
    env->reward_kickoff_touchback = (float)kw(kwargs, "reward_kickoff_touchback", 0.0);
    env->reward_surf_taken = (float)kw(kwargs, "reward_surf_taken", 0.0);
    env->reward_surf_inflicted = (float)kw(kwargs, "reward_surf_inflicted", 0.0);
    // Profile C exposure-EV + sequencing/net-EV knobs (bb_blockev; spec
    // defaults when enabled: k_kd 0.06, k_value 0.5, k_ball 0.3, k_seq ~0.02).
    env->reward_k_kd = (float)kw(kwargs, "reward_k_kd", 0.0);
    env->reward_k_value = (float)kw(kwargs, "reward_k_value", 0.0);
    env->reward_k_self_injury = (float)kw(kwargs, "reward_k_self_injury", 0.0);
    env->reward_k_ball = (float)kw(kwargs, "reward_k_ball", 0.0);
    env->reward_k_seq = (float)kw(kwargs, "reward_k_seq", 0.0);
    env->reward_k_turnover = (float)kw(kwargs, "reward_k_turnover", 0.0);
    // Possession annuity transfer per own-turn-ended-holding (suggested 0.03)
    env->reward_possession = (float)kw(kwargs, "reward_possession", 0.0);
    env->reward_k_assist = (float)kw(kwargs, "reward_k_assist", 0.0);
    // Rush tax per GFI square at declaration (suggested 0.01-0.02)
    env->reward_rush_cost = (float)kw(kwargs, "reward_rush_cost", 0.0);
    // R6v1 carrier-exposure penalties, positive magnitudes charged via -=.
    env->reward_carrier_exposure = (float)kw(kwargs, "reward_carrier_exposure", 0.0);
    env->reward_carrier_exposure_soft =
        (float)kw(kwargs, "reward_carrier_exposure_soft", 0.0);
    env->reward_carrier_threat = (float)kw(kwargs, "reward_carrier_threat", 0.0);
    // R12v1 defensive scoring-lane threat penalties (D133-A), positive
    // magnitudes charged via -=. 1-turn (hard) + optional 2-turn (soft) tiers.
    env->reward_defensive_threat = (float)kw(kwargs, "reward_defensive_threat", 0.0);
    env->reward_defensive_threat_soft =
        (float)kw(kwargs, "reward_defensive_threat_soft", 0.0);
    // Legacy/quarantined D114 stat-matching scale. New complete reward
    // manifests require 0 because the historical targets are semantically
    // invalid; retain the kwarg only for artifact reproduction.
    env->reward_statmatch_scale = (float)kw(kwargs, "reward_statmatch_scale", 0.0);
    // Validate only after every reward field has been populated. Keeping this
    // call above the final fields made apply_kwargs' validation incomplete.
    bbe_validate_reward_config(env);
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
    env->scripted_opponent_type = (int)kw(kwargs, "scripted_opponent_type", 0.0);
    if (env->scripted_opponent_team < 0 || env->scripted_opponent_team > 1) {
        env->scripted_opponent_team = 1;
    }
    if (env->scripted_opponent_type < 0 || env->scripted_opponent_type > 1) {
        env->scripted_opponent_type = 0;
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
    // CAPACITY: vec_log (src/bindings_cpu.cpp / bindings.cu) must hand us a
    // dict large enough for these keys plus the vecenv-appended "n". We emit
    // 144 (capacity is 160 — training/puffer_dict_capacity.patch), so there is
    // room for 15 more. Growing past the call-site capacity is SILENT HEAP CORRUPTION
    // upstream (assert compiles out under NDEBUG); our vendored dict_set
    // aborts loudly instead (training/puffer_dict_capacity.patch).
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
    float clip_frac = log->reward_samples > 0.0f
        ? log->reward_clipped_samples / log->reward_samples : 0.0f;
    float clip_frac_nonzero = log->reward_nonzero_samples > 0.0f
        ? log->reward_clipped_samples / log->reward_nonzero_samples : 0.0f;
    float nonfinite_frac = log->reward_samples > 0.0f
        ? log->reward_nonfinite_samples / log->reward_samples : 0.0f;
    dict_set(out, "reward_clip_frac", clip_frac);
    dict_set(out, "reward_clip_frac_nonzero", clip_frac_nonzero);
    dict_set(out, "reward_clip_excess", log->reward_clip_excess);
    dict_set(out, "reward_clip_terminal_samples_per_episode",
             log->reward_clip_terminal_samples);
    dict_set(out, "reward_clip_nonterminal_samples_per_episode",
             log->reward_clip_nonterminal_samples);
    dict_set(out, "reward_episode_abs_max_mean",
             log->reward_episode_abs_max_mean);
    dict_set(out, "reward_nonfinite_frac", nonfinite_frac);
    dict_set(out, "reward_samples_per_episode", log->reward_samples);
    dict_set(out, "reward_nonzero_samples_per_episode",
             log->reward_nonzero_samples);
    dict_set(out, "reward_clipped_samples_per_episode",
             log->reward_clipped_samples);
    dict_set(out, "reward_nonfinite_samples_per_episode",
             log->reward_nonfinite_samples);
    dict_set(out, "reward_clip_episodes", log->reward_clip_episodes);
    dict_set(out, "reward_nonfinite_episodes", log->reward_nonfinite_episodes);
    dict_set(out, "reward_component_setup_done",
             log->reward_component[BBE_REWARD_SETUP_DONE]);
    dict_set(out, "reward_component_setup_autofix",
             log->reward_component[BBE_REWARD_SETUP_AUTOFIX]);
    dict_set(out, "reward_component_ball_gain",
             log->reward_component[BBE_REWARD_BALL_GAIN]);
    dict_set(out, "reward_component_ball_loss",
             log->reward_component[BBE_REWARD_BALL_LOSS]);
    dict_set(out, "reward_component_distance_ball",
             log->reward_component[BBE_REWARD_DISTANCE_BALL]);
    dict_set(out, "reward_component_distance_endzone",
             log->reward_component[BBE_REWARD_DISTANCE_ENDZONE]);
    dict_set(out, "reward_component_injury_inflicted",
             log->reward_component[BBE_REWARD_INJURY_INFLICTED]);
    dict_set(out, "reward_component_injury_taken",
             log->reward_component[BBE_REWARD_INJURY_TAKEN]);
    dict_set(out, "reward_component_send_off",
             log->reward_component[BBE_REWARD_SEND_OFF]);
    dict_set(out, "reward_component_touchback",
             log->reward_component[BBE_REWARD_TOUCHBACK]);
    dict_set(out, "reward_component_surf_inflicted",
             log->reward_component[BBE_REWARD_SURF_INFLICTED]);
    dict_set(out, "reward_component_surf_taken",
             log->reward_component[BBE_REWARD_SURF_TAKEN]);
    dict_set(out, "reward_component_block_exposure",
             log->reward_component[BBE_REWARD_BLOCK_EXPOSURE]);
    dict_set(out, "reward_component_block_self_injury",
             log->reward_component[BBE_REWARD_BLOCK_SELF_INJURY]);
    dict_set(out, "reward_component_block_sequence",
             log->reward_component[BBE_REWARD_BLOCK_SEQUENCE]);
    dict_set(out, "reward_component_block_turnover",
             log->reward_component[BBE_REWARD_BLOCK_TURNOVER]);
    dict_set(out, "reward_component_possession",
             log->reward_component[BBE_REWARD_POSSESSION]);
    dict_set(out, "reward_component_block_assist",
             log->reward_component[BBE_REWARD_BLOCK_ASSIST]);
    dict_set(out, "reward_component_rush",
             log->reward_component[BBE_REWARD_RUSH]);
    dict_set(out, "reward_component_carrier_exposure",
             log->reward_component[BBE_REWARD_CARRIER_EXPOSURE]);
    dict_set(out, "reward_component_carrier_exposure_soft",
             log->reward_component[BBE_REWARD_CARRIER_EXPOSURE_SOFT]);
    dict_set(out, "reward_component_carrier_threat",
             log->reward_component[BBE_REWARD_CARRIER_THREAT]);
    dict_set(out, "reward_component_defensive_threat",
             log->reward_component[BBE_REWARD_DEFENSIVE_THREAT]);
    dict_set(out, "reward_component_defensive_threat_soft",
             log->reward_component[BBE_REWARD_DEFENSIVE_THREAT_SOFT]);
    dict_set(out, "reward_component_touchdown",
             log->reward_component[BBE_REWARD_TOUCHDOWN]);
    dict_set(out, "reward_component_result_winloss",
             log->reward_component[BBE_REWARD_RESULT_WINLOSS]);
    dict_set(out, "reward_component_result_draw",
             log->reward_component[BBE_REWARD_RESULT_DRAW]);
    dict_set(out, "reward_component_statmatch",
             log->reward_component[BBE_REWARD_STATMATCH]);
    dict_set(out, "reward_component_residual",
             log->reward_component_residual);
    dict_set(out, "reward_component_mismatch_samples_per_episode",
             log->reward_component_mismatch_samples);
    dict_set(out, "reward_component_nonfinite_samples_per_episode",
             log->reward_component_nonfinite_samples);
    dict_set(out, "reward_terminal_suppressed_signed",
             log->reward_terminal_suppressed_signed);
    dict_set(out, "reward_terminal_suppressed_abs",
             log->reward_terminal_suppressed_abs);
    dict_set(out, "reward_postclip_return", log->reward_postclip_return);
    dict_set(out, "reward_clip_signed_delta",
             log->reward_clip_signed_delta);
    dict_set(out, "illegal_frac", log->illegal_frac);
    dict_set(out, "blocks", log->blocks);
    dict_set(out, "blocks_thrown", log->blocks_thrown);
    dict_set(out, "blocks_thrown_t0", log->blocks_thrown_t0);
    dict_set(out, "blocks_thrown_t1", log->blocks_thrown_t1);
    dict_set(out, "blocks_vs_carrier", log->blocks_vs_carrier);
    dict_set(out, "carrier_block_frac", log->carrier_block_frac);
    dict_set(out, "block_1d_frac", log->block_1d_frac);
    dict_set(out, "block_2d_frac", log->block_2d_frac);
    dict_set(out, "block_3d_frac", log->block_3d_frac);
    dict_set(out, "block_2dred_frac", log->block_2dred_frac);
    dict_set(out, "block_3dred_frac", log->block_3dred_frac);
    dict_set(out, "block_1d_carrier_frac", log->block_1d_carrier_frac);
    dict_set(out, "block_2d_carrier_frac", log->block_2d_carrier_frac);
    dict_set(out, "block_2dred_carrier_frac", log->block_2dred_carrier_frac);
    dict_set(out, "offassist_1d", log->offassist_1d);
    dict_set(out, "offassist_2d", log->offassist_2d);
    dict_set(out, "offassist_3d", log->offassist_3d);
    dict_set(out, "offassist_2dred", log->offassist_2dred);
    dict_set(out, "pickup_success", log->pickup_success);
    dict_set(out, "possession_rate", log->possession_rate);
    dict_set(out, "ball_fwd_adv", log->ball_fwd_adv);
    dict_set(out, "ball_path_len", log->ball_path_len);
    dict_set(out, "blitzes", log->blitzes);
    dict_set(out, "dodge_attempts", log->dodge_attempts);
    dict_set(out, "gfi_attempts", log->gfi_attempts);
    dict_set(out, "pickup_attempts", log->pickup_attempts);
    dict_set(out, "pass_attempts", log->pass_attempts);
    dict_set(out, "handoff_attempts", log->handoff_attempts);
    dict_set(out, "knockdowns_inflicted", log->knockdowns_inflicted);
    dict_set(out, "knockdowns_own", log->knockdowns_own);
    dict_set(out, "carrier_knockdowns", log->carrier_knockdowns);
    dict_set(out, "ep_send_offs", log->ep_send_offs);
    dict_set(out, "ep_touchbacks", log->ep_touchbacks);
    dict_set(out, "carrier_exposed_full", log->carrier_exposed_full);
    dict_set(out, "carrier_exposed_soft", log->carrier_exposed_soft);
    dict_set(out, "ep_carrier_threat", log->ep_carrier_threat);
    dict_set(out, "ep_contact_fav", log->ep_contact_fav);
    dict_set(out, "ep_def_threats_1t", log->def_threats_1t);
    dict_set(out, "ep_def_threats_2t", log->def_threats_2t);
    dict_set(out, "def_deep_safety", log->def_deep_safety);
    dict_set(out, "def_deep_safety_zero_frac", log->def_deep_safety_zero_frac);
    dict_set(out, "def_carrier_path_zerotz", log->def_carrier_path_zerotz);
    dict_set(out, "def_carrier_min_dodges", log->def_carrier_min_dodges);
    dict_set(out, "def_carrier_marked_frac", log->def_carrier_marked_frac);
    // BB2025 Stalling (D193). stall_rolls = crowd D6s CONSUMED = how often the
    // team actually stalled (dice-independent, and still counted on turns 7-8);
    // stall_crowd_acted = the roll succeeded; stall_turnovers = it cost the
    // turn (acted - turnovers = Steady Footing saves). stall_rate_turn1_6* is
    // the reward-audit gate metric: stalls per completed team turn, turns 1-6.
    dict_set(out, "stall_rolls", log->stall_rolls);
    dict_set(out, "stall_rolls_t0", log->stall_rolls_t0);
    dict_set(out, "stall_rolls_t1", log->stall_rolls_t1);
    dict_set(out, "stall_crowd_acted", log->stall_crowd_acted);
    dict_set(out, "stall_turnovers", log->stall_turnovers);
    dict_set(out, "stall_turnovers_t0", log->stall_turnovers_t0);
    dict_set(out, "stall_turnovers_t1", log->stall_turnovers_t1);
    dict_set(out, "stall_rolls_turn1_6", log->stall_rolls_turn1_6);
    dict_set(out, "stall_turnovers_turn1_6", log->stall_turnovers_turn1_6);
    dict_set(out, "stall_turns_turn1_6", log->stall_turns_turn1_6);
    dict_set(out, "stall_rate_turn1_6", log->stall_rate_turn1_6);
    dict_set(out, "stall_rate_turn1_6_t0", log->stall_rate_turn1_6_t0);
    dict_set(out, "stall_rate_turn1_6_t1", log->stall_rate_turn1_6_t1);
    dict_set(out, "stall_rolls_turn1", log->stall_rolls_by_turn[0]);
    dict_set(out, "stall_rolls_turn2", log->stall_rolls_by_turn[1]);
    dict_set(out, "stall_rolls_turn3", log->stall_rolls_by_turn[2]);
    dict_set(out, "stall_rolls_turn4", log->stall_rolls_by_turn[3]);
    dict_set(out, "stall_rolls_turn5", log->stall_rolls_by_turn[4]);
    dict_set(out, "stall_rolls_turn6", log->stall_rolls_by_turn[5]);
    dict_set(out, "stall_rolls_turn7", log->stall_rolls_by_turn[6]);
    dict_set(out, "stall_rolls_turn8", log->stall_rolls_by_turn[7]);
    _Static_assert(BB_STALL_TURNS == 8,
                   "stall_rolls_turnN keys must cover BB_STALL_TURNS");
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

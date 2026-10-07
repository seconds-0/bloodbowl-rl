// bbplay.c: ctypes shim for the human-vs-policy play harness.
//
// Compiles the PufferLib env amalgamation (puffer/bloodbowl/bloodbowl.h pulls
// in every engine source) as ONE translation unit, so observations, masks,
// exact-joint projection, bbe_decode and c_step are the training code itself.
// Nothing under puffer/bloodbowl/ or engine/ is modified; this file only reads
// env state and calls c_reset / c_step.
//
// Differences from the vec binding (binding.c), all deliberate:
//   * one env, two agent rows, buffers owned here (the test-fixture layout);
//   * apply_kwargs is mirrored for the play-relevant fields (see
//     bbp_create_env) and for every reward coefficient (BBP_REWARD_FIELDS);
//     play_harness/tests/test_native_config.py guards drift;
//   * a submitted tuple is checked against exact joint support BEFORE c_step,
//     because c_step abort()s the process on an out-of-support tuple;
//   * c_step auto-resets the env at the terminal step, so the natural final
//     state is rebuilt by re-applying the terminal action to a pre-step copy;
//   * a session can be copied for search (bbp_clone_for_search). A copy never
//     carries the source's dice stream: see the clone section below.
#include "bloodbowl.h"

#define BBP_ABI_VERSION 5

// Return codes for bbp_step and bbp_step_scripted.
#define BBP_STEP_OK 0
#define BBP_STEP_TERMINAL 1
#define BBP_STEP_REJECTED -1      // tuple outside exact joint support
#define BBP_STEP_NO_DECISION -2   // env is not waiting on a decision
#define BBP_STEP_COLLISION -3     // two distinct engine actions share the tuple
#define BBP_STEP_OVER -4          // session already reached a terminal step
#define BBP_STEP_NOT_BOT_TURN -5  // scripted step while the other coach decides
#define BBP_STEP_BAD_BOT -6       // unknown scripted bot type

// Reasons bbp_clone_for_search and bbp_copy_into refuse.
#define BBP_CLONE_OK 0
#define BBP_CLONE_BAD_ARGS -1     // NULL, dst == src, or dst is not a clone
#define BBP_CLONE_REAL_STREAM -2  // the stream id is the real dice stream's
#define BBP_CLONE_TERMINAL -3     // the source already reached a terminal step

// Scripted bot types, the env's scripted_opponent_type values (bloodbowl.ini).
#define BBP_BOT_CONTACT 0         // bbe_contact_bot_pick (contact_bot.h)
#define BBP_BOT_OFFENSE 1         // bbe_offense_bot_pick (offense_bot.h)

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
    bb_match final_match;
    int final_valid;
    int terminal;
    int rejected;
    int collisions;
    int steps;
    int decisions_at_terminal;
    bb_action last_action;
    int last_agent;
    float last_rewards[BBE_AGENTS];
    // Stalling tally before the latest c_step, and the natural final tally
    // (pre-step tally plus the terminal action's replay on a scratch sink),
    // because c_step's auto-reset clears the env's own tally.
    bb_stall_tally pre_stall;
    bb_stall_tally final_stall;
    // 1 for a search copy (bbp_clone_for_search): its dice are its own, it
    // leaves the thread's stalling sink as it found it, and once terminal it
    // gives no observation (the env has reset to the next procgen match).
    int clone;
} bbp_session;

int bbp_abi_version(void) { return BBP_ABI_VERSION; }
int bbp_obs_size(void) { return BBE_OBS_SIZE; }
int bbp_obs_version(void) { return BBE_OBS_VERSION; }
int bbp_mask_size(void) { return BBE_MASK_SIZE; }
int bbp_legal_max(void) { return BB_LEGAL_MAX; }
int bbp_team_count(void) { return BB_TEAM_COUNT; }
int bbp_skill_count(void) { return BB_SKILL_COUNT; }

// Struct layout probe so the Python ctypes mirror can refuse a mismatch.
int bbp_layout(int32_t* out, int cap) {
    int32_t v[] = {
        (int32_t)sizeof(bb_match),
        (int32_t)sizeof(bb_player),
        (int32_t)sizeof(bb_frame),
        (int32_t)offsetof(bb_match, grid),
        (int32_t)offsetof(bb_match, ball),
        (int32_t)offsetof(bb_match, half),
        (int32_t)offsetof(bb_match, stack),
        (int32_t)offsetof(bb_match, stack_top),
        (int32_t)offsetof(bb_match, status),
        (int32_t)offsetof(bb_match, decision_team),
        (int32_t)offsetof(bb_match, step_count),
        (int32_t)offsetof(bb_match, team_id),
        (int32_t)offsetof(bb_match, turnovers_completed),
        (int32_t)offsetof(bb_player, ma),
        (int32_t)offsetof(bb_player, x),
        (int32_t)offsetof(bb_player, flags),
        (int32_t)offsetof(bb_player, position_id),
        (int32_t)offsetof(bb_player, p_bloodlust),
    };
    int n = (int)(sizeof v / sizeof v[0]);
    for (int i = 0; i < n && i < cap; i++) out[i] = v[i];
    return n;
}

static void bbp_wire(bbp_session* s) {
    Bloodbowl* env = &s->env;
    env->num_agents = BBE_AGENTS;
    env->observations = s->obs;
    env->actions = s->actions;
    env->rewards = s->rewards;
    env->terminals = s->terminals;
    env->action_mask = s->masks;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env->obs_ptr[a] = s->obs + a * BBE_OBS_SIZE;
        env->action_ptr[a] = s->actions + a * 3;
        env->action_mask_ptr[a] = s->masks + a * BBE_MASK_SIZE;
        env->reward_ptr[a] = s->rewards + a;
        env->terminal_ptr[a] = s->terminals + a;
    }
}

// Every reward coefficient apply_kwargs (binding.c) reads, in the order of the
// table bbp_create_rewards takes. F = float field, I = int field.
#define BBP_REWARD_FIELDS(F, I) \
    F(reward_td) F(reward_win) F(reward_draw) \
    F(reward_setup_done) F(reward_setup_autofix) \
    F(reward_ball_gain) F(reward_ball_loss) \
    F(reward_dist_ball) F(reward_dist_endzone) F(reward_dist_pbrs_gamma) \
    F(reward_injury_inflicted) F(reward_injury_taken) \
    I(reward_injury_value_scaled) \
    F(reward_send_off) F(reward_kickoff_touchback) \
    F(reward_surf_taken) F(reward_surf_inflicted) \
    F(reward_k_kd) F(reward_k_value) F(reward_k_self_injury) F(reward_k_ball) \
    F(reward_k_seq) F(reward_k_turnover) \
    F(reward_possession) F(reward_k_assist) F(reward_rush_cost) \
    F(reward_carrier_exposure) F(reward_carrier_exposure_soft) \
    F(reward_carrier_threat) \
    F(reward_defensive_threat) F(reward_defensive_threat_soft) \
    F(reward_statmatch_scale)

#define BBP_REWARD_NAME(field) #field,
static const char* const bbp_reward_names[] = {
    BBP_REWARD_FIELDS(BBP_REWARD_NAME, BBP_REWARD_NAME)
};
#undef BBP_REWARD_NAME
#define BBP_REWARD_COUNT ((int)(sizeof bbp_reward_names / sizeof bbp_reward_names[0]))

int bbp_reward_field_count(void) { return BBP_REWARD_COUNT; }

const char* bbp_reward_field_name(int i) {
    return (i >= 0 && i < BBP_REWARD_COUNT) ? bbp_reward_names[i] : NULL;
}

static void bbp_set_rewards(Bloodbowl* env, const float* table) {
    int i = 0;
#define BBP_SET_F(field) env->field = table[i++];
#define BBP_SET_I(field) env->field = (int)table[i++];
    BBP_REWARD_FIELDS(BBP_SET_F, BBP_SET_I)
#undef BBP_SET_F
#undef BBP_SET_I
}

static void bbp_get_rewards(const Bloodbowl* env, float* table) {
    int i = 0;
#define BBP_GET(field) table[i++] = (float)env->field;
    BBP_REWARD_FIELDS(BBP_GET, BBP_GET)
#undef BBP_GET
}

// 0 when bbe_validate_reward_config accepts the env's coefficients, else the
// number of its check that fails. That function abort()s the process, which a
// bad manifest must not do to a Python caller, so its checks are repeated here
// in its order (test_native_config.py counts them against the header). Check 6
// is the shim's own: the header never tests the PBRS gamma for a finite value.
static int bbp_reward_config_error(const Bloodbowl* env) {
    if (!bbe_reward_config_scalars_valid(env, NULL)) return 1;
    if (env->reward_carrier_threat != 0.0f &&
        (env->reward_carrier_exposure != 0.0f ||
         env->reward_carrier_exposure_soft != 0.0f)) {
        return 2;
    }
    if (env->reward_carrier_threat != 0.0f && env->reward_k_assist != 0.0f) return 3;
    if (!bbe_reward_potential_sign_valid(env)) return 4;
    if (!bbe_reward_envelope_valid(env)) return 5;
    if (!(env->reward_dist_pbrs_gamma >= 0.0f && env->reward_dist_pbrs_gamma <= 1.0f)) {
        return 6;
    }
    return 0;
}

// The int coefficients are flags. They are checked on the raw table value,
// before bbp_set_rewards converts it: a NaN, an infinity or an out-of-range
// float converted to int is undefined behaviour.
static int bbp_reward_flags_valid(const float* table) {
    int i = 0, ok = 1;
#define BBP_SKIP(field) i++;
#define BBP_FLAG(field) ok &= (table[i] == 0.0f || table[i] == 1.0f); i++;
    BBP_REWARD_FIELDS(BBP_SKIP, BBP_FLAG)
#undef BBP_SKIP
#undef BBP_FLAG
    return ok;
}

// 0 when bbp_create_rewards would accept this table, -1 for a wrong length,
// 7 for an int coefficient that is not exactly 0 or 1, else the failing check
// of bbp_reward_config_error.
int bbp_reward_table_error(const float* table, int n) {
    if (!table || n != BBP_REWARD_COUNT) return -1;
    if (!bbp_reward_flags_valid(table)) return 7;
    Bloodbowl env;
    memset(&env, 0, sizeof env);
    bbp_set_rewards(&env, table);
    return bbp_reward_config_error(&env);
}

// rewards: BBP_REWARD_COUNT coefficients in BBP_REWARD_FIELDS order, or NULL
// for the objective defaults and zero shaping.
static bbp_session* bbp_create_env(uint64_t seed, int episode, int home_team,
                                   int away_team, int skillup_max_players,
                                   int skillup_max_each, float skillup_secondary_pct,
                                   int max_decisions, const float* rewards) {
    bbp_session* s = (bbp_session*)calloc(1, sizeof(bbp_session));
    if (!s) return NULL;
    bbp_wire(s);
    Bloodbowl* env = &s->env;
    // Mirrors apply_kwargs (binding.c) at the bloodbowl.ini defaults for every
    // field that changes observations, legality, rosters or episode bounds.
    // Rewards are not observed and do not change the policy's inputs
    // (test_reward_independence.py), so a session without a table keeps the
    // objective defaults and zero shaping.
    if (rewards) {
        bbp_set_rewards(env, rewards);
    } else {
        env->reward_td = BBE_DEFAULT_REWARD_TD;
        env->reward_win = BBE_DEFAULT_REWARD_WIN;
        env->reward_draw = BBE_DEFAULT_REWARD_DRAW;
    }
    if (bbp_reward_config_error(env)) {
        free(s);
        return NULL;
    }
    env->reward_configured = 1;
    bbe_validate_reward_config(env);
    env->demo_endzone_maxdist = 0;
    env->demo_pickup_maxdist = 0;
    env->demo_postkick_maxturn = 0;
    env->demo_pass_maxrange = 0;
    env->skillup_max_players = skillup_max_players;
    env->skillup_max_each = skillup_max_each;
    env->skillup_secondary_pct = skillup_secondary_pct;
    env->macro_moves = 0;
    env->reach_mover = -1;
    env->macro_mover = -1;
    env->demo_reset_pct = 0.0f;
    env->exclude_team = -1;
    env->force_home_team = home_team;
    env->force_away_team = away_team;
    env->scripted_opponent = 0;
    env->scripted_opponent_team = 1;
    env->scripted_opponent_type = 0;
    env->scripted_bank_tag = 0;
    env->max_decisions = (max_decisions <= 0 || max_decisions > BBE_MAX_DECISIONS)
                             ? BBE_MAX_DECISIONS : max_decisions;
    env->render_fps = 60;
    env->seed = seed;
    env->episode = episode;
    c_reset(env);
    s->last_agent = -1;
    return s;
}

// episode: number of matches this env has already finished. The env seeds
// procgen from (seed, episode + 1), so a native vec env i with base seed B
// reproduces here as seed = B + i, episode = completed matches on that row.
bbp_session* bbp_create(uint64_t seed, int episode, int home_team, int away_team,
                        int skillup_max_players, int skillup_max_each,
                        float skillup_secondary_pct, int max_decisions) {
    return bbp_create_env(seed, episode, home_team, away_team, skillup_max_players,
                          skillup_max_each, skillup_secondary_pct, max_decisions,
                          NULL);
}

// bbp_create with a full reward coefficient table (the training reward
// manifest), so the session's per-step rewards are the trainer's. NULL when
// the table is refused; bbp_reward_table_error says why.
bbp_session* bbp_create_rewards(uint64_t seed, int episode, int home_team,
                                int away_team, int skillup_max_players,
                                int skillup_max_each, float skillup_secondary_pct,
                                int max_decisions, const float* rewards, int n) {
    if (bbp_reward_table_error(rewards, n)) return NULL;
    return bbp_create_env(seed, episode, home_team, away_team, skillup_max_players,
                          skillup_max_each, skillup_secondary_pct, max_decisions,
                          rewards);
}

// The session's reward coefficients in BBP_REWARD_FIELDS order.
int bbp_reward_table(bbp_session* s, float* out, int cap) {
    float v[BBP_REWARD_COUNT];
    bbp_get_rewards(&s->env, v);
    for (int i = 0; i < BBP_REWARD_COUNT && i < cap; i++) out[i] = v[i];
    return BBP_REWARD_COUNT;
}

// c_step leaves this thread's stalling sink on the env it stepped. Freeing
// that env must not leave the sink pointing into freed memory.
static void bbp_release(bbp_session* s) {
    if (!s) return;
    if (bb_stall_attached() == &s->env.ep_stall) bb_stall_attach(NULL);
    free(s);
}

void bbp_destroy(bbp_session* s) { bbp_release(s); }

// NULL for a terminal clone: what its buffers hold then is the next procgen
// match, which a rollout must never read as the state after the game.
const uint8_t* bbp_obs(bbp_session* s, int agent) {
    if (s->clone && s->terminal) return NULL;
    return (agent == 0 || agent == 1) ? s->env.obs_ptr[agent] : NULL;
}

const unsigned char* bbp_mask(bbp_session* s, int agent) {
    if (s->clone && s->terminal) return NULL;
    return (agent == 0 || agent == 1) ? s->env.action_mask_ptr[agent] : NULL;
}

const bb_match* bbp_match(bbp_session* s) { return &s->env.match; }

const bb_match* bbp_final_match(bbp_session* s) {
    return s->final_valid ? &s->final_match : NULL;
}

int bbp_status(bbp_session* s) { return s->env.match.status; }
int bbp_decision_team(bbp_session* s) { return s->env.match.decision_team; }
int bbp_n_legal(bbp_session* s) { return s->env.n_legal; }

// Legal engine actions for the deciding coach plus their exact policy-head
// projection (arg head, square head) in that coach's egocentric frame.
int bbp_legal(bbp_session* s, uint8_t* actions4, uint16_t* proj2, int cap) {
    Bloodbowl* env = &s->env;
    int n = env->n_legal;
    if (env->match.status != BB_STATUS_DECISION) n = 0;
    for (int i = 0; i < n && i < cap; i++) {
        actions4[4 * i] = env->legal[i].type;
        actions4[4 * i + 1] = env->legal[i].arg;
        actions4[4 * i + 2] = env->legal[i].x;
        actions4[4 * i + 3] = env->legal[i].y;
        proj2[2 * i] = env->legal_arg[i];
        proj2[2 * i + 1] = env->legal_sq[i];
    }
    return n;
}

// Exact joint support for one agent row, packed exactly like
// my_pack_joint_actions (binding.c): t | arg << 10 | sq << 20. The waiting
// row is the singleton NONE tuple. macro_moves is off in this harness.
int bbp_joint_support(bbp_session* s, int agent, uint32_t* out, int cap) {
    Bloodbowl* env = &s->env;
    if (env->match.status != BB_STATUS_DECISION ||
        env->match.decision_team != agent || env->n_legal <= 0) {
        if (cap >= 1) out[0] = (uint32_t)BB_A_NONE | (32u << 10) | (390u << 20);
        return 1;
    }
    int n = env->n_legal;
    for (int i = 0; i < n && i < cap; i++) {
        out[i] = (uint32_t)env->legal[i].type |
                 ((uint32_t)env->legal_arg[i] << 10) |
                 ((uint32_t)env->legal_sq[i] << 20);
    }
    return n;
}

static int bbp_find_tuple(bbp_session* s, int t, int arg, int sq, int* collision) {
    Bloodbowl* env = &s->env;
    int exact = -1;
    *collision = 0;
    for (int i = 0; i < env->n_legal; i++) {
        if (env->legal[i].type != t || env->legal_arg[i] != arg ||
            env->legal_sq[i] != sq) {
            continue;
        }
        if (exact < 0) {
            exact = i;
        } else if (!bb_action_eq(env->legal[exact], env->legal[i])) {
            *collision = 1;
            return -1;
        }
    }
    return exact;
}

// Index into bbp_legal of the tuple, or -1 (outside support), -3 (collision).
int bbp_tuple_index(bbp_session* s, int t, int arg, int sq) {
    int collision = 0;
    int idx = bbp_find_tuple(s, t, arg, sq, &collision);
    return collision ? -3 : idx;
}

static void bbp_clear_action_rows(Bloodbowl* env) {
    for (int a = 0; a < BBE_AGENTS; a++) {
        env->action_ptr[a][0] = (float)BB_A_NONE;
        env->action_ptr[a][1] = 32.0f;
        env->action_ptr[a][2] = 390.0f;
    }
}

// The engine's own scripted pick, exactly as c_step dispatches it for
// scripted_opponent_type. The caller has checked the decision and the type.
static bb_action bbp_bot_pick(Bloodbowl* env, int bot_type) {
    return bot_type == BBP_BOT_OFFENSE
               ? bbe_offense_bot_pick(&env->match, env->legal, env->n_legal)
               : bbe_contact_bot_pick(&env->match, env->legal, env->n_legal);
}

// Run the real c_step with the action rows already written, then rebuild the
// natural final state if the step was terminal. act is the engine action c_step
// applies, agent the deciding coach.
static int bbp_run_c_step(bbp_session* s, bb_action act, int agent) {
    Bloodbowl* env = &s->env;
    bb_match pre = env->match;
    bb_rng pre_rng = env->rng;
    int pre_decisions = env->decisions;
    s->pre_stall = env->ep_stall;
    c_step(env);
    s->steps++;
    s->last_action = act;
    s->last_agent = agent;
    s->last_rewards[0] = env->reward_ptr[0][0];
    s->last_rewards[1] = env->reward_ptr[1][0];
    if (env->terminal_ptr[0][0] != 0.0f || env->terminal_ptr[1][0] != 0.0f) {
        // c_step already reset to a fresh procgen match. Rebuild the natural
        // final state from the pre-step copy on a scratch stalling sink so the
        // replay cannot touch the env's own tally.
        bb_stall_tally scratch;
        bb_stall_reset(&scratch);
        bb_stall_tally* prev = bb_stall_attached();
        bb_stall_attach(&scratch);
        s->final_match = pre;
        bb_apply_trusted(&s->final_match, act, &pre_rng);
        bb_stall_attach(prev);
        s->final_stall = s->pre_stall;
        for (int t2 = 0; t2 < 2; t2++) {
            for (int k = 0; k < BB_STALL_TURNS; k++) {
                s->final_stall.rolls[t2][k] += scratch.rolls[t2][k];
                s->final_stall.acted[t2][k] += scratch.acted[t2][k];
                s->final_stall.turnovers[t2][k] += scratch.turnovers[t2][k];
                s->final_stall.turn_ends[t2][k] += scratch.turn_ends[t2][k];
            }
        }
        s->final_valid = 1;
        s->terminal = 1;
        s->decisions_at_terminal = pre_decisions + 1;
        return BBP_STEP_TERMINAL;
    }
    return BBP_STEP_OK;
}

static int bbp_step_real(bbp_session* s, int t, int arg, int sq) {
    Bloodbowl* env = &s->env;
    if (s->terminal) return BBP_STEP_OVER;
    if (env->match.status != BB_STATUS_DECISION || env->n_legal <= 0) {
        return BBP_STEP_NO_DECISION;
    }
    int collision = 0;
    int idx = bbp_find_tuple(s, t, arg, sq, &collision);
    if (collision) {
        s->collisions++;
        return BBP_STEP_COLLISION;
    }
    if (idx < 0) {
        s->rejected++;
        return BBP_STEP_REJECTED;
    }
    int agent = env->match.decision_team;
    bb_action act = env->legal[idx];
    bbp_clear_action_rows(env);
    env->action_ptr[agent][0] = (float)t;
    env->action_ptr[agent][1] = (float)arg;
    env->action_ptr[agent][2] = (float)sq;
    return bbp_run_c_step(s, act, agent);
}

// After a step of a clone, on every return path: put this thread's stalling
// sink back where it was (c_step moved it to the clone, which is scratch and
// may be freed next), and drop the dice stream of a clone that just ended,
// because the env's terminal reset reseeded it from the copied real seed.
static int bbp_clone_step_done(bbp_session* s, bb_stall_tally* prev, int rc) {
    if (s->clone) {
        bb_stall_attach(prev);
        if (rc == BBP_STEP_TERMINAL) memset(&s->env.rng, 0, sizeof s->env.rng);
    }
    return rc;
}

// Apply the deciding coach's tuple through the real c_step. Never aborts on
// bad input: the tuple is validated against exact support first.
int bbp_step(bbp_session* s, int t, int arg, int sq) {
    bb_stall_tally* prev = bb_stall_attached();
    return bbp_clone_step_done(s, prev, bbp_step_real(s, t, arg, sq));
}

// Let the engine's scripted bot decide for `team` through c_step's own
// scripted_opponent branch: the env carries scripted_opponent = 1 with this
// type and team for the one step (bank tag 0, the frozen-eval setting), then
// the fields go back to the bbp_create values. Both action rows hold the NONE
// tuple, which that branch never reads.
static int bbp_step_scripted_real(bbp_session* s, int bot_type, int team) {
    Bloodbowl* env = &s->env;
    if (s->terminal) return BBP_STEP_OVER;
    if (bot_type != BBP_BOT_CONTACT && bot_type != BBP_BOT_OFFENSE) {
        return BBP_STEP_BAD_BOT;
    }
    if (env->match.status != BB_STATUS_DECISION || env->n_legal <= 0) {
        return BBP_STEP_NO_DECISION;
    }
    int agent = env->match.decision_team;
    if (agent != team) return BBP_STEP_NOT_BOT_TURN;
    bb_action act = bbp_bot_pick(env, bot_type);
    bbp_clear_action_rows(env);
    env->scripted_opponent = 1;
    env->scripted_opponent_type = bot_type;
    env->scripted_opponent_team = team;
    env->scripted_bank_tag = 0;
    int rc = bbp_run_c_step(s, act, agent);
    env->scripted_opponent = 0;
    env->scripted_opponent_type = 0;
    env->scripted_opponent_team = 1;
    return rc;
}

int bbp_step_scripted(bbp_session* s, int bot_type, int team) {
    bb_stall_tally* prev = bb_stall_attached();
    return bbp_clone_step_done(s, prev, bbp_step_scripted_real(s, bot_type, team));
}

// Legal actions after applying a tuple on a scratch copy of the session.
// Used for UI lookahead (the action menu shown before ACTIVATE is committed).
// The real match, its dice stream and the policy are untouched. Returns the
// number of actions, -1 if the tuple is refused, -2 if the copy reached a
// terminal step.
int bbp_peek_legal(bbp_session* s, int t, int arg, int sq, uint8_t* actions4,
                   uint16_t* proj2, int cap) {
    bbp_session* c = (bbp_session*)malloc(sizeof(bbp_session));
    if (!c) return -1;
    memcpy(c, s, sizeof(bbp_session));
    bbp_wire(c);
    bb_stall_tally* prev = bb_stall_attached();
    int rc = bbp_step_real(c, t, arg, sq);
    int n = rc == BBP_STEP_OK ? bbp_legal(c, actions4, proj2, cap)
                              : (rc == BBP_STEP_TERMINAL ? -2 : -1);
    free(c);
    bb_stall_attach(prev);
    return n;
}

// ---- Search clones -----------------------------------------------------------
//
// A clone is a whole-session copy that can be stepped with bbp_step and read
// like any session. The match holds dice already rolled and no future dice;
// those live in env.rng, which a memcpy would carry over. So every exported
// way to make a copy reseeds that stream, and none takes the real stream's id:
// a search that steps a clone rolls its own dice, never the real game's next
// ones. bbp_test_copy_dice below is the single exception, for tests.

// c_reset seeds env.rng as PCG32 (seed + episode * 7919, stream 1).
#define BBP_REAL_DICE_STREAM 1u

// PCG32 keeps (stream << 1) | 1, so two ids that differ only in the top bit
// name the same sequence.
static int bbp_is_real_stream(uint64_t stream) {
    return (stream << 1u) == ((uint64_t)BBP_REAL_DICE_STREAM << 1u);
}

// BBP_CLONE_OK when `src` may be copied onto the dice stream `stream`.
int bbp_clone_refusal(const bbp_session* src, uint64_t stream) {
    if (!src) return BBP_CLONE_BAD_ARGS;
    if (bbp_is_real_stream(stream)) return BBP_CLONE_REAL_STREAM;
    if (src->terminal) return BBP_CLONE_TERMINAL;
    return BBP_CLONE_OK;
}

static void bbp_copy_reseeded(bbp_session* dst, const bbp_session* src,
                              uint64_t seed, uint64_t stream) {
    memcpy(dst, src, sizeof(bbp_session));
    bbp_wire(dst);
    dst->clone = 1;
    // Zeroed first so no byte of the source's stream survives, padding
    // included; bb_rng_seed then clears the script and sink pointers too.
    memset(&dst->env.rng, 0, sizeof dst->env.rng);
    bb_rng_seed(&dst->env.rng, seed, stream);
}

// A copy of `s` whose dice are PCG32 (seed, stream). NULL when refused
// (bbp_clone_refusal) or out of memory. Free with bbp_free_clone.
bbp_session* bbp_clone_for_search(const bbp_session* s, uint64_t seed,
                                  uint64_t stream) {
    if (bbp_clone_refusal(s, stream) != BBP_CLONE_OK) return NULL;
    bbp_session* c = (bbp_session*)malloc(sizeof(bbp_session));
    if (!c) return NULL;
    bbp_copy_reseeded(c, s, seed, stream);
    return c;
}

// bbp_clone_for_search into a clone that is already allocated. dst is left
// untouched when the copy is refused.
int bbp_copy_into(bbp_session* dst, const bbp_session* src, uint64_t seed,
                  uint64_t stream) {
    if (!dst || dst == src || !dst->clone) return BBP_CLONE_BAD_ARGS;
    int refusal = bbp_clone_refusal(src, stream);
    if (refusal != BBP_CLONE_OK) return refusal;
    bbp_copy_reseeded(dst, src, seed, stream);
    return BBP_CLONE_OK;
}

// Frees a clone; a real session is left alone (bbp_destroy owns those).
void bbp_free_clone(bbp_session* s) {
    if (s && s->clone) bbp_release(s);
}

// TEST ONLY. Gives dst the dice stream of src, so a clone can replay the real
// game's dice (clone fidelity and oracle rollout tests) and a root's stream can
// be replaced. This is the one way a copy comes to hold real dice; nothing
// under play_harness/ outside tests/ may call it (test_search_clone.py greps).
void bbp_test_copy_dice(bbp_session* dst, const bbp_session* src) {
    dst->env.rng = src->env.rng;
}

// TEST ONLY. 1 when this thread's stalling sink is s's tally; with s NULL, 1
// when no sink is attached.
int bbp_test_stall_attached(const bbp_session* s) {
    const bb_stall_tally* want = s ? &s->env.ep_stall : NULL;
    return bb_stall_attached() == want;
}

// Integrity and bookkeeping counters.
//   [0] env->illegal            [1] env->illegal_projection_collision
//   [2] log.error_episodes      [3] rejected submissions
//   [4] collisions (pre-check)  [5] steps applied
//   [6] terminal                [7] final_valid
//   [8] final status            [9] env->decisions
//   [10] env->episode           [11] decisions at the terminal step
int bbp_counters(bbp_session* s, int32_t* out, int cap) {
    Bloodbowl* env = &s->env;
    int32_t v[] = {
        env->illegal,
        env->illegal_projection_collision,
        (int32_t)env->log.error_episodes,
        s->rejected,
        s->collisions,
        s->steps,
        s->terminal,
        s->final_valid,
        s->final_valid ? (int32_t)s->final_match.status : -1,
        env->decisions,
        env->episode,
        s->decisions_at_terminal,
    };
    int n = (int)(sizeof v / sizeof v[0]);
    for (int i = 0; i < n && i < cap; i++) out[i] = v[i];
    return n;
}

int bbp_last_action(bbp_session* s, uint8_t* out4) {
    out4[0] = s->last_action.type;
    out4[1] = s->last_action.arg;
    out4[2] = s->last_action.x;
    out4[3] = s->last_action.y;
    return s->last_agent;
}

void bbp_last_rewards(bbp_session* s, float* out2) {
    out2[0] = s->last_rewards[0];
    out2[1] = s->last_rewards[1];
}

#define BBP_FNV_INIT 1469598103934665603ull

static uint64_t bbp_fnv(uint64_t h, const void* data, size_t n) {
    const uint8_t* p = (const uint8_t*)data;
    for (size_t i = 0; i < n; i++) {
        h ^= p[i];
        h *= 1099511628211ull;
    }
    return h;
}

// FNV-1a over the whole match struct and the dice stream state: the
// determinism fingerprint for traces.
uint64_t bbp_state_digest(bbp_session* s) {
    uint64_t h = bbp_fnv(BBP_FNV_INIT, &s->env.match, sizeof(bb_match));
    return bbp_fnv(h, &s->env.rng, sizeof(bb_rng));
}

// FNV-1a over everything a later observation, legal list or step can read,
// plus the bookkeeping that is not reward: the match, both rng streams, the
// legal list and its projections, the encode caches, the counters, the
// stalling tally, both output buffers and the session's own flags. Reward
// coefficients, reward state and the Log are left out, so two sessions that
// differ only in their reward table share this digest at every step. So do a
// clone and its source while they hold the same dice.
uint64_t bbp_env_digest(bbp_session* s) {
    const Bloodbowl* env = &s->env;
    uint64_t h = bbp_state_digest(s);
#define BBP_H(x) h = bbp_fnv(h, &(x), sizeof(x))
    BBP_H(env->procgen);
    BBP_H(env->seed);
    BBP_H(env->episode);
    BBP_H(env->decisions);
    BBP_H(env->illegal);
    BBP_H(env->illegal_projection_collision);
    BBP_H(env->demo_started);
    BBP_H(env->n_legal);
    int n = env->n_legal > 0 ? env->n_legal : 0;
    h = bbp_fnv(h, env->legal, (size_t)n * sizeof env->legal[0]);
    h = bbp_fnv(h, env->legal_arg, (size_t)n * sizeof env->legal_arg[0]);
    h = bbp_fnv(h, env->legal_sq, (size_t)n * sizeof env->legal_sq[0]);
    BBP_H(env->macro_len);
    BBP_H(env->macro_pos);
    BBP_H(env->macro_mover);
    BBP_H(env->reach_mover);
    BBP_H(env->reach_blitz);
    BBP_H(env->ev_valid);
    BBP_H(env->ev_mover);
    BBP_H(env->ev_blitz);
    for (int d = 0; d < BB_NUM_PLAYERS; d++) {
        if ((env->ev_valid >> d) & 1u) BBP_H(env->ev_cache[d]);
    }
    BBP_H(env->setup_t0);
    BBP_H(env->setup_len);
    BBP_H(env->setup_fast);
    BBP_H(env->setup_block_start);
    BBP_H(env->setup_sq_off);
    BBP_H(env->v4_dirty);
    BBP_H(env->skill_keys);
    BBP_H(env->skill_rows);
    BBP_H(env->pending_pickup_slot);
    BBP_H(env->pending_gfi_slot);
    BBP_H(env->pending_dodge_slot);
    BBP_H(env->prev_active_team);
    BBP_H(env->possessor);
    BBP_H(env->score_prev);
    BBP_H(env->score_start);
    BBP_H(env->sent_off_prev);
    BBP_H(env->kickoff_touchback_latched);
    BBP_H(env->ep_turns);
    BBP_H(env->ep_turns_with_ball);
    BBP_H(env->ep_turnovers);
    BBP_H(env->ep_tds_team);
    BBP_H(env->ep_stall);
    BBP_H(s->obs);
    BBP_H(s->masks);
    BBP_H(s->final_valid);
    BBP_H(s->terminal);
    BBP_H(s->rejected);
    BBP_H(s->collisions);
    BBP_H(s->steps);
    BBP_H(s->decisions_at_terminal);
    BBP_H(s->last_action);
    BBP_H(s->last_agent);
#undef BBP_H
    return h;
}

int bbp_session_bytes(void) { return (int)sizeof(bbp_session); }

// Scripted drivers. Index into bbp_legal of the bot's pick for the deciding
// coach: -1 not at a decision, -2 unknown bot type, -3 pick not in the list.
int bbp_scripted_bot_index(bbp_session* s, int bot_type) {
    Bloodbowl* env = &s->env;
    if (bot_type != BBP_BOT_CONTACT && bot_type != BBP_BOT_OFFENSE) return -2;
    if (env->match.status != BB_STATUS_DECISION || env->n_legal <= 0) return -1;
    bb_action a = bbp_bot_pick(env, bot_type);
    for (int i = 0; i < env->n_legal; i++) {
        if (bb_action_eq(env->legal[i], a)) return i;
    }
    return -3;
}

// Contact bot index, or -1.
int bbp_contact_bot_index(bbp_session* s) {
    int i = bbp_scripted_bot_index(s, BBP_BOT_CONTACT);
    return i < 0 ? -1 : i;
}

// ---- UI annotations (read-only probes over engine helpers) -----------------

// Secure the Ball picks up on a flat 2+ (3+ in Pouring Rain) regardless of AG
// (proc_move.c, May 2026 FAQ); the generic helper prices an ordinary pick-up.
static void bbp_secure_ball_pickup(const bb_match* m, int act_kind, int pt, float* pp) {
    if (pt && act_kind == BB_ACT_SECURE_BALL) {
        int target = m->weather == BB_WEATHER_RAIN ? 3 : 2;
        *pp = (float)(7 - target) / 6.0f;
    }
}

// Per-step success components for a prospective STEP of `slot` to (x, y).
// tests[3] = rush, dodge, pickup target numbers (0 = no test); p[3] = their
// base success probabilities. act_kind is the declared bb_act_kind, or -1.
void bbp_step_success(bbp_session* s, int slot, int x, int y, int is_blitz, int act_kind,
                      int32_t* tests, float* p) {
    int rt = 0, dt = 0, pt = 0;
    float rp = 1.0f, dp = 1.0f, pp = 1.0f;
    bb_step_success_components(&s->env.match, slot, x, y, is_blitz, &rt, &rp,
                               &dt, &dp, &pt, &pp);
    bbp_secure_ball_pickup(&s->env.match, act_kind, pt, &pp);
    tests[0] = rt;
    tests[1] = dt;
    tests[2] = pt;
    p[0] = rp;
    p[1] = dp;
    p[2] = pp;
}

// Reachability field for `mover`: flattened y * 26 + x.
void bbp_reach(bbp_session* s, int mover, uint8_t* dodges, uint8_t* gfis,
               uint8_t* len, int8_t* prev_xy) {
    bb_reach_field f;
    bb_reach_field_compute(&s->env.match, mover, &f);
    for (int y = 0; y < BB_PITCH_WID; y++) {
        for (int x = 0; x < BB_PITCH_LEN; x++) {
            int i = y * BB_PITCH_LEN + x;
            dodges[i] = f.cost[x][y].dodges;
            gfis[i] = f.cost[x][y].gfis;
            len[i] = f.len[x][y];
            prev_xy[2 * i] = f.prev_x[x][y];
            prev_xy[2 * i + 1] = f.prev_y[x][y];
        }
    }
}

// Pre-roll block outcome probabilities (bb_blockev order).
void bbp_block_ev(bbp_session* s, int att, int def, int is_blitz, float* out6) {
    bb_blockev ev;
    bb_block_ev(&s->env.match, att, def, is_blitz, NULL, &ev);
    out6[0] = ev.p_def_down;
    out6[1] = ev.p_att_down;
    out6[2] = ev.p_def_removed;
    out6[3] = ev.p_att_removed;
    out6[4] = ev.p_ball_out;
    out6[5] = ev.p_turnover;
}

// Success components along a planned multi-square path, for the path preview.
// Evaluated on a scratch copy of the match where the mover is walked square by
// square (grid, moved count, rushes, ball pickup), so later steps see the
// mover's new origin and movement spent. Display only: the copy never reaches
// c_step and the real match is untouched. xy holds n (x, y) pairs; tests3 and
// probs3 receive rush, dodge, pickup per step. Returns the steps evaluated.
int bbp_path_odds(bbp_session* s, int slot, int n, const int8_t* xy, int is_blitz,
                  int act_kind, int32_t* tests3, float* probs3) {
    if (slot < 0 || slot >= BB_NUM_PLAYERS || n <= 0) return 0;
    bb_match c = s->env.match;
    bb_player* p = &c.players[slot];
    if (p->location != BB_LOC_ON_PITCH) return 0;
    int done = 0;
    for (int i = 0; i < n; i++) {
        int x = xy[2 * i], y = xy[2 * i + 1];
        if (!bb_on_pitch_xy(x, y)) break;
        int rt = 0, dt = 0, pt = 0;
        float rp = 1.0f, dp = 1.0f, pp = 1.0f;
        bb_step_success_components(&c, slot, x, y, is_blitz, &rt, &rp, &dt, &dp, &pt, &pp);
        bbp_secure_ball_pickup(&c, act_kind, pt, &pp);
        tests3[3 * i] = rt;
        tests3[3 * i + 1] = dt;
        tests3[3 * i + 2] = pt;
        probs3[3 * i] = rp;
        probs3[3 * i + 1] = dp;
        probs3[3 * i + 2] = pp;
        done++;
        c.grid[p->x][p->y] = 0;
        p->x = (uint8_t)x;
        p->y = (uint8_t)y;
        c.grid[x][y] = (uint8_t)(slot + 1);
        if (rt) p->rushes++;
        p->moved++;
        if (pt) {
            c.ball.state = BB_BALL_HELD;
            c.ball.carrier = (uint8_t)slot;
        }
    }
    return done;
}

// Stalling crowd rolls per team: out8 = rolls[2], acted[2], turnovers[2],
// turn_ends[2], summed over turns. Natural final tally after the terminal step.
int bbp_stall_counts(bbp_session* s, int32_t* out8) {
    const bb_stall_tally* t = s->terminal ? &s->final_stall : &s->env.ep_stall;
    for (int team = 0; team < 2; team++) {
        int32_t r = 0, a = 0, tv = 0, te = 0;
        for (int k = 0; k < BB_STALL_TURNS; k++) {
            r += (int32_t)t->rolls[team][k];
            a += (int32_t)t->acted[team][k];
            tv += (int32_t)t->turnovers[team][k];
            te += (int32_t)t->turn_ends[team][k];
        }
        out8[team] = r;
        out8[2 + team] = a;
        out8[4 + team] = tv;
        out8[6 + team] = te;
    }
    return 8;
}

// Stalling predicate at activation start (bb_can_score_without_dice), used to
// name the crowd roll on the End Turn confirmation.
int bbp_can_score_without_dice(bbp_session* s, int carrier) {
    if (carrier < 0 || carrier >= BB_NUM_PLAYERS) return 0;
    return bb_can_score_without_dice(&s->env.match, carrier) ? 1 : 0;
}

int bbp_count_assists(bbp_session* s, int for_slot, int against_slot) {
    return bb_count_assists(&s->env.match, for_slot, against_slot);
}

int bbp_tackle_zones(bbp_session* s, int team, int x, int y) {
    return bb_tackle_zones(&s->env.match, team, x, y);
}

// ---- Names -------------------------------------------------------------------

const char* bbp_team_display(int team_id) {
    return (team_id >= 0 && team_id < BB_TEAM_COUNT) ? bb_team_defs[team_id].display
                                                     : NULL;
}

const char* bbp_team_key(int team_id) {
    return (team_id >= 0 && team_id < BB_TEAM_COUNT) ? bb_team_defs[team_id].id : NULL;
}

const char* bbp_position_display(int team_id, int position_id) {
    if (team_id < 0 || team_id >= BB_TEAM_COUNT) return NULL;
    const bb_team_def* t = &bb_team_defs[team_id];
    return (position_id >= 0 && position_id < t->num_positions)
               ? t->positions[position_id].display
               : NULL;
}

const char* bbp_skill_display(int skill_id) {
    return (skill_id >= 0 && skill_id < BB_SKILL_COUNT) ? bb_skill_defs[skill_id].display
                                                        : NULL;
}

const char* bbp_skill_key(int skill_id) {
    return (skill_id >= 0 && skill_id < BB_SKILL_COUNT) ? bb_skill_defs[skill_id].id
                                                        : NULL;
}

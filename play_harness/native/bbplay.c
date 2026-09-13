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
//     bbp_create); play_harness/tests/test_native_config.py guards drift;
//   * a submitted tuple is checked against exact joint support BEFORE c_step,
//     because c_step abort()s the process on an out-of-support tuple;
//   * c_step auto-resets the env at the terminal step, so the natural final
//     state is rebuilt by re-applying the terminal action to a pre-step copy.
#include "bloodbowl.h"

#define BBP_ABI_VERSION 3

// Return codes for bbp_step.
#define BBP_STEP_OK 0
#define BBP_STEP_TERMINAL 1
#define BBP_STEP_REJECTED -1      // tuple outside exact joint support
#define BBP_STEP_NO_DECISION -2   // env is not waiting on a decision
#define BBP_STEP_COLLISION -3     // two distinct engine actions share the tuple
#define BBP_STEP_OVER -4          // session already reached a terminal step

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

// episode: number of matches this env has already finished. The env seeds
// procgen from (seed, episode + 1), so a native vec env i with base seed B
// reproduces here as seed = B + i, episode = completed matches on that row.
bbp_session* bbp_create(uint64_t seed, int episode, int home_team, int away_team,
                        int skillup_max_players, int skillup_max_each,
                        float skillup_secondary_pct, int max_decisions) {
    bbp_session* s = (bbp_session*)calloc(1, sizeof(bbp_session));
    if (!s) return NULL;
    bbp_wire(s);
    Bloodbowl* env = &s->env;
    // Mirrors apply_kwargs (binding.c) at the bloodbowl.ini defaults for every
    // field that changes observations, legality, rosters or episode bounds.
    // Reward fields keep the objective defaults and zero shaping: rewards are
    // not observed and do not change the policy's inputs.
    env->reward_td = BBE_DEFAULT_REWARD_TD;
    env->reward_win = BBE_DEFAULT_REWARD_WIN;
    env->reward_draw = BBE_DEFAULT_REWARD_DRAW;
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

void bbp_destroy(bbp_session* s) { free(s); }

const uint8_t* bbp_obs(bbp_session* s, int agent) {
    return (agent == 0 || agent == 1) ? s->env.obs_ptr[agent] : NULL;
}

const unsigned char* bbp_mask(bbp_session* s, int agent) {
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

// Apply the deciding coach's tuple through the real c_step. Never aborts on
// bad input: the tuple is validated against exact support first.
int bbp_step(bbp_session* s, int t, int arg, int sq) {
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
    bb_match pre = env->match;
    bb_rng pre_rng = env->rng;
    int pre_decisions = env->decisions;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env->action_ptr[a][0] = (float)BB_A_NONE;
        env->action_ptr[a][1] = 32.0f;
        env->action_ptr[a][2] = 390.0f;
    }
    env->action_ptr[agent][0] = (float)t;
    env->action_ptr[agent][1] = (float)arg;
    env->action_ptr[agent][2] = (float)sq;
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
    int rc = bbp_step(c, t, arg, sq);
    int n = rc == BBP_STEP_OK ? bbp_legal(c, actions4, proj2, cap)
                              : (rc == BBP_STEP_TERMINAL ? -2 : -1);
    free(c);
    bb_stall_attach(&s->env.ep_stall);
    return n;
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

// FNV-1a over the whole match struct and the dice stream state: the
// determinism fingerprint for traces.
uint64_t bbp_state_digest(bbp_session* s) {
    uint64_t h = 1469598103934665603ull;
    const uint8_t* p = (const uint8_t*)&s->env.match;
    for (size_t i = 0; i < sizeof(bb_match); i++) {
        h ^= p[i];
        h *= 1099511628211ull;
    }
    const uint8_t* r = (const uint8_t*)&s->env.rng;
    for (size_t i = 0; i < sizeof(bb_rng); i++) {
        h ^= r[i];
        h *= 1099511628211ull;
    }
    return h;
}

// Scripted drivers. Both return an index into bbp_legal, or -1.
int bbp_contact_bot_index(bbp_session* s) {
    Bloodbowl* env = &s->env;
    if (env->match.status != BB_STATUS_DECISION || env->n_legal <= 0) return -1;
    bb_action a = bbe_contact_bot_pick(&env->match, env->legal, env->n_legal);
    for (int i = 0; i < env->n_legal; i++) {
        if (bb_action_eq(env->legal[i], a)) return i;
    }
    return -1;
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

// bloodbowl.h — PufferLib 4.0 native env wrapping the BB2025 engine.
//
// Two agents per match (home/away coach). Each c_step applies the DECIDING
// agent's action (the other agent's action is ignored that step), advances the
// engine to the next decision, and emits observations + per-head legality
// masks. Episodes are full matches over procedurally generated rosters.
//
// Observation (uint8, BBE_OBS_SIZE = 832B), egocentric: each agent sees its
// own players first and the pitch x-mirrored for the away coach, so
// "forward" is always +x. Layout (offsets from the BBE_* macros below):
//   [0..767]   32 players x BBE_PLAYER_BYTES (24): rows 0-15 = my team,
//              16-31 = opponent (row = slot, XOR 16 for the away agent):
//                [0]  x+1, [1] y+1 (0 = off pitch; x mirrored for away)
//                [2]  location (bb_loc), [3] stance (bb_stance)
//                [4]  flags low byte, [5] flags high byte (BB_PF_*)
//                [6..10]  ma, st, ag, pa, av
//                [11..22] skill ids x BBE_SKILL_SLOTS (12) (id+1, 0 = none)
//                [23] pad
//   [768..783] ball + decision context (BBE_CTX_OFF):
//                [0]  ball state (bb_ball_state)
//                [1]  ball x+1, [2] ball y+1 (0 = off pitch)
//                [3]  carrier row+1 (0 = none)
//                [4]  top-frame proc (bb_proc), [5] its phase
//                [6]  frame a as row+1 when the proc stores a player slot
//                     there (bbe_frame_a_is_slot), else 0
//                [7]  frame b likewise (bbe_frame_b_is_slot)
//                [8..9] spare
//                [10] I am the deciding coach, [11] my team is active
//                [12..15] spare
//   [784..831] scalars (BBE_SCALAR_OFF):
//                [0]  half, [1] my turn, [2] opp turn
//                [3]  my score, [4] opp score
//                [5]  my rerolls, [6] opp rerolls, [7] weather
//                [8..13] blitz/pass/handoff/foul/ttm/secure used this turn
//                [14] my apothecaries, [15] opp apothecaries
//                [16] my bribes, [17] opp bribes, [18] I am kicking
//                [19] my team id, [20] opp team id, [21..47] spare
//
// Action heads (ACT_SIZES {30, 33, 391}): bb_action type | arg (0-31 direct,
// 32 = sentinel for 0xFE/0xFF args) | square (y*26+x, 390 = none).
// Decoding snaps to the nearest legal action (exact -> same-type -> first),
// so even maskless backends (torch/MPS practice runs) stay legal.
#pragma once

#include <stdlib.h>
#include <string.h>

// --- Engine amalgamation (build.sh compiles binding.c as a single TU) -------
// `engine/` and `bb/` next to this header are symlinks in the dev tree
// (-> ../../engine/{src,include/bb}) and real copies in the installed
// vendor/PufferLib/ocean/bloodbowl/ tree (tools/install_puffer_env.sh uses
// cp -RL). Three sources define a file-local DIR8 table; rename per "TU".
#define DIR8 DIR8_match_tu
#include "engine/bb_match.c"
#include "engine/bb_rng.c"
#include "engine/bb_replay.c"
#include "engine/bb_skills.c"
#include "engine/bb_hooks.c"
#include "engine/bb_procgen.c"
#include "engine/gen_skills.c"
#include "engine/gen_teams.c"
#include "engine/gen_tables.c"
#include "engine/skills_core.c"
#include "engine/skills_agility.c"
#include "engine/skills_devious_traits.c"
#include "engine/skills_mutation_passing.c"
#include "engine/proc_table.c"
#include "engine/proc_test.c"
#include "engine/proc_turn.c"
#include "engine/proc_move.c"
#include "engine/proc_block.c"
#include "engine/proc_ttm.c"
#undef DIR8
#define DIR8 DIR8_ball_tu
#include "engine/proc_ball.c"
#undef DIR8
#define DIR8 DIR8_kick_tu
#include "engine/proc_match.c"
#undef DIR8

#define BBE_PLAYER_BYTES 24    // 11 stat/state bytes + 12 skill-id slots + pad
#define BBE_SKILL_SLOTS 12     // >= max base-roster skills (10) + procgen cap
#define BBE_OBS_SIZE 832       // 32*24 players + 16 ball/ctx + 48 scalars
#define BBE_CTX_OFF (BB_NUM_PLAYERS * BBE_PLAYER_BYTES) // 768
#define BBE_SCALAR_OFF (BBE_CTX_OFF + 16)               // 784
#define BBE_HEAD_TYPE 30
#define BBE_HEAD_ARG 33
#define BBE_HEAD_SQ 391
#define BBE_MASK_SIZE (BBE_HEAD_TYPE + BBE_HEAD_ARG + BBE_HEAD_SQ)
#define BBE_AGENTS 2
#define BBE_MAX_DECISIONS 4096 // episode safety bound
#define BBE_MAX_BANKS 8        // frozen selfplay-pool banks (matches selfplay.py)

_Static_assert(BBE_HEAD_TYPE == BB_A_TYPE_COUNT,
               "action-type head out of sync with bb_actions.h");
_Static_assert(BBE_HEAD_SQ == BB_PITCH_LEN * BB_PITCH_WID + 1,
               "square head out of sync with pitch dimensions");
_Static_assert(BBE_OBS_SIZE == BBE_SCALAR_OFF + 48, "obs layout out of sync");
_Static_assert(BB_SKILL_COUNT <= 254, "skill id + 1 must fit a byte");

// Floats only; summed across envs then divided by n (vecenv.h). n must be last.
typedef struct {
    float perf;            // win = 1, draw = 0.5, loss = 0
    float score_diff;      // own TDs - opponent TDs (home-agent perspective)
    float tds;             // total touchdowns in the match
    float episode_return;
    float episode_length;
    float illegal_frac;    // sampled actions that had to be snapped to legal
    // Learner (slot 0) score vs frozen bank b on envs tagged b+1; selfplay.py
    // reads hist_score_bank_<b>/hist_n_bank_<b> to drive bank swaps.
    float hist_score_bank[BBE_MAX_BANKS];
    float hist_n_bank[BBE_MAX_BANKS];
    // Episodes ended by the defensive reset (BB_STATUS_ERROR or an empty
    // legal set at a DECISION). Should stay at 0.0 on the dashboard; anything
    // else means the engine/binding contract broke mid-training.
    float error_episodes;
    float n;
} Log;

typedef struct {
    Log log;
    // Base buffers assigned unconditionally by create_static_vec (identity
    // layout). The env body uses the per-slot pointers below instead.
    uint8_t* observations;
    float* actions;
    float* rewards;
    float* terminals;
    unsigned char* action_mask;
    // Per-agent slot pointers (filled by my_setup_perm; perm-aware).
    uint8_t* obs_ptr[BBE_AGENTS];
    unsigned char* action_mask_ptr[BBE_AGENTS];
    float* action_ptr[BBE_AGENTS];
    float* reward_ptr[BBE_AGENTS];
    float* terminal_ptr[BBE_AGENTS];
    int num_agents;
    // Selfplay pool (MY_USES_TAGS): tag 0 = pure selfplay; tag b+1 = slot 1
    // plays frozen bank b, slot 0 = learner. boundary_reached set on episode
    // end so selfplay.py can align bank swaps to game boundaries.
    int tag;
    int boundary_reached;
    // Reward shaping / episode bound ([env] kwargs in config/bloodbowl.ini).
    float reward_td;
    float reward_win;
    float reward_draw; // applied to BOTH agents on equal scores (default 0)
    // Setup shaping (default 0 = off): a voluntary legal SETUP_DONE earns
    // reward_setup_done; exhausting the placement budget so the engine
    // autofixes the formation earns reward_setup_autofix (negative). The two
    // cases are distinguishable because a forced DONE is the ONLY legal
    // action (n_legal == 1) while a voluntary one always has alternatives.
    float reward_setup_done;
    float reward_setup_autofix;
    // Ball-possession shaping (default 0 = off). Possession is judged only
    // when the ball SETTLES (held or grounded) — a ball in the air is limbo,
    // so a completed pass is neutral instead of loss-then-gain. Keep
    // |reward_ball_loss| > reward_ball_gain or pickup/drop cycles farm reward.
    float reward_ball_gain;
    float reward_ball_loss;
    // Injury shaping (default 0 = off): per opponent removed to KO/CAS.
    float reward_injury_inflicted;
    float reward_injury_taken;
    int max_decisions;
    // Spectator rendering (bbe_render.h); NULL until c_render is first called.
    int render_fps;
    void* client;

    bb_match match;
    bb_rng rng;     // in-match dice
    bb_rng procgen; // roster generation stream
    uint64_t seed;
    uint32_t episode;
    int decisions;
    int illegal;
    float ep_return[BBE_AGENTS];
    bb_action legal[BB_LEGAL_MAX];
    int n_legal;
    int score_prev[2];
    int possessor;   // last settled possession: -1 none, else team; IN_AIR = limbo
    int out_prev[2]; // players in the KO + casualty boxes (injury shaping)
} Bloodbowl;

static void bbe_refresh_legal(Bloodbowl* env) {
    env->n_legal = env->match.status == BB_STATUS_DECISION
                       ? bb_legal_actions(&env->match, env->legal)
                       : 0;
}

// --- Observation encoding ------------------------------------------------------
// Egocentric player index: my players are 0..15, opponents 16..31, in BOTH
// the observation rows and the player-slot action args. XOR with 16 flips
// team blocks for the away agent; identity for home.
static int bbe_ego_slot(int agent, int slot) {
    return agent == BB_AWAY ? (slot ^ BB_TEAM_SLOTS) : slot;
}

// Frame params a/b hold player slots only for SOME procs. The four
// highest-frequency decision procs store TEAM IDS in a (PREGAME: toss winner;
// SETUP/KICKOFF: kicking team; TEAM_TURN: acting team), and several store
// kinds/flags in b (MOVE: bb_act_kind; TEST: bb_test_kind; CASUALTY /
// KO_RECOVERY: apothecary-window flags). Team ids 0/1 pass a
// `< BB_NUM_PLAYERS` check, so without a whitelist they get XOR-16
// ego-remapped as if they were slots — the away agent would see "opponent
// row 17" where the home agent sees "my player 0" for the same semantic
// state, breaking the egocentric invariant on the modal decision type
// (adversarial review M14). Whitelist per proc; non-slots encode as 0.
static bool bbe_frame_a_is_slot(int proc) {
    switch (proc) {
    case BB_PROC_ACTIVATION:  // a = activating player
    case BB_PROC_MOVE:        // a = mover
    case BB_PROC_TEST:        // a = tested player
    case BB_PROC_BLOCK:       // a = attacker
    case BB_PROC_PUSH:        // a = pusher (direction origin)
    case BB_PROC_CASUALTY:    // a = victim
    case BB_PROC_FOUL:        // a = fouler
    case BB_PROC_KO_RECOVERY: // a = KO-patch candidate
    case BB_PROC_PASS:        // a = thrower (interception window)
        return true;
    default:
        return false;
    }
}

static bool bbe_frame_b_is_slot(int proc) {
    switch (proc) {
    case BB_PROC_BLOCK: // b = defender
    case BB_PROC_PUSH:  // b = pushee
    case BB_PROC_FOUL:  // b = victim
        return true;
    default:
        return false;
    }
}

static void bbe_encode_obs(Bloodbowl* env, int agent) {
    unsigned char* o = env->obs_ptr[agent];
    memset(o, 0, BBE_OBS_SIZE);
    bb_match* m = &env->match;
    int me = agent; // agent 0 = home coach, 1 = away

    for (int i = 0; i < BB_NUM_PLAYERS; i++) {
        // Egocentric ordering: my players first (row = bbe_ego_slot(slot)).
        int team = i < BB_TEAM_SLOTS ? me : 1 - me;
        int slot = team * BB_TEAM_SLOTS + (i & 15);
        const bb_player* p = &m->players[slot];
        unsigned char* t = o + i * BBE_PLAYER_BYTES;
        if (p->location == BB_LOC_ON_PITCH) {
            // Mirror x for the away coach so "forward" is always +x.
            int px = me == BB_HOME ? p->x : (BB_PITCH_LEN - 1 - p->x);
            t[0] = (unsigned char)(px + 1);
            t[1] = (unsigned char)(p->y + 1);
        }
        t[2] = p->location;
        t[3] = p->stance;
        t[4] = (unsigned char)(p->flags & 0xFF);
        t[5] = (unsigned char)(p->flags >> 8);
        t[6] = (unsigned char)p->ma;
        t[7] = (unsigned char)p->st;
        t[8] = (unsigned char)p->ag;
        t[9] = (unsigned char)p->pa;
        t[10] = (unsigned char)p->av;
        // Skill ids (+1, 0 = none). BBE_SKILL_SLOTS covers the largest base
        // roster list (10) plus the procgen advancement cap (bb_procgen.c
        // stops adding at 12 total) — no silent truncation.
        int k = 11;
        for (int sk = bb_next_skill(&p->skills, 0);
             sk >= 0 && k < 11 + BBE_SKILL_SLOTS;
             sk = bb_next_skill(&p->skills, sk + 1)) {
            t[k++] = (unsigned char)(sk + 1);
        }
    }

    unsigned char* b = o + BBE_CTX_OFF;
    b[0] = m->ball.state;
    if (m->ball.state != BB_BALL_OFF_PITCH) {
        int bx = me == BB_HOME ? m->ball.x : (BB_PITCH_LEN - 1 - m->ball.x);
        b[1] = (unsigned char)(bx + 1);
        b[2] = (unsigned char)(m->ball.y + 1);
    }
    if (m->ball.carrier != BB_NO_PLAYER) {
        b[3] = (unsigned char)(1 + bbe_ego_slot(me, m->ball.carrier));
    }
    const bb_frame* top = m->stack_top ? &m->stack[m->stack_top - 1] : 0;
    if (top) {
        b[4] = top->proc;
        b[5] = top->phase;
        // Frame a/b are player slots only for whitelisted procs (see
        // bbe_frame_*_is_slot); remap those egocentrically (+1, 0 =
        // none/not-a-slot). Frame x/y are NOT exposed: their semantics vary
        // per proc (squares, latch bits, skill payloads), so away-mirroring
        // can't be applied consistently — the legal-action mask carries the
        // spatial decision context instead.
        b[6] = (bbe_frame_a_is_slot(top->proc) && top->a < BB_NUM_PLAYERS)
                   ? (unsigned char)(1 + bbe_ego_slot(me, top->a))
                   : 0;
        b[7] = (bbe_frame_b_is_slot(top->proc) && top->b < BB_NUM_PLAYERS)
                   ? (unsigned char)(1 + bbe_ego_slot(me, top->b))
                   : 0;
    }
    b[10] = (unsigned char)(m->decision_team == me);
    b[11] = (unsigned char)(m->active_team == me);

    unsigned char* s = o + BBE_SCALAR_OFF;
    s[0] = m->half;
    s[1] = m->turn[me];
    s[2] = m->turn[1 - me];
    s[3] = m->score[me];
    s[4] = m->score[1 - me];
    s[5] = m->rerolls[me];
    s[6] = m->rerolls[1 - me];
    s[7] = m->weather;
    s[8] = m->blitz_used;
    s[9] = m->pass_used;
    s[10] = m->handoff_used;
    s[11] = m->foul_used;
    s[12] = m->ttm_used;
    s[13] = m->secure_used;
    s[14] = m->apothecary[me];
    s[15] = m->apothecary[1 - me];
    s[16] = m->bribes[me];
    s[17] = m->bribes[1 - me];
    s[18] = (unsigned char)(m->kicking_team == me);
    s[19] = m->team_id[me];
    s[20] = m->team_id[1 - me];
}

// --- Action encode/decode --------------------------------------------------------
// Per-type action contract (mirrors the comments in bb_actions.h). x,y is a
// pitch square ONLY for these types — for everything else x carries payloads
// (skill ids for USE_REROLL) or nothing, and must never reach the square head.
static bool bbe_type_spatial(int type) {
    switch (type) {
    case BB_A_SETUP_PLACE:
    case BB_A_KICK_TARGET:
    case BB_A_STEP:
    case BB_A_JUMP:
    case BB_A_BLOCK_TARGET:
    case BB_A_PASS_TARGET:
    case BB_A_HANDOFF_TARGET:
    case BB_A_FOUL_TARGET:
    case BB_A_TTM_TARGET:
    case BB_A_PUSH_SQUARE:
    case BB_A_SPECIAL_TARGET:
        return true;
    default:
        return false;
    }
}

// arg is a player slot for these types (egocentric remap applies).
static bool bbe_arg_is_slot(int type) {
    switch (type) {
    case BB_A_SETUP_PLACE:
    case BB_A_SETUP_REMOVE:
    case BB_A_TOUCHBACK:
    case BB_A_ACTIVATE:
        return true;
    default:
        return false;
    }
}

static int bbe_sq_index(int agent, int x, int y) {
    int px = agent == BB_HOME ? x : (BB_PITCH_LEN - 1 - x);
    return y * BB_PITCH_LEN + px;
}

// Head-space square index for a legal action: real square (incl. (0,0)) for
// spatial types, the 390 "none" sentinel otherwise.
static int bbe_action_sq(int agent, bb_action a) {
    return bbe_type_spatial(a.type) ? bbe_sq_index(agent, a.x, a.y) : 390;
}

// Head-space arg index for a legal action: player slots remapped to the
// agent's egocentric view (matching obs rows); 0xFE/0xFF markers and args
// beyond the direct range collapse into sentinel 32.
static int bbe_action_arg(int agent, bb_action a) {
    int arg = a.arg;
    if (bbe_arg_is_slot(a.type) && arg < BB_NUM_PLAYERS) {
        arg = bbe_ego_slot(agent, arg);
    }
    if (arg == 0xFE || arg == 0xFF) return 32;
    return arg < 32 ? arg : 32;
}

static void bbe_fill_mask(Bloodbowl* env, int agent) {
    unsigned char* mask = env->action_mask_ptr[agent];
    memset(mask, 0, BBE_MASK_SIZE);
    if (env->match.status != BB_STATUS_DECISION ||
        env->match.decision_team != agent || env->n_legal <= 0) {
        // Waiting agent (or defensive: no legal actions): only the null
        // action — an all-zero mask row would NaN the masked sampler.
        mask[BB_A_NONE] = 1;
        mask[BBE_HEAD_TYPE + 32] = 1;            // arg sentinel
        mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390] = 1; // square none
        return;
    }
    for (int i = 0; i < env->n_legal; i++) {
        bb_action a = env->legal[i];
        mask[a.type] = 1;
        mask[BBE_HEAD_TYPE + bbe_action_arg(agent, a)] = 1;
        mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + bbe_action_sq(agent, a)] = 1;
    }
}

static bb_action bbe_decode(Bloodbowl* env, int agent, const float* heads) {
    int t = (int)heads[0];
    int arg = (int)heads[1];
    int sq = (int)heads[2];
    // Pass 1: exact match in head space (type + arg-class + square).
    for (int i = 0; i < env->n_legal; i++) {
        bb_action a = env->legal[i];
        if (a.type != t) continue;
        if (bbe_action_arg(agent, a) != arg) continue;
        if (bbe_action_sq(agent, a) != sq) continue;
        return a;
    }
    env->illegal++;
    // Pass 2: same type, matching square.
    for (int i = 0; i < env->n_legal; i++) {
        bb_action a = env->legal[i];
        if (a.type == t && bbe_action_sq(agent, a) == sq) return a;
    }
    for (int i = 0; i < env->n_legal; i++) {
        if (env->legal[i].type == t) return env->legal[i];
    }
    // Pass 3: anything legal.
    return env->legal[0];
}

// --- Lifecycle -------------------------------------------------------------------
static void bbe_emit_all(Bloodbowl* env) {
    for (int a = 0; a < BBE_AGENTS; a++) {
        bbe_encode_obs(env, a);
        bbe_fill_mask(env, a);
    }
}

static void bbe_reset_match(Bloodbowl* env) {
    env->episode++;
    bb_rng_seed(&env->procgen, env->seed * 2654435761u + env->episode, 11);
    bb_match_init_random(&env->match, &env->procgen);
    bb_rng_seed(&env->rng, env->seed + env->episode * 7919u, 1);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->decisions = 0;
    env->illegal = 0;
    env->ep_return[0] = env->ep_return[1] = 0;
    env->score_prev[0] = env->score_prev[1] = 0;
    env->possessor = -1;
    // Procgen can pre-injure players into the CAS box; baseline the counts.
    for (int t = 0; t < 2; t++) {
        int out = 0;
        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
            int loc = env->match.players[s].location;
            out += (loc == BB_LOC_KO || loc == BB_LOC_CAS);
        }
        env->out_prev[t] = out;
    }
}

static void c_reset(Bloodbowl* env) {
    // Defaults for callers that skip apply_kwargs (standalone driver, tests).
    if (env->max_decisions <= 0) env->max_decisions = BBE_MAX_DECISIONS;
    if (env->reward_td == 0.0f && env->reward_win == 0.0f) {
        env->reward_td = 1.0f;
        env->reward_win = 3.0f;
    }
    bbe_reset_match(env);
    bbe_emit_all(env);
}

static void bbe_finish_episode(Bloodbowl* env) {
    bb_match* m = &env->match;
#ifdef BBE_DEBUG_EPISODES
    printf("episode end: status=%d half=%d turns=%d/%d score=%d-%d decisions=%d\n",
           m->status, m->half, m->turn[0], m->turn[1], m->score[0], m->score[1],
           env->decisions);
#endif
    float result = m->score[0] > m->score[1] ? 1.0f
                   : (m->score[0] < m->score[1] ? 0.0f : 0.5f);
    // Win bonus from each agent's perspective.
    float bonus[2] = {0, 0};
    if (m->score[0] != m->score[1]) {
        int w = m->score[0] > m->score[1] ? 0 : 1;
        bonus[w] = env->reward_win;
        bonus[1 - w] = -env->reward_win;
    } else {
        // Slightly-negative draws (both sides) make mutual stalling a
        // non-equilibrium while leaving draw >> loss, so securing a draw
        // when behind stays correct play. Win > Draw >> Loss.
        bonus[0] = bonus[1] = env->reward_draw;
    }
    for (int a = 0; a < BBE_AGENTS; a++) {
        env->reward_ptr[a][0] += bonus[a];
        env->ep_return[a] += bonus[a];
        env->terminal_ptr[a][0] = 1.0f;
    }
    env->log.perf += result;
    env->log.score_diff += (float)(m->score[0] - m->score[1]);
    env->log.tds += (float)(m->score[0] + m->score[1]);
    env->log.episode_return += env->ep_return[0];
    env->log.episode_length += (float)env->decisions;
    env->log.illegal_frac += env->decisions
                                 ? (float)env->illegal / (float)env->decisions
                                 : 0;
    // Selfplay pool bookkeeping: on tagged envs slot 0 is the learner playing
    // frozen bank tag-1; result is already slot-0 perspective.
    if (env->tag > 0 && env->tag <= BBE_MAX_BANKS) {
        env->log.hist_score_bank[env->tag - 1] += result;
        env->log.hist_n_bank[env->tag - 1] += 1;
    }
    env->boundary_reached = 1;
    env->log.n += 1;
    bbe_reset_match(env);
}

static void c_step(Bloodbowl* env) {
    for (int a = 0; a < BBE_AGENTS; a++) {
        env->reward_ptr[a][0] = 0.0f;
        env->terminal_ptr[a][0] = 0.0f;
    }
    bb_match* m = &env->match;
    if (m->status == BB_STATUS_DECISION && env->n_legal > 0) {
        int agent = m->decision_team;
        bb_action act = bbe_decode(env, agent, env->action_ptr[agent]);
        // Setup shaping: forced DONE (budget exhausted -> sole legal action)
        // vs voluntary legal DONE. Must inspect n_legal BEFORE bb_apply.
        if (act.type == BB_A_SETUP_DONE) {
            float r = env->n_legal == 1 ? env->reward_setup_autofix
                                        : env->reward_setup_done;
            if (r != 0.0f) {
                env->reward_ptr[agent][0] += r;
                env->ep_return[agent] += r;
            }
        }
        bb_apply(m, act, &env->rng);
        env->decisions++;
        // Touchdown rewards.
        bool scored = false;
        for (int t = 0; t < 2; t++) {
            int d = m->score[t] - env->score_prev[t];
            if (d > 0) {
                scored = true;
                env->reward_ptr[t][0] += env->reward_td * (float)d;
                env->reward_ptr[1 - t][0] -= env->reward_td * (float)d;
                env->ep_return[t] += env->reward_td * (float)d;
                env->ep_return[1 - t] -= env->reward_td * (float)d;
                env->score_prev[t] = m->score[t];
            }
        }
        // Ball-possession shaping on SETTLED transitions only. Scoring or a
        // drive reset clears possession without penalty — losing the ball to
        // a touchdown or the half-time whistle isn't a fumble.
        if (env->reward_ball_gain != 0.0f || env->reward_ball_loss != 0.0f) {
            if (scored) {
                env->possessor = -1;
            } else if (m->ball.state == BB_BALL_HELD) {
                int cur = BB_TEAM_OF(m->ball.carrier);
                if (cur != env->possessor) {
                    if (env->possessor >= 0) {
                        env->reward_ptr[env->possessor][0] += env->reward_ball_loss;
                        env->ep_return[env->possessor] += env->reward_ball_loss;
                    }
                    env->reward_ptr[cur][0] += env->reward_ball_gain;
                    env->ep_return[cur] += env->reward_ball_gain;
                    env->possessor = cur;
                }
            } else if (m->ball.state == BB_BALL_ON_GROUND && env->possessor >= 0) {
                env->reward_ptr[env->possessor][0] += env->reward_ball_loss;
                env->ep_return[env->possessor] += env->reward_ball_loss;
                env->possessor = -1;
            } else if (m->ball.state == BB_BALL_OFF_PITCH && env->possessor >= 0) {
                // Drive reset (setup/kickoff on the stack) clears silently; a
                // crowd-surfed carrier's ball stays in limbo until the
                // throw-in settles, which then emits the loss above.
                for (int i = 0; i < m->stack_top; i++) {
                    if (m->stack[i].proc == BB_PROC_SETUP ||
                        m->stack[i].proc == BB_PROC_KICKOFF) {
                        env->possessor = -1;
                        break;
                    }
                }
            }
            // BB_BALL_IN_AIR: limbo — judged when it settles.
        }
        // Injury shaping: a player leaving the pitch to the KO or casualty
        // box punishes his coach and rewards the opponent (crowd-shoves and
        // failed-dodge self-injuries included — your attrition is always
        // your opponent's gain in Blood Bowl).
        if (env->reward_injury_inflicted != 0.0f || env->reward_injury_taken != 0.0f) {
            for (int t = 0; t < 2; t++) {
                int out = 0;
                for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
                    int loc = m->players[s].location;
                    out += (loc == BB_LOC_KO || loc == BB_LOC_CAS);
                }
                int d = out - env->out_prev[t];
                if (d > 0) {
                    env->reward_ptr[t][0] += env->reward_injury_taken * (float)d;
                    env->ep_return[t] += env->reward_injury_taken * (float)d;
                    env->reward_ptr[1 - t][0] += env->reward_injury_inflicted * (float)d;
                    env->ep_return[1 - t] += env->reward_injury_inflicted * (float)d;
                }
                env->out_prev[t] = out;
            }
        }
    }
    if (m->status == BB_STATUS_ERROR ||
        (m->status == BB_STATUS_DECISION && env->n_legal <= 0)) {
        // Both should be unreachable (decode snaps to legal; every decision
        // window offers at least one action). The second guard matters: a
        // DECISION whose legal set came back empty would otherwise livelock
        // the env forever — the mask path emits a defensive null action, but
        // the step path would never apply anything and never terminate.
        env->log.error_episodes += 1;
        bbe_finish_episode(env);
    } else if (m->status == BB_STATUS_MATCH_OVER ||
               env->decisions >= env->max_decisions) {
        bbe_finish_episode(env);
    }
    bbe_refresh_legal(env);
    bbe_emit_all(env);
}

// Spectator rendering (raylib). Included here, after the Bloodbowl struct, so
// the client can draw straight from env state. Training never calls c_render;
// builds without raylib on the include path (fuzzing, quick local compiles)
// degrade to a no-op renderer.
#if defined(__has_include)
#if __has_include("raylib.h")
#define BBE_HAVE_RAYLIB 1
#endif
#endif

#ifdef BBE_HAVE_RAYLIB
#include "bbe_render.h"
#endif

static void c_render(Bloodbowl* env) {
#ifdef BBE_HAVE_RAYLIB
    bbe_render_draw(env);
#else
    (void)env;
#endif
}

static void c_close(Bloodbowl* env) {
    (void)env; // no heap allocations beyond the struct itself
}

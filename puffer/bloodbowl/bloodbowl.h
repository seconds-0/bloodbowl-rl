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
//                [23] opposing tackle zones marking the player's square
//                     (on-pitch only, else 0)
//   [768..783] ball + decision context (BBE_CTX_OFF):
//                [0]  ball state (bb_ball_state)
//                [1]  ball x+1, [2] ball y+1 (0 = off pitch)
//                [3]  carrier row+1 (0 = none)
//                [4]  top-frame proc (bb_proc), [5] its phase
//                [6]  frame a as row+1 when the proc stores a player slot
//                     there (bbe_frame_a_is_slot), else 0
//                [7]  frame b likewise (bbe_frame_b_is_slot)
//                [8]  pending TEST target number (2..6 when the top frame
//                     is a TEST reroll window, else 0)
//                [9]  spare
//                [10] I am the deciding coach, [11] my team is active
//                [12..15] spare
//   [784..831] scalars (BBE_SCALAR_OFF):
//                [0]  half, [1] my turn, [2] opp turn
//                [3]  my score, [4] opp score
//                [5]  my rerolls, [6] opp rerolls, [7] weather
//                [8..13] blitz/pass/handoff/foul/ttm/secure used this turn
//                [14] my apothecaries, [15] opp apothecaries
//                [16] my bribes, [17] opp bribes, [18] I am kicking
//                [19..47] spare (team ids deliberately NOT observed — see
//                         the encoder comment; forces roster-reading)
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

#define BBE_PLAYER_BYTES 24    // 11 stat/state bytes + 12 skill-id slots + TZ byte
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

// Engine-compat stamp for demo-state bank files (.bbs "BBS1": written by
// tools/bb_lockstep.c --dump-states, consumed by the env's demo-state reset
// curriculum). Any bb_match layout change (sizeof) or content-table resize
// (teams, skills, action types) invalidates banked raw-struct snapshots.
// Same-architecture only — the blob is a host-ABI memcpy, not a portable
// serialization; this stamp plus the header's match_size are the guards.
static inline uint32_t bbe_state_fingerprint(void) {
    return (uint32_t)sizeof(bb_match) * 2654435761u
         ^ ((uint32_t)BB_TEAM_COUNT << 20)
         ^ ((uint32_t)BB_SKILL_COUNT << 10)
         ^ (uint32_t)BB_A_TYPE_COUNT;
}

// Floats only; summed across envs then divided by n (vecenv.h). n must be last.
typedef struct {
    float perf;            // win = 1, draw = 0.5, loss = 0
    float score_diff;      // own TDs - opponent TDs (home-agent perspective)
    float tds;             // total touchdowns in the match
    float episode_return;
    float episode_length;
    float illegal_frac;    // sampled actions that had to be snapped to legal
    // Behavioral micro-stats, summed per episode (dashboard shows per-episode
    // means after the /n aggregation). Motivated by a spectator finding:
    // policies never declared blocks and walked out of tackle zones
    // obliviously — these make that visible on the dashboard instead of
    // requiring a spectator session. Counting details: bbe_count_action /
    // bbe_count_knockdowns.
    float blocks;               // BB_A_DECLARE of BB_ACT_BLOCK
    float blitzes;              // BB_A_DECLARE of BB_ACT_BLITZ
    float dodge_attempts;       // STEPs out of >=1 opposing TZ (dodge test due)
    float gfi_attempts;         // STEPs beyond MA (rush/GFI test due)
    float pickup_attempts;      // STEPs onto the loose ball's square
    float pass_attempts;        // BB_A_PASS_TARGET actions
    float knockdowns_inflicted; // actor's opponents downed during his window
    float knockdowns_own;       // actor's own players downed (failed dodges...)
    // Learner (slot 0) score vs frozen bank b on envs tagged b+1; selfplay.py
    // reads hist_score_bank_<b>/hist_n_bank_<b> to drive bank swaps.
    float hist_score_bank[BBE_MAX_BANKS];
    float hist_n_bank[BBE_MAX_BANKS];
    // Per-slot results + draw rate: read by puffer match (pufferl.py match()
    // consumes env/slot_0_score, env/slot_1_score, env/draw_rate).
    float slot_0_score;
    float slot_1_score;
    float draw_rate;
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
    // Bootstrap curriculum potentials (default 0 = off). Potential-BASED
    // (reward = delta-potential, telescoping -> un-farmable): while the ball
    // is loose, each side's potential is -k_fetch * dist(nearest standing
    // teammate, ball); while carrying, -k_advance * dist(carrier, opposing
    // end zone). A ladder OUT of the mutual-avoidance basin (both 10B
    // from-scratch arms converged to 0-0 draws) — anneal to 0 via chained
    // runs once tds/match wakes up; NOT a permanent reward (see
    // docs/reward-audit-decision-time.md doctrine vs scaffolding).
    float reward_dist_ball;
    float reward_dist_endzone;
    // Injury shaping (default 0 = off): per opponent removed to KO/CAS.
    float reward_injury_inflicted;
    float reward_injury_taken;
    // Scale injury rewards by victim gold cost / 100k (price-weighted
    // attrition: a 125k Mummy pays ~3x a 40k Skeleton). 0 = flat.
    int reward_injury_value_scaled;
    // Surf shaping (default 0 = off): per player crowd-pushed off the pitch,
    // charged at the (deterministic) push event regardless of injury dice.
    float reward_surf_taken;
    float reward_surf_inflicted;
    // Procgen controls: held-out-team experiments and fixed-matchup eval.
    // -1 = unconstrained.
    int exclude_team;
    int force_home_team;
    int force_away_team;
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
    // Behavioral micro-stat counters for the CURRENT episode (summed into
    // the Log by bbe_finish_episode, zeroed by bbe_reset_match).
    int ep_blocks, ep_blitzes;
    int ep_dodge_attempts, ep_gfi_attempts;
    int ep_pickup_attempts, ep_pass_attempts;
    int ep_knockdowns_inflicted, ep_knockdowns_own;
    float ep_return[BBE_AGENTS];
    bb_action legal[BB_LEGAL_MAX];
    int n_legal;
    int score_prev[2];
    int possessor;   // last settled possession: -1 none, else team; IN_AIR = limbo
    // Bootstrap potentials, per channel: deltas emitted only WITHIN a regime
    // (ball stays loose / same team keeps carrying); regime transitions emit
    // nothing — pickup itself is priced by reward_ball_gain. -1 = inactive.
    float pot_fetch_prev[2];
    float pot_carry_prev[2];
    int out_prev[2]; // players in the KO + casualty boxes (injury shaping)
    int surf_prev[2]; // m->surfs snapshot (surf shaping)
    uint32_t out_mask_prev[2]; // per-player out bits (value-scaled injuries)
    // Obs-encode caches (perf; ~23% of step time was encode). skill_rows are
    // the 12 obs skill-id bytes per slot — a pure function of the player's
    // skillset, which the engine only writes at init/procgen. Rebuilt lazily
    // whenever skill_keys[slot] != players[slot].skills (a 24-byte compare),
    // so future mid-match skill mutation stays correct by construction.
    // Zero-init is consistent: zero key + zero row == skill-less player.
    // tz_scratch is the per-step marking-TZ byte per slot — identical for
    // both agent views, so bbe_emit_all computes it once instead of twice.
    bb_skillset skill_keys[BB_NUM_PLAYERS];
    uint8_t skill_rows[BB_NUM_PLAYERS][BBE_SKILL_SLOTS];
    uint8_t tz_scratch[BB_NUM_PLAYERS]; // valid only within bbe_emit_all's step
    // Head-space projection of legal[] for the DECIDING agent, written by
    // bbe_fill_mask (which had to compute it anyway) and reused by
    // bbe_decode, which previously re-derived arg/sq per scanned action over
    // up to three fallback passes (review LOW: decode 3-pass fold).
    uint16_t legal_sq[BB_LEGAL_MAX];
    uint8_t legal_arg[BB_LEGAL_MAX];
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
            // [23] opposing tackle zones marking this player's square —
            // dodge/pickup/catch difficulty and Marked/Open status without
            // the policy re-deriving adjacency from 31 other rows. The count
            // is view-independent; bbe_emit_all computed it once this step.
            t[23] = env->tz_scratch[slot];
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
        // stops adding at 12 total) — no silent truncation. Rows are cached
        // per slot (the bb_next_skill walk was ~300 bit-scans/step) behind a
        // skillset dirty-check, so a hypothetical mid-match skill change
        // still re-encodes.
        if (memcmp(&env->skill_keys[slot], &p->skills, sizeof(bb_skillset)) != 0) {
            env->skill_keys[slot] = p->skills;
            uint8_t* row = env->skill_rows[slot];
            memset(row, 0, BBE_SKILL_SLOTS);
            int k = 0;
            for (int sk = bb_next_skill(&p->skills, 0);
                 sk >= 0 && k < BBE_SKILL_SLOTS;
                 sk = bb_next_skill(&p->skills, sk + 1)) {
                row[k++] = (unsigned char)(sk + 1);
            }
        }
        memcpy(t + 11, env->skill_rows[slot], BBE_SKILL_SLOTS);
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
        // [8] pending TEST target: at a TEST reroll window, the needed roll
        // (2..6, modifiers already applied — proc_test.c keeps it in frame
        // x), else 0. Lets the policy price a reroll directly instead of
        // re-deriving stats/modifiers from the board rows.
        b[8] = top->proc == BB_PROC_TEST ? top->x : 0;
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
    // s[19]/s[20] intentionally unused: team ids are NOT observed. Identity
    // is fully derivable from the visible per-player stats/skills, and hiding
    // the id forces the policy to read rosters — the structural guarantee
    // behind the held-out / homebrew team generalization tests.
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
        int ha = bbe_action_arg(agent, a);
        int hs = bbe_action_sq(agent, a);
        // Cache the head projection for bbe_decode (same agent, same list).
        env->legal_arg[i] = (unsigned char)ha;
        env->legal_sq[i] = (uint16_t)hs;
        mask[a.type] = 1;
        mask[BBE_HEAD_TYPE + ha] = 1;
        mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + hs] = 1;
    }
}

// Snap the sampled heads onto a legal action. Uses the head projections
// bbe_fill_mask cached for the deciding agent on this exact legal list; one
// scan replaces the old three recompute passes with identical selection:
// first exact (type, arg, sq) match, else first same-type same-square, else
// first same-type, else legal[0]. Only the exact tier is non-illegal.
static bb_action bbe_decode(Bloodbowl* env, int agent, const float* heads) {
    (void)agent; // projections were cached for the deciding agent
    int t = (int)heads[0];
    int arg = (int)heads[1];
    int sq = (int)heads[2];
    int same_type_sq = -1, same_type = -1;
    for (int i = 0; i < env->n_legal; i++) {
        if (env->legal[i].type != t) continue;
        if (env->legal_sq[i] == sq) {
            if (env->legal_arg[i] == arg) return env->legal[i]; // exact
            if (same_type_sq < 0) same_type_sq = i;
        }
        if (same_type < 0) same_type = i;
    }
    env->illegal++;
    if (same_type_sq >= 0) return env->legal[same_type_sq];
    if (same_type >= 0) return env->legal[same_type];
    return env->legal[0];
}

// --- Lifecycle -------------------------------------------------------------------
static void bbe_emit_all(Bloodbowl* env) {
    // Marking-TZ bytes are view-independent; compute once for both encodes.
    const bb_match* m = &env->match;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        env->tz_scratch[s] =
            p->location == BB_LOC_ON_PITCH
                ? (uint8_t)bb_tackle_zones(m, BB_TEAM_OF(s), p->x, p->y)
                : 0;
    }
    for (int a = 0; a < BBE_AGENTS; a++) {
        bbe_encode_obs(env, a);
        bbe_fill_mask(env, a);
    }
}

static void bbe_reset_match(Bloodbowl* env) {
    env->episode++;
    bb_rng_seed(&env->procgen, env->seed * 2654435761u + env->episode, 11);
    // Procgen controls: exclude_team bars a team from training draws
    // (holdout); force_* pins a side for fixed-matchup eval.
    if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
        env->force_away_team >= 0) {
        bb_match_init_forced(&env->match, &env->procgen, env->force_home_team,
                             env->force_away_team, env->exclude_team);
    } else {
        bb_match_init_random(&env->match, &env->procgen);
    }
    bb_rng_seed(&env->rng, env->seed + env->episode * 7919u, 1);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->decisions = 0;
    env->illegal = 0;
    env->ep_blocks = env->ep_blitzes = 0;
    env->ep_dodge_attempts = env->ep_gfi_attempts = 0;
    env->ep_pickup_attempts = env->ep_pass_attempts = 0;
    env->ep_knockdowns_inflicted = env->ep_knockdowns_own = 0;
    env->ep_return[0] = env->ep_return[1] = 0;
    env->score_prev[0] = env->score_prev[1] = 0;
    env->possessor = -1;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = -1.0f;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = -1.0f;
    // Procgen can pre-injure players into the CAS box; baseline the counts.
    for (int t = 0; t < 2; t++) {
        int out = 0;
        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
            int loc = env->match.players[s].location;
            out += (loc == BB_LOC_KO || loc == BB_LOC_CAS);
        }
        env->out_prev[t] = out;
        env->surf_prev[t] = env->match.surfs[t];
        uint32_t mask = 0;
        for (int sl = t * BB_TEAM_SLOTS; sl < (t + 1) * BB_TEAM_SLOTS; sl++) {
            int loc = env->match.players[sl].location;
            if (loc == BB_LOC_KO || loc == BB_LOC_CAS) mask |= 1u << sl;
        }
        env->out_mask_prev[t] = mask;
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
    env->log.slot_0_score += result;
    env->log.slot_1_score += 1.0f - result;
    env->log.draw_rate += (m->score[0] == m->score[1]) ? 1.0f : 0.0f;
    env->log.score_diff += (float)(m->score[0] - m->score[1]);
    env->log.tds += (float)(m->score[0] + m->score[1]);
    env->log.episode_return += env->ep_return[0];
    env->log.episode_length += (float)env->decisions;
    env->log.illegal_frac += env->decisions
                                 ? (float)env->illegal / (float)env->decisions
                                 : 0;
    env->log.blocks += (float)env->ep_blocks;
    env->log.blitzes += (float)env->ep_blitzes;
    env->log.dodge_attempts += (float)env->ep_dodge_attempts;
    env->log.gfi_attempts += (float)env->ep_gfi_attempts;
    env->log.pickup_attempts += (float)env->ep_pickup_attempts;
    env->log.pass_attempts += (float)env->ep_pass_attempts;
    env->log.knockdowns_inflicted += (float)env->ep_knockdowns_inflicted;
    env->log.knockdowns_own += (float)env->ep_knockdowns_own;
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

// --- Behavioral micro-stats --------------------------------------------------
// Decision-time counting from PRE-apply state — the same quantities the
// engine derives internally when resolving the action (proc_move.c
// BB_A_STEP: rush iff moved >= ma, dodge iff the ORIGIN square is marked).
// dodge/gfi count INTENDED tests: a Tentacles hold or a failed rush can stop
// the later rolls from ever happening. That's fine — this is behavioral
// telemetry ("does the policy choose contact / risky moves at all"), not a
// dice-roll census. gfi_attempts approximates: jump rushes and the
// blitz-block rush are not counted, only over-MA STEPs.
static void bbe_count_action(Bloodbowl* env, bb_action act) {
    const bb_match* m = &env->match;
    switch (act.type) {
    case BB_A_DECLARE:
        if (act.arg == BB_ACT_BLOCK) env->ep_blocks++;
        else if (act.arg == BB_ACT_BLITZ) env->ep_blitzes++;
        break;
    case BB_A_STEP: {
        // A STEP decision always comes from a MOVE frame (a = mover).
        const bb_frame* top = m->stack_top ? &m->stack[m->stack_top - 1] : 0;
        if (top && top->proc == BB_PROC_MOVE && top->a < BB_NUM_PLAYERS) {
            const bb_player* p = &m->players[top->a];
            if (p->moved >= p->ma) env->ep_gfi_attempts++;
            if (bb_tackle_zones(m, BB_TEAM_OF(top->a), p->x, p->y) > 0) {
                env->ep_dodge_attempts++;
            }
        }
        if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == act.x &&
            m->ball.y == act.y) {
            env->ep_pickup_attempts++;
        }
        break;
    }
    case BB_A_PASS_TARGET:
        env->ep_pass_attempts++;
        break;
    default:
        break;
    }
}

// Bitmask of players standing on the pitch, one bit per slot (32 slots).
static uint32_t bbe_standing_mask(const bb_match* m) {
    uint32_t mask = 0;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STANDING) {
            mask |= 1u << s;
        }
    }
    return mask;
}

// Post-apply: every player who WAS standing on the pitch and is now prone/
// stunned — or in the KO/CAS box, since bb_remove_from_pitch resets stance
// on the way out — went down during this apply window. Attribution is by
// the coach whose action drove the window: his opponents going down are
// inflicted, his own players are own (failed dodges, skulls, both-downs).
// A crowd-surfed player counts only when injured into a box (KO/CAS);
// surfed-but-fine players return via RESERVES and are not knockdowns.
static void bbe_count_knockdowns(Bloodbowl* env, uint32_t was_standing,
                                 int actor) {
    const bb_match* m = &env->match;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        if (!(was_standing & (1u << s))) continue;
        const bb_player* p = &m->players[s];
        bool down = (p->location == BB_LOC_ON_PITCH &&
                     p->stance != BB_STANCE_STANDING) ||
                    p->location == BB_LOC_KO || p->location == BB_LOC_CAS;
        if (!down) continue;
        if (BB_TEAM_OF(s) == actor) env->ep_knockdowns_own++;
        else env->ep_knockdowns_inflicted++;
    }
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
        bbe_count_action(env, act);
        uint32_t was_standing = bbe_standing_mask(m);
        // Trusted fast path: act came from bbe_decode, which only returns
        // elements of env->legal — the legal set enumerated on THIS state by
        // bbe_refresh_legal. Membership holds by construction, so skip
        // bb_apply's internal re-enumeration + eq-scan (~22% of step time).
        // All other callers (tests, fuzz, lockstep) stay on checked bb_apply.
        bb_apply_trusted(m, act, &env->rng);
        env->decisions++;
        bbe_count_knockdowns(env, was_standing, agent);
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
        // your opponent's gain in Blood Bowl). Optionally price-weighted by
        // the victim's roster cost (a Mummy is worth ~3 Skeletons).
        if (env->reward_injury_inflicted != 0.0f || env->reward_injury_taken != 0.0f) {
            for (int t = 0; t < 2; t++) {
                int out = 0;
                uint32_t mask = 0;
                float weight = 0;
                for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
                    int loc = m->players[s].location;
                    if (loc != BB_LOC_KO && loc != BB_LOC_CAS) continue;
                    out++;
                    mask |= 1u << s;
                    if (!(env->out_mask_prev[t] & (1u << s)) &&
                        env->reward_injury_value_scaled) {
                        const bb_team_def* td = &bb_team_defs[m->team_id[t]];
                        weight += (float)td->positions[m->players[s].position_id]
                                      .cost_k / 100.0f;
                    }
                }
                int d = out - env->out_prev[t];
                if (d > 0) {
                    float w = env->reward_injury_value_scaled ? weight : (float)d;
                    env->reward_ptr[t][0] += env->reward_injury_taken * w;
                    env->ep_return[t] += env->reward_injury_taken * w;
                    env->reward_ptr[1 - t][0] += env->reward_injury_inflicted * w;
                    env->ep_return[1 - t] += env->reward_injury_inflicted * w;
                }
                env->out_prev[t] = out;
                env->out_mask_prev[t] = mask;
            }
        }
        // Bootstrap potentials: emit delta-potential per side. Skip across
        // score/drive boundaries (potential resets silently, like possession).
        if (env->reward_dist_ball != 0.0f || env->reward_dist_endzone != 0.0f) {
            for (int t = 0; t < 2; t++) {
                // Fetch channel: active only while the ball is loose.
                float pf = -1.0f;
                if (m->ball.state == BB_BALL_ON_GROUND) {
                    int best = 99;
                    for (int sl = t * BB_TEAM_SLOTS; sl < (t + 1) * BB_TEAM_SLOTS; sl++) {
                        const bb_player* p = &m->players[sl];
                        if (p->location != BB_LOC_ON_PITCH ||
                            p->stance != BB_STANCE_STANDING) continue;
                        int dx = p->x > m->ball.x ? p->x - m->ball.x : m->ball.x - p->x;
                        int dy = p->y > m->ball.y ? p->y - m->ball.y : m->ball.y - p->y;
                        int d = dx > dy ? dx : dy;
                        if (d < best) best = d;
                    }
                    if (best < 99) pf = -env->reward_dist_ball * (float)best;
                }
                if (!scored && pf > -1.0f && env->pot_fetch_prev[t] > -1.0f) {
                    float dr = pf - env->pot_fetch_prev[t];
                    env->reward_ptr[t][0] += dr;
                    env->ep_return[t] += dr;
                }
                env->pot_fetch_prev[t] = pf;
                // Carry channel: active only while this team holds the ball.
                float pc = -1.0f;
                if (m->ball.state == BB_BALL_HELD && BB_TEAM_OF(m->ball.carrier) == t) {
                    const bb_player* c = &m->players[m->ball.carrier];
                    int ez = bb_endzone_x(t);
                    int d = c->x > ez ? c->x - ez : ez - c->x;
                    pc = -env->reward_dist_endzone * (float)d;
                }
                if (!scored && pc > -1.0f && env->pot_carry_prev[t] > -1.0f) {
                    float dr = pc - env->pot_carry_prev[t];
                    env->reward_ptr[t][0] += dr;
                    env->ep_return[t] += dr;
                }
                env->pot_carry_prev[t] = pc;
            }
        }
        // Surf shaping: charged at the (deterministic) crowd-push event,
        // independent of the injury dice that follow. Zero-sum pair.
        if (env->reward_surf_taken != 0.0f || env->reward_surf_inflicted != 0.0f) {
            for (int t = 0; t < 2; t++) {
                int d = m->surfs[t] - env->surf_prev[t];
                if (d > 0) {
                    env->reward_ptr[t][0] += env->reward_surf_taken * (float)d;
                    env->ep_return[t] += env->reward_surf_taken * (float)d;
                    env->reward_ptr[1 - t][0] += env->reward_surf_inflicted * (float)d;
                    env->ep_return[1 - t] += env->reward_surf_inflicted * (float)d;
                }
                env->surf_prev[t] = m->surfs[t];
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

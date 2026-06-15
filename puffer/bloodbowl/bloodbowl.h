// bloodbowl.h — PufferLib 4.0 native env wrapping the BB2025 engine.
//
// Two agents per match (home/away coach). Each c_step applies the DECIDING
// agent's action (the other agent's action is ignored that step), advances the
// engine to the next decision, and emits observations + per-head legality
// masks. Episodes are full matches over procedurally generated rosters.
//
// Observation (uint8, BBE_OBS_SIZE = 2782B, obs v4), egocentric: each agent
// sees its own players first and the pitch x-mirrored for the away coach, so
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
//   [832..1611] tackle-zone planes (obs v3, BBE_TZ_OFF): two per-square
//              TZ-count planes of 390 bytes each (index y*26 + x, x
//              mirrored for the away agent like every spatial feature):
//                [832..1221]  TZs exerted by MY players on each square
//                [1222..1611] TZs exerted by OPPONENT players on each square
//              The opponent plane is destination danger: dodging into /
//              out of coverage was unobservable per-square before v3 (only
//              the mover's own marked count, player byte [23], was visible).
//
// Action heads (ACT_SIZES {30, 33, 391}): bb_action type | arg (0-31 direct,
// 32 = sentinel for 0xFE/0xFF args) | square (y*26+x, 390 = none).
// Decoding snaps to the nearest legal action (exact -> same-type -> first),
// so even maskless backends (torch/MPS practice runs) stay legal.
#pragma once

#include <stdlib.h>
#include <string.h>
#include <math.h>   // sqrtf — aggregate-stat-matching pseudo-reward (D114)

// --- Engine amalgamation (build.sh compiles binding.c as a single TU) -------
// `engine/` and `bb/` next to this header are symlinks in the dev tree
// (-> ../../engine/{src,include/bb}) and real copies in the installed
// vendor/PufferLib/ocean/bloodbowl/ tree (tools/install_puffer_env.sh uses
// cp -RL). Four sources define a file-local DIR8 table; rename per "TU".
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
#include "engine/bb_blockev.c"
#undef DIR8
#define DIR8 DIR8_ball_tu
#include "engine/proc_ball.c"
#undef DIR8
#define DIR8 DIR8_kick_tu
#include "engine/proc_match.c"
#undef DIR8
#define DIR8 DIR8_reachability_tu
#include "engine/bb_reachability.c"
#undef DIR8

#define BBE_PLAYER_BYTES 24    // 11 stat/state bytes + 12 skill-id slots + TZ byte
#define BBE_SKILL_SLOTS 12     // >= max base-roster skills (10) + procgen cap
#define BBE_OBS_SIZE 2782      // v3 1612 + 3*390 decision-support planes (obs v4)
#define BBE_CTX_OFF (BB_NUM_PLAYERS * BBE_PLAYER_BYTES) // 768
#define BBE_SCALAR_OFF (BBE_CTX_OFF + 16)               // 784
#define BBE_TZ_OFF (BBE_SCALAR_OFF + 48)                // 832
#define BBE_TZ_PLANE (BB_PITCH_LEN * BB_PITCH_WID)      // 390 bytes per plane
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
_Static_assert(BBE_TZ_OFF == BBE_SCALAR_OFF + 48, "obs layout out of sync");
// Obs-v4 decision-support planes (docs/obs-v4-spec.md): exact outcome
// probabilities for the pending decision's candidates — A1/A2 block
// P(def down)/P(att down) from bb_blockev's closed form, B step-success
// from the move proc's own test math. Probabilities, never values.
#define BBE_A1_OFF (BBE_TZ_OFF + 2 * BBE_TZ_PLANE)  // 1612
#define BBE_A2_OFF (BBE_A1_OFF + BBE_TZ_PLANE)      // 2002
#define BBE_B_OFF (BBE_A2_OFF + BBE_TZ_PLANE)       // 2392
_Static_assert(BBE_OBS_SIZE == BBE_B_OFF + BBE_TZ_PLANE,
               "obs size out of sync with the v4 plane layout");
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
    // Aggregate-statistic-matching pseudo-reward (D114): the per-agent
    // episode-end term added when reward_statmatch_scale > 0 on a kickoff-pure
    // episode. <= 0 always (a penalty proportional to z-score L2 distance from
    // the human baseline). Stays 0.0 on the dashboard when the knob is off or
    // on curriculum-start episodes. Watch it converge toward 0 during a
    // statmatch arm; a stuck-large value means an untracked-dimension exploit.
    float statmatch_term;
    float illegal_frac;    // sampled actions that had to be snapped to legal
    // Behavioral micro-stats, summed per episode (dashboard shows per-episode
    // means after the /n aggregation). Motivated by a spectator finding:
    // policies never declared blocks and walked out of tackle zones
    // obliviously — these make that visible on the dashboard instead of
    // requiring a spectator session. Counting details: bbe_count_action /
    // bbe_count_knockdowns.
    float blocks;               // BB_A_DECLARE of BB_ACT_BLOCK
    float blocks_thrown;
    float block_1d_frac;
    float block_2d_frac;
    float block_3d_frac;
    float block_2dred_frac;
    float block_3dred_frac;        // resolved block dice pools (CHOOSE_DIE)
    float pickup_success;       // pickup attempts that ended holding the ball
    float possession_rate;      // fraction of team-turns ENDED holding the ball
                                // (Alex 2026-06-06: integrates pickup success +
                                // ball security; can't be farmed by attempts)
    float blitzes;              // BB_A_DECLARE of BB_ACT_BLITZ
    float dodge_attempts;       // STEPs out of >=1 opposing TZ (dodge test due)
    float gfi_attempts;         // STEPs beyond MA (rush/GFI test due)
    float pickup_attempts;      // STEPs onto the loose ball's square
    float pass_attempts;        // BB_A_PASS_TARGET actions
    float handoff_attempts;     // BB_A_HANDOFF_TARGET actions
    float knockdowns_inflicted; // actor's opponents downed during his window
    float knockdowns_own;       // actor's own players downed (failed dodges...)
    float carrier_exposed_full; // R6v1 full carrier-exposure firings
    float carrier_exposed_soft; // R6v1 one-roll carrier-exposure firings
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
    // Demo-state reset curriculum: episodes started from a banked mid-game
    // state (should track demo_reset_pct when the bank is staged), and bank
    // draws that failed validation and silently fell back to procgen
    // (should stay at 0.0 — anything else means a corrupt/stale bank).
    float demo_episodes;
    float demo_fallbacks;
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
    // Profile C exposure-EV transfer (default 0 = off; D33 motivation,
    // docs/reward-audit-decision-time.md). Fires at BB_A_BLOCK_TARGET —
    // BEFORE any dice — as a zero-sum transfer priced by the closed-form
    // block tree (bb_blockev, choice nodes resolved with spec-default
    // weights):
    //   exposure = k_kd    * P(def knocked down)
    //            + k_value * P(def removed) * def_cost_k/100
    //            + k_ball  * P(ball dislodged)   [0 unless def carries]
    //   attacker team: +exposure   defender team: -exposure
    // Dice outcomes carry no shaping anywhere on this path: a well-chosen
    // 2d+Block throw is +EV at declaration, curing the never-blocking meta.
    float reward_k_kd;
    float reward_k_value;
    float reward_k_ball;
    // Sequencing charge (same doc, Addendum 1): risky rolls taken while safe
    // activations remain unspent expose the rest of your turn to your own
    // dice. Charged to the acting team at the block declaration:
    //   k_seq * P(turnover of this roll) * pending_safe_activations
    // Exempt on the team's LAST turn of the half (Addendum 2: a turnover
    // then destroys nothing the whistle wasn't about to). v1 scope: block
    // declarations only (movement-roll sequencing is a follow-up).
    float reward_k_seq;
    // Possession annuity (Alex, 2026-06-06 — the reward-chain redesign):
    // ending your own team turn HOLDING the ball pays +p to the holder and
    // -p to the opponent (zero-sum transfer at the turn boundary). Holding
    // is an income STREAM, not a lump sum: the free kickoff scoop becomes
    // the entry ticket, protecting the carrier protects the income, and the
    // defense bleeds until it takes the ball away. Max 16 events/side/game,
    // binary each — structurally unfarmable. Replaces the ball_loss fine
    // (the measured possession-poison: every masked arm converged to
    // rational ball-avoidance under loss-fines; kzero@1.7B attempted ZERO
    // kickoff pickups).
    float reward_possession;
    // Rush (GFI) tax: charged per rush square AT DECLARATION (decision-time,
    // dice-independent — the exposure-pricing family). Exists because under
    // scoring scarcity the critic prices failed GFIs at ~nothing (the
    // opponent can't convert turnovers either), so potentials make rushing
    // free income and the policy GFI-spams (~17/ep observed; humans ~2-5).
    float reward_rush_cost;
    // Carrier-exposure penalty (R6v1, D120/D123-A): positive magnitudes
    // charged via subtraction at settled own-turn-end when a standing carrier
    // is not scoring-exempt and gives the opponent free adjacent access.
    // One-sided only: no opponent credit, no reward for being safe. 0 = off.
    float reward_carrier_exposure;
    // Optional softer one-sided tier, charged instead of the full tier when
    // adjacent access requires exactly one dodge or GFI. Positive magnitude;
    // 0 = off.
    float reward_carrier_exposure_soft;
    // Aggregate-statistic matching (D114): episode-end pseudo-reward that pulls
    // the full-game behavioral stat vector toward the FIXED human baseline
    // (docs/human-baseline.json). term = -scale * sqrt(sum_i z_i^2) over the 7
    // stats {tds, dodgeRoll, pickUpRoll, passRoll, goForItRoll, block_2dred_frac,
    // possession_rate}, z_i = (agent_i - human_mean_i)/human_std_i (diagonal
    // Mahalanobis / Z-score L2, raw episodic term, NOT PBRS). Stats are
    // MATCH-LEVEL (both teams summed, matching how the baseline was measured),
    // so the single term is applied SYMMETRICALLY to both self-play agents.
    // Activates ONLY on kickoff-pure episodes (demo_started == 0) — curriculum
    // episodes are too short for full-game stat targets. MUST run with
    // reward_possession == 0 (the annuity's dense gradient would dominate the
    // joint possession_rate target). 0 = off (default). See D114.
    float reward_statmatch_scale;
    // Backplay curriculum (D47): when >0, demo resets rejection-sample the
    // bank for SCORING-PROXIMAL states — a standing carrier within this
    // many squares of their endzone — so the policy experiences touchdowns
    // densely before the start distribution expands backward. 0 = uniform
    // bank sampling (default). Stages launched manually (6 -> 12 -> 0),
    // like the k-anneal chain.
    int demo_endzone_maxdist;
    // Pickup curriculum (D64): when >0, demo resets rejection-sample the bank
    // for BALL-ACQUISITION states — a LOOSE ball (on the ground) within this
    // many Chebyshev squares of a standing player of the team-to-move — so the
    // policy densely experiences the scoop that backplay skips (backplay starts
    // with the ball already HELD). 0 = off (default). Mutually exclusive with
    // demo_endzone_maxdist (backplay takes precedence if both >0). Stages
    // launched manually, expanding outward like the backplay ladder.
    int demo_pickup_maxdist;
    // Post-kickoff pickup drill (Alex, D68): when >0, demo resets
    // rejection-sample the bank for the natural game opening — a LOOSE ball
    // with the team-to-move on team-turn <= this value (1 = strict
    // post-kickoff scoop, 2 = + early recoveries). Unlike the mid-game pickup
    // drill (D67 context-lock failure), the drill state here IS the game's
    // real starting context — 28.5% of the bank qualifies at maxturn 1.
    // Precedence: endzone > pickup > postkick (first nonzero wins).
    int demo_postkick_maxturn;
    // Passing ladder (D72): >0 = demo resets prefer states where the
    // team-to-move holds the ball with a standing downfield receiver within
    // this Chebyshev pass-range. Pure ladder, graduates to kickoff (D69).
    int demo_pass_maxrange;
    // Procgen skill-entropy knobs. Defaults reproduce historical procgen:
    // 0-4 advancement draws/team, 1-2 skills/draw, primary categories only.
    int skillup_max_players;
    int skillup_max_each;
    float skillup_secondary_pct;
    // v5 path-actions (D82): when 1, the STEP square head selects ANY
    // reachable destination; the env routes a min-risk path (Dijkstra over
    // dodge/rush costs) and auto-applies it step-by-step, returning control
    // on any interruption (TEST window, knockdown, activation end). The
    // ENGINE is untouched — steps stay atomic and validated. 0 = v4
    // semantics, bit-identical (all macro code is gated on this knob).
    int macro_moves;
    // macro scratch: planned path + reachability of the current MOVE window
    uint8_t macro_px[40], macro_py[40];
    int macro_len, macro_pos, macro_mover;
    int reach_mover, reach_blitz;        // -1 = reach arrays invalid
    float reach_cost[390];
    uint8_t reach_p255[390];             // approx P(path succeeds) for obs B
    int16_t reach_parent[390];           // square idx -> predecessor idx
    uint8_t reach_len[390];
    // Demo-state reset curriculum (Backplay / chess fen_curric pattern,
    // docs/rl-best-practices.md hole #2): with probability demo_reset_pct
    // each episode starts from a uniformly drawn banked mid-game state
    // (resources/bloodbowl/state_bank.bbs, built by
    // validation/build_state_bank.py from FUMBBL replays) instead of a
    // procgen kickoff. 0 = off (default). demo_started flags the CURRENT
    // episode for the Log.
    float demo_reset_pct;
    int demo_started;
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
    int ep_blocks_thrown;
    // Block-dice tier distribution (Alex's blocking-rationality gauge): a
    // healthy game trends toward 2d/3d attacker-choice and away from red
    // (defender-choice) and 1d. Classified at the CHOOSE_DIE window from
    // the block frame: nd in data bits 9-10, defender-chooses in bit 11
    // (proc_block.c layout).
    int ep_block_tier[5]; // 0=1d, 1=2d, 2=3d, 3=2d-red, 4=3d-red
    int ep_pickup_success;
    int pending_pickup_slot;    // mover of THIS step's pickup attempt (-1 none)
    int ep_turns[2], ep_turns_with_ball[2];
    int prev_active_team;       // turn-boundary detector for possession_rate
    int ep_carrier_exposed_full, ep_carrier_exposed_soft;
    // Per-team behavior counters for the spectator's live archetype plates
    // ("BRUISER"/"BALLHAWK"/...): contact = block+blitz declarations, ball =
    // weighted ball engagement (pickups, passes, squares moved carrying).
    // Reset with the episode; turns_at_reset normalizes demo-started
    // episodes (their turn counters start mid-game).
    int ep_team_contact[2];
    int ep_team_ball[2];
    int turns_at_reset[2];
    int ep_dodge_attempts, ep_gfi_attempts;
    int ep_pickup_attempts, ep_pass_attempts, ep_handoff_attempts;
    int ep_knockdowns_inflicted, ep_knockdowns_own;
    float ep_return[BBE_AGENTS];
    bb_action legal[BB_LEGAL_MAX];
    int n_legal;
    int score_prev[2];
    // Scores at episode START (0-0 from kickoff; the banked scores on a demo
    // reset). The Log's tds/score_diff count only the DELTAS scored within
    // the episode; win/draw/loss stays the ABSOLUTE final comparison (the
    // match's real result, wherever it was resumed from).
    int score_start[2];
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
    // tz_plane / tz_scratch are the per-step tackle-zone scratch — counts
    // are view-independent (mirroring is an indexing flip at encode), so
    // bbe_compute_tz fills them once per step instead of twice.
    bb_skillset skill_keys[BB_NUM_PLAYERS];
    uint8_t skill_rows[BB_NUM_PLAYERS][BBE_SKILL_SLOTS];
    // [team][y*26+x] (home view): TZs exerted BY team's players on a square.
    uint8_t tz_plane[2][BBE_TZ_PLANE];  // valid only within bbe_emit_all's step
    uint8_t tz_scratch[BB_NUM_PLAYERS]; // valid only within bbe_emit_all's step
    // Head-space projection of legal[] for the DECIDING agent, written by
    // bbe_fill_mask (which had to compute it anyway) and reused by
    // bbe_decode, which previously re-derived arg/sq per scanned action over
    // up to three fallback passes (review LOW: decode 3-pass fold).
    uint16_t legal_sq[BB_LEGAL_MAX];
    uint8_t legal_arg[BB_LEGAL_MAX];
    // SETUP fast-path cache (SPS pass): setup_legal stamps identical square
    // templates per candidate; the mask fill projects block 0 once and
    // stamps later blocks after a masked-u32 verification (irregular lists
    // — e.g. Quick Snap — fall back per block; no proc heuristics trusted).
    // bbe_decode then resolves SETUP_PLACE heads arithmetically. Written
    // ONLY by the deciding agent's fill (the waiting agent's early-return
    // must not clobber them — both fills precede the decode).
    int setup_t0;                          // first SETUP_PLACE block start (-1)
    int setup_len;                         // template length
    uint8_t setup_fast;                    // every PLACE entry block-stamped
    uint8_t v4_dirty[2];                   // per-agent: v4 planes hold bytes
    // Encode->pricing bb_block_ev cache: the obs-v4 fill evaluates every
    // candidate target on the SAME pre-apply state the Profile-C pricing
    // later prices, so pricing is a structural cache hit. Keyed by
    // (mover, blitz); validity cleared at each refill and after every
    // apply. Lives in the env (never bb_match — bank fingerprint safe).
    bb_blockev ev_cache[BB_NUM_PLAYERS];
    uint32_t ev_valid;                     // bit per defender slot
    int ev_mover;
    int ev_blitz;
    int setup_block_start[BBE_HEAD_ARG];   // projected arg -> block start (-1)
    uint16_t setup_sq_off[BBE_HEAD_SQ];    // sq -> template offset (0xFFFF)
} Bloodbowl;

// v5 macro-moves (D82): forward decls — used by obs encode before definition
static void bbe_macro_reach(Bloodbowl* env, const bb_match* m, int mover,
                            int is_blitz);
static bb_action bbe_macro_plan(Bloodbowl* env, int mover, int dst);

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
    // Zero only the conditionally-written regions: player/ctx/scalars
    // (0..BBE_TZ_OFF). The TZ planes are fully rewritten below, and the v4
    // planes are cleared lazily via v4_dirty (set when filled; forced on
    // reset and on perm re-pointing in my_setup_perm).
    memset(o, 0, BBE_TZ_OFF);
    if (env->v4_dirty[agent]) {
        memset(o + BBE_A1_OFF, 0, BBE_OBS_SIZE - BBE_A1_OFF);
        env->v4_dirty[agent] = 0;
    }
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

    // [BBE_TZ_OFF..] obs v3 tackle-zone planes: my coverage, then the
    // opponent's (destination danger), per square, x-mirrored for the away
    // agent. bbe_compute_tz filled tz_plane in home orientation this step.
    unsigned char* tz = o + BBE_TZ_OFF;
    if (me == BB_HOME) {
        memcpy(tz, env->tz_plane[me], BBE_TZ_PLANE);
        memcpy(tz + BBE_TZ_PLANE, env->tz_plane[1 - me], BBE_TZ_PLANE);
    } else {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            const uint8_t* my_row = env->tz_plane[me] + y * BB_PITCH_LEN;
            const uint8_t* op_row = env->tz_plane[1 - me] + y * BB_PITCH_LEN;
            unsigned char* out_my = tz + y * BB_PITCH_LEN;
            unsigned char* out_op = out_my + BBE_TZ_PLANE;
            for (int x = 0; x < BB_PITCH_LEN; x++) {
                out_my[x] = my_row[BB_PITCH_LEN - 1 - x];
                out_op[x] = op_row[BB_PITCH_LEN - 1 - x];
            }
        }
    }

    // Obs-v4 planes: only for the DECIDING agent (zero otherwise), only at
    // MOVE-proc decisions whose legal list offers steps / block targets.
    // x is ego-mirrored exactly like the TZ planes above.
    if (m->decision_team == me && top && top->proc == BB_PROC_MOVE &&
        top->a < BB_NUM_PLAYERS && env->n_legal > 0) {
        int mover = top->a;
        int is_blitz = top->b == BB_ACT_BLITZ;
        unsigned char* a1 = o + BBE_A1_OFF;
        unsigned char* a2 = o + BBE_A2_OFF;
        unsigned char* bp = o + BBE_B_OFF;
        env->v4_dirty[agent] = 1;
        env->ev_valid = 0;
        env->ev_mover = mover;
        env->ev_blitz = is_blitz;
        for (int i = 0; i < env->n_legal; i++) {
            bb_action act = env->legal[i];
            if (act.type != BB_A_STEP && act.type != BB_A_BLOCK_TARGET) {
                continue;
            }
            int ex = me == BB_HOME ? act.x : (BB_PITCH_LEN - 1 - act.x);
            int idx = act.y * BB_PITCH_LEN + ex;
            if (act.type == BB_A_BLOCK_TARGET) {
                int def = bb_slot_at(m, act.x, act.y);
                if (def >= 0) {
                    bb_blockev ev;
                    bb_block_ev(m, mover, def, is_blitz, NULL, &ev);
                    env->ev_cache[def] = ev;
                    env->ev_valid |= 1u << def;
                    a1[idx] = (unsigned char)(ev.p_def_down * 255.0f + 0.5f);
                    a2[idx] = (unsigned char)(ev.p_att_down * 255.0f + 0.5f);
                }
            } else {
                bp[idx] = (unsigned char)bb_step_success_p255(
                    m, mover, act.x, act.y, is_blitz);
            }
        }
        // v5 macro-moves: destination-level success approximations for all
        // reachable squares (base-test math, no skill hooks — advisory;
        // adjacents keep their exact values from the loop above).
        if (env->macro_moves && env->reach_mover == mover &&
            env->reach_blitz == is_blitz) {  // read-only: fill_mask computed it
            for (int d = 0; d < 390; d++) {
                if (env->reach_parent[d] < 0) continue;
                int dx2 = d % BB_PITCH_LEN, dy2 = d / BB_PITCH_LEN;
                int ex3 = me == BB_HOME ? dx2 : (BB_PITCH_LEN - 1 - dx2);
                int idx3 = dy2 * BB_PITCH_LEN + ex3;
                if (bp[idx3] == 0) bp[idx3] = env->reach_p255[d];
            }
        }
    }
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

// Same square template? Compare actions as u32 with the arg byte masked
// off (bb_action is 4 packed bytes: type, arg, x, y).
static int bbe_setup_blocks_match(const bb_action* a, const bb_action* b,
                                  int len) {
    for (int k = 0; k < len; k++) {
        uint32_t ua, ub;
        memcpy(&ua, &a[k], 4);
        memcpy(&ub, &b[k], 4);
        if ((ua ^ ub) & 0xFFFF00FFu) return 0;
    }
    return 1;
}


static long bbe_macro_dbg_plans, bbe_macro_dbg_steps;  // diag, remove post-balloon
// ---- v5 macro-move reachability (D82) ---------------------------------------
// Dijkstra over the 8-connected pitch from the mover's square, bounded by
// movement_left + remaining rushes. Cost prefers safe paths: each step costs
// 1, +50 if it leaves a marked square (dodge), +12 if beyond MA (rush).
// reach_p255 accumulates an APPROXIMATE success probability (base test math,
// no skill hooks — advisory for the obs B plane only; the engine rolls the
// real dice). Engine statics (movement_left, bb_max_rushes, bb_tackle_zones)
// are visible: the binding compiles env+engine as one TU.
static void bbe_macro_reach(Bloodbowl* env, const bb_match* m, int mover,
                            int is_blitz) {
    if (env->reach_mover == mover && env->reach_blitz == is_blitz) return;
    env->reach_mover = mover;
    env->reach_blitz = is_blitz;
    const bb_player* p = &m->players[mover];
    int team = BB_TEAM_OF(mover);
    int ma_left = movement_left(m, mover);
    int rush_left = bb_max_rushes(m, mover) - p->rushes;
    if (rush_left < 0) rush_left = 0;
    int budget = ma_left + rush_left;
    if (budget > 39) budget = 39;
    for (int i = 0; i < 390; i++) {
        env->reach_cost[i] = 1e9f;
        env->reach_parent[i] = -1;
        env->reach_p255[i] = 0;
        env->reach_len[i] = 0;
    }
    int src = p->y * BB_PITCH_LEN + p->x;
    env->reach_cost[src] = 0.0f;
    env->reach_p255[src] = 255;
    // simple O(V^2) Dijkstra — 390 nodes, called once per MOVE window
    uint8_t done[390] = {0};
    for (;;) {
        int u = -1; float best = 1e9f;
        for (int i = 0; i < 390; i++)
            if (!done[i] && env->reach_cost[i] < best) { best = env->reach_cost[i]; u = i; }
        if (u < 0) break;
        done[u] = 1;
        int ux = u % BB_PITCH_LEN, uy = u / BB_PITCH_LEN;
        int steps = env->reach_len[u];
        if (steps >= budget) continue;
        int from_tz = bb_tackle_zones(m, team, ux, uy) > 0;
        for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
            if (!dx && !dy) continue;
            int nx = ux + dx, ny = uy + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            if (m->grid[nx][ny]) continue;
            int v = ny * BB_PITCH_LEN + nx;
            int is_rush = steps >= ma_left;
            float c = 1.0f + (from_tz ? 50.0f : 0.0f) + (is_rush ? 12.0f : 0.0f);
            if (env->reach_cost[u] + c < env->reach_cost[v]) {
                env->reach_cost[v] = env->reach_cost[u] + c;
                env->reach_parent[v] = (int16_t)u;
                env->reach_len[v] = (uint8_t)(steps + 1);
                float pstep = 1.0f;
                if (from_tz) {
                    int tzd = bb_tackle_zones(m, team, nx, ny);
                    int tgt = bb_test_target(p->ag, -tzd);
                    pstep *= (float)(7 - tgt) / 6.0f;
                }
                if (is_rush) pstep *= 5.0f / 6.0f;
                if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == nx &&
                    m->ball.y == ny) {
                    int tzb = bb_tackle_zones(m, team, nx, ny);
                    int tgt = bb_test_target(p->ag, -tzb);
                    pstep *= (float)(7 - tgt) / 6.0f;
                }
                float pp = (float)env->reach_p255[u] / 255.0f * pstep;
                env->reach_p255[v] = (uint8_t)(pp * 255.0f + 0.5f);
            }
        }
    }
    env->reach_p255[src] = 0;      // staying put is not a STEP
    env->reach_cost[src] = 1e9f;
}

// Build env->macro_* from reach_parent for destination square dst (abs idx).
// Returns the FIRST step as a bb_action (adjacent, unoccupied — same
// conditions move_legal enumerates, so safe for bb_apply_trusted).
static bb_action bbe_macro_plan(Bloodbowl* env, int mover, int dst) {
    int chain[40]; int n = 0;
    for (int v = dst; v >= 0 && n < 40; v = env->reach_parent[v]) {
        if (env->reach_parent[v] < 0) break;  // reached source
        chain[n++] = v;
    }
    env->macro_len = 0;
    for (int i = n - 1; i >= 0; i--) {
        env->macro_px[env->macro_len] = (uint8_t)(chain[i] % BB_PITCH_LEN);
        env->macro_py[env->macro_len] = (uint8_t)(chain[i] / BB_PITCH_LEN);
        env->macro_len++;
    }
    env->macro_pos = 1;            // [0] is applied immediately by c_step
    env->macro_mover = mover;
    return (bb_action){BB_A_STEP, 0, env->macro_px[0], env->macro_py[0]};
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
    env->setup_t0 = -1;
    env->setup_len = 0;
    int setup_fast = 1;
    int i = 0;
    while (i < env->n_legal) {
        bb_action a = env->legal[i];
        if (a.type != BB_A_SETUP_PLACE) {
            int ha = bbe_action_arg(agent, a);
            int hs = bbe_action_sq(agent, a);
            env->legal_arg[i] = (unsigned char)ha;
            env->legal_sq[i] = (uint16_t)hs;
            mask[a.type] = 1;
            mask[BBE_HEAD_TYPE + ha] = 1;
            mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + hs] = 1;
            i++;
            continue;
        }
        // SETUP_PLACE run for one candidate (same arg).
        int j = i + 1;
        while (j < env->n_legal && env->legal[j].type == BB_A_SETUP_PLACE &&
               env->legal[j].arg == a.arg) {
            j++;
        }
        int len = j - i;
        if (env->setup_t0 < 0) {
            // Block 0: full projection + the decode maps.
            env->setup_t0 = i;
            env->setup_len = len;
            for (int k = i; k < j; k++) {
                bb_action b = env->legal[k];
                int ha = bbe_action_arg(agent, b);
                int hs = bbe_action_sq(agent, b);
                env->legal_arg[k] = (unsigned char)ha;
                env->legal_sq[k] = (uint16_t)hs;
                mask[b.type] = 1;
                mask[BBE_HEAD_TYPE + ha] = 1;
                mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + hs] = 1;
            }
            memset(env->setup_sq_off, 0xFF, sizeof env->setup_sq_off);
            for (int k = 0; k < BBE_HEAD_ARG; k++) {
                env->setup_block_start[k] = -1;
            }
            for (int k = 0; k < len; k++) {
                env->setup_sq_off[env->legal_sq[i + k]] = (uint16_t)k;
            }
            env->setup_block_start[env->legal_arg[i]] = i;
        } else if (len == env->setup_len &&
                   bbe_setup_blocks_match(env->legal + env->setup_t0,
                                          env->legal + i, len)) {
            // Verified identical square template: stamp instead of project.
            // Type + square-head mask bits were set by block 0; only the
            // arg bit and the cached projections differ.
            int ha = bbe_action_arg(agent, a);
            memcpy(env->legal_sq + i, env->legal_sq + env->setup_t0,
                   (size_t)len * sizeof(uint16_t));
            memset(env->legal_arg + i, ha, (size_t)len);
            mask[BBE_HEAD_TYPE + ha] = 1;
            env->setup_block_start[ha] = i;
        } else {
            // Irregular block (e.g. Quick Snap per-player squares): generic
            // projection, arithmetic decode off for this list.
            setup_fast = 0;
            for (int k = i; k < j; k++) {
                bb_action b = env->legal[k];
                int ha = bbe_action_arg(agent, b);
                int hs = bbe_action_sq(agent, b);
                env->legal_arg[k] = (unsigned char)ha;
                env->legal_sq[k] = (uint16_t)hs;
                mask[b.type] = 1;
                mask[BBE_HEAD_TYPE + ha] = 1;
                mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + hs] = 1;
            }
        }
        i = j;
    }
    env->setup_fast = (uint8_t)(env->setup_t0 >= 0 && setup_fast);
    // v5 macro-moves (D82): in a MOVE window, additionally mark every
    // REACHABLE destination square legal for the STEP head; decode routes
    // non-adjacent picks via bbe_macro_plan.
    if (env->macro_moves) {
        const bb_match* mm = &env->match;
        if (mm->stack_top > 0 && mm->decision_team == agent) {
            const bb_frame* tf = &mm->stack[mm->stack_top - 1];
            if (tf->proc == BB_PROC_MOVE && tf->a < BB_NUM_PLAYERS &&
                can_step(mm, tf->a) && mask[BB_A_STEP]) {
                bbe_macro_reach(env, mm, tf->a, tf->b == BB_ACT_BLITZ);
                for (int d = 0; d < 390; d++) {
                    if (env->reach_parent[d] < 0) continue;
                    int dx = d % BB_PITCH_LEN, dy = d / BB_PITCH_LEN;
                    int ex2 = agent == BB_HOME ? dx : (BB_PITCH_LEN - 1 - dx);
                    mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + dy * BB_PITCH_LEN + ex2] = 1;
                }
            }
        }
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
    if (t == BB_A_SETUP_PLACE && env->setup_fast) {
        // Arithmetic resolution against the stamped template — selection
        // tiers identical to the generic scan below (incl. illegal++).
        int bs = (arg >= 0 && arg < BBE_HEAD_ARG)
                     ? env->setup_block_start[arg] : -1;
        uint16_t off = (sq >= 0 && sq < BBE_HEAD_SQ)
                           ? env->setup_sq_off[sq] : (uint16_t)0xFFFF;
        if (bs >= 0 && off != 0xFFFF) return env->legal[bs + off];
        env->illegal++;
        if (off != 0xFFFF) return env->legal[env->setup_t0 + off];
        return env->legal[env->setup_t0];
    }
    int same_type_sq = -1, same_type = -1;
    for (int i = 0; i < env->n_legal; i++) {
        if (env->legal[i].type != t) continue;
        if (env->legal_sq[i] == sq) {
            if (env->legal_arg[i] == arg) return env->legal[i]; // exact
            if (same_type_sq < 0) same_type_sq = i;
        }
        if (same_type < 0) same_type = i;
    }
    // v5 macro-moves (D82): a STEP to a reachable non-adjacent destination
    // is a PLANNED PATH, not an illegal pick. Ego->absolute, then route.
    if (env->macro_moves && t == BB_A_STEP && same_type_sq < 0 &&
        sq >= 0 && sq < 390 && env->reach_mover >= 0 &&
        env->match.stack_top > 0 &&
        env->match.stack[env->match.stack_top - 1].proc == BB_PROC_MOVE &&
        (int)env->match.stack[env->match.stack_top - 1].a == env->reach_mover) {
        int ax = sq % BB_PITCH_LEN, ay = sq / BB_PITCH_LEN;
        if (agent == BB_AWAY) ax = BB_PITCH_LEN - 1 - ax;
        int abs_sq = ay * BB_PITCH_LEN + ax;
        if (env->reach_parent[abs_sq] >= 0) {
            bbe_macro_dbg_plans++;
            return bbe_macro_plan(env, env->reach_mover, abs_sq);
        }
    }
    env->illegal++;
    if (same_type_sq >= 0) return env->legal[same_type_sq];
    if (same_type >= 0) return env->legal[same_type];
    return env->legal[0];
}

// --- Spectator event feed ----------------------------------------------------
// Lightweight render-feed hook (viewer sidebar): fired from c_step's event
// sites with POD identifiers only — the RENDER thread formats text (the
// memorial SIGSEGV lesson: never share strings across the env/render
// threads). Training never registers it; the `if` is the entire cost.
enum {
    BBE_EV_BLOCK_DECL = 0, // a = actor slot, b = -1
    BBE_EV_BLITZ_DECL,
    BBE_EV_BLOCK_THROWN,   // a = attacker, b = defender
    BBE_EV_DODGE,          // a = mover
    BBE_EV_GFI,
    BBE_EV_PICKUP_TRY,     // a = mover
    BBE_EV_PICKUP_OK,
    BBE_EV_PASS,           // a = passer
    BBE_EV_HANDOFF,        // a = actor
    BBE_EV_KNOCKDOWN,      // a = victim, b = causer window owner
    BBE_EV_TD,             // a = scorer
    BBE_EV_TURNOVER,       // a = team (0/1)
};
extern void (*bbe_feed_hook)(const Bloodbowl* env, int kind, int a, int b);
void (*bbe_feed_hook)(const Bloodbowl* env, int kind, int a, int b) = 0;
#define BBE_FEED(env, kind, a, b) \
    do { if (bbe_feed_hook) bbe_feed_hook((env), (kind), (a), (b)); } while (0)

// --- Demo-state bank (Backplay / chess-FEN curriculum) -----------------------
// Shared, lazily loaded once per process (per TU — binding.c is the single
// training TU, mirroring chess's SHARED_FEN_CURRICULUM in my_vec_init).
// File: "BBS1" written by tools/bb_lockstep.c --dump-states, concatenated by
// validation/build_state_bank.py, staged by tools/install_puffer_env.sh.
// Missing file = curriculum silently off (the chess pattern); a header that
// fails the match_size/fingerprint guards is reported and ignored — training
// on stale-engine states would be silent corruption. Only BB_STATUS_DECISION
// records are kept (resumable by definition).
#define BBE_STATE_BANK_PATH "resources/bloodbowl/state_bank.bbs"
#define BBE_STATE_BANK_REC_META 12 // replay_id u32, cmd u32, half, turn, pad[2]

static const char* bbe_state_bank_path = BBE_STATE_BANK_PATH;
static bb_match* bbe_state_bank = NULL;
static int bbe_state_bank_n = 0;
static int bbe_state_bank_tried = 0;

static uint32_t bbe_le32(const uint8_t* b) {
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) |
           ((uint32_t)b[3] << 24);
}

// Load the bank once. Call sites: the binding's init entry points (before
// any stepping thread exists) and, for standalone callers (driver, tests),
// lazily from the first bbe_reset_match with demo_reset_pct > 0.
static void bbe_state_bank_load(void) {
    if (bbe_state_bank_tried) return;
    bbe_state_bank_tried = 1;
    FILE* f = fopen(bbe_state_bank_path, "rb");
    if (f == NULL) return; // no bank staged: curriculum off
    uint8_t hdr[16];
    size_t rec_len = BBE_STATE_BANK_REC_META + sizeof(bb_match);
    if (fread(hdr, 1, sizeof hdr, f) != sizeof hdr ||
        memcmp(hdr, "BBS1", 4) != 0 || bbe_le32(hdr + 4) != 1u ||
        bbe_le32(hdr + 8) != (uint32_t)sizeof(bb_match) ||
        bbe_le32(hdr + 12) != bbe_state_fingerprint()) {
        fprintf(stderr,
                "bloodbowl: state bank %s incompatible with this engine build "
                "(stale bank? rebuild with validation/build_state_bank.py) — "
                "demo resets disabled\n",
                bbe_state_bank_path);
        fclose(f);
        return;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        fclose(f);
        return;
    }
    long size = ftell(f);
    long n = size > 16 ? (size - 16) / (long)rec_len : 0;
    if (n <= 0 || (size - 16) % (long)rec_len != 0) {
        fprintf(stderr, "bloodbowl: state bank %s malformed (%ld bytes) — "
                        "demo resets disabled\n",
                bbe_state_bank_path, size);
        fclose(f);
        return;
    }
    bb_match* bank = (bb_match*)malloc((size_t)n * sizeof(bb_match));
    int kept = 0;
    for (long i = 0; i < n; i++) {
        if (fseek(f, 16 + i * (long)rec_len + BBE_STATE_BANK_REC_META,
                  SEEK_SET) != 0 ||
            fread(&bank[kept], sizeof(bb_match), 1, f) != 1) {
            break;
        }
        // Resumable points only; anything else would error out of c_step.
        // Index-bearing bytes are validated too: reward pricing and obs
        // encoding index team/position tables with them, and the BBS1
        // fingerprint guards the engine BUILD, not record content (panel).
        if (bank[kept].status == BB_STATUS_DECISION &&
            bank[kept].stack_top > 0 &&
            bank[kept].team_id[0] < BB_TEAM_COUNT &&
            bank[kept].team_id[1] < BB_TEAM_COUNT) {
            int ok = 1;
            for (int s = 0; s < BB_NUM_PLAYERS; s++) {
                if (bank[kept].players[s].position_id >= BB_MAX_POSITIONS) {
                    ok = 0;
                    break;
                }
            }
            kept += ok;
        }
    }
    fclose(f);
    if (kept == 0) {
        free(bank);
        return;
    }
    bbe_state_bank = bank;
    bbe_state_bank_n = kept;
    printf("Loaded %d demo states from %s\n", kept, bbe_state_bank_path);
}

// --- Lifecycle -------------------------------------------------------------------
// Per-step tackle-zone scratch, computed ONCE for both agent views:
// tz_plane[t][y*26+x] = TZs exerted BY team t's players on that square
// (home orientation; the away mirror is an index flip at encode time), and
// tz_scratch[s] = opposing TZs marking player s's square (player byte [23]).
// One pass over on-pitch players (8 neighbor increments per TZ-exerting
// player) builds both — never 390 bb_tackle_zones calls per plane.
static void bbe_compute_tz(Bloodbowl* env) {
    const bb_match* m = &env->match;
    memset(env->tz_plane, 0, sizeof env->tz_plane);
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        if (!bb_exerts_tz(m, s)) continue; // off-pitch/prone/NO_TZ/Distracted
        const bb_player* p = &m->players[s];
        uint8_t* plane = env->tz_plane[BB_TEAM_OF(s)];
        for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                plane[ny * BB_PITCH_LEN + nx]++;
            }
        }
    }
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        // Marked count for s = TZs the OPPOSING team exerts on s's square.
        env->tz_scratch[s] =
            p->location == BB_LOC_ON_PITCH
                ? env->tz_plane[1 - BB_TEAM_OF(s)][p->y * BB_PITCH_LEN + p->x]
                : 0;
    }
}

static void bbe_emit_all(Bloodbowl* env) {
    bbe_compute_tz(env);
    for (int a = 0; a < BBE_AGENTS; a++) {
        bbe_encode_obs(env, a);
        bbe_fill_mask(env, a);
    }
}

static void bbe_reset_match(Bloodbowl* env) {
    env->episode++;
    bb_rng_seed(&env->procgen, env->seed * 2654435761u + env->episode, 11);
    // Demo-state reset curriculum: with probability demo_reset_pct, resume
    // from a uniformly drawn banked mid-game state instead of a procgen
    // kickoff (both draws from the procgen stream). A banked state that
    // fails validation falls back to procgen silently, counted in the Log.
    env->reach_mover = -1;          // v5 scratch: new match = stale reach
    env->macro_len = env->macro_pos = 0;
    env->macro_mover = -1;
    env->demo_started = 0;
    if (env->demo_reset_pct > 0.0f) {
        bbe_state_bank_load(); // lazy once; no-op when already tried
        if (bbe_state_bank_n > 0 &&
            (float)(bb_rng_next(&env->procgen) >> 8) * (1.0f / 16777216.0f) <
                env->demo_reset_pct) {
            int idx = (int)(bb_rng_next(&env->procgen) %
                            (uint32_t)bbe_state_bank_n);
            // Backplay: rejection-sample for a standing carrier within
            // demo_endzone_maxdist of their endzone; fall back to the last
            // uniform draw if the bank tier is thin (loud via demo stats
            // would lie — count fallbacks separately below).
            if (env->demo_endzone_maxdist > 0) {
                for (int try = 0; try < 256; try++) {
                    const bb_match* cand = &bbe_state_bank[idx];
                    int c = cand->ball.carrier;
                    if (cand->ball.state == BB_BALL_HELD && c != BB_NO_PLAYER) {
                        const bb_player* cp = &cand->players[c];
                        if (cp->location == BB_LOC_ON_PITCH &&
                            cp->stance == BB_STANCE_STANDING) {
                            int d = cp->x - bb_endzone_x(BB_TEAM_OF(c));
                            if (d < 0) d = -d;
                            if (d <= env->demo_endzone_maxdist) break;
                        }
                    }
                    idx = (int)(bb_rng_next(&env->procgen) %
                                (uint32_t)bbe_state_bank_n);
                }
            } else if (env->demo_pickup_maxdist > 0) {
                // Pickup curriculum (D64): rejection-sample for a LOOSE ball
                // with a standing player of the team-to-move within
                // demo_pickup_maxdist (Chebyshev) — the scoop backplay skips.
                // Fall back to the last uniform draw if the tier is thin
                // (counted in demo_fallbacks below, same as backplay).
                for (int try = 0; try < 256; try++) {
                    const bb_match* cand = &bbe_state_bank[idx];
                    if (cand->ball.state == BB_BALL_ON_GROUND) {
                        int bx = cand->ball.x, by = cand->ball.y;
                        int at = cand->active_team;
                        int hit = 0;
                        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
                            if (BB_TEAM_OF(s) != at) continue;
                            const bb_player* p = &cand->players[s];
                            if (p->location != BB_LOC_ON_PITCH ||
                                p->stance != BB_STANCE_STANDING) continue;
                            int dx = (int)p->x - bx; if (dx < 0) dx = -dx;
                            int dy = (int)p->y - by; if (dy < 0) dy = -dy;
                            int d = dx > dy ? dx : dy;
                            if (d <= env->demo_pickup_maxdist) { hit = 1; break; }
                        }
                        if (hit) break;
                    }
                    idx = (int)(bb_rng_next(&env->procgen) %
                                (uint32_t)bbe_state_bank_n);
                }
            } else if (env->demo_postkick_maxturn > 0) {
                // Post-kickoff scoop drill (D68): loose ball at the top of a
                // drive — the team-to-move's turn counter is still <= N.
                for (int try = 0; try < 256; try++) {
                    const bb_match* cand = &bbe_state_bank[idx];
                    if (cand->ball.state == BB_BALL_ON_GROUND &&
                        (int)cand->turn[cand->active_team & 1] <=
                            env->demo_postkick_maxturn)
                        break;
                    idx = (int)(bb_rng_next(&env->procgen) %
                                (uint32_t)bbe_state_bank_n);
                }
            } else if (env->demo_pass_maxrange > 0) {
                // Passing ladder (D72): team-to-move HOLDS the ball and has a
                // standing friendly receiver DOWNFIELD (closer to the enemy
                // endzone than the carrier) within Chebyshev pass-range N — a
                // state where throwing is a live option. Pure ladder, meant to
                // GRADUATE to kickoff (demo_reset_pct -> 0) per D69, not to be
                // mixed in perpetuity. ~15% of bank qualifies at range 6.
                for (int try = 0; try < 256; try++) {
                    const bb_match* cand = &bbe_state_bank[idx];
                    int c = cand->ball.carrier;
                    if (cand->ball.state == BB_BALL_HELD && c != BB_NO_PLAYER &&
                        BB_TEAM_OF(c) == cand->active_team) {
                        const bb_player* cp = &cand->players[c];
                        int tgt0 = (bb_endzone_x(BB_TEAM_OF(c)) == 0);
                        int cx = tgt0 ? cp->x : (BB_PITCH_LEN - 1 - cp->x);
                        int hit = 0;
                        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
                            if (BB_TEAM_OF(s) != cand->active_team || s == c)
                                continue;
                            const bb_player* p = &cand->players[s];
                            if (p->location != BB_LOC_ON_PITCH ||
                                p->stance != BB_STANCE_STANDING) continue;
                            int rx = tgt0 ? p->x : (BB_PITCH_LEN - 1 - p->x);
                            if (rx >= cx) continue;  // not downfield of carrier
                            int dx = (int)p->x - cp->x; if (dx < 0) dx = -dx;
                            int dy = (int)p->y - cp->y; if (dy < 0) dy = -dy;
                            int rng = dx > dy ? dx : dy;
                            if (rng <= env->demo_pass_maxrange) { hit = 1; break; }
                        }
                        if (hit) break;
                    }
                    idx = (int)(bb_rng_next(&env->procgen) %
                                (uint32_t)bbe_state_bank_n);
                }
            }
            env->match = bbe_state_bank[idx];
            if (env->match.status == BB_STATUS_DECISION &&
                env->match.stack_top > 0) {
                env->demo_started = 1;
            } else {
                env->log.demo_fallbacks += 1.0f;
            }
        }
    }
    if (!env->demo_started) {
        // Procgen controls: exclude_team bars a team from training draws
        // (holdout); force_* pins a side for fixed-matchup eval. NOTE: banked
        // demo states carry their FUMBBL rosters — neither constraint is
        // enforced on the demo path (keep demo_reset_pct = 0 for holdout
        // evals).
        if (env->exclude_team >= 0 || env->force_home_team >= 0 ||
            env->force_away_team >= 0) {
            bb_procgen_params pp = {
                env->skillup_max_players,
                env->skillup_max_each,
                env->skillup_secondary_pct
            };
            bb_match_init_forced_p(&env->match, &env->procgen,
                                   env->force_home_team, env->force_away_team,
                                   env->exclude_team, &pp);
        } else {
            bb_procgen_params pp = {
                env->skillup_max_players,
                env->skillup_max_each,
                env->skillup_secondary_pct
            };
            bb_match_init_random_p(&env->match, &env->procgen, &pp);
        }
    }
    // Fresh in-match dice stream either way; a resumed state replays under
    // new dice. bb_advance is a no-op for a banked state (already at a
    // DECISION) and runs procgen kickoffs to their first decision.
    bb_rng_seed(&env->rng, env->seed + env->episode * 7919u, 1);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->decisions = 0; // max_decisions budgets from the resume point
    env->illegal = 0;
    env->ep_blocks = env->ep_blitzes = 0;
    env->ep_blocks_thrown = 0;
    memset(env->ep_block_tier, 0, sizeof env->ep_block_tier);
    env->ep_pickup_success = 0;
    env->pending_pickup_slot = -1;
    env->ep_turns[0] = env->ep_turns[1] = 0;
    env->ep_turns_with_ball[0] = env->ep_turns_with_ball[1] = 0;
    env->prev_active_team = env->match.active_team;
    env->ep_carrier_exposed_full = env->ep_carrier_exposed_soft = 0;
    env->ep_dodge_attempts = env->ep_gfi_attempts = 0;
    env->ep_pickup_attempts = env->ep_pass_attempts = 0;
    env->ep_handoff_attempts = 0;
    env->ep_knockdowns_inflicted = env->ep_knockdowns_own = 0;
    for (int t = 0; t < 2; t++) {
        env->ep_team_contact[t] = 0;
        env->ep_team_ball[t] = 0;
        env->turns_at_reset[t] =
            (env->match.half - 1) * 8 + env->match.turn[t];
    }
    env->ep_return[0] = env->ep_return[1] = 0;
    // Baseline scores from the (possibly resumed) match so TD step rewards
    // and the Log's tds/score_diff deltas count only what happens from here.
    env->score_prev[0] = env->score_start[0] = env->match.score[0];
    env->score_prev[1] = env->score_start[1] = env->match.score[1];
    // Settled-possession baseline from the loaded ball state (a banked
    // carrier must not pay reward_ball_loss for a pre-existing loose ball,
    // nor earn reward_ball_gain for already holding it). Grounded/in-air/
    // off-pitch all start as "no possessor" — exactly the from-kickoff
    // semantics.
    env->possessor = env->match.ball.state == BB_BALL_HELD
                         ? BB_TEAM_OF(env->match.ball.carrier)
                         : -1;
    // Potentials start inactive in both channels: the first post-reset step
    // primes them without emitting a delta, so a resumed carrier/loose ball
    // never books a phantom potential jump against the -1 sentinel.
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = -1.0f;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = -1.0f;
    // Procgen can pre-injure players into the CAS box, and banked demo
    // states arrive with whatever KO/CAS boxes and surf counts the human
    // game had reached; baseline all of it so injury/surf shaping prices
    // only NEW events.
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
    // Force a full v4-plane clear on the first encode of a (re)pointed obs
    // buffer (my_setup_perm also sets these — vecenv re-points obs_ptr
    // without a reset).
    env->v4_dirty[0] = 1;
    env->v4_dirty[1] = 1;
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
    // tds/score_diff are EPISODE deltas: TDs scored from the start state,
    // which is 0-0 from kickoff but the banked scores on a demo reset —
    // pre-resume human TDs are not the policy's doing. perf/win/draw above
    // stay on the absolute final scores (the match's real result).
    int d0 = m->score[0] - env->score_start[0];
    int d1 = m->score[1] - env->score_start[1];
    env->log.score_diff += (float)(d0 - d1);
    env->log.tds += (float)(d0 + d1);
    if (env->demo_started) env->log.demo_episodes += 1.0f;
    env->log.episode_return += env->ep_return[0];
    env->log.episode_length += (float)env->decisions;
    env->log.illegal_frac += env->decisions
                                 ? (float)env->illegal / (float)env->decisions
                                 : 0;
    env->log.blocks += (float)env->ep_blocks;
    env->log.blocks_thrown += (float)env->ep_blocks_thrown;
    if (env->ep_blocks_thrown > 0) {
        float tb = (float)env->ep_blocks_thrown;
        env->log.block_1d_frac += (float)env->ep_block_tier[0] / tb;
        env->log.block_2d_frac += (float)env->ep_block_tier[1] / tb;
        env->log.block_3d_frac += (float)env->ep_block_tier[2] / tb;
        env->log.block_2dred_frac += (float)env->ep_block_tier[3] / tb;
        env->log.block_3dred_frac += (float)env->ep_block_tier[4] / tb;
    }
    env->log.pickup_success += (float)env->ep_pickup_success;
    {
        int turns = env->ep_turns[0] + env->ep_turns[1];
        int held = env->ep_turns_with_ball[0] + env->ep_turns_with_ball[1];
        if (turns > 0) env->log.possession_rate += (float)held / (float)turns;
    }
    env->log.blitzes += (float)env->ep_blitzes;
    env->log.dodge_attempts += (float)env->ep_dodge_attempts;
    env->log.gfi_attempts += (float)env->ep_gfi_attempts;
    env->log.pickup_attempts += (float)env->ep_pickup_attempts;
    env->log.pass_attempts += (float)env->ep_pass_attempts;
    env->log.handoff_attempts += (float)env->ep_handoff_attempts;
    env->log.knockdowns_inflicted += (float)env->ep_knockdowns_inflicted;
    env->log.knockdowns_own += (float)env->ep_knockdowns_own;
    env->log.carrier_exposed_full += (float)env->ep_carrier_exposed_full;
    env->log.carrier_exposed_soft += (float)env->ep_carrier_exposed_soft;
    // --- Aggregate-statistic-matching pseudo-reward (D114) ------------------
    // Episode-end term = -scale * sqrt(sum_i z_i^2) over the 7 full-game stats,
    // z_i = (agent_stat_i - human_mean_i)/human_std_i. Pulls the policy's
    // full-game behavioral profile toward the FIXED human baseline
    // (docs/human-baseline.json). Diagonal-Mahalanobis / Z-score L2 — a RAW
    // episodic term, NOT PBRS. Stats are MATCH-LEVEL (both teams summed), the
    // same quantities the dashboard reports and the baseline was measured on,
    // so the single term is applied SYMMETRICALLY to both self-play agents.
    // Gate: only on kickoff-pure episodes (demo_started == 0) — curriculum
    // episodes are too short for full-game stat targets to be meaningful. MUST
    // be run with reward_possession == 0 (the annuity would dominate the joint
    // possession_rate target). See D114 for std-derivation reasoning.
    float statmatch = 0.0f;
    if (env->reward_statmatch_scale > 0.0f && !env->demo_started) {
        // Human baseline means (docs/human-baseline.json) and stds. No per-game
        // corpus was retained, so stds are a principled fallback (D114):
        //   counts (Poisson-like): std = sqrt(mean);
        //   fractions over n events: std = sqrt(p(1-p)/n)
        //     block_2dred over ~88.83 blocks/game; possession over ~35.66
        //     team-turns/game (453617 team-turns / 12722 games).
        // Order: tds, dodgeRoll, pickUpRoll, passRoll, goForItRoll,
        //        block_2dred_frac, possession_rate.
        static const float HB_MEAN[7] = {
            2.217f, 25.68f, 7.29f, 1.97f, 17.38f, 0.0169f, 0.378f };
        // block_2dred_frac's raw std (0.01368) is smaller than its mean and the
        // agent sits ~10x human, so its z dominates ~84% of ||z||^2 (D114's
        // flagged caveat) -- statmatch1 was effectively a 1-axis 2dred pull.
        // Floored to 0.05 (D118-A) for a more balanced 7-way pull in statmatch2;
        // statmatch1's own progress (0.0169 target, agent ~0.125 after 5B) means
        // this floor matters less than it did at the start.
        static const float HB_STD[7] = {
            1.4890f, 5.0675f, 2.7000f, 1.4036f, 4.1689f, 0.05000f, 0.08120f };
        // This episode's match-level stat vector (both teams).
        float ep_tds   = (float)((m->score[0] - env->score_start[0]) +
                                 (m->score[1] - env->score_start[1]));
        float ep_2dred = env->ep_blocks_thrown > 0
            ? (float)env->ep_block_tier[3] / (float)env->ep_blocks_thrown : 0.0f;
        int   tot_turns = env->ep_turns[0] + env->ep_turns[1];
        int   tot_held  = env->ep_turns_with_ball[0] + env->ep_turns_with_ball[1];
        float ep_poss  = tot_turns > 0 ? (float)tot_held / (float)tot_turns : 0.0f;
        float stat[7] = {
            ep_tds,
            (float)env->ep_dodge_attempts,
            (float)env->ep_pickup_attempts,
            (float)env->ep_pass_attempts,
            (float)env->ep_gfi_attempts,
            ep_2dred,
            ep_poss,
        };
        float ss = 0.0f;
        for (int i = 0; i < 7; i++) {
            float z = (stat[i] - HB_MEAN[i]) / HB_STD[i];
            ss += z * z;
        }
        statmatch = -env->reward_statmatch_scale * sqrtf(ss);
    }
    for (int a = 0; a < BBE_AGENTS; a++) {
        env->reward_ptr[a][0] += statmatch;
        env->ep_return[a]     += statmatch;
    }
    env->log.statmatch_term += statmatch;
    // episode_return was logged above from slot 0's pre-statmatch ep_return;
    // fold the statmatch term in so the dashboard's episode_return is total.
    env->log.episode_return += statmatch;
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
        if (act.arg == BB_ACT_BLOCK || act.arg == BB_ACT_BLITZ) {
            env->ep_team_contact[m->decision_team & 1]++;
            BBE_FEED(env, act.arg == BB_ACT_BLOCK ? BBE_EV_BLOCK_DECL
                                                  : BBE_EV_BLITZ_DECL,
                     -1, -1);
        }
        break;
    case BB_A_STEP: {
        // A STEP decision always comes from a MOVE frame (a = mover).
        const bb_frame* top = m->stack_top ? &m->stack[m->stack_top - 1] : 0;
        if (top && top->proc == BB_PROC_MOVE && top->a < BB_NUM_PLAYERS) {
            const bb_player* p = &m->players[top->a];
            if (p->moved >= p->ma) {
                env->ep_gfi_attempts++;
                BBE_FEED(env, BBE_EV_GFI, top->a, -1);
                if (env->reward_rush_cost != 0.0f) {
                    int rt = BB_TEAM_OF(top->a);
                    env->reward_ptr[rt][0] -= env->reward_rush_cost;
                    env->ep_return[rt] -= env->reward_rush_cost;
                }
            }
            if (bb_tackle_zones(m, BB_TEAM_OF(top->a), p->x, p->y) > 0) {
                env->ep_dodge_attempts++;
                BBE_FEED(env, BBE_EV_DODGE, top->a, -1);
            }
            // Ball-engagement axis: carrying the ball forward counts 1/step,
            // attempting a pickup counts 3 (rare, decisive events weigh more).
            if (p->flags & BB_PF_HAS_BALL) {
                env->ep_team_ball[BB_TEAM_OF(top->a)]++;
            }
        }
        if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == act.x &&
            m->ball.y == act.y) {
            env->ep_pickup_attempts++;
            if (top && top->proc == BB_PROC_MOVE && top->a < BB_NUM_PLAYERS) {
                env->ep_team_ball[BB_TEAM_OF(top->a)] += 3;
                env->pending_pickup_slot = top->a; // success judged post-apply
                BBE_FEED(env, BBE_EV_PICKUP_TRY, top->a, -1);
            }
        }
        break;
    }
    case BB_A_PASS_TARGET:
        env->ep_pass_attempts++;
        env->ep_team_ball[m->decision_team & 1] += 3;
        BBE_FEED(env, BBE_EV_PASS,
                 m->ball.state == BB_BALL_HELD ? m->ball.carrier : -1, -1);
        break;
    case BB_A_HANDOFF_TARGET:
        env->ep_handoff_attempts++;
        BBE_FEED(env, BBE_EV_HANDOFF,
                 m->ball.state == BB_BALL_HELD ? m->ball.carrier : -1, -1);
        break;
    case BB_A_CHOOSE_DIE: {
        // Exactly one die pick per RESOLVED block (incl. the Frenzy second
        // block) — the clean denominator for knockdown-conversion claims
        // (panel: declarations include blitzes that never reach a block).
        env->ep_blocks_thrown++;
        const bb_frame* bf = m->stack_top ? &m->stack[m->stack_top - 1] : 0;
        BBE_FEED(env, BBE_EV_BLOCK_THROWN, bf ? bf->a : -1, bf ? bf->b : -1);
        if (bf) {
            int nd = ((bf->data >> 9) & 3) + 1;
            int red = (bf->data & (1u << 11)) != 0; // BLK_DEF_CHOOSES
            int tier = nd == 1 ? 0 : (nd == 2 ? (red ? 3 : 1) : (red ? 4 : 2));
            env->ep_block_tier[tier]++;
        }
        break;
    }
    default:
        break;
    }
}

// Live behavior archetype for the spectator's per-team plates. Pure read;
// thresholds calibrated against measured baselines (D33 probe: random play
// ~8 contact declarations/episode across both teams; D34 bruiser ~17;
// trained scorers carry the ball every drive but rarely declare blocks).
// turns_seen normalizes demo-started episodes that begin mid-game.
static const char* bbe_team_archetype(const Bloodbowl* env, int t) {
    const bb_match* m = &env->match;
    int turns_now = (m->half - 1) * 8 + m->turn[t];
    int turns_seen = turns_now - env->turns_at_reset[t] + 1;
    if (turns_seen < 3) return "SIZING UP...";
    float contact_rate = (float)env->ep_team_contact[t] / (float)turns_seen;
    int ball_engaged = env->ep_team_ball[t] >= 6; // ~pickup + 3 carried squares
    int contact_heavy = contact_rate >= 0.4f;     // ~6+ declarations/half
    if (contact_heavy && ball_engaged) return "ALL-ROUNDER";
    if (contact_heavy) return "BRUISER";
    if (ball_engaged) return "BALLHAWK";
    if (env->ep_team_contact[t] == 0 && turns_seen >= 5) return "COWARD";
    return "TIMID";
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
        // Profile C: decision-time exposure transfer + sequencing charge,
        // priced on the PRE-apply state (the declaration IS the decision —
        // no dice have rolled yet). Standing attackers only: a prone Jump-Up
        // block routes through an extra gating test (rare; unpriced v1).
        if ((env->reward_k_kd != 0.0f || env->reward_k_value != 0.0f ||
             env->reward_k_ball != 0.0f || env->reward_k_seq != 0.0f) &&
            act.type == BB_A_BLOCK_TARGET && m->stack_top > 0) {
            const bb_frame* mf = &m->stack[m->stack_top - 1];
            int batt = mf->a;
            int bdef = bb_slot_at(m, act.x, act.y);
            if (mf->proc == BB_PROC_MOVE && bdef != BB_NO_PLAYER &&
                m->players[batt].stance == BB_STANCE_STANDING) {
                bb_blockev ev;
                // Choice nodes use the spec-default weights (stable play
                // model); the env knobs only scale the priced transfer.
                int is_blitz = mf->b == BB_ACT_BLITZ;
                if (env->ev_mover == batt && env->ev_blitz == is_blitz &&
                    ((env->ev_valid >> bdef) & 1u)) {
                    ev = env->ev_cache[bdef]; // filled by this decision's encode
#ifdef BBE_EV_CACHE_CHECK
                    bb_blockev chk;
                    bb_block_ev(m, batt, bdef, is_blitz, NULL, &chk);
                    if (memcmp(&chk, &ev, sizeof ev) != 0) {
                        fprintf(stderr, "EV CACHE MISMATCH att=%d def=%d\n",
                                batt, bdef);
                        abort();
                    }
#endif
                } else {
                    bb_block_ev(m, batt, bdef, is_blitz, NULL, &ev);
                }
                int bteam = BB_TEAM_OF(batt);
                // Rush gate (panel HIGH): a blitz block declared with no
                // movement left rolls a 2+ Rush FIRST; failure = knocked
                // down in place, NO block (proc_move.c BB_A_BLOCK_TARGET).
                // Price the block tree scaled by P(rush succeeds) — else the
                // attacker banks exposure for blocks that fizzle 1/6+ of the
                // time (a farmable zero-sum subsidy) — and fold the
                // rush-failure turnover (knockdown of the active blitzer,
                // saved only by Steady Footing) into the sequencing charge.
                float p_deliver = 1.0f;
                float p_own_to = ev.p_turnover;
                if (is_blitz && movement_left(m, batt) == 0) {
                    const bb_player* bp = &m->players[batt];
                    bb_ctx rc = {BB_TEST_RUSH, (uint8_t)batt, BB_NO_PLAYER,
                                 (uint8_t)batt, (int8_t)bp->x, (int8_t)bp->y,
                                 (int8_t)bp->x, (int8_t)bp->y, -1, 1};
                    int rmod = bb_hook_mods(m, &rc);
                    if (m->weather == BB_WEATHER_BLIZZARD) rmod -= 1;
                    p_deliver = (float)(7 - bb_test_target(2, rmod)) / 6.0f;
                    float sf =
                        bb_has_skill(&bp->skills, BB_SK_STEADY_FOOTING)
                            ? 5.0f / 6.0f
                            : 1.0f;
                    p_own_to = p_deliver * ev.p_turnover +
                               (1.0f - p_deliver) * sf;
                }
                float exposure =
                    p_deliver *
                    (env->reward_k_kd * ev.p_def_down +
                     env->reward_k_value * ev.p_def_removed *
                         player_cost_100k(m, bdef) + // bb_blockev.c (same TU)
                     env->reward_k_ball * ev.p_ball_out);
                env->reward_ptr[bteam][0] += exposure;
                env->reward_ptr[1 - bteam][0] -= exposure;
                env->ep_return[bteam] += exposure;
                env->ep_return[1 - bteam] -= exposure;
                // Sequencing charge: own-turnover risk x unbanked safe
                // activations; exempt on the team's last turn of the half
                // and during Charge! free activations (panel: a Charge!
                // turnover ends only the few free activations, not the
                // team's real turn — full `pending` overstates the stake).
                if (env->reward_k_seq != 0.0f && m->turn[bteam] < 8 &&
                    !bb_in_kickoff_charge(m)) {
                    int pending = 0;
                    for (int s = bteam * BB_TEAM_SLOTS;
                         s < (bteam + 1) * BB_TEAM_SLOTS; s++) {
                        if (s == batt) continue;
                        const bb_player* sp = &m->players[s];
                        pending += sp->location == BB_LOC_ON_PITCH &&
                                   sp->stance == BB_STANCE_STANDING &&
                                   !(sp->flags & BB_PF_USED);
                    }
                    float seq = env->reward_k_seq * p_own_to * (float)pending;
                    env->reward_ptr[bteam][0] -= seq;
                    env->ep_return[bteam] -= seq;
                }
            }
        }
        uint32_t was_standing = bbe_standing_mask(m);
        // Trusted fast path: act came from bbe_decode, which only returns
        // elements of env->legal — the legal set enumerated on THIS state by
        // bbe_refresh_legal. Membership holds by construction, so skip
        // bb_apply's internal re-enumeration + eq-scan (~22% of step time).
        // All other callers (tests, fuzz, lockstep) stay on checked bb_apply.
        bb_apply_trusted(m, act, &env->rng);
        env->ev_valid = 0; // state advanced: encode-time EVs are stale
        env->decisions++;
        // Pickup success: the attempted scooper holds the ball post-apply.
        if (env->pending_pickup_slot >= 0) {
            if (m->ball.state == BB_BALL_HELD &&
                m->ball.carrier == (uint8_t)env->pending_pickup_slot) {
                env->ep_pickup_success++;
                BBE_FEED(env, BBE_EV_PICKUP_OK, env->pending_pickup_slot, -1);
            }
            env->pending_pickup_slot = -1;
        }
        // v5 macro-moves (D82): follow the planned path while uninterrupted.
        // One policy decision = the whole move; control returns on any TEST
        // window, knockdown, occupied square, or activation end. Post-loop
        // accounting is state-diff based so it stays correct across the
        // macro; per-step metrics/taxes go through bbe_count_action.
        if (env->macro_moves && env->macro_pos < env->macro_len) {
            while (env->macro_pos < env->macro_len &&
                   env->decisions < env->max_decisions &&
                   m->status == BB_STATUS_DECISION && m->stack_top > 0) {
                const bb_frame* tf = &m->stack[m->stack_top - 1];
                if (tf->proc != BB_PROC_MOVE ||
                    (int)tf->a != env->macro_mover) break;
                // mirror move_legal's may_move gate (Codex HIGH): plain
                // BLOCK activations and post-pickup TTM/KTM cannot step
                if (tf->b == BB_ACT_BLOCK || (tf->data & MV_BLOCK_DONE)) break;
                int nx = env->macro_px[env->macro_pos];
                int ny = env->macro_py[env->macro_pos];
                if (!bb_on_pitch_xy(nx, ny) || m->grid[nx][ny]) break;
                if (!can_step(m, env->macro_mover)) break;
                bb_action mact = {BB_A_STEP, 0, (uint8_t)nx, (uint8_t)ny};
                bbe_count_action(env, mact);
                bb_apply_trusted(m, mact, &env->rng);
                bbe_macro_dbg_steps++;
                if ((bbe_macro_dbg_steps % 200000) == 1)
                    fprintf(stderr, "[MACRO] plans=%ld cont_steps=%ld\n",
                            bbe_macro_dbg_plans, bbe_macro_dbg_steps);
                env->ev_valid = 0;
                env->reach_mover = -1;
                env->decisions++;
                env->macro_pos++;
                if (env->pending_pickup_slot >= 0) {
                    if (m->ball.state == BB_BALL_HELD &&
                        m->ball.carrier == (uint8_t)env->pending_pickup_slot) {
                        env->ep_pickup_success++;
                        BBE_FEED(env, BBE_EV_PICKUP_OK,
                                 env->pending_pickup_slot, -1);
                    }
                    env->pending_pickup_slot = -1;
                }
            }
            env->macro_len = 0;
            env->macro_pos = 0;
        }
        env->reach_mover = -1;  // state advanced: reachability is stale
        // Possession-rate bookkeeping: when the active team flips, the
        // previous team's turn ENDED — score whether they ended it holding,
        // and pay the possession annuity transfer (see reward_possession).
        if ((int)m->active_team != env->prev_active_team) {
            int t = env->prev_active_team & 1;
            env->ep_turns[t]++;
            // Possession METRIC (D90, Alex): a turn that ends in your own
            // touchdown counts as ending WITH possession — you carried it in.
            // Metric only; the annuity transfer below still requires HELD
            // (reward_td already pays the score).
            if (m->score[t] > env->score_prev[t]) {
                env->ep_turns_with_ball[t]++;
            } else if (m->ball.state == BB_BALL_HELD &&
                BB_TEAM_OF(m->ball.carrier) == t) {
                env->ep_turns_with_ball[t]++;
                if (env->reward_possession != 0.0f) {
                    env->reward_ptr[t][0] += env->reward_possession;
                    env->reward_ptr[1 - t][0] -= env->reward_possession;
                    env->ep_return[t] += env->reward_possession;
                    env->ep_return[1 - t] -= env->reward_possession;
                }
            }
            if (env->reward_carrier_exposure != 0.0f ||
                env->reward_carrier_exposure_soft != 0.0f) {
                bb_carrier_exposure ex = bb_carrier_exposure_eval(m, t);
                if (ex.full) {
                    if (env->reward_carrier_exposure != 0.0f) {
                        env->reward_ptr[t][0] -= env->reward_carrier_exposure;
                        env->ep_return[t] -= env->reward_carrier_exposure;
                        env->ep_carrier_exposed_full++;
                    }
                } else if (ex.soft && env->reward_carrier_exposure_soft != 0.0f) {
                    env->reward_ptr[t][0] -= env->reward_carrier_exposure_soft;
                    env->ep_return[t] -= env->reward_carrier_exposure_soft;
                    env->ep_carrier_exposed_soft++;
                }
            }
            env->prev_active_team = (int)m->active_team;
        }
        bbe_count_knockdowns(env, was_standing, agent);
        // Touchdown rewards.
        bool scored = false;
        for (int t = 0; t < 2; t++) {
            int d = m->score[t] - env->score_prev[t];
            if (d > 0) {
                scored = true;
                BBE_FEED(env, BBE_EV_TD,
                         m->ball.state == BB_BALL_HELD ? m->ball.carrier : -1,
                         -1);
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
                        // Bounds-clamped lookup (bb_blockev.c, same TU) —
                        // demo-bank records carry raw index bytes.
                        weight += player_cost_100k(m, s);
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

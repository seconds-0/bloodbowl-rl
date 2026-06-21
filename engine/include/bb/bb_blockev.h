// bb_blockev.h — closed-form, skill-transformed block outcome probabilities,
// evaluated at DECLARATION time (zero dice). Powers the Profile C exposure-EV
// transfer and the sequencing charge (docs/reward-audit-decision-time.md).
//
// The evaluator walks the one-block face tree exactly as proc_block.c
// resolves it — dice pool from ST + assists (+Horns on blitz, latched
// Cheering Fans, Dauntless as a closed-form mixture), per-face skill
// transforms (Block / Wrestle / Dodge-vs-Tackle / Juggernaut / Strip Ball /
// Steady Footing), armour with the engine's exact Mighty-Blow auto-policy and
// Claws, injury bands with Thick Skull / Stunty — and resolves CHOICE nodes
// (die pick, the D29 Wrestle use/decline windows) OWNER-OPTIMALLY under the
// zero-sum utility below, per the spec's "owner-optimal, not fixed-rule"
// requirement.
//
// Choice-node utility (attacker maximizes, defender minimizes):
//   U = k_kd    * (P(def down)    - P(att down))
//     + k_value * (P(def removed)*cost_def - P(att removed)*cost_att) / 100
//     + k_ball  * P(ball dislodged from the defender)
//     - k_to    * P(attacker-caused turnover)
// The emitted probabilities are exact under these choice policies; the
// acceptance suite pins the weight-independent dominance cases (the
// 2dB-2.8%-vs-3d-3.7% turnover inversion is Addendum 3's mandatory test).
//
// v1 scope (documented approximations — every one is a conscious cut):
//  - NO rerolls in the priced tree (team / Brawler / Pro): prices the
//    no-reroll line. Reroll-aware pricing is a v2 layer.
//  - Frenzy's mandatory second block is evaluated with the SAME pool
//    geometry (assists are not recomputed after the push relocation).
//  - KO counts as removal (the apothecary KO-patch window is ignored).
//  - Block preambles are not priced: Foul Appearance, Dump-Off, Trickster.
//  - Stand Firm appears only as the carrier's Strip-Ball cancel (a carrier
//    with the option always declines the pushback); push GEOMETRY (surf,
//    chains) is the surf knob's domain, not this evaluator's.
//  - Saboteur is ignored (rare trait, off-roster).
//  - The attacker is charged turnover only when their team is active.
#ifndef BB_BLOCKEV_H
#define BB_BLOCKEV_H

#include "bb_match.h"

typedef struct {
    float p_def_down;     // defender Knocked Down (armour sequence runs)
    float p_att_down;     // attacker Knocked Down
    float p_def_removed;  // defender leaves the pitch (KO or CAS band)
    float p_att_removed;  // attacker leaves the pitch
    float p_ball_out;     // ball leaves the defender's grip (0 if not carrying)
    float p_turnover;     // active-team turnover from this block's own dice
} bb_blockev;

typedef struct {
    float k_kd;    // tactical value of a knockdown          (spec: 0.06)
    float k_value; // removal priced by victim cost/100k     (spec: 0.5)
    float k_ball;  // carrier dislodge premium               (spec: 0.3)
    float k_to;    // turnover aversion, choice-ordering only (default 0.3)
} bb_blockev_w;

// Spec-default weights.
bb_blockev_w bb_blockev_w_default(void);

// Evaluate a declared block (att -> def, is_blitz per the declaration) from
// the current state. Pure: no RNG, no state mutation.
void bb_block_ev(const bb_match* m, int att, int def, int is_blitz,
                 const bb_blockev_w* w, bb_blockev* out);

// Contact favorability potential: sum, over `team`'s standing on-pitch
// players currently adjacent to standing enemies, of that player's best
// adjacent no-blitz P(defender down). Pure and bounded to existing contacts.
float bb_team_contact_favorability(const bb_match* m, int team);

// Choice-policy introspection for the Monte Carlo differential
// (tools/blockev_mc.c): the per-face utilities (attacker's perspective,
// indexed by bb_block_die 1..6, Both Down already minimax-resolved) and the
// Wrestle-window decisions. The MC driver replays the REAL engine making
// exactly these choices, so any frequency mismatch is tree-math drift, not
// policy disagreement.
typedef struct {
    float face_u[7];   // [1..6]; chooser takes max (attacker) / min (defender)
    int att_wrestles;  // attacker's Both-Down window: use Wrestle?
    int def_wrestles;  // defender's window (reached only if attacker declines)
} bb_blockev_policy;

// frenzy_done: evaluating the mandatory SECOND block (its push utility must
// not chain a third) — pass 1 there, 0 for a fresh declaration.
void bb_block_ev_policy(const bb_match* m, int att, int def, int is_blitz,
                        int frenzy_done, const bb_blockev_w* w,
                        bb_blockev_policy* out);

// Shared closed forms (also used by tests and the foul exposure):
// P(armour breaks | victim knocked down by causer); mb_on_injury_out (may be
// NULL) receives P(Mighty Blow still unspent | broken) for the injury stage.
float bb_ev_armour_break(const bb_match* m, int victim, int causer,
                         float* mb_on_injury_out);
// P(victim leaves pitch | knocked down by causer) — armour x injury bands.
float bb_ev_removal(const bb_match* m, int victim, int causer);

#endif // BB_BLOCKEV_H

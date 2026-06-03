// skills_core.c — high-impact skill/trait implementations (hook registrations).
//
// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
// core_rules/skills_and_traits) it implements. Block-face skills (Block,
// Wrestle, Tackle, Dodge-on-Stumble, Guard assists) live in proc_block.c via
// bb_skills.h queries; this file covers the registration-table classes.
#include "bb/bb_hooks.h"
#include "bb/bb_proc.h"

// --- Re-roll grants -----------------------------------------------------------
// DODGE: "Once per Turn ... may re-roll a single Agility Test when attempting
// to Dodge."
BB_SKILL_REROLL(DODGE, 1u << BB_TEST_DODGE)
// SURE FEET: "Once per Turn ... may re-roll the D6 when attempting to Rush."
BB_SKILL_REROLL(SURE_FEET, 1u << BB_TEST_RUSH)
// SURE HANDS: "may re-roll any failed attempt to pick up the ball" (not
// once-per-turn limited; the once-per-test limit still applies).
BB_SKILL_REROLL(SURE_HANDS, 1u << BB_TEST_PICKUP)
// PASS: "may re-roll a failed Passing Ability Test when performing a Pass".
BB_SKILL_REROLL(PASS, 1u << BB_TEST_PASS)
// CATCH: "This player may re-roll any failed Agility Test when attempting to
// Catch the ball." Interception attempts are NOT Catch attempts in BB2025
// (Disturbing Presence / Extra Arms / Stunty name Intercept separately):
// the dispatcher (bb_hook_reroll) excludes CATCH-kind tests whose ctx
// carries a thrower in `other`. (adversarial review M11)
BB_SKILL_REROLL(CATCH, 1u << BB_TEST_CATCH)

// --- Test modifiers -------------------------------------------------------------
// TWO HEADS: "+1 modifier to the Agility Test when this player attempts to
// Dodge."
BB_SKILL_MOD(TWO_HEADS) {
    (void)m;
    return c->kind == BB_TEST_DODGE ? 1 : 0;
}

// EXTRA ARMS: "+1 modifier when this player attempts to pick up or Catch the
// ball."
BB_SKILL_MOD(EXTRA_ARMS) {
    (void)m;
    return (c->kind == BB_TEST_PICKUP || c->kind == BB_TEST_CATCH) ? 1 : 0;
}

// BIG HAND: "This player ignores all negative modifiers when attempting to
// pick up the ball." The engine's negative pickup modifiers are the Marking
// -1s and Pouring Rain's -1 (the call sites add rain BEFORE this hook runs),
// so the refund covers both. (adversarial review M13)
BB_SKILL_MOD(BIG_HAND) {
    if (c->kind != BB_TEST_PICKUP) return 0;
    int neg = bb_tackle_zones(m, BB_TEAM_OF(c->player), c->to_x, c->to_y);
    if (m->weather == BB_WEATHER_RAIN) neg += 1;
    return neg;
}

// ACCURATE: "+1 modifier when this player makes a Passing Ability Test for a
// Quick Pass or a Short Pass."
BB_SKILL_MOD(ACCURATE) {
    (void)m;
    return (c->kind == BB_TEST_PASS && c->range_band <= 1) ? 1 : 0;
}

// CANNONEER: "+1 modifier ... for a Long Pass or a Long Bomb."
BB_SKILL_MOD(CANNONEER) {
    (void)m;
    return (c->kind == BB_TEST_PASS && c->range_band >= 2) ? 1 : 0;
}

// NERVES OF STEEL: "This player may ignore any modifiers for being Marked
// when making an Agility Test to Catch the ball, or when making a Passing
// Ability Test to Pass the ball." The BB2025 text has NO Intercept clause
// (unlike BB2020): an interception attempt — a CATCH-kind test whose ctx
// carries the thrower in `other` — keeps its Marking penalties.
// (adversarial review M11)
BB_SKILL_MOD(NERVES_OF_STEEL) {
    if (c->kind != BB_TEST_PASS && c->kind != BB_TEST_CATCH) return 0;
    if (c->kind == BB_TEST_CATCH && c->other != BB_NO_PLAYER)
        return 0; // interception, not a Catch
    const bb_player* p = &m->players[c->player];
    return bb_tackle_zones(m, BB_TEAM_OF(c->player), p->x, p->y);
}

// --- Auras ----------------------------------------------------------------------
// DISTURBING PRESENCE: "any opposition player ... must apply a -1 modifier
// when they make a Passing Ability Test, or attempt to Catch or Intercept,
// for each player on your team with this skill within three squares of them."
BB_SKILL_AURA(DISTURBING_PRESENCE) {
    if (c->kind != BB_TEST_PASS && c->kind != BB_TEST_CATCH) return 0;
    const bb_player* src = &m->players[c->other];   // aura source
    const bb_player* act = &m->players[c->player];  // acting player
    if (BB_TEAM_OF(c->other) == BB_TEAM_OF(c->player)) return 0;
    if (src->stance == BB_STANCE_STUNNED || src->stance == BB_STANCE_STUNNED_USED)
        return 0; // stunned players' DP still applies when prone per FAQ; not stunned? TODO-verify
    int dx = src->x - act->x, dy = src->y - act->y;
    if (dx < 0) dx = -dx;
    if (dy < 0) dy = -dy;
    int cheb = dx > dy ? dx : dy;
    return cheb <= 3 ? -1 : 0;
}

// --- Activation gates --------------------------------------------------------------
// BONE HEAD: "roll a D6 ... on a 1, the player forgets what they are doing:
// their activation ends immediately and they lose their Tackle Zone."
BB_SKILL_GATE(BONE_HEAD, 2, BB_GATE_LOSE_ACT_AND_TZ)
// REALLY STUPID: fails on 1-3 unless assisted by a team-mate (assist handling
// is a TODO refine: gate target 4 without adjacency check yet).
BB_SKILL_GATE(REALLY_STUPID, 4, BB_GATE_LOSE_ACT_AND_TZ)
// UNCHANNELLED FURY: "on a 1-3 ... unless taking a Block or Blitz action".
// Action-conditional gates are refined with the declaration rework; gate 4
// approximates and is flagged for the differential harness.
BB_SKILL_GATE(UNCHANNELLED_FURY, 4, BB_GATE_LOSE_ACTIVATION)

// --- Push-interaction skills -----------------------------------------------------
// STAND FIRM: "may choose to not be pushed back" (always-on here; the choice
// to decline is a TODO decision window).
BB_SKILL_PUSHF(STAND_FIRM, BB_PUSHF_STAND_FIRM)
// SIDE STEP: "the player's coach chooses which square the player is moved to,
// and it can be any adjacent unoccupied square."
BB_SKILL_PUSHF(SIDESTEP, BB_PUSHF_SIDE_STEP)
// FEND: "the attacking player may not follow up."
BB_SKILL_PUSHF(FEND, BB_PUSHF_FEND)
// GRAB / JUGGERNAUT carry their effects via attacker-side checks in
// proc_block.c (registered here for the table's completeness).
BB_SKILL_PUSHF(GRAB, BB_PUSHF_GRAB)
BB_SKILL_PUSHF(JUGGERNAUT, BB_PUSHF_JUGGERNAUT)

// HORNS: "+1 to their Strength ... when they perform a Block as part of a
// Blitz Action."
BB_SKILL_ST_BLITZ(HORNS, 1)

// BREAK TACKLE: "Once during their activation, when this player makes an
// Agility Test in order to Dodge, they may apply a +1 modifier if their
// Strength is 4 or less, or a +2 modifier if their Strength is 5 or more."
// (Always-on approximation: at most one dodge per step sequence benefits per
// activation in practice almost always; exact once-per-activation latch is a
// TODO flagged for the FUMBBL differential.)
BB_SKILL_MOD(BREAK_TACKLE) {
    if (c->kind != BB_TEST_DODGE) return 0;
    return m->players[c->player].st >= 5 ? 2 : 1;
}

// TAKE ROOT: "roll a D6 ... On a 1, the player becomes Rooted" — gate target 2
// with the ROOTED failure kind (acts in place; unpushable; un-roots on going
// down or at the end of the drive).
BB_SKILL_GATE(TAKE_ROOT, 2, BB_GATE_ROOTED)

// LEAP: jumping may cross ANY single adjacent square (legality in proc_move)
// and "may reduce the negative modifiers ... by 1, to a minimum of -1" —
// approximated as +1 on the jump test (exact min--1 clamping TODO: needs the
// pre-hook modifier total in ctx).
BB_SKILL_MOD(LEAP) {
    (void)m;
    return c->kind == BB_TEST_JUMP ? 1 : 0;
}

// POGO: "may ignore all negative modifiers they would receive by Jumping" —
// approximated by cancelling the marker-derived modifier.
BB_SKILL_MOD(POGO) {
    if (c->kind != BB_TEST_JUMP) return 0;
    int from_tz = bb_tackle_zones(m, BB_TEAM_OF(c->player), c->from_x, c->from_y);
    int to_tz = bb_tackle_zones(m, BB_TEAM_OF(c->player), c->to_x, c->to_y);
    return from_tz > to_tz ? from_tz : to_tz;
}

// TIMMM-BER!: "+1 modifier to the roll for standing up for each Open Standing
// team-mate adjacent to this player."
BB_SKILL_MOD(TIMMM_BER) {
    if (c->kind != BB_TEST_STANDUP) return 0;
    const bb_player* p = &m->players[c->player];
    int n = 0;
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int x = p->x + dx, y = p->y + dy;
            if (!bb_on_pitch_xy(x, y)) continue;
            int s = bb_slot_at(m, x, y);
            if (s >= 0 && BB_TEAM_OF(s) == BB_TEAM_OF(c->player) &&
                m->players[s].stance == BB_STANCE_STANDING &&
                !bb_is_marked(m, s)) {
                n++;
            }
        }
    }
    return n;
}

// STUNTY: "When this player attempts to Dodge, they do not suffer any
// negative modifiers to their Agility Test for being Marked by opposition
// players. Additionally, this player applies a -1 modifier to the Agility
// Test when attempting to Intercept the ball."
BB_SKILL_MOD(STUNTY) {
    if (c->kind == BB_TEST_DODGE) {
        return bb_tackle_zones(m, BB_TEAM_OF(c->player), c->to_x, c->to_y);
    }
    if (c->kind == BB_TEST_CATCH && c->other != BB_NO_PLAYER) {
        return -1; // interception attempt (ctx carries the thrower)
    }
    return 0;
}

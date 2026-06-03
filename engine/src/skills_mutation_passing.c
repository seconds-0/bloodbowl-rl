// skills_mutation_passing.c — MUTATION and PASSING category skill
// implementations (hook registrations).
//
// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
// core_rules/skills_and_traits) it implements. The other not-yet-implemented
// skills of these categories (Foul Appearance, Iron Hard Skin, Monstrous
// Mouth, Tentacles, Cloud Burster, Dump-Off, Give and Go, Hail Mary Pass,
// Leader, On the Ball, Punt, Safe Pass) require new procedure integration
// (pre-block interrupts, pass-sequence/armour-sequence changes, activation
// continuation, special actions) and are intentionally NOT registered here.
#include "bb/bb_hooks.h"
#include "bb/bb_proc.h"

// --- Auras ----------------------------------------------------------------------

// PREHENSILE TAIL: "When an opposition player attempts to Dodge, Jump or Leap
// away from a square in this player's Tackle Zone, they apply an additional
// -1 modifier to the Agility Test. If a player tries to leave the Tackle Zone
// of multiple players with this Skill at the same time, only one of those
// players may use this Skill."
// Jump/Leap Agility Tests do not exist yet (jump is proc_move phase 3); this
// hook covers the Dodge test, keyed on the square being LEFT (c->from), not
// the destination. The only-one rule is enforced by letting only the
// lowest-slot qualifying tail contribute its -1.
static bool tail_marks_left_square(const bb_match* m, int src, const bb_ctx* c) {
    if (BB_TEAM_OF(src) == BB_TEAM_OF(c->player)) return false;
    if (!bb_has_skill(&m->players[src].skills, BB_SK_PREHENSILE_TAIL)) return false;
    if (!bb_exerts_tz(m, src)) return false; // prone/distracted: no Tackle Zone
    int dx = m->players[src].x - c->from_x;
    int dy = m->players[src].y - c->from_y;
    if (dx < 0) dx = -dx;
    if (dy < 0) dy = -dy;
    return (dx | dy) != 0 && dx <= 1 && dy <= 1;
}

BB_SKILL_AURA(PREHENSILE_TAIL) {
    if (c->kind == BB_TEST_JUMP) {
        // "-1 modifier ... when they attempt to Dodge, Jump or Leap to leave
        // this player's Tackle Zone."
        const bb_player* src0 = &m->players[c->other];
        if (BB_TEAM_OF(c->other) == BB_TEAM_OF(c->player)) return 0;
        if (!bb_exerts_tz(m, c->other)) return 0;
        if (bb_adjacent(src0->x, src0->y, c->from_x, c->from_y)) return -1;
        return 0;
    }
    if (c->kind != BB_TEST_DODGE) return 0;
    if (!tail_marks_left_square(m, c->other, c)) return 0;
    // "only one of those players may use this Skill": the lowest-slot
    // qualifying tail is the canonical user; every other tail abstains.
    for (int s = 0; s < c->other; s++) {
        if (tail_marks_left_square(m, s, c)) return 0;
    }
    return -1;
}

// --- Test modifiers -------------------------------------------------------------

// VERY LONG LEGS: "This player may apply a +1 modifier to the Agility Test
// whenever they attempt to Leap or Jump, and may apply a +2 modifier to the
// Agility Test whenever they attempt to Intercept the ball. Additionally,
// this player ignores the Cloud Burster Skill."
// Interceptions are dispatched as BB_TEST_CATCH with c->other = the thrower
// (proc_ball.c pass_start_interception); ordinary catches pass BB_NO_PLAYER.
// The +1 for Leap/Jump awaits BB_TEST kinds for those moves; the Cloud
// Burster interaction awaits Cloud Burster's interception-eligibility
// integration.
BB_SKILL_MOD(VERY_LONG_LEGS) {
    // "+1 modifier ... when they attempt to Jump or Leap."
    if (c->kind == BB_TEST_JUMP) return 1;
    (void)m;
    if (c->kind == BB_TEST_CATCH && c->other != BB_NO_PLAYER) return 2;
    return 0;
}

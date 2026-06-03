// skills_devious_traits.c — Devious-category skills and Traits (hook
// registrations).
//
// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
// core_rules/skills_and_traits) it implements. Most of the Devious category
// (fouling decision windows, push-back conditions) and most Traits (Special
// Actions, activation interrupts, Throw Team-mate) need new procedure
// integration and are deliberately NOT registered here — they are tracked in
// the batch report. This file covers the registration-table classes only.
#include "bb/bb_hooks.h"

// --- Test modifiers -----------------------------------------------------------
// TITCHY: "A player with this Trait may apply a +1 modifier to the Agility
// Test when attempting to Dodge."
BB_SKILL_MOD(TITCHY) {
    (void)m;
    return c->kind == BB_TEST_DODGE ? 1 : 0;
}

// DRUNKARD: "This player applies a -1 modifier to test whenever they attempt
// to Rush." LIVE: all four Rush call sites in proc_move.c (step, jump-rush
// chain, jump apply, rush-for-block) build a BB_TEST_RUSH bb_ctx and consult
// bb_hook_mods, so this -1 fires there — do NOT add a second inline -1 at
// the call sites. (A stale "dead code" note here previously claimed the
// opposite; adversarial review LOW.)
BB_SKILL_MOD(DRUNKARD) {
    (void)m;
    return c->kind == BB_TEST_RUSH ? -1 : 0;
}

// --- Auras ----------------------------------------------------------------------
// TITCHY (second clause): "However, when an opposition player attempts to
// Dodge into a square within this player's Tackle Zone, this player will not
// apply a -1 modifier to the opposition player's Agility Test for Marking
// the opposition player." The base Dodge modifier is -1 per opponent Marking
// the destination square (proc_move subtracts bb_tackle_zones at the
// destination), so a Titchy player Marking the destination contributes +1
// here, cancelling exactly their own -1. A Titchy player exerting no Tackle
// Zone (Prone, Stunned, Distracted) contributes no -1 and therefore no +1.
// A STUNTY dodger already refunds EVERY Marking -1 through its own mod
// (skills_core.c), Titchy markers included — there is no -1 left for this
// aura to withhold, so it must contribute nothing (else the two "withhold
// the -1" effects would stack into a net +1; adversarial review M9).
BB_SKILL_AURA(TITCHY) {
    if (c->kind != BB_TEST_DODGE) return 0;
    if (BB_TEAM_OF(c->other) == BB_TEAM_OF(c->player)) return 0;
    if (!bb_exerts_tz(m, c->other)) return 0; // not Marking: no -1 to cancel
    if (bb_has_skill(&m->players[c->player].skills, BB_SK_STUNTY))
        return 0; // Stunty's own mod already cancelled this -1 (review M9)
    const bb_player* t = &m->players[c->other];
    int dx = t->x - c->to_x, dy = t->y - c->to_y;
    if (dx < 0) dx = -dx;
    if (dy < 0) dy = -dy;
    int cheb = dx > dy ? dx : dy;
    return cheb == 1 ? 1 : 0; // Marking the destination square
}

// --- Roster-construction traits (no match-time hook) ---------------------------
// INSIGNIFICANT: "When creating a Team Draft List, you may not include more
// players with this Trait than players without this Trait." A pure team-draft
// constraint with no in-match effect: nothing to register. The constraint
// belongs to the roster builder / procedural team generator (Phase 5).

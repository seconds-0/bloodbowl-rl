#include "bb/bb_skills.h"
#include "bb/bb_proc.h"
#include "bb/bb_hooks.h"

int bb_skill_reroll_for(const bb_match* m, int slot, int kind) {
    // Re-roll grants live in the hook registration table (skills_core.c
    // registers Dodge/Sure Feet/Sure Hands/Pass/Catch; further skills register
    // themselves). Once-per-turn latching is enforced by bb_hook_reroll.
    return bb_hook_reroll(m, slot, kind);
}

int bb_loner_value(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    if (!bb_has_skill(&p->skills, BB_SK_LONER)) return 0;
    return p->p_loner > 0 ? p->p_loner : 4;
}

int bb_max_rushes(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    return bb_has_skill(&p->skills, BB_SK_SPRINT) ? 3 : 2;
}

bool bb_is_stunty(const bb_match* m, int slot) {
    return bb_has_skill(&m->players[slot].skills, BB_SK_STUNTY);
}

bool bb_has_block(const bb_match* m, int slot) {
    return bb_has_skill(&m->players[slot].skills, BB_SK_BLOCK);
}

bool bb_has_wrestle(const bb_match* m, int slot) {
    return bb_has_skill(&m->players[slot].skills, BB_SK_WRESTLE);
}

bool bb_has_dodge_skill(const bb_match* m, int slot) {
    return bb_has_skill(&m->players[slot].skills, BB_SK_DODGE);
}

bool bb_has_tackle_adjacent(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = p->x + dx, ny = p->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(slot) && bb_exerts_tz(m, s) &&
                bb_has_skill(&m->players[s].skills, BB_SK_TACKLE)) {
                return true;
            }
        }
    }
    return false;
}

bool bb_can_assist(const bb_match* m, int assister, int target_slot) {
    const bb_player* a = &m->players[assister];
    const bb_player* t = &m->players[target_slot];
    if (a->location != BB_LOC_ON_PITCH || a->stance != BB_STANCE_STANDING) return false;
    if (a->flags & BB_PF_DISTRACTED) return false;
    if (a->flags & BB_PF_EYE_GOUGED) return false;
    if (!bb_adjacent(a->x, a->y, t->x, t->y)) return false;
    if (bb_has_skill(&a->skills, BB_SK_GUARD)) {
        // DEFENSIVE: "During your opponent's Turns, opposition players Marked
        // by this player cannot use the Guard ... Skill."
        bool cancelled = false;
        if (BB_TEAM_OF(assister) != m->active_team) {
            for (int dx = -1; dx <= 1 && !cancelled; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int nx = a->x + dx, ny = a->y + dy;
                    if (!bb_on_pitch_xy(nx, ny)) continue;
                    int s2 = bb_slot_at(m, nx, ny);
                    if (s2 >= 0 && BB_TEAM_OF(s2) != BB_TEAM_OF(assister) &&
                        bb_exerts_tz(m, s2) &&
                        bb_has_skill(&m->players[s2].skills, BB_SK_DEFENSIVE)) {
                        cancelled = true;
                        break;
                    }
                }
            }
        }
        if (!cancelled) return true;
    }
    // Without Guard: may not be marked by any standing opponent other than the
    // target of the block.
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = a->x + dx, ny = a->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s >= 0 && s != target_slot && BB_TEAM_OF(s) != BB_TEAM_OF(assister) &&
                bb_exerts_tz(m, s)) {
                return false;
            }
        }
    }
    return true;
}

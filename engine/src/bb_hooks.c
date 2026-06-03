// bb_hooks.c — skill-hook dispatchers.
#include "bb/bb_hooks.h"
#include "bb/bb_proc.h"

bb_skill_hooks bb_hooks[BB_SKILL_COUNT];
uint64_t bb_skill_exercised[BB_SKILL_COUNT];

int bb_next_skill(const bb_skillset* s, int start) {
    for (int w = start >> 6; w < BB_SKILL_WORDS; w++) {
        uint64_t bits = s->w[w];
        if (w == start >> 6) bits &= ~0ULL << (start & 63);
        while (bits) {
            int bit = __builtin_ctzll(bits);
            int id = (w << 6) + bit;
            if (id >= BB_SKILL_COUNT) return -1;
            return id;
        }
    }
    return -1;
}

int bb_hook_mods(const bb_match* m, const bb_ctx* c) {
    int total = 0;
    // Own skills.
    const bb_player* p = &m->players[c->player];
    bb_ctx own = *c;
    own.owner = c->player;
    for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
         sk = bb_next_skill(&p->skills, sk + 1)) {
        if (bb_hooks[sk].mod) {
            int v = bb_hooks[sk].mod(m, &own);
            if (v) bb_cover(sk);
            total += v;
        }
    }
    // Auras from every other on-pitch player with an aura hook.
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        if (s == c->player) continue;
        const bb_player* q = &m->players[s];
        if (q->location != BB_LOC_ON_PITCH) continue;
        for (int sk = bb_next_skill(&q->skills, 0); sk >= 0;
             sk = bb_next_skill(&q->skills, sk + 1)) {
            if (!bb_hooks[sk].aura) continue;
            bb_ctx ac = *c;
            ac.other = (uint8_t)s; // aura source
            ac.owner = (uint8_t)s;
            int v = bb_hooks[sk].aura(m, &ac);
            if (v) bb_cover(sk);
            total += v;
        }
    }
    return total;
}

int bb_hook_reroll(const bb_match* m, const bb_ctx* c) {
    // BB2025 treats Intercept as a distinct test from Catch: no skill grants
    // an interception re-roll (the Catch skill re-rolls a test "when
    // attempting to Catch the ball" only). Interception ctxs carry the
    // thrower in `other`. (adversarial review M11)
    if (c->kind == BB_TEST_CATCH && c->other != BB_NO_PLAYER) return -1;
    const bb_player* p = &m->players[c->player];
    if (p->skill_rr_used & (1u << c->kind)) return -1;
    for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
         sk = bb_next_skill(&p->skills, sk + 1)) {
        if (bb_hooks[sk].reroll_kinds & (1u << c->kind)) {
            // No bb_cover here: this is a QUERY (also reached from const
            // bb_legal_actions); coverage is recorded when the re-roll is
            // actually consumed, in test_apply (review P3).
            return sk;
        }
    }
    return -1;
}

int bb_hook_activation_gate(const bb_match* m, int slot, int* target, int* gk) {
    const bb_player* p = &m->players[slot];
    for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
         sk = bb_next_skill(&p->skills, sk + 1)) {
        if (bb_hooks[sk].activate_gate) {
            *target = bb_hooks[sk].activate_gate;
            *gk = bb_hooks[sk].gate_kind;
            bb_cover(sk);
            return sk;
        }
    }
    return -1;
}

int bb_hook_push_flags(const bb_match* m, int slot) {
    int flags = 0;
    const bb_player* p = &m->players[slot];
    for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
         sk = bb_next_skill(&p->skills, sk + 1)) {
        if (bb_hooks[sk].push_flags) bb_cover(sk);
        flags |= bb_hooks[sk].push_flags;
    }
    return flags;
}

int bb_hook_st_mod_blitz(const bb_match* m, int slot) {
    int b = 0;
    const bb_player* p = &m->players[slot];
    for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
         sk = bb_next_skill(&p->skills, sk + 1)) {
        if (bb_hooks[sk].st_mod_blitz) bb_cover(sk);
        b += bb_hooks[sk].st_mod_blitz;
    }
    return b;
}

static int chain_mod(const bb_match* m, int downed, int causer, int which) {
    int total = 0;
    bb_ctx c = {0, (uint8_t)downed, (uint8_t)(causer < 0 ? BB_NO_PLAYER : causer),
                0, 0, 0, 0, 0, -1, 0};
    // Causer's skills (Mighty Blow, Claws...) and victim's (Thick Skull is
    // band-based, not a mod; but e.g. armour bonuses) both consulted.
    int sides[2] = {causer, downed};
    for (int i = 0; i < 2; i++) {
        if (sides[i] < 0) continue;
        c.owner = (uint8_t)sides[i]; // hook callbacks know whose skill fires
        const bb_player* p = &m->players[sides[i]];
        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
             sk = bb_next_skill(&p->skills, sk + 1)) {
            bb_mod_fn fn = which == 0 ? bb_hooks[sk].armour_mod : bb_hooks[sk].injury_mod;
            if (fn) {
                int v = fn(m, &c);
                if (v) bb_cover(sk);
                total += v;
            }
        }
    }
    return total;
}

int bb_hook_armour_mod(const bb_match* m, int downed, int causer) {
    return chain_mod(m, downed, causer, 0);
}

int bb_hook_injury_mod(const bb_match* m, int downed, int causer) {
    return chain_mod(m, downed, causer, 1);
}

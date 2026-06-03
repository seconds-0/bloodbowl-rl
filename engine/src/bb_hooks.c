// bb_hooks.c — skill-hook dispatchers.
#include "bb/bb_hooks.h"
#include "bb/bb_proc.h"

bb_skill_hooks bb_hooks[BB_SKILL_COUNT];

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
    for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
         sk = bb_next_skill(&p->skills, sk + 1)) {
        if (bb_hooks[sk].mod) total += bb_hooks[sk].mod(m, c);
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
            total += bb_hooks[sk].aura(m, &ac);
        }
    }
    return total;
}

int bb_hook_reroll(const bb_match* m, int slot, int kind) {
    const bb_player* p = &m->players[slot];
    if (p->skill_rr_used & (1u << kind)) return -1;
    for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
         sk = bb_next_skill(&p->skills, sk + 1)) {
        if (bb_hooks[sk].reroll_kinds & (1u << kind)) return sk;
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
            return sk;
        }
    }
    return -1;
}

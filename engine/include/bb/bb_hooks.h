// bb_hooks.h — the skill/trait effect framework.
//
// Procedures never test skill ids inline (beyond the Phase-2 starter set in
// bb_skills.h, which is migrating here). Instead they build a bb_ctx for the
// situation and query the hook dispatchers. Each skill registers its effect
// functions at load time via BB_SKILL_* registration macros — one skill, one
// registration, any file. Parallel implementation batches therefore never
// edit shared files.
//
// Hook classes:
//   mod      — additive modifier to a D6 test (dodge/rush/pickup/catch/pass/
//              interception), from the ACTING player's own skills.
//   aura     — additive modifier contributed by OTHER players' skills (e.g.
//              Disturbing Presence); dispatcher scans both teams.
//   reroll   — grants a self re-roll for a test kind (one use per turn).
//   activate — negatrait gate run when a player activates (Bone Head etc.);
//              returns the D6 target to pass, 0 = no gate. Effects on failure
//              are standardized (lose activation; LOSE_TZ variants).
// Block-face interactions, movement-legality changes (Leap, Break Tackle) and
// armour/injury chain effects (Mighty Blow, Claws, Regeneration) have
// dedicated query functions implemented over the same registration table.
#ifndef BB_HOOKS_H
#define BB_HOOKS_H

#include "bb/bb_match.h"
#include "bb/bb_skills.h"

typedef struct {
    uint8_t kind;     // bb_test_kind
    uint8_t player;   // acting player slot
    uint8_t other;    // opponent/target slot or BB_NO_PLAYER
    int8_t from_x, from_y; // origin square (moves) or actor square
    int8_t to_x, to_y;     // destination/target square
    int8_t range_band;     // passes: 0 quick / 1 short / 2 long / 3 bomb; else -1
    uint8_t is_blitz;      // within a blitz action
} bb_ctx;

typedef int (*bb_mod_fn)(const bb_match* m, const bb_ctx* c);

// Push-interaction flags (consulted by the PUSH/BLOCK procedures).
enum {
    BB_PUSHF_STAND_FIRM = 1 << 0, // may not be pushed
    BB_PUSHF_SIDE_STEP = 1 << 1,  // defender's coach picks the push square
    BB_PUSHF_FEND = 1 << 2,       // attacker may not follow up
    BB_PUSHF_GRAB = 1 << 3,       // attacker: defender may not use Side Step
    BB_PUSHF_JUGGERNAUT = 1 << 4, // attacker (blitz): Both Down = Push; cancels
                                  // Fend/Stand Firm/Wrestle
};

typedef struct {
    bb_mod_fn mod;        // own-skill test modifier
    bb_mod_fn aura;       // modifier this skill inflicts on OTHERS' tests
    bb_mod_fn armour_mod; // armour-roll modifier (c->player = downed player,
                          // c->other = causer; positive helps the causer)
    bb_mod_fn injury_mod; // injury-roll modifier (same convention)
    uint8_t reroll_kinds; // bitmask of bb_test_kind this skill lets you re-roll
    uint8_t activate_gate; // D6 target for the activation negatrait (0 = none)
    uint8_t gate_kind;     // bb_gate_kind behavior on failure
    uint8_t push_flags;    // BB_PUSHF_* (owner's effect in pushes)
    int8_t st_mod_blitz;   // ST bonus when blocking as part of a Blitz (Horns)
} bb_skill_hooks;

typedef enum {
    BB_GATE_NONE = 0,
    BB_GATE_LOSE_ACTIVATION,      // fails: activation ends (marked used)
    BB_GATE_LOSE_ACT_AND_TZ,      // fails: also Distracted-like (loses TZ)
} bb_gate_kind;

extern bb_skill_hooks bb_hooks[BB_SKILL_COUNT];

// Registration: define a function and attach it to a skill at load time.
//   BB_SKILL_MOD(two_heads) { return c->kind == BB_TEST_DODGE ? 1 : 0; }
#define BB_SKILL_MOD(skill)                                                  \
    static int bb_mod_##skill(const bb_match* m, const bb_ctx* c);           \
    __attribute__((constructor)) static void bb_reg_mod_##skill(void) {      \
        bb_hooks[BB_SK_##skill].mod = bb_mod_##skill;                        \
    }                                                                        \
    static int bb_mod_##skill(const bb_match* m, const bb_ctx* c)

#define BB_SKILL_AURA(skill)                                                 \
    static int bb_aura_##skill(const bb_match* m, const bb_ctx* c);          \
    __attribute__((constructor)) static void bb_reg_aura_##skill(void) {     \
        bb_hooks[BB_SK_##skill].aura = bb_aura_##skill;                      \
    }                                                                        \
    static int bb_aura_##skill(const bb_match* m, const bb_ctx* c)

#define BB_SKILL_REROLL(skill, kinds_mask)                                   \
    __attribute__((constructor)) static void bb_reg_rr_##skill(void) {       \
        bb_hooks[BB_SK_##skill].reroll_kinds = (kinds_mask);                 \
    }

#define BB_SKILL_GATE(skill, target, kind_)                                  \
    __attribute__((constructor)) static void bb_reg_gate_##skill(void) {     \
        bb_hooks[BB_SK_##skill].activate_gate = (target);                    \
        bb_hooks[BB_SK_##skill].gate_kind = (kind_);                         \
    }

// --- Dispatchers (bb_hooks.c) ------------------------------------------------
// Total modifier for a test: own-skill mods + opposing auras + situational
// rules already passed in by the caller (TZ counts, weather, range).
int bb_hook_mods(const bb_match* m, const bb_ctx* c);

// Skill granting a re-roll for this test, or -1 (honours once-per-turn).
int bb_hook_reroll(const bb_match* m, int slot, int kind);

// Activation gate for this player: fills *target and *gate_kind; returns the
// gating skill id or -1.
int bb_hook_activation_gate(const bb_match* m, int slot, int* target, int* gk);

// Iterate a player's skills: returns the next set skill id >= start, or -1.
int bb_next_skill(const bb_skillset* s, int start);

// Aggregate queries used by the block/push/injury procedures.
int bb_hook_push_flags(const bb_match* m, int slot);
int bb_hook_st_mod_blitz(const bb_match* m, int slot);
int bb_hook_armour_mod(const bb_match* m, int downed, int causer);
int bb_hook_injury_mod(const bb_match* m, int downed, int causer);

#define BB_SKILL_PUSHF(skill, flags)                                         \
    __attribute__((constructor)) static void bb_reg_pf_##skill(void) {       \
        bb_hooks[BB_SK_##skill].push_flags = (flags);                        \
    }

#define BB_SKILL_ST_BLITZ(skill, bonus)                                      \
    __attribute__((constructor)) static void bb_reg_stb_##skill(void) {      \
        bb_hooks[BB_SK_##skill].st_mod_blitz = (bonus);                      \
    }

#define BB_SKILL_ARMOUR_MOD(skill)                                           \
    static int bb_amod_##skill(const bb_match* m, const bb_ctx* c);          \
    __attribute__((constructor)) static void bb_reg_am_##skill(void) {       \
        bb_hooks[BB_SK_##skill].armour_mod = bb_amod_##skill;                \
    }                                                                        \
    static int bb_amod_##skill(const bb_match* m, const bb_ctx* c)

#define BB_SKILL_INJURY_MOD(skill)                                           \
    static int bb_imod_##skill(const bb_match* m, const bb_ctx* c);          \
    __attribute__((constructor)) static void bb_reg_im_##skill(void) {       \
        bb_hooks[BB_SK_##skill].injury_mod = bb_imod_##skill;                \
    }                                                                        \
    static int bb_imod_##skill(const bb_match* m, const bb_ctx* c)

#endif // BB_HOOKS_H

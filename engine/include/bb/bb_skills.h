// bb_skills.h — skill hook surface.
//
// Phase 2 implements a STARTER SET of game-defining skills wired into the core
// procedures: loner, dodge (reroll + stumble), block, wrestle, tackle, guard,
// thick_skull, stunty, sure_feet, sure_hands, sure hands, pass, catch, sprint.
// The full ~108 skill/trait set lands in Phase 3 through these same hooks —
// procedures never test skill ids directly except via this module.
#ifndef BB_SKILLS_H
#define BB_SKILLS_H

#include "bb/bb_match.h"
#include "bb/gen_skills.h"

// Test kinds used by the generic TEST procedure.
typedef enum {
    BB_TEST_DODGE = 0,
    BB_TEST_RUSH,
    BB_TEST_PICKUP,
    BB_TEST_PASS,
    BB_TEST_CATCH,
    BB_TEST_LONER,      // internal: team-reroll gate
    BB_TEST_GENERIC,
    BB_TEST_KIND_COUNT
} bb_test_kind;

// Skill that grants a self-reroll for this test kind, if the player has it and
// hasn't used it this activation. Returns skill id or -1.
int bb_skill_reroll_for(const bb_match* m, int slot, int kind);

// Loner (X+) gate value for team rerolls; 0 if player has no Loner.
int bb_loner_value(const bb_match* m, int slot);

// Max rushes (GFIs) this activation (2, or 3 with Sprint).
int bb_max_rushes(const bb_match* m, int slot);

// Whether `slot` uses the Stunty injury bands.
bool bb_is_stunty(const bb_match* m, int slot);

// Block-face interactions (starter set).
bool bb_has_block(const bb_match* m, int slot);
bool bb_has_wrestle(const bb_match* m, int slot);
bool bb_has_tackle_adjacent(const bb_match* m, int slot); // any standing adjacent opponent with Tackle
bool bb_has_dodge_skill(const bb_match* m, int slot);

// Guard: assist even while marked.
bool bb_can_assist(const bb_match* m, int assister, int target_slot);

#endif // BB_SKILLS_H

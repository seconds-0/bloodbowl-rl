// bb_actions.h — the decision interface between the engine and an agent.
//
// The engine runs as a procedure-stack state machine (see bb_match.h). It
// advances autonomously until a COACH DECISION is required, then surfaces the
// set of legal actions. Both coaches act through this same interface (self-play:
// one policy plays both sides; in-turn opponent choices — e.g. whether to use a
// defensive skill — are decisions for the other coach).
//
// An action is a fixed 4-byte struct, stable across versions once assigned —
// it is the unit of the replay format and of the RL action space.
#ifndef BB_ACTIONS_H
#define BB_ACTIONS_H

#include "bb/bb_types.h"

typedef enum {
    BB_A_NONE = 0,

    // --- Setup phase ---
    BB_A_SETUP_PLACE,    // arg = player slot, x,y = square (place / move during setup)
    BB_A_SETUP_REMOVE,   // arg = player slot (back to reserves during setup)
    BB_A_SETUP_DONE,     // formation confirmed
    BB_A_KICK_TARGET,    // x,y = nominated kick target square
    BB_A_TOUCHBACK,      // arg = player slot to give the ball to

    // --- Team turn ---
    BB_A_ACTIVATE,       // arg = player slot, begin its activation
    BB_A_DECLARE,        // arg = bb_act_kind for the activation just begun
    BB_A_END_TURN,       // voluntarily end the team turn

    // --- Activation ---
    BB_A_STEP,           // x,y = adjacent square to move into (one square)
    BB_A_STAND_UP,
    BB_A_JUMP,           // x,y = landing square (jump over prone/adjacent per BB2025)
    BB_A_BLOCK_TARGET,   // x,y = adjacent opponent to block (also blitz block)
    BB_A_PASS_TARGET,    // x,y = target square of a pass
    BB_A_HANDOFF_TARGET, // x,y = adjacent team-mate square
    BB_A_FOUL_TARGET,    // x,y = prone/stunned opponent to foul
    BB_A_TTM_TARGET,     // x,y = throw team-mate target square
    BB_A_SECURE_BALL,    // BB2025 Secure the Ball action
    BB_A_PICKUP_DECLINE, // decline optional pickup-adjacent rules (reserved)
    BB_A_END_ACTIVATION,

    // --- Block resolution ---
    BB_A_CHOOSE_DIE,     // arg = index 0..2 into the rolled block-dice pool
    BB_A_PUSH_SQUARE,    // x,y = square the pushed player is moved to
    BB_A_FOLLOW_UP,      // arg = 1 follow up / 0 stay

    // --- Rerolls & skills (generic decision points) ---
    BB_A_USE_REROLL,     // arg = bb_reroll_source
    BB_A_DECLINE_REROLL,
    BB_A_USE_SKILL,      // arg = skill id (optional ACTIVE skill at this point)
    BB_A_DECLINE_SKILL,  // arg = skill id

    // --- Post-injury / special ---
    BB_A_APOTHECARY,     // arg = 1 use / 0 decline
    BB_A_CHOOSE_OPTION,  // arg = index into a procedure-defined option list
                         // (kickoff-event choices, casualty re-roll picks,
                         //  prayer targets, argue-the-call, etc.)
    BB_A_SPECIAL_TARGET, // x,y = target of a declared Special Action (Stab,
                         // Hypnotic Gaze, ...); arg = variant where needed

    BB_A_TYPE_COUNT
} bb_action_type;

// Activation kinds for BB_A_DECLARE.
typedef enum {
    BB_ACT_MOVE = 0,
    BB_ACT_BLOCK,
    BB_ACT_BLITZ,
    BB_ACT_PASS,
    BB_ACT_HANDOFF,
    BB_ACT_FOUL,
    BB_ACT_TTM,          // throw team-mate
    BB_ACT_SECURE_BALL,  // BB2025
    BB_ACT_STAB,         // Stab Special Action (also blitz-block replacement)
    BB_ACT_GAZE,         // Hypnotic Gaze Special Action (move, then gaze)
    BB_ACT_KTM,          // Kick Team-mate (separate once-per-turn budget)
    BB_ACT_CHAINSAW,     // Chainsaw Attack Special Action
    BB_ACT_BREATHE_FIRE, // Breathe Fire Special Action
    BB_ACT_VOMIT,        // Projectile Vomit Special Action
    BB_ACT_KIND_COUNT
} bb_act_kind;

typedef enum {
    BB_RR_TEAM = 0,      // team re-roll
    BB_RR_SKILL,         // skill-granted re-roll for this specific test (Dodge, Pass, ...)
    BB_RR_PRO,
    BB_RR_LEADER,
    BB_RR_SOURCE_COUNT
} bb_reroll_source;

typedef struct {
    uint8_t type; // bb_action_type
    uint8_t arg;
    uint8_t x, y;
} bb_action;

static inline uint32_t bb_action_pack(bb_action a) {
    return (uint32_t)a.type | ((uint32_t)a.arg << 8) | ((uint32_t)a.x << 16) | ((uint32_t)a.y << 24);
}
static inline bb_action bb_action_unpack(uint32_t v) {
    bb_action a = { (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24) };
    return a;
}
static inline bool bb_action_eq(bb_action a, bb_action b) {
    return bb_action_pack(a) == bb_action_pack(b);
}

// Upper bound on simultaneously legal actions. Setup placement is the worst
// case: 16 players x ~190 own-half squares ~= 3000. The factored RL action
// heads never materialize this list; it exists for replay validation, tests
// and fuzzing.
#define BB_LEGAL_MAX 4096

#endif // BB_ACTIONS_H

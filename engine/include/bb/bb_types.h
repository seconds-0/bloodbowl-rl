// bb_types.h — core constants and plain types for the BB2025 engine.
// Everything in the engine is fixed-size and memcpy-able; no heap in the hot loop.
#ifndef BB_TYPES_H
#define BB_TYPES_H

#include <stdint.h>
#include <stdbool.h>

// --- Pitch ----------------------------------------------------------------
// x runs along the length of the pitch (0..25), y across the width (0..14).
// x == 0 is the HOME end zone column; x == 25 is the AWAY end zone column.
// Home team attacks toward x == 25 (scores there); away scores at x == 0.
// Wide zones: y in [0,3] and [11,14]. Centre field: y in [4,10].
// Line of scrimmage columns: x == 12 (home side) / x == 13 (away side).
#define BB_PITCH_LEN 26
#define BB_PITCH_WID 15

#define BB_TEAM_SLOTS 16   // max players on a matchday roster per team
#define BB_NUM_PLAYERS 32  // slots 0..15 home, 16..31 away
#define BB_ON_PITCH_MAX 11

#define BB_HOME 0
#define BB_AWAY 1
#define BB_NO_PLAYER 0xFF
#define BB_TEAM_OF(p) ((p) >> 4)         // player slot -> team
#define BB_SLOT_OF(p) ((p) & 0x0F)       // player slot -> index within team

// --- Skills / traits ------------------------------------------------------
// Skill and trait ids are generated from engine/data/spec/skills.yaml by
// tools/codegen.py into gen_skills.h (BB_SK_* enum). The bitmask must hold
// every skill + trait + star-player bespoke rule.
#define BB_SKILL_WORDS 3   // 192 bits

typedef struct {
    uint64_t w[BB_SKILL_WORDS];
} bb_skillset;

static inline bool bb_has_skill(const bb_skillset* s, int id) {
    return (s->w[id >> 6] >> (id & 63)) & 1u;
}
static inline void bb_add_skill(bb_skillset* s, int id) {
    s->w[id >> 6] |= (uint64_t)1 << (id & 63);
}
static inline void bb_clear_skill(bb_skillset* s, int id) {
    s->w[id >> 6] &= ~((uint64_t)1 << (id & 63));
}

// --- Player ----------------------------------------------------------------
typedef enum {
    BB_LOC_ON_PITCH = 0,
    BB_LOC_RESERVES,
    BB_LOC_KO,
    BB_LOC_CAS,       // casualty box (out for the match)
    BB_LOC_SENT_OFF,  // ejected by the ref
    BB_LOC_ABSENT,    // empty roster slot
} bb_loc;

typedef enum {
    BB_STANCE_STANDING = 0,
    BB_STANCE_PRONE,
    BB_STANCE_STUNNED,
    BB_STANCE_STUNNED_USED, // stunned players flip to prone at the END of their
                            // team's next turn; this marks the intermediate step
} bb_stance;

// Transient per-activation / per-turn player flags.
enum {
    BB_PF_USED          = 1 << 0,  // has activated this team turn
    BB_PF_ACTIVATING    = 1 << 1,  // currently the active player
    BB_PF_DISTRACTED    = 1 << 2,  // BB2025 Distracted status (until end of next activation)
    BB_PF_HAS_BALL      = 1 << 3,
    BB_PF_BLITZED       = 1 << 4,  // performed the team blitz action this turn
    BB_PF_ROOTED        = 1 << 5,  // Take Root etc.: may not move
    BB_PF_HYPNOTIZED    = 1 << 6,
    BB_PF_USED_SKILL_A  = 1 << 7,  // generic once-per-X skill-use latches; the
    BB_PF_USED_SKILL_B  = 1 << 8,  // mapping is procedure-specific
    BB_PF_SECURED_BALL  = 1 << 9,  // BB2025 Secure the Ball performed
    BB_PF_NO_TZ         = 1 << 10, // currently exerts no tackle zone (computed conditions
                                   // also apply; this latches e.g. Hypnotic Gaze)
    BB_PF_EYE_GOUGED    = 1 << 11, // cannot assist until next activated
} ;

typedef struct {
    bb_skillset skills;
    int8_t ma, st, ag, pa, av; // effective stats; ag/pa/av are target numbers, pa 0 = "-"
    uint8_t x, y;              // valid when location == BB_LOC_ON_PITCH
    uint8_t location;          // bb_loc
    uint8_t stance;            // bb_stance
    uint16_t flags;            // BB_PF_*
    uint8_t moved;             // squares moved this activation
    uint8_t rushes;            // rushes (GFIs) used this activation
    uint8_t position_id;       // index into the roster's position table (for obs)
    uint8_t star_id;           // 0 = regular player, else star player id + 1
    int8_t niggling;           // accumulated niggling injuries (league play)
    uint8_t spp_game;          // SPP events this match (for league mode)
    uint8_t skill_rr_used;     // bitmask by bb_test_kind: skill re-rolls are
                               // once per TURN per player (cleared at turn start)
} bb_player;

// --- Ball -------------------------------------------------------------------
typedef enum {
    BB_BALL_OFF_PITCH = 0, // pre-kickoff / out of bounds being thrown in
    BB_BALL_ON_GROUND,
    BB_BALL_HELD,          // carried by .carrier
    BB_BALL_IN_AIR,        // mid-pass/kick scatter resolution
} bb_ball_state;

typedef struct {
    uint8_t state;   // bb_ball_state
    uint8_t x, y;
    uint8_t carrier; // player slot or BB_NO_PLAYER
} bb_ball;

// --- Dice -------------------------------------------------------------------
// Block dice faces.
typedef enum {
    BB_BD_ATTACKER_DOWN = 1, // "skull"
    BB_BD_BOTH_DOWN,
    BB_BD_PUSH_1,            // two push faces on the die
    BB_BD_PUSH_2,
    BB_BD_STUMBLE,           // "defender stumbles"
    BB_BD_POW,               // "defender down"
} bb_block_die;

// --- Weather ----------------------------------------------------------------
typedef enum {
    BB_WEATHER_SWELTERING = 0,
    BB_WEATHER_SUNNY,
    BB_WEATHER_PERFECT,
    BB_WEATHER_RAIN,
    BB_WEATHER_BLIZZARD,
} bb_weather;

#endif // BB_TYPES_H

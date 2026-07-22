#ifndef BANK_SCENARIO_PREDICATES_H
#define BANK_SCENARIO_PREDICATES_H

#include "bb/bb_match.h"

enum {
    BBS_RISK_BLOCK = 1u << 0,
    BBS_RISK_DODGE = 1u << 1,
    BBS_RISK_PICKUP = 1u << 2,
};

typedef enum {
    BBS_POOL_NONE = 0,
    BBS_POOL_3D_RED,
    BBS_POOL_2D_RED,
    BBS_POOL_1D,
    BBS_POOL_2D,
    BBS_POOL_3D,
    BBS_POOL_DYNAMIC,
} bbs_pool_class;

typedef struct {
    uint8_t valid_boundary;
    uint8_t eligible_players;
    uint8_t ball_state;

    uint8_t s1;
    uint8_t s1_recoverers;
    uint8_t s1_cheapest_dodges;
    uint8_t s1_cheapest_gfis;
    uint8_t s1_ball_tackle_zones;
    uint8_t s1_has_sure_hands;

    uint8_t s2;
    uint8_t s2_opponent_reachers;
    uint8_t s2_cheapest_dodges;
    uint8_t s2_cheapest_gfis;

    uint8_t s3;
    uint8_t s3_zero_roll_players;
    uint8_t s3_risk_mask;

    uint8_t s4;
    uint8_t s4_full;
    uint8_t s4_soft;
    uint8_t s4_r6v1_full;
    uint8_t s4_r6v1_soft;

    uint8_t s5;
    int8_t s5_horizon;
    uint8_t s5_carrier_marked;
    uint8_t s5_team_threats_1turn;
    uint8_t s5_team_threats_2turn;

    uint8_t s6;
    uint8_t s6a;
    uint8_t s6b;
    uint8_t s6_fixed_class_mask;
    uint8_t s6_dynamic_blocks;
    uint16_t s6_class_changing_moves;
} bbs_scenario_facts;

// Pure, RNG-free opportunity classification for the first decision of a team
// turn. Returns 0 on success and nonzero when the snapshot is not a valid
// boundary. The input match is never modified.
int bbs_classify_scenarios(const bb_match* match, bbs_scenario_facts* facts);

#endif

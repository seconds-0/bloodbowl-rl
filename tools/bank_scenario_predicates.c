#include "bank_scenario_predicates.h"

#include "bb/bb_proc.h"
#include "bb/bb_reachability.h"
#include "bb/bb_skills.h"
#include "bb/gen_skills.h"

#include <limits.h>
#include <string.h>

static int reachable(bb_reach_cost cost) {
    return cost.dodges != BB_REACH_UNREACHABLE;
}

static int cost_better(bb_reach_cost candidate, bb_reach_cost current) {
    int candidate_rolls = (int)candidate.dodges + (int)candidate.gfis;
    int current_rolls = (int)current.dodges + (int)current.gfis;
    if (candidate_rolls != current_rolls) return candidate_rolls < current_rolls;
    if (candidate.dodges != current.dodges) {
        return candidate.dodges < current.dodges;
    }
    return candidate.gfis < current.gfis;
}

static void normalize_next_turn_movement(bb_match* match, int team) {
    for (int slot = team * BB_TEAM_SLOTS;
         slot < (team + 1) * BB_TEAM_SLOTS; slot++) {
        match->players[slot].moved = 0;
        match->players[slot].rushes = 0;
        match->players[slot].flags &=
            (uint16_t)~(BB_PF_USED | BB_PF_ACTIVATING | BB_PF_BLITZED);
    }
}

static int selected_path_avoids_loose_ball(const bb_match* match,
                                           const bb_reach_field* field,
                                           int x, int y) {
    if (match->ball.state != BB_BALL_ON_GROUND) return 1;
    for (;;) {
        if (x == match->ball.x && y == match->ball.y) return 0;
        int previous_x = field->prev_x[x][y];
        int previous_y = field->prev_y[x][y];
        if (previous_x < 0 || previous_y < 0) return 1;
        x = previous_x;
        y = previous_y;
    }
}

static int standing_on_pitch(const bb_match* match, int slot) {
    const bb_player* player = &match->players[slot];
    return player->location == BB_LOC_ON_PITCH &&
           player->stance == BB_STANCE_STANDING;
}

static int direct_block_target(const bb_match* match, int attacker, int defender) {
    if (!standing_on_pitch(match, attacker) ||
        !standing_on_pitch(match, defender)) {
        return 0;
    }
    if (BB_TEAM_OF(attacker) == BB_TEAM_OF(defender)) return 0;
    const bb_player* a = &match->players[attacker];
    const bb_player* d = &match->players[defender];
    return bb_adjacent(a->x, a->y, d->x, d->y);
}

static bbs_pool_class fixed_direct_pool_class(const bb_match* match,
                                              int attacker, int defender) {
    if (!direct_block_target(match, attacker, defender)) return BBS_POOL_NONE;
    const bb_player* a = &match->players[attacker];
    const bb_player* d = &match->players[defender];
    if (bb_has_skill(&a->skills, BB_SK_DAUNTLESS)) return BBS_POOL_DYNAMIC;

    int attacker_strength = (int)a->st +
                            bb_count_assists(match, attacker, defender);
    int defender_strength = (int)d->st +
                            bb_count_assists(match, defender, attacker);
    int attacker_team = BB_TEAM_OF(attacker);
    if (attacker_team == match->active_team &&
        match->cheer_assist[attacker_team]) {
        attacker_strength++;
    }
    if (attacker_strength > defender_strength) {
        return attacker_strength > 2 * defender_strength ? BBS_POOL_3D
                                                         : BBS_POOL_2D;
    }
    if (defender_strength > attacker_strength) {
        return defender_strength > 2 * attacker_strength ? BBS_POOL_3D_RED
                                                         : BBS_POOL_2D_RED;
    }
    return BBS_POOL_1D;
}

static int class_mask_has_multiple(uint8_t mask) {
    int count = 0;
    for (int pool = BBS_POOL_3D_RED; pool <= BBS_POOL_3D; pool++) {
        if (mask & (uint8_t)(1u << pool)) count++;
    }
    return count >= 2;
}

static int has_zero_roll_destination(const bb_match* match, int slot,
                                     bb_reach_field* field_out) {
    bb_reach_field_compute(match, slot, field_out);
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            bb_reach_cost cost = field_out->cost[x][y];
            if (field_out->len[x][y] == 0 || !reachable(cost)) continue;
            if (cost.dodges != 0 || cost.gfis != 0) continue;
            if (!selected_path_avoids_loose_ball(match, field_out, x, y)) {
                continue;
            }
            return 1;
        }
    }
    return 0;
}

static uint16_t class_changing_zero_roll_moves(const bb_match* match,
                                               const uint8_t eligible[BB_NUM_PLAYERS]) {
    int team = match->active_team;
    uint16_t changes = 0;
    for (int mover = team * BB_TEAM_SLOTS;
         mover < (team + 1) * BB_TEAM_SLOTS; mover++) {
        if (!eligible[mover] || !standing_on_pitch(match, mover)) continue;
        if (match->players[mover].flags & BB_PF_ROOTED) continue;

        bb_reach_field field;
        bb_reach_field_compute(match, mover, &field);
        for (int x = 0; x < BB_PITCH_LEN; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                bb_reach_cost cost = field.cost[x][y];
                if (field.len[x][y] == 0 || !reachable(cost)) continue;
                if (cost.dodges != 0 || cost.gfis != 0) continue;
                if (!selected_path_avoids_loose_ball(match, &field, x, y)) {
                    continue;
                }
                if (match->ball.state == BB_BALL_HELD &&
                    match->ball.carrier == mover &&
                    x == bb_endzone_x(team)) {
                    continue;
                }

                bb_match moved = *match;
                bb_place(&moved, mover, x, y);
                if (moved.ball.state == BB_BALL_HELD &&
                    moved.ball.carrier == mover) {
                    moved.ball.x = (uint8_t)x;
                    moved.ball.y = (uint8_t)y;
                }

                int destination_changes_class = 0;
                for (int attacker = team * BB_TEAM_SLOTS;
                     attacker < (team + 1) * BB_TEAM_SLOTS &&
                     !destination_changes_class; attacker++) {
                    if (attacker == mover || !eligible[attacker] ||
                        !standing_on_pitch(match, attacker)) {
                        continue;
                    }
                    int opponent = 1 - team;
                    for (int defender = opponent * BB_TEAM_SLOTS;
                         defender < (opponent + 1) * BB_TEAM_SLOTS; defender++) {
                        bbs_pool_class before =
                            fixed_direct_pool_class(match, attacker, defender);
                        if (before == BBS_POOL_NONE ||
                            before == BBS_POOL_DYNAMIC) {
                            continue;
                        }
                        bbs_pool_class after =
                            fixed_direct_pool_class(&moved, attacker, defender);
                        if (after != before && after != BBS_POOL_NONE &&
                            after != BBS_POOL_DYNAMIC) {
                            destination_changes_class = 1;
                            break;
                        }
                    }
                }
                if (destination_changes_class && changes < UINT16_MAX) changes++;
            }
        }
    }
    return changes;
}

int bbs_classify_scenarios(const bb_match* match, bbs_scenario_facts* facts) {
    if (!facts) return 1;
    memset(facts, 0, sizeof(*facts));
    facts->s1_cheapest_dodges = BB_REACH_UNREACHABLE;
    facts->s1_cheapest_gfis = BB_REACH_UNREACHABLE;
    facts->s2_cheapest_dodges = BB_REACH_UNREACHABLE;
    facts->s2_cheapest_gfis = BB_REACH_UNREACHABLE;
    facts->s5_horizon = -1;
    if (!match || match->status != BB_STATUS_DECISION ||
        match->active_team > BB_AWAY ||
        match->decision_team != match->active_team ||
        match->stack_top == 0 ||
        match->stack_top > BB_STACK_MAX ||
        match->stack[match->stack_top - 1].proc != BB_PROC_TEAM_TURN ||
        match->stack[match->stack_top - 1].phase != 1 ||
        !bb_in_team_turn(match, match->active_team)) {
        return 2;
    }
    facts->valid_boundary = 1;
    facts->ball_state = match->ball.state;

    uint8_t eligible[BB_NUM_PLAYERS] = {0};
    bb_action legal[BB_LEGAL_MAX];
    int legal_count = bb_legal_actions(match, legal);
    if (legal_count <= 0 || legal_count > BB_LEGAL_MAX) return 3;
    for (int index = 0; index < legal_count; index++) {
        if (legal[index].type != BB_A_ACTIVATE) continue;
        if (legal[index].arg >= BB_NUM_PLAYERS) return 4;
        eligible[legal[index].arg] = 1;
        if (facts->eligible_players < UINT8_MAX) facts->eligible_players++;
    }

    int team = match->active_team;
    int opponent = 1 - team;
    if (match->ball.state == BB_BALL_ON_GROUND &&
        bb_on_pitch_xy(match->ball.x, match->ball.y)) {
        bb_reach_cost best = {BB_REACH_UNREACHABLE, BB_REACH_UNREACHABLE};
        for (int slot = team * BB_TEAM_SLOTS;
             slot < (team + 1) * BB_TEAM_SLOTS; slot++) {
            if (!eligible[slot] || !standing_on_pitch(match, slot) ||
                (match->players[slot].flags & BB_PF_ROOTED) ||
                bb_has_skill(&match->players[slot].skills, BB_SK_NO_BALL)) {
                continue;
            }
            bb_reach_field field;
            bb_reach_field_compute(match, slot, &field);
            bb_reach_cost cost = field.cost[match->ball.x][match->ball.y];
            if (!reachable(cost)) continue;
            if (facts->s1_recoverers < UINT8_MAX) facts->s1_recoverers++;
            if (!reachable(best) || cost_better(cost, best)) best = cost;
            if (bb_has_skill(&match->players[slot].skills, BB_SK_SURE_HANDS)) {
                facts->s1_has_sure_hands = 1;
            }
        }
        facts->s1 = facts->s1_recoverers > 0;
        if (facts->s1) {
            facts->s1_cheapest_dodges = best.dodges;
            facts->s1_cheapest_gfis = best.gfis;
            int zones = bb_tackle_zones(match, team, match->ball.x, match->ball.y);
            facts->s1_ball_tackle_zones =
                (uint8_t)(zones > UINT8_MAX ? UINT8_MAX : zones);
        }

        if (facts->s1) {
            bb_match next = *match;
            normalize_next_turn_movement(&next, opponent);
            bb_reach_cost opponent_best = {
                BB_REACH_UNREACHABLE, BB_REACH_UNREACHABLE};
            for (int slot = opponent * BB_TEAM_SLOTS;
                 slot < (opponent + 1) * BB_TEAM_SLOTS; slot++) {
                if (!standing_on_pitch(&next, slot) ||
                    (next.players[slot].flags & BB_PF_ROOTED) ||
                    bb_has_skill(&next.players[slot].skills, BB_SK_NO_BALL)) {
                    continue;
                }
                bb_reach_field field;
                bb_reach_field_compute(&next, slot, &field);
                bb_reach_cost cost = field.cost[next.ball.x][next.ball.y];
                if (!reachable(cost)) continue;
                if (facts->s2_opponent_reachers < UINT8_MAX) {
                    facts->s2_opponent_reachers++;
                }
                if (!reachable(opponent_best) ||
                    cost_better(cost, opponent_best)) {
                    opponent_best = cost;
                }
            }
            facts->s2 = facts->s2_opponent_reachers > 0;
            if (facts->s2) {
                facts->s2_cheapest_dodges = opponent_best.dodges;
                facts->s2_cheapest_gfis = opponent_best.gfis;
            }
        }
    }

    for (int slot = team * BB_TEAM_SLOTS;
         slot < (team + 1) * BB_TEAM_SLOTS; slot++) {
        if (!eligible[slot] || !standing_on_pitch(match, slot) ||
            (match->players[slot].flags & BB_PF_ROOTED)) {
            continue;
        }
        bb_reach_field field;
        if (has_zero_roll_destination(match, slot, &field) &&
            facts->s3_zero_roll_players < UINT8_MAX) {
            facts->s3_zero_roll_players++;
        }
        if (bb_is_marked(match, slot)) {
            for (int x = 0; x < BB_PITCH_LEN; x++) {
                for (int y = 0; y < BB_PITCH_WID; y++) {
                    bb_reach_cost cost = field.cost[x][y];
                    if (field.len[x][y] > 0 && reachable(cost) &&
                        cost.dodges > 0) {
                        facts->s3_risk_mask |= BBS_RISK_DODGE;
                    }
                }
            }
        }
    }
    if (facts->s1) facts->s3_risk_mask |= BBS_RISK_PICKUP;

    uint8_t fixed_mask = 0;
    for (int attacker = team * BB_TEAM_SLOTS;
         attacker < (team + 1) * BB_TEAM_SLOTS; attacker++) {
        if (!eligible[attacker] || !standing_on_pitch(match, attacker)) continue;
        for (int defender = opponent * BB_TEAM_SLOTS;
             defender < (opponent + 1) * BB_TEAM_SLOTS; defender++) {
            bbs_pool_class pool =
                fixed_direct_pool_class(match, attacker, defender);
            if (pool == BBS_POOL_NONE) continue;
            facts->s3_risk_mask |= BBS_RISK_BLOCK;
            if (pool == BBS_POOL_DYNAMIC) {
                if (facts->s6_dynamic_blocks < UINT8_MAX) {
                    facts->s6_dynamic_blocks++;
                }
            } else {
                fixed_mask |= (uint8_t)(1u << pool);
            }
        }
    }
    facts->s3 = facts->eligible_players >= 4 &&
                facts->s3_zero_roll_players >= 2 &&
                facts->s3_risk_mask != 0;

    if (match->ball.state == BB_BALL_HELD &&
        match->ball.carrier < BB_NUM_PLAYERS &&
        BB_TEAM_OF(match->ball.carrier) == team &&
        standing_on_pitch(match, match->ball.carrier)) {
        int carrier = match->ball.carrier;
        bb_match next = *match;
        normalize_next_turn_movement(&next, opponent);
        bb_reach_access access = bb_min_access_cost(
            &next, opponent, next.players[carrier].x, next.players[carrier].y);
        facts->s4_full = bb_is_marked(&next, carrier) || access.any_free;
        facts->s4_soft = !facts->s4_full && access.any_one_roll;
        facts->s4 = facts->s4_full || facts->s4_soft;
        bb_carrier_exposure r6v1 = bb_carrier_exposure_eval(match, team);
        facts->s4_r6v1_full = r6v1.full;
        facts->s4_r6v1_soft = r6v1.soft;
    }

    if (match->ball.state == BB_BALL_HELD &&
        match->ball.carrier < BB_NUM_PLAYERS &&
        BB_TEAM_OF(match->ball.carrier) == opponent &&
        standing_on_pitch(match, match->ball.carrier)) {
        facts->s5_horizon =
            (int8_t)bb_def_threat_turns(match, match->ball.carrier);
        facts->s5 = facts->s5_horizon == 1 || facts->s5_horizon == 2;
        facts->s5_carrier_marked = bb_is_marked(match, match->ball.carrier);
        bb_def_threat threats = bb_def_threat_eval(match, team);
        facts->s5_team_threats_1turn = threats.n_threats_1turn;
        facts->s5_team_threats_2turn = threats.n_threats_2turn;
    }

    facts->s6_fixed_class_mask = fixed_mask;
    facts->s6a = class_mask_has_multiple(fixed_mask);
    facts->s6_class_changing_moves =
        class_changing_zero_roll_moves(match, eligible);
    facts->s6b = facts->s6_class_changing_moves > 0;
    facts->s6 = facts->s6a || facts->s6b;
    return 0;
}

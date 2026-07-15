#include "bb_test.h"
#include "bb_fixtures.h"
#include "bb/bb_proc.h"
#include "bb/gen_skills.h"
#include "../../tools/bank_scenario_predicates.h"
#include "../../tools/bank_scenario_scan.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

static void scenario_boundary(bb_match* m) {
    bb_rng rng;
    bb_rng_seed(&rng, 1, 1);
    BB_CHECK_EQ(fx_run(m, &rng), BB_STATUS_DECISION);
    BB_CHECK(bb_in_team_turn(m, m->active_team));
}

BB_TEST(scenario_s1_s2_normalize_opponent_prior_turn_movement) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 2);
    fx_lineman(&m, BB_HOME, 0, 5, 7);
    int opponent = fx_lineman(&m, BB_AWAY, 0, 10, 7);
    fx_ball_ground(&m, 7, 7);
    scenario_boundary(&m);
    m.players[opponent].moved = (uint8_t)m.players[opponent].ma;
    m.players[opponent].rushes = (uint8_t)bb_max_rushes(&m, opponent);

    bbs_scenario_facts facts;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s1);
    BB_CHECK(facts.s2);
    BB_CHECK_EQ(facts.s1_recoverers, 1);
    BB_CHECK_EQ(facts.s2_opponent_reachers, 1);
}

BB_TEST(scenario_s1_excludes_no_ball_and_held_ball) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int recoverer = fx_lineman(&m, BB_HOME, 0, 5, 7);
    fx_ball_ground(&m, 6, 7);
    fx_lineman(&m, BB_AWAY, 0, 6, 8);
    fx_give_skill(&m, recoverer, BB_SK_NO_BALL);
    scenario_boundary(&m);

    bbs_scenario_facts facts;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(!facts.s1);

    bb_clear_skill(&m.players[recoverer].skills, BB_SK_NO_BALL);
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s1);
    BB_CHECK_EQ(facts.s1_ball_tackle_zones, 1);

    fx_ball_held(&m, recoverer);
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(!facts.s1);
}

BB_TEST(scenario_s3_is_opportunity_pressure_not_quality) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_HOME, 0, 4, 4);
    fx_lineman(&m, BB_HOME, 1, 4, 10);
    fx_lineman(&m, BB_HOME, 2, 8, 4);
    fx_lineman(&m, BB_HOME, 3, 10, 7);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    scenario_boundary(&m);

    bbs_scenario_facts facts;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s3);
    BB_CHECK(facts.eligible_players >= 4);
    BB_CHECK(facts.s3_zero_roll_players >= 2);
    BB_CHECK(facts.s3_risk_mask & BBS_RISK_BLOCK);

    bb_remove_from_pitch(&m, BB_HOME * BB_TEAM_SLOTS + 2, BB_LOC_RESERVES);
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(!facts.s3);
}

BB_TEST(scenario_s4_raw_access_survives_r6v1_endzone_exemption) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int carrier = fx_lineman(&m, BB_HOME, 0, 24, 7);
    fx_ball_held(&m, carrier);
    fx_lineman(&m, BB_AWAY, 0, 24, 8);
    scenario_boundary(&m);

    bbs_scenario_facts facts;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s4);
    BB_CHECK(facts.s4_full);
    BB_CHECK(!facts.s4_soft);
    BB_CHECK(!facts.s4_r6v1_full);
    BB_CHECK(!facts.s4_r6v1_soft);
}

BB_TEST(scenario_s5_uses_geometric_carrier_horizon) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_HOME, 0, 12, 7);
    int carrier = fx_lineman(&m, BB_AWAY, 0, 6, 7);
    fx_ball_held(&m, carrier);
    scenario_boundary(&m);

    bbs_scenario_facts facts;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s5);
    BB_CHECK_EQ(facts.s5_horizon, 1);

    bb_place(&m, carrier, 12, 6);
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s5);
    BB_CHECK_EQ(facts.s5_horizon, 2);

    bb_place(&m, carrier, 25, 6);
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(!facts.s5);
    BB_CHECK(facts.s5_horizon > 2);
}

BB_TEST(scenario_s6a_spans_fixed_direct_block_classes) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_player(&m, BB_HOME, 0, 10, 6, 6, 3, 3, 4, 9);
    fx_player(&m, BB_AWAY, 0, 11, 6, 6, 3, 3, 4, 9);
    int stronger = fx_player(&m, BB_HOME, 1, 10, 10, 6, 4, 3, 4, 9);
    fx_player(&m, BB_AWAY, 1, 11, 10, 6, 3, 3, 4, 9);
    scenario_boundary(&m);

    bbs_scenario_facts facts;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s6a);
    BB_CHECK(facts.s6);
    BB_CHECK(facts.s6_fixed_class_mask & (1u << BBS_POOL_1D));
    BB_CHECK(facts.s6_fixed_class_mask & (1u << BBS_POOL_2D));

    fx_give_skill(&m, stronger, BB_SK_DAUNTLESS);
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(!facts.s6a);
    BB_CHECK(facts.s6_dynamic_blocks >= 1);
}

BB_TEST(scenario_s6b_requires_real_assist_after_zero_roll_move) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_HOME, 0, 10, 7);
    int mover = fx_player(&m, BB_HOME, 1, 9, 9, 1, 3, 3, 4, 9);
    fx_lineman(&m, BB_AWAY, 0, 11, 7);
    scenario_boundary(&m);

    bbs_scenario_facts facts;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s6b);
    BB_CHECK(facts.s6_class_changing_moves >= 1);

    int marker = fx_lineman(&m, BB_AWAY, 1, 11, 9);
    (void)marker;
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(!facts.s6b);

    fx_give_skill(&m, mover, BB_SK_GUARD);
    BB_CHECK_EQ(bbs_classify_scenarios(&m, &facts), 0);
    BB_CHECK(facts.s6b);

    BB_CHECK_EQ(bb_slot_at(&m, 9, 9), mover);
    BB_CHECK_EQ(bb_slot_at(&m, 10, 8), -1);
}

BB_TEST(scenario_rejects_non_boundary_without_mutating_input) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    fx_lineman(&m, BB_HOME, 0, 5, 5);
    bb_match before;
    memcpy(&before, &m, sizeof(m));
    bbs_scenario_facts facts;
    BB_CHECK(bbs_classify_scenarios(&m, &facts) != 0);
    BB_CHECK(memcmp(&m, &before, sizeof(m)) == 0);

    m.stack_top = BB_STACK_MAX + 1;
    memcpy(&before, &m, sizeof(m));
    BB_CHECK(bbs_classify_scenarios(&m, &facts) != 0);
    BB_CHECK(memcmp(&m, &before, sizeof(m)) == 0);
}

static void fixture_u32(uint8_t* output, uint32_t value) {
    output[0] = (uint8_t)value;
    output[1] = (uint8_t)(value >> 8);
    output[2] = (uint8_t)(value >> 16);
    output[3] = (uint8_t)(value >> 24);
}

static size_t scenario_bank_fixture(uint8_t* payload, const bb_match* match) {
    memcpy(payload, "BBS1", 4);
    fixture_u32(payload + 4, 1);
    fixture_u32(payload + 8, (uint32_t)sizeof(*match));
    fixture_u32(payload + 12, bbs_scenario_local_fingerprint());
    fixture_u32(payload + 16, 1234);
    fixture_u32(payload + 20, 99);
    payload[24] = match->half;
    payload[25] = match->turn[match->active_team];
    payload[26] = 0;
    payload[27] = 0;
    memcpy(payload + 28, match, sizeof(*match));
    return 28 + sizeof(*match);
}

static int scan_fixture(const uint8_t* payload, size_t bytes,
                        char* output, size_t output_bytes,
                        const char** error) {
    FILE* input = tmpfile();
    FILE* target = tmpfile();
    BB_CHECK(input != NULL);
    BB_CHECK(target != NULL);
    if (!input || !target) {
        if (input) fclose(input);
        if (target) fclose(target);
        return -1;
    }
    BB_CHECK_EQ(fwrite(payload, 1, bytes, input), bytes);
    BB_CHECK_EQ(fflush(input), 0);
    BB_CHECK_EQ(fseek(input, 0, SEEK_SET), 0);
    int result = bbs_scan_stream(input, target, error);
    BB_CHECK_EQ(fflush(target), 0);
    BB_CHECK_EQ(fseek(target, 0, SEEK_SET), 0);
    if (output && output_bytes > 0) {
        size_t read = fread(output, 1, output_bytes - 1, target);
        output[read] = '\0';
    }
    BB_CHECK_EQ(fclose(input), 0);
    BB_CHECK_EQ(fclose(target), 0);
    return result;
}

BB_TEST(scenario_scanner_validates_bbs_and_record_contract) {
    bb_match match;
    fx_match_midturn(&match, BB_HOME, 0);
    fx_lineman(&match, BB_HOME, 0, 5, 7);
    scenario_boundary(&match);

    uint8_t valid[28 + sizeof(bb_match)];
    size_t bytes = scenario_bank_fixture(valid, &match);
    const char* error = NULL;
    char output[2048];
    BB_CHECK_EQ(scan_fixture(valid, bytes, output, sizeof(output), &error), 0);
    BB_CHECK(error == NULL);
    BB_CHECK(strstr(output, "\"record_index\":0") != NULL);
    BB_CHECK(strstr(output, "\"replay_id\":1234") != NULL);

    uint8_t broken[sizeof(valid)];
    memcpy(broken, valid, bytes);
    broken[0] = 'N';
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "bad BBS1 magic") == 0);

    memcpy(broken, valid, bytes);
    fixture_u32(broken + 4, 2);
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "unsupported BBS1 version") == 0);

    memcpy(broken, valid, bytes);
    fixture_u32(broken + 8, (uint32_t)sizeof(match) + 1);
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "match size differs from local ABI") == 0);

    memcpy(broken, valid, bytes);
    fixture_u32(broken + 12, bbs_scenario_local_fingerprint() ^ 1u);
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "engine fingerprint differs from local build") == 0);

    BB_CHECK(scan_fixture(valid, bytes - 1, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "body is not a positive whole-record multiple") == 0);

    memcpy(broken, valid, bytes);
    broken[26] = 1;
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "invalid record metadata") == 0);

    memcpy(broken, valid, bytes);
    broken[25] = (uint8_t)(match.turn[match.active_team] + 1);
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "metadata and match clock disagree") == 0);

    memcpy(broken, valid, bytes);
    bb_match invalid_match;
    memcpy(&invalid_match, broken + 28, sizeof(invalid_match));
    invalid_match.team_id[0] = BB_TEAM_COUNT;
    memcpy(broken + 28, &invalid_match, sizeof(invalid_match));
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "record content indices are invalid") == 0);

    memcpy(broken, valid, bytes);
    memcpy(&invalid_match, broken + 28, sizeof(invalid_match));
    invalid_match.stack_top = BB_STACK_MAX + 1;
    memcpy(broken + 28, &invalid_match, sizeof(invalid_match));
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "record content indices are invalid") == 0);

    memcpy(broken, valid, bytes);
    memcpy(&invalid_match, broken + 28, sizeof(invalid_match));
    invalid_match.players[BB_HOME * BB_TEAM_SLOTS].x = BB_PITCH_LEN;
    memcpy(broken + 28, &invalid_match, sizeof(invalid_match));
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "record content indices are invalid") == 0);

    memcpy(broken, valid, bytes);
    memcpy(&invalid_match, broken + 28, sizeof(invalid_match));
    invalid_match.grid[0][0] = BB_NUM_PLAYERS + 1;
    memcpy(broken + 28, &invalid_match, sizeof(invalid_match));
    BB_CHECK(scan_fixture(broken, bytes, NULL, 0, &error) != 0);
    BB_CHECK(strcmp(error, "record content indices are invalid") == 0);
}

// BB2025 Dump-off: optional defending-coach Quick Pass immediately before a
// targeting Action, using every ordinary Quick Pass rule except Turnover.
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb_fixtures.h"
#include "bb_test.h"

static bb_action act(int type, int arg, int x, int y) {
    return (bb_action){(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
}

static void dump_fixture(bb_match* m, bb_rng* rng, int active,
                         int* attacker, int* defender, int* receiver) {
    int inactive = 1 - active;
    fx_match_midturn(m, active, 0);
    *attacker = fx_lineman(m, active, 0, 10, 7);
    *defender = fx_player(m, inactive, 0, 11, 7, 7, 3, 2, 3, 8);
    *receiver = fx_lineman(m, inactive, 1, 13, 7);
    fx_give_skill(m, *defender, BB_SK_DUMP_OFF);
    fx_ball_held(m, *defender);
    BB_CHECK_EQ(fx_run(m, rng), BB_STATUS_DECISION);
    bb_push_targeted_action(m, *attacker, *defender, BB_TA_BLOCK, 0);
    m->status = BB_STATUS_RUNNING;
    BB_CHECK_EQ(fx_run(m, rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(m->decision_team, inactive);
}

static bool stack_has(const bb_match* m, int proc) {
    for (int i = 0; i < m->stack_top; i++) {
        if (m->stack[i].proc == proc) return true;
    }
    return false;
}

BB_TEST(dump_off_is_reached_through_normal_activate_declare_block_target) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int attacker = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int defender = fx_player(&m, BB_AWAY, 0, 11, 7, 7, 3, 2, 3, 8);
    fx_give_skill(&m, defender, BB_SK_DUMP_OFF);
    fx_ball_held(&m, defender);
    const uint8_t dice[] = {3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_ACTIVATE, attacker, 0, 0), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_DECLARE, BB_ACT_BLOCK, 0, 0), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_BLOCK_TARGET, 0, 11, 7), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_TARGETED_ACTION);
    BB_CHECK_EQ(bb_top(&m)->phase, 0);
    BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0)) >= 0);
}

BB_TEST(dump_off_decline_is_explicit_and_block_resumes_once_both_sides) {
    for (int active = BB_HOME; active <= BB_AWAY; active++) {
        bb_match m;
        int attacker, defender, receiver;
        const uint8_t dice[] = {3}; // exactly the resumed Block pool
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);
        dump_fixture(&m, &rng, active, &attacker, &defender, &receiver);

        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0)) >= 0);
        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 1, 0, 0)) >= 0);
        BB_CHECK_EQ(fx_apply(&m,
                            act(BB_A_CHOOSE_OPTION, 1, 0, 0),
                            &rng), BB_STATUS_DECISION);
        BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
        BB_CHECK_EQ(bb_top(&m)->phase, 2);
        BB_CHECK_EQ(m.ball.carrier, defender);
        BB_CHECK_EQ(m.active_team, active);
        BB_CHECK(!m.turnover);
        BB_CHECK(!bb_rng_error(&rng));
    }
}

BB_TEST(dump_off_surfaces_every_quick_pass_square_and_ordinary_catch) {
    bb_match m;
    int attacker, defender, receiver;
    const uint8_t dice[] = {6, 3, 3}; // accurate PA, catch, resumed Block
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    dump_fixture(&m, &rng, BB_HOME, &attacker, &defender, &receiver);

    BB_CHECK_EQ(fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    // Normal Pass targets are squares, including empty and opposition-occupied
    // squares. Dump-off restricts only the range to Quick (d^2 <= 12).
    BB_CHECK(fx_find(&m, act(BB_A_PASS_TARGET, 0, 13, 7)) >= 0); // team-mate
    BB_CHECK(fx_find(&m, act(BB_A_PASS_TARGET, 0, 10, 7)) >= 0); // opponent
    BB_CHECK(fx_find(&m, act(BB_A_PASS_TARGET, 0, 11, 10)) >= 0); // empty edge
    BB_CHECK_EQ(fx_find(&m, act(BB_A_PASS_TARGET, 0, 15, 7)), -1); // non-Quick
    BB_CHECK_EQ(fx_find(&m, act(BB_A_PASS_TARGET, 0, 11, 7)), -1); // origin

    BB_CHECK_EQ(fx_apply(&m, act(BB_A_PASS_TARGET, 0, 13, 7), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK(!m.turnover);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
    BB_CHECK_EQ(bb_top(&m)->phase, 2); // original Action resumed once
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(dump_off_reuses_pass_skill_reroll_for_inactive_thrower) {
    bb_match m;
    int attacker, defender, receiver;
    const uint8_t dice[] = {2, 4, 3, 3}; // PA fail, Pass reroll, catch, Block
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    dump_fixture(&m, &rng, BB_HOME, &attacker, &defender, &receiver);
    fx_give_skill(&m, defender, BB_SK_PASS);

    fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_PASS_TARGET, 0, 13, 7), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_SKILL,
                             BB_SK_PASS, 0)) >= 0);
    BB_CHECK_EQ(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)), -1);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_SKILL,
                                BB_SK_PASS, 0), &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
    BB_CHECK_EQ(bb_top(&m)->phase, 2);
    BB_CHECK(!m.turnover);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(dump_off_nested_catch_skill_reroll_keeps_no_turnover_context) {
    bb_match m;
    int attacker, defender, receiver;
    const uint8_t dice[] = {6, 1, 3, 3}; // PA, failed catch, Catch reroll, Block
    bb_rng rng;
    bb_rng_script(&rng, dice, 4);
    dump_fixture(&m, &rng, BB_HOME, &attacker, &defender, &receiver);
    fx_give_skill(&m, receiver, BB_SK_CATCH);

    fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_PASS_TARGET, 0, 13, 7), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_AWAY);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_SKILL,
                             BB_SK_CATCH, 0)) >= 0);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_USE_REROLL, BB_RR_SKILL,
                                BB_SK_CATCH, 0), &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
    BB_CHECK_EQ(bb_top(&m)->phase, 2);
    BB_CHECK(!m.turnover);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(dump_off_completed_to_inactive_team_preserves_normal_turn_end) {
    bb_match m;
    int attacker, defender, receiver;
    const uint8_t dice[] = {6, 3, 3}; // pass, catch, Push Back block face
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    dump_fixture(&m, &rng, BB_HOME, &attacker, &defender, &receiver);
    fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
    fx_apply(&m, act(BB_A_PASS_TARGET, 0, 13, 7), &rng);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_CHOOSE_DIE, 0, 0, 0), &rng),
                BB_STATUS_DECISION);
    BB_CHECK(fx_has_type(&m, BB_A_PUSH_SQUARE));
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&m, legal);
    int push = -1;
    for (int i = 0; i < n; i++) if (legal[i].type == BB_A_PUSH_SQUARE) { push = i; break; }
    BB_CHECK(push >= 0);
    fx_apply(&m, legal[push], &rng);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_FOLLOW_UP, 0, 0, 0), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK(fx_has_type(&m, BB_A_END_TURN));
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_END_TURN, 0, 0, 0), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
    BB_CHECK_EQ(m.ball.carrier, receiver);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(dump_off_touchdown_unwinds_owner_context_without_leak) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int attacker = fx_lineman(&m, BB_HOME, 0, 4, 7);
    int defender = fx_player(&m, BB_AWAY, 0, 3, 7, 7, 3, 2, 3, 8);
    int scorer = fx_lineman(&m, BB_AWAY, 1, 0, 7);
    fx_give_skill(&m, defender, BB_SK_DUMP_OFF);
    fx_ball_held(&m, defender);
    const uint8_t dice[] = {6, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3};
    bb_rng rng;
    bb_rng_script(&rng, dice, 12);
    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    bb_push_targeted_action(&m, attacker, defender, BB_TA_BLOCK, 0);
    m.status = BB_STATUS_RUNNING;
    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
    fx_apply(&m, act(BB_A_PASS_TARGET, 0, 0, 7), &rng);
    BB_CHECK_EQ(m.score[BB_AWAY], 1);
    BB_CHECK_EQ(m.ball.carrier, BB_NO_PLAYER); // drive reset cleared the scorer
    BB_CHECK(m.players[scorer].location != BB_LOC_ON_PITCH);
    BB_CHECK(!stack_has(&m, BB_PROC_BLOCK));
    for (int i = 0; i < m.stack_top; i++) {
        BB_CHECK(!(m.stack[i].proc == BB_PROC_BLOCK && m.stack[i].phase == 8));
    }
    BB_CHECK(!m.turnover);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(dump_off_fumble_and_inaccurate_flight_never_turn_over) {
    { // Fumble bounces from the thrower, then the Block still resolves.
        bb_match m;
        int attacker, defender, receiver;
        const uint8_t dice[] = {1, 7, 3}; // fumble, bounce, Block
        bb_rng rng;
        bb_rng_script(&rng, dice, 3);
        dump_fixture(&m, &rng, BB_HOME, &attacker, &defender, &receiver);
        fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
        BB_CHECK_EQ(fx_apply(&m, act(BB_A_PASS_TARGET, 0, 13, 7), &rng),
                    BB_STATUS_DECISION);
        BB_CHECK_EQ(m.active_team, BB_HOME);
        BB_CHECK(!m.turnover);
        BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
        BB_CHECK_EQ(bb_top(&m)->phase, 2);
        BB_CHECK_EQ(m.ball.carrier, BB_NO_PLAYER);
        BB_CHECK(!bb_rng_error(&rng));
    }
    { // Failed non-fumble PA is Inaccurate: Scatter(3), Bounce, no Turnover.
        bb_match m;
        int attacker, defender, receiver;
        const uint8_t dice[] = {2, 1, 1, 1, 1, 3};
        bb_rng rng;
        bb_rng_script(&rng, dice, 6);
        dump_fixture(&m, &rng, BB_HOME, &attacker, &defender, &receiver);
        fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
        BB_CHECK_EQ(fx_apply(&m, act(BB_A_PASS_TARGET, 0, 13, 7), &rng),
                    BB_STATUS_DECISION);
        BB_CHECK_EQ(m.active_team, BB_HOME);
        BB_CHECK(!m.turnover);
        BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
        BB_CHECK_EQ(bb_top(&m)->phase, 2);
        BB_CHECK(!bb_rng_error(&rng));
    }
}

BB_TEST(dump_off_interception_choice_and_success_do_not_turn_over) {
    bb_match m;
    int attacker, defender, receiver;
    const uint8_t dice[] = {6, 6, 3}; // accurate, interception, resumed Block
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    dump_fixture(&m, &rng, BB_HOME, &attacker, &defender, &receiver);
    int interceptor = fx_lineman(&m, BB_HOME, 1, 12, 7);

    fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_PASS_TARGET, 0, 13, 7), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.decision_team, BB_HOME);
    BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0xFE, 0, 0)) >= 0);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.ball.carrier, interceptor);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK(!m.turnover);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
    BB_CHECK_EQ(bb_top(&m)->phase, 2);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(dump_off_triggers_on_each_directly_targeted_special_action) {
    static const struct {
        int action_kind, skill, variant;
        uint8_t dice[3];
        int ndice;
    } cases[] = {
        {BB_ACT_STAB, BB_SK_STAB, BB_TA_STAB, {1, 1, 0}, 2},
        {BB_ACT_GAZE, BB_SK_HYPNOTIC_GAZE, BB_TA_GAZE, {3, 0, 0}, 1},
        {BB_ACT_CHAINSAW, BB_SK_CHAINSAW, BB_TA_CHAINSAW, {2, 1, 1}, 3},
        {BB_ACT_BREATHE_FIRE, BB_SK_BREATHE_FIRE, BB_TA_BREATHE_FIRE,
         {3, 0, 0}, 1},
        {BB_ACT_VOMIT, BB_SK_PROJECTILE_VOMIT, BB_TA_VOMIT, {2, 1, 1}, 3},
    };
    for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int actor = fx_lineman(&m, BB_HOME, 0, 10, 7);
        int target = fx_player(&m, BB_AWAY, 0, 11, 7, 7, 3, 2, 3, 8);
        fx_give_skill(&m, actor, cases[i].skill);
        fx_give_skill(&m, target, BB_SK_DUMP_OFF);
        fx_ball_held(&m, target);
        bb_rng rng;
        bb_rng_script(&rng, cases[i].dice, cases[i].ndice);
        BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
        fx_apply(&m, act(BB_A_ACTIVATE, actor, 0, 0), &rng);
        BB_CHECK_EQ(fx_apply(&m,
                            act(BB_A_DECLARE, cases[i].action_kind, 0, 0),
                            &rng), BB_STATUS_DECISION);
        BB_CHECK_EQ(fx_apply(&m,
                            act(BB_A_SPECIAL_TARGET, cases[i].variant, 11, 7),
                            &rng), BB_STATUS_DECISION);
        BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_TARGETED_ACTION);
        BB_CHECK_EQ(bb_top(&m)->a, actor);
        BB_CHECK_EQ(bb_top(&m)->b, target);
        BB_CHECK_EQ(bb_top(&m)->x, cases[i].variant);
        BB_CHECK_EQ(m.decision_team, BB_AWAY);
        BB_CHECK(fx_find(&m,
                         act(BB_A_CHOOSE_OPTION, 0, 0, 0)) >= 0);
        fx_apply(&m, act(BB_A_CHOOSE_OPTION, 1, 0, 0), &rng);
        BB_CHECK(!stack_has(&m, BB_PROC_TARGETED_ACTION));
        BB_CHECK(!bb_rng_error(&rng));
    }
}

BB_TEST(targeted_action_both_skills_have_unique_order_choices) {
    bb_match m; int attacker, target, receiver;
    const uint8_t dice[] = {6, 3, 3}; bb_rng rng; bb_rng_script(&rng, dice, 3);
    dump_fixture(&m, &rng, BB_HOME, &attacker, &target, &receiver);
    fx_give_skill(&m, target, BB_SK_TRICKSTER);
    m.status = BB_STATUS_RUNNING; BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    bb_action legal[BB_LEGAL_MAX]; int nlegal = bb_legal_actions(&m, legal);
    BB_CHECK_EQ(nlegal, 4);
    for (int i = 0; i < 4; i++) BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, i, 0, 0)) >= 0);
    for (int i = 0; i < nlegal; i++) for (int j = i + 1; j < nlegal; j++)
        BB_CHECK(!bb_action_eq(legal[i], legal[j]));

    /* Trickster first moves the same target slot; Dump-off remains available. */
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_CHOOSE_OPTION, 2, 0, 0), &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(bb_top(&m)->phase, 4);
    BB_CHECK(fx_find(&m, act(BB_A_SPECIAL_TARGET, BB_SK_TRICKSTER, 10, 6)) >= 0);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_SPECIAL_TARGET, BB_SK_TRICKSTER, 10, 6), &rng),
                BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[target].x, 10); BB_CHECK_EQ(m.players[target].y, 6);
    BB_CHECK_EQ(m.ball.x, 10); BB_CHECK_EQ(m.ball.y, 6);
    BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0)) >= 0);
}

BB_TEST(my_ball_forbids_dump_off_but_preserves_trickster_both_sides) {
    for (int active = BB_HOME; active <= BB_AWAY; active++) {
        bb_match m; int attacker, target, receiver;
        const uint8_t dice[] = {3}; bb_rng rng; bb_rng_script(&rng, dice, 1);
        dump_fixture(&m, &rng, active, &attacker, &target, &receiver);
        fx_give_skill(&m, target, BB_SK_TRICKSTER);

        /* Before My Ball, both optional skills are distinct legal choices. */
        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0)) >= 0);
        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 1, 0, 0)) >= 0);
        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 2, 0, 0)) >= 0);
        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 3, 0, 0)) >= 0);

        fx_give_skill(&m, target, BB_SK_MY_BALL);
        /* My Ball forbids willingly relinquishing possession through Dump-off,
         * while the unrelated Trickster choices remain available. */
        BB_CHECK_EQ(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0)), -1);
        BB_CHECK_EQ(fx_find(&m, act(BB_A_CHOOSE_OPTION, 1, 0, 0)), -1);
        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 2, 0, 0)) >= 0);
        BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 3, 0, 0)) >= 0);
        BB_CHECK_EQ(m.decision_team, 1 - active);
    }
}

BB_TEST(trickster_ball_and_chain_exclusion_does_not_exclude_dump_off) {
    bb_match m; int attacker, target, receiver;
    const uint8_t dice[] = {3}; bb_rng rng; bb_rng_script(&rng, dice, 1);
    dump_fixture(&m, &rng, BB_HOME, &attacker, &target, &receiver);
    fx_give_skill(&m, target, BB_SK_TRICKSTER);
    bb_top(&m)->y |= BB_TA_FROM_BALL_CHAIN;
    m.status = BB_STATUS_RUNNING; BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 0, 0, 0)) >= 0);
    BB_CHECK_EQ(fx_find(&m, act(BB_A_CHOOSE_OPTION, 2, 0, 0)), -1);
}

BB_TEST(trickster_loose_ball_pickup_is_optional_and_has_no_team_reroll) {
    bb_match m; fx_match_midturn(&m, BB_HOME, 0);
    int actor = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int target = fx_player(&m, BB_AWAY, 0, 11, 7, 7, 3, 2, 3, 8);
    fx_give_skill(&m, target, BB_SK_TRICKSTER);
    fx_give_skill(&m, target, BB_SK_SURE_HANDS);
    m.ball.state = BB_BALL_ON_GROUND; m.ball.x = 10; m.ball.y = 6;
    const uint8_t dice[] = {1, 1, 3}; bb_rng rng; bb_rng_script(&rng, dice, 3);
    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    bb_push_targeted_action(&m, actor, target, BB_TA_BLOCK, 0);
    m.status = BB_STATUS_RUNNING; BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    fx_apply(&m, act(BB_A_CHOOSE_OPTION, 2, 0, 0), &rng);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_SPECIAL_TARGET, BB_SK_TRICKSTER, 10, 6), &rng),
                BB_STATUS_DECISION);
    BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 4, 0, 0)) >= 0);
    BB_CHECK(fx_find(&m, act(BB_A_CHOOSE_OPTION, 5, 0, 0)) >= 0);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_CHOOSE_OPTION, 4, 0, 0), &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_TEST);
    BB_CHECK_EQ(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_TEAM, 0, 0)), -1);
    BB_CHECK(fx_find(&m, act(BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_SURE_HANDS, 0)) >= 0);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_DECLINE_REROLL, 0, 0, 0), &rng), BB_STATUS_DECISION);
    BB_CHECK(!m.turnover);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(trickster_relocation_keeps_slot_target_and_defers_touchdown_until_action) {
    bb_match m; fx_match_midturn(&m, BB_HOME, 0);
    int actor = fx_lineman(&m, BB_HOME, 0, 1, 7);
    int target = fx_player(&m, BB_AWAY, 0, 2, 7, 7, 3, 2, 3, 8);
    fx_give_skill(&m, actor, BB_SK_HYPNOTIC_GAZE);
    fx_give_skill(&m, target, BB_SK_TRICKSTER);
    fx_ball_held(&m, target);
    const uint8_t dice[] = {3}; bb_rng rng; bb_rng_script(&rng, dice, 1);
    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    bb_push_targeted_action(&m, actor, target, BB_TA_GAZE, 0);
    m.status = BB_STATUS_RUNNING; BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    fx_apply(&m, act(BB_A_CHOOSE_OPTION, 2, 0, 0), &rng);
    BB_CHECK_EQ(fx_apply(&m, act(BB_A_SPECIAL_TARGET, BB_SK_TRICKSTER, 0, 7), &rng),
                BB_STATUS_DECISION);
    /* The scripted Gaze die is consumed before the delayed score.  TD then
     * clears the drive, so the post-decision state is the next setup. */
    BB_CHECK_EQ(m.score[BB_AWAY], 1);
    BB_CHECK_EQ(m.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(rng.script_pos, 1);
    BB_CHECK(!bb_rng_error(&rng));
}

BB_TEST(trickster_respects_rooted_and_no_ball_pickup_guard) {
    bb_match m; fx_match_midturn(&m, BB_HOME, 0);
    int actor = fx_lineman(&m, BB_HOME, 0, 10, 7);
    int target = fx_player(&m, BB_AWAY, 0, 11, 7, 7, 3, 2, 3, 8);
    fx_give_skill(&m, target, BB_SK_TRICKSTER);
    m.players[target].flags |= BB_PF_ROOTED;
    const uint8_t dice[] = {1, 3}; bb_rng rng; bb_rng_script(&rng, dice, 2);
    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    bb_push_targeted_action(&m, actor, target, BB_TA_BLOCK, 0);
    m.status = BB_STATUS_RUNNING;
    /* Rooted removes the Trickster window entirely, so Block dice are next. */
    BB_CHECK_EQ(fx_run(&m, &rng), BB_STATUS_DECISION);
    BB_CHECK_EQ(bb_top(&m)->proc, BB_PROC_BLOCK);

    /* Without Rooted, No Ball may relocate but pickup fails and bounces
     * automatically without consuming a pickup D6 or causing a turnover. */
    bb_match n; fx_match_midturn(&n, BB_HOME, 0);
    actor = fx_lineman(&n, BB_HOME, 0, 10, 7);
    target = fx_player(&n, BB_AWAY, 0, 11, 7, 7, 3, 2, 3, 8);
    fx_give_skill(&n, target, BB_SK_TRICKSTER); fx_give_skill(&n, target, BB_SK_NO_BALL);
    n.ball.state = BB_BALL_ON_GROUND; n.ball.x = 10; n.ball.y = 6;
    bb_rng_script(&rng, dice, 2); BB_CHECK_EQ(fx_run(&n, &rng), BB_STATUS_DECISION);
    bb_push_targeted_action(&n, actor, target, BB_TA_BLOCK, 0);
    n.status = BB_STATUS_RUNNING; fx_run(&n, &rng);
    fx_apply(&n, act(BB_A_CHOOSE_OPTION, 2, 0, 0), &rng);
    fx_apply(&n, act(BB_A_SPECIAL_TARGET, BB_SK_TRICKSTER, 10, 6), &rng);
    BB_CHECK_EQ(fx_apply(&n, act(BB_A_CHOOSE_OPTION, 4, 0, 0), &rng), BB_STATUS_DECISION);
    BB_CHECK(!(n.players[target].flags & BB_PF_HAS_BALL));
    BB_CHECK(!n.turnover); BB_CHECK_EQ(rng.script_pos, 2); BB_CHECK(!bb_rng_error(&rng));
}

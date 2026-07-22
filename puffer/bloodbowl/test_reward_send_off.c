#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"
#include "bb_fixtures.h"

enum {
    ATT = 0,
    DEF = BB_TEAM_SLOTS,
};

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char mask[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
} RewardFixture;

static void check_float(float got, float want) {
    float d = got - want;
    if (d < 0.0f) d = -d;
    BB_CHECK(d < 0.00001f);
}

static float reward_clip_frac(const Log* log) {
    return log->reward_samples > 0.0f
        ? log->reward_clipped_samples / log->reward_samples : 0.0f;
}

static float reward_clip_frac_nonzero(const Log* log) {
    return log->reward_nonzero_samples > 0.0f
        ? log->reward_clipped_samples / log->reward_nonzero_samples : 0.0f;
}

static float reward_nonfinite_frac(const Log* log) {
    return log->reward_samples > 0.0f
        ? log->reward_nonfinite_samples / log->reward_samples : 0.0f;
}

static void setup_env_buffers(RewardFixture* f) {
    memset(f, 0, sizeof(*f));
    Bloodbowl* env = &f->env;
    env->num_agents = BBE_AGENTS;
    env->max_decisions = BBE_MAX_DECISIONS;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env->obs_ptr[a] = f->obs + a * BBE_OBS_SIZE;
        env->action_ptr[a] = f->actions + a * 3;
        env->action_mask_ptr[a] = f->mask + a * BBE_MASK_SIZE;
        env->reward_ptr[a] = f->rewards + a;
        env->terminal_ptr[a] = f->terminals + a;
        env->v4_dirty[a] = 1;
    }
}

static void build_foul_env(RewardFixture* f, float reward_send_off,
                           const uint8_t* dice, int n_dice) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    env->reward_send_off = reward_send_off;
    fx_match_midturn(&env->match, BB_HOME, 0);
    fx_lineman(&env->match, 0, 0, 10, 5);
    int victim = fx_lineman(&env->match, 1, 0, 10, 6);
    env->match.players[victim].stance = BB_STANCE_PRONE;
    fx_lineman(&env->match, 0, 1, 2, 2);
    fx_lineman(&env->match, 1, 1, 23, 12);

    bb_rng_script(&env->rng, dice, n_dice);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = env->match.active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = -1;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = env->match.score[0];
    env->score_prev[1] = env->score_start[1] = env->match.score[1];
    for (int t = 0; t < 2; t++) {
        int sent = 0;
        int out = 0;
        uint32_t out_mask = 0;
        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
            int loc = env->match.players[s].location;
            sent += (loc == BB_LOC_SENT_OFF);
            out += (loc == BB_LOC_KO || loc == BB_LOC_CAS);
            if (loc == BB_LOC_KO || loc == BB_LOC_CAS) out_mask |= 1u << s;
        }
        env->sent_off_prev[t] = sent;
        env->out_prev[t] = out;
        env->out_mask_prev[t] = out_mask;
        env->surf_prev[t] = env->match.surfs[t];
    }
    bbe_emit_all(env);
}

static int build_kickoff_touchback_env(RewardFixture* f,
                                       float reward_kickoff_touchback,
                                       const uint8_t* dice, int n_dice) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    env->reward_kickoff_touchback = reward_kickoff_touchback;
    bb_match* m = &env->match;
    memset(m, 0, sizeof(*m));
    m->team_id[0] = BB_TEAM_HUMAN;
    m->team_id[1] = BB_TEAM_ORC;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        m->players[s].location = BB_LOC_ABSENT;
    }
    m->half = 1;
    m->weather = BB_WEATHER_PERFECT;
    m->ball.state = BB_BALL_OFF_PITCH;
    m->ball.carrier = BB_NO_PLAYER;
    m->status = BB_STATUS_RUNNING;
    m->kicking_team = BB_HOME;
    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
    bb_top(m)->phase = 2; // next advance pushes KICKOFF

    int receiver = fx_lineman(m, BB_AWAY, 0, 20, 7);

    bb_rng_script(&env->rng, dice, n_dice);
    bb_advance(m, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = m->active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = -1;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = m->score[0];
    env->score_prev[1] = env->score_start[1] = m->score[1];
    bbe_emit_all(env);
    return receiver;
}

static void step_action(RewardFixture* f, bb_action a) {
    Bloodbowl* env = &f->env;
    int agent = env->match.decision_team & 1;
    env->action_ptr[agent][0] = (float)a.type;
    env->action_ptr[agent][1] = (float)bbe_action_arg(agent, a);
    env->action_ptr[agent][2] = (float)bbe_action_sq(agent, a);
    c_step(env);
}

static void step_random_masked(RewardFixture* f, bb_rng* rng) {
    for (int a = 0; a < BBE_AGENTS; a++) {
        bbe_sample_joint_uniform(&f->env, a, f->env.action_ptr[a], rng);
    }
    c_step(&f->env);
}

static void drive_foul_to_argue(RewardFixture* f) {
    step_action(f, (bb_action){BB_A_ACTIVATE, ATT, 0, 0});
    step_action(f, (bb_action){BB_A_DECLARE, BB_ACT_FOUL, 0, 0});
    step_action(f, (bb_action){BB_A_FOUL_TARGET, 0, 10, 6});
}

BB_TEST(puffer_reward_send_off_penalizes_fouling_team_only) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 2};
    build_foul_env(&f, -0.15f, dice, 2);

    drive_foul_to_argue(&f);
    BB_CHECK_EQ(f.env.match.players[ATT].location, BB_LOC_ON_PITCH);
    check_float(f.rewards[0], 0.0f);
    check_float(f.rewards[1], 0.0f);

    step_action(&f, (bb_action){BB_A_CHOOSE_OPTION, 0, 0, 0});
    BB_CHECK_EQ(f.env.match.players[ATT].location, BB_LOC_SENT_OFF);
    check_float(f.rewards[0], -0.15f);
    check_float(f.rewards[1], 0.0f);
    check_float(f.env.ep_return[0], -0.15f);
    check_float(f.env.ep_return[1], 0.0f);
    check_float(f.env.step_reward_component[BB_HOME][BBE_REWARD_SEND_OFF],
                -0.15f);
    BB_CHECK_EQ(f.env.ep_send_offs, 1);
}

BB_TEST(puffer_reward_send_off_bribe_save_fires_nothing) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 2, 6};
    build_foul_env(&f, -0.15f, dice, 3);
    f.env.match.bribes[0] = 1;

    drive_foul_to_argue(&f);
    BB_CHECK_EQ(f.env.match.players[ATT].location, BB_LOC_ON_PITCH);
    BB_CHECK_EQ(f.env.match.bribes[0], 0);
    check_float(f.rewards[0], 0.0f);
    check_float(f.rewards[1], 0.0f);
    check_float(f.env.ep_return[0], 0.0f);
    check_float(f.env.ep_return[1], 0.0f);
    BB_CHECK_EQ(f.env.ep_send_offs, 0);
}

BB_TEST(puffer_reward_send_off_argue_save_fires_nothing) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 2, 6};
    build_foul_env(&f, -0.15f, dice, 3);

    drive_foul_to_argue(&f);
    step_action(&f, (bb_action){BB_A_CHOOSE_OPTION, 1, 0, 0});
    BB_CHECK_EQ(f.env.match.players[ATT].location, BB_LOC_ON_PITCH);
    check_float(f.rewards[0], 0.0f);
    check_float(f.rewards[1], 0.0f);
    check_float(f.env.ep_return[0], 0.0f);
    check_float(f.env.ep_return[1], 0.0f);
    BB_CHECK_EQ(f.env.ep_send_offs, 0);
}

BB_TEST(puffer_reward_send_off_default_zero_no_reward) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 2};
    build_foul_env(&f, 0.0f, dice, 2);

    drive_foul_to_argue(&f);
    step_action(&f, (bb_action){BB_A_CHOOSE_OPTION, 0, 0, 0});
    BB_CHECK_EQ(f.env.match.players[ATT].location, BB_LOC_SENT_OFF);
    check_float(f.rewards[0], 0.0f);
    check_float(f.rewards[1], 0.0f);
    check_float(f.env.ep_return[0], 0.0f);
    check_float(f.env.ep_return[1], 0.0f);
}

BB_TEST(puffer_reward_kickoff_touchback_penalizes_kicking_team_once) {
    RewardFixture f;
    // Target (13,0); d8=1 -> (-1,-1), d6=2 -> (11,-2): off the pitch.
    static const uint8_t dice[] = {1, 2, 1, 1};
    int receiver = build_kickoff_touchback_env(&f, -0.125f, dice, 4);
    BB_CHECK_EQ(f.env.match.decision_team, BB_HOME);

    step_action(&f, (bb_action){BB_A_KICK_TARGET, 0, 13, 0});
    BB_CHECK_EQ(f.env.match.decision_team, BB_AWAY);
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_OFF_PITCH);
    BB_CHECK(f.env.match.stack_top > 0);
    const bb_frame* top = &f.env.match.stack[f.env.match.stack_top - 1];
    BB_CHECK_EQ(top->proc, BB_PROC_KICKOFF);
    BB_CHECK_EQ(top->phase, 2);
    check_float(f.rewards[BB_HOME], -0.125f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.env.ep_return[BB_HOME], -0.125f);
    check_float(f.env.ep_return[BB_AWAY], 0.0f);
    check_float(f.env.step_reward_component[BB_HOME][BBE_REWARD_TOUCHBACK],
                -0.125f);
    BB_CHECK_EQ(f.env.ep_touchbacks, 1);
    BB_CHECK_EQ(f.env.kickoff_touchback_latched, 1);

    step_action(&f, (bb_action){BB_A_TOUCHBACK, receiver, 0, 0});
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, receiver);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.env.ep_return[BB_HOME], -0.125f);
    check_float(f.env.ep_return[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.ep_touchbacks, 1);
    BB_CHECK_EQ(f.env.kickoff_touchback_latched, 0);
}

BB_TEST(puffer_reward_kickoff_touchback_default_zero_no_reward) {
    RewardFixture f;
    static const uint8_t dice[] = {1, 2, 1, 1};
    build_kickoff_touchback_env(&f, 0.0f, dice, 4);

    step_action(&f, (bb_action){BB_A_KICK_TARGET, 0, 13, 0});
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.env.ep_return[BB_HOME], 0.0f);
    check_float(f.env.ep_return[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.ep_touchbacks, 1);
}

BB_TEST(puffer_possession_bookkeeping_ignores_kickoff_charge_flip) {
    RewardFixture f;
    static const uint8_t dice[] = {1};
    build_kickoff_touchback_env(&f, 0.0f, dice, 1);

    // Reframe the live kickoff decision as the end of a Charge! event. This
    // is a real active-team flip (kicker -> receiver), but not a completed
    // team turn and therefore must not enter the possession denominator.
    bb_match* m = &f.env.match;
    BB_CHECK(m->stack_top > 0);
    bb_frame* top = &m->stack[m->stack_top - 1];
    BB_CHECK_EQ(top->proc, BB_PROC_KICKOFF);
    top->phase = 7;
    top->x = 0;
    top->data = 0;
    m->active_team = BB_HOME;
    m->decision_team = BB_HOME;
    m->status = BB_STATUS_DECISION;
    f.env.prev_active_team = BB_HOME;
    bbe_refresh_legal(&f.env);
    bbe_emit_all(&f.env);
    BB_CHECK(!bb_in_team_turn(m, m->active_team));

    step_action(&f, (bb_action){BB_A_END_TURN, 0, 0, 0});
    BB_CHECK_EQ(m->active_team, BB_AWAY);
    BB_CHECK_EQ(f.env.ep_turns[BB_HOME], 0);
    BB_CHECK_EQ(f.env.ep_turns[BB_AWAY], 0);
    BB_CHECK_EQ(f.env.ep_turns_with_ball[BB_HOME], 0);
    BB_CHECK_EQ(f.env.ep_turns_with_ball[BB_AWAY], 0);
}

static int build_carrier_threat_env(RewardFixture* f,
                                    float reward_carrier_threat) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    env->reward_carrier_threat = reward_carrier_threat;
    bbe_validate_reward_config(env);

    fx_match_midturn(&env->match, BB_HOME, 0);
    int carrier = fx_lineman(&env->match, BB_HOME, 0, 13, 7);
    fx_ball_held(&env->match, carrier);
    fx_lineman(&env->match, BB_AWAY, 0, 13, 8); // adjacent free block threat
    fx_lineman(&env->match, BB_AWAY, 1, 23, 12);

    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = env->match.active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = BB_HOME;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = env->match.score[0];
    env->score_prev[1] = env->score_start[1] = env->match.score[1];
    bbe_emit_all(env);
    return carrier;
}

BB_TEST(puffer_reward_carrier_threat_symmetric_charge_sums_constant) {
    RewardFixture f;
    build_carrier_threat_env(&f, 0.05f);

    bb_carrier_threat_breakdown th;
    float tc = bb_carrier_threat_eval(&f.env.match, &th);
    BB_CHECK(th.carrier_team == BB_HOME);
    BB_CHECK(tc > 0.0f);

    step_action(&f, (bb_action){BB_A_END_TURN, 0, 0, 0});
    float want_home = 0.05f * (BB_CARRIER_THREAT_T_MAX - tc);
    float want_away = 0.05f * tc;
    check_float(f.rewards[BB_HOME], want_home);
    check_float(f.rewards[BB_AWAY], want_away);
    check_float(f.rewards[BB_HOME] + f.rewards[BB_AWAY],
                0.05f * BB_CARRIER_THREAT_T_MAX);
    check_float(f.env.ep_return[BB_HOME], want_home);
    check_float(f.env.ep_return[BB_AWAY], want_away);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_CARRIER_THREAT],
        want_home);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_CARRIER_THREAT],
        want_away);
    check_float(f.env.ep_carrier_threat, th.uncapped_total);
}

BB_TEST(puffer_reward_carrier_threat_default_zero_inert) {
    RewardFixture f;
    build_carrier_threat_env(&f, 0.0f);

    bb_carrier_threat_breakdown th;
    float tc = bb_carrier_threat_eval(&f.env.match, &th);
    BB_CHECK(tc > 0.0f); // the state has signal; default-zero ignores it

    step_action(&f, (bb_action){BB_A_END_TURN, 0, 0, 0});
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.env.ep_return[BB_HOME], 0.0f);
    check_float(f.env.ep_return[BB_AWAY], 0.0f);
    check_float(f.env.ep_carrier_threat, 0.0f);
}

BB_TEST(puffer_possession_annuity_fires_on_genuine_team_turn_end) {
    RewardFixture f;
    build_carrier_threat_env(&f, 0.0f);
    f.env.reward_possession = 0.03f;

    step_action(&f, (bb_action){BB_A_END_TURN, 0, 0, 0});
    BB_CHECK_EQ(f.env.ep_turns[BB_HOME], 1);
    BB_CHECK_EQ(f.env.ep_turns[BB_AWAY], 0);
    BB_CHECK_EQ(f.env.ep_turns_with_ball[BB_HOME], 1);
    BB_CHECK_EQ(f.env.ep_turns_with_ball[BB_AWAY], 0);
    check_float(f.rewards[BB_HOME], 0.03f);
    check_float(f.rewards[BB_AWAY], -0.03f);
    check_float(f.env.ep_return[BB_HOME], 0.03f);
    check_float(f.env.ep_return[BB_AWAY], -0.03f);
    check_float(f.env.step_reward_component[BB_HOME][BBE_REWARD_POSSESSION],
                0.03f);
    check_float(f.env.step_reward_component[BB_AWAY][BBE_REWARD_POSSESSION],
                -0.03f);
}

static int build_distance_potential_env(RewardFixture* f, bool held_ball,
                                        int player_x, int ball_x) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    env->reward_dist_ball = 0.05f;
    env->reward_dist_endzone = 0.20f;

    fx_match_midturn(&env->match, BB_HOME, 0);
    int mover = fx_lineman(&env->match, BB_HOME, 0, player_x, 7);
    fx_lineman(&env->match, BB_AWAY, 0, 23, 12);
    if (held_ball) fx_ball_held(&env->match, mover);
    else fx_ball_ground(&env->match, ball_x, 7);

    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = env->match.active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = held_ball ? BB_HOME : -1;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = env->match.score[0];
    env->score_prev[1] = env->score_start[1] = env->match.score[1];
    bbe_emit_all(env);
    return mover;
}

BB_TEST(puffer_reward_carry_potential_emits_full_pitch_delta) {
    RewardFixture f;
    int mover = build_distance_potential_env(&f, true, 5, 0);

    step_action(&f, (bb_action){BB_A_ACTIVATE, mover, 0, 0});
    check_float(f.rewards[BB_HOME], 0.0f); // primes the carry potential
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0});
    check_float(f.rewards[BB_HOME], 0.0f);
    step_action(&f, (bb_action){BB_A_STEP, 0, 6, 7});

    // HOME's end zone is x=25: moving x=5 -> 6 reduces distance 20 -> 19.
    check_float(f.rewards[BB_HOME], 0.20f);
    check_float(f.env.ep_return[BB_HOME], 0.20f);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_ENDZONE],
        0.20f);
    check_float(f.env.step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL],
                0.0f);
}

BB_TEST(puffer_reward_fetch_potential_emits_full_pitch_delta) {
    RewardFixture f;
    int mover = build_distance_potential_env(&f, false, 4, 25);

    step_action(&f, (bb_action){BB_A_ACTIVATE, mover, 0, 0});
    check_float(f.rewards[BB_HOME], 0.0f); // primes the fetch potential
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0});
    check_float(f.rewards[BB_HOME], 0.0f);
    step_action(&f, (bb_action){BB_A_STEP, 0, 5, 7});

    // Moving toward the loose ball reduces Chebyshev distance 21 -> 20.
    check_float(f.rewards[BB_HOME], 0.05f);
    check_float(f.env.ep_return[BB_HOME], 0.05f);
    check_float(f.env.step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL],
                0.05f);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_ENDZONE],
        0.0f);
}

BB_TEST(puffer_possession_metric_counts_touchdown_ending_turn_once) {
    RewardFixture f;
    int mover = build_distance_potential_env(&f, true, 24, 0);
    f.env.reward_dist_ball = 0.0f;
    f.env.reward_dist_endzone = 0.0f;
    f.env.reward_possession = 0.03f;

    step_action(&f, (bb_action){BB_A_ACTIVATE, mover, 0, 0});
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0});
    step_action(&f, (bb_action){BB_A_STEP, 0, 25, 7});

    BB_CHECK_EQ(f.env.match.score[BB_HOME], 1);
    BB_CHECK_EQ(f.env.ep_turns[BB_HOME], 1);
    BB_CHECK_EQ(f.env.ep_turns_with_ball[BB_HOME], 1);
    BB_CHECK_EQ(f.env.ep_turns[BB_AWAY], 0);
    BB_CHECK_EQ(f.env.ep_turns_with_ball[BB_AWAY], 0);
    // The TD objective prices the score; the possession annuity is metric-only
    // on a scoring turn and must not also pay a terminal possession coupon.
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
}

BB_TEST(puffer_final_turn_touchdown_stacks_objective_without_possession_clip) {
    RewardFixture f;
    int mover = build_distance_potential_env(&f, true, 24, 0);
    f.env.reward_configured = 1;
    f.env.reward_td = 0.4f;
    f.env.reward_win = 0.6f;
    f.env.reward_possession = 0.03f;
    f.env.reward_dist_ball = 0.0f;
    f.env.reward_dist_endzone = 0.0f;
    // This already-open HOME turn is the final outstanding turn of half 2.
    // Scoring must finish the match in the same c_step that emits the TD.
    f.env.match.half = 2;
    f.env.match.turn[BB_HOME] = 8;
    f.env.match.turn[BB_AWAY] = 8;

    step_action(&f, (bb_action){BB_A_ACTIVATE, mover, 0, 0});
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0});
    step_action(&f, (bb_action){BB_A_STEP, 0, 25, 7});

    check_float(f.terminals[BB_HOME], 1.0f);
    check_float(f.terminals[BB_AWAY], 1.0f);
    check_float(f.rewards[BB_HOME], 1.0f);
    check_float(f.rewards[BB_AWAY], -1.0f);
    // The scoring turn enters the possession metric, but its annuity coupon is
    // suppressed because the TD already priced this boundary.
    check_float(f.env.log.possession_rate, 1.0f);
    check_float(reward_clip_frac(&f.env.log), 0.0f);
    check_float(f.env.log.reward_clip_episodes, 0.0f);
    check_float(f.env.log.reward_episode_abs_max_mean, 1.0f);
}

BB_TEST(puffer_possession_bookkeeping_survives_auto_empty_opponent_turn) {
    RewardFixture f;
    setup_env_buffers(&f);
    Bloodbowl* env = &f.env;
    env->reward_possession = 0.03f;
    env->reward_carrier_threat = 0.05f;

    fx_match_midturn(&env->match, BB_HOME, 0);
    int carrier = fx_lineman(&env->match, BB_HOME, 0, 5, 5);
    fx_ball_held(&env->match, carrier);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = env->match.active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = BB_HOME;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = env->match.score[0];
    env->score_prev[1] = env->score_start[1] = env->match.score[1];
    bbe_emit_all(env);

    step_action(&f, (bb_action){BB_A_END_TURN, 0, 0, 0});

    // bb_advance compresses AWAY's playerless turn and reaches HOME's next
    // decision in the same c_step, so final active_team alone cannot see
    // either boundary.
    BB_CHECK_EQ(env->match.active_team, BB_HOME);
    BB_CHECK_EQ(env->ep_turns[BB_HOME], 1);
    BB_CHECK_EQ(env->ep_turns[BB_AWAY], 1);
    BB_CHECK_EQ(env->ep_turns_with_ball[BB_HOME], 1);
    BB_CHECK_EQ(env->ep_turns_with_ball[BB_AWAY], 0);
    // The original HOME boundary must also fire positional hooks even though
    // the playerless AWAY turn was compressed and active_team returned HOME.
    check_float(f.rewards[BB_HOME],
                0.03f + 0.05f * BB_CARRIER_THREAT_T_MAX);
    check_float(f.rewards[BB_AWAY], -0.03f);
    check_float(env->ep_carrier_threat, 0.0f);
}

BB_TEST(puffer_turnover_bookkeeping_counts_failure_created_by_action) {
    RewardFixture f;
    static const uint8_t dice[] = {1, 1, 1, 1};
    setup_env_buffers(&f);
    Bloodbowl* env = &f.env;

    fx_match_midturn(&env->match, BB_HOME, 0);
    int mover = fx_lineman(&env->match, BB_HOME, 0, 5, 5);
    fx_lineman(&env->match, BB_HOME, 1, 2, 2);
    fx_lineman(&env->match, BB_AWAY, 0, 5, 6); // marks the mover
    fx_lineman(&env->match, BB_AWAY, 1, 23, 12);
    bb_rng_script(&env->rng, dice, sizeof dice);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = env->match.active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = -1;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = env->match.score[0];
    env->score_prev[1] = env->score_start[1] = env->match.score[1];
    bbe_emit_all(env);

    step_action(&f, (bb_action){BB_A_ACTIVATE, mover, 0, 0});
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0});
    step_action(&f, (bb_action){BB_A_STEP, 0, 4, 5});

    BB_CHECK_EQ(env->match.turnovers_completed[BB_HOME], 1);
    BB_CHECK_EQ(env->ep_turnovers[BB_HOME], 1);
    BB_CHECK_EQ(env->ep_turns[BB_HOME], 1);
    BB_CHECK_EQ(env->ep_turnovers[BB_AWAY], 0);
}

BB_TEST(puffer_reward_explicit_zero_objective_survives_reset) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_td = 0.0f;
    f.env.reward_win = 0.0f;
    f.env.reward_draw = 0.0f;
    f.env.reward_configured = 1;

    c_reset(&f.env);

    check_float(f.env.reward_td, 0.0f);
    check_float(f.env.reward_win, 0.0f);
    check_float(f.env.reward_draw, 0.0f);
}

BB_TEST(puffer_reward_standalone_defaults_match_public_config) {
    RewardFixture f;
    setup_env_buffers(&f);

    c_reset(&f.env);

    check_float(f.env.reward_td, 0.4f);
    check_float(f.env.reward_win, 0.6f);
    check_float(f.env.reward_draw, 0.0f);
}

BB_TEST(puffer_reward_config_rejects_nonfinite_coefficients) {
    RewardFixture f;
    setup_env_buffers(&f);
    const char* bad_field = NULL;

    BB_CHECK(bbe_reward_config_scalars_valid(&f.env, &bad_field));
    f.env.reward_dist_endzone = INFINITY;
    BB_CHECK(!bbe_reward_config_scalars_valid(&f.env, &bad_field));
    BB_CHECK(bad_field != NULL);
    BB_CHECK(strcmp(bad_field, "reward_dist_endzone") == 0);

    f.env.reward_dist_endzone = 3.402823466e+38F;
    BB_CHECK(!bbe_reward_config_scalars_valid(&f.env, &bad_field));
    BB_CHECK(strcmp(bad_field, "reward_dist_endzone") == 0);
}

BB_TEST(puffer_reward_clip_telemetry_sees_terminal_stack) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_win = 0.8f;
    f.env.match.score[BB_HOME] = 1;
    f.env.match.score[BB_AWAY] = 0;
    f.rewards[BB_HOME] = 0.4f;
    f.rewards[BB_AWAY] = -0.4f;
    f.env.step_objective_reward[BB_HOME] = 0.4f;
    f.env.step_objective_reward[BB_AWAY] = -0.4f;
    f.env.ep_return[BB_HOME] = 0.4f;
    f.env.ep_return[BB_AWAY] = -0.4f;

    bbe_finish_episode(&f.env);

    check_float(reward_clip_frac(&f.env.log), 1.0f);
    check_float(f.env.log.reward_clip_episodes, 1.0f);
    check_float(f.env.log.reward_nonfinite_episodes, 0.0f);
    check_float(f.env.log.reward_clip_excess, 0.4f);
    check_float(f.env.log.reward_clip_terminal_samples, 2.0f);
    check_float(f.env.log.reward_clip_nonterminal_samples, 0.0f);
    check_float(f.env.log.reward_episode_abs_max_mean, 1.2f);
    check_float(reward_nonfinite_frac(&f.env.log), 0.0f);
}

BB_TEST(puffer_terminal_result_discards_incidental_shaping_before_emission) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_win = 0.6f;
    f.env.match.score[BB_HOME] = 1;
    f.env.match.score[BB_AWAY] = 0;

    // A minimal deterministic reproducer with the failed screen's observed
    // 1.015 magnitude. The old code stacked a terminal loss bonus on this
    // -0.415 action subtotal. The retained artifact does not identify its one
    // clip as terminal/non-terminal, so this locks the independently confirmed
    // structural hazard rather than claiming the historical sample's sign.
    f.rewards[BB_HOME] = 0.415f;
    f.rewards[BB_AWAY] = -0.415f;
    f.env.ep_return[BB_HOME] = 0.415f;
    f.env.ep_return[BB_AWAY] = -0.415f;

    bbe_finish_episode(&f.env);

    check_float(f.rewards[BB_HOME], 0.6f);
    check_float(f.rewards[BB_AWAY], -0.6f);
    check_float(f.env.log.episode_return, 0.6f);
    check_float(reward_clip_frac(&f.env.log), 0.0f);
    check_float(f.env.log.reward_clip_episodes, 0.0f);
    check_float(f.env.log.reward_episode_abs_max_mean, 0.6f);
    check_float(f.env.log.reward_clip_terminal_samples, 0.0f);
    check_float(f.env.log.reward_clip_nonterminal_samples, 0.0f);
}

BB_TEST(puffer_reward_clip_telemetry_splits_nonterminal_emissions) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.rewards[BB_HOME] = 1.015f;
    f.rewards[BB_AWAY] = 0.0f;
    bbe_record_reward_emission(&f.env);

    f.rewards[BB_HOME] = f.rewards[BB_AWAY] = 0.0f;
    bbe_finish_episode(&f.env);

    check_float(f.env.log.reward_clipped_samples, 1.0f);
    check_float(f.env.log.reward_clip_terminal_samples, 0.0f);
    check_float(f.env.log.reward_clip_nonterminal_samples, 1.0f);
}

BB_TEST(puffer_reward_clip_telemetry_includes_statmatch_terminal_term) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_statmatch_scale = 1.0f;

    bbe_finish_episode(&f.env);

    BB_CHECK(f.env.log.statmatch_term < -1.0f);
    check_float(reward_clip_frac(&f.env.log), 1.0f);
    check_float(f.env.log.reward_clip_episodes, 1.0f);
    BB_CHECK(f.env.log.reward_episode_abs_max_mean > 1.0f);
    BB_CHECK(f.env.log.reward_clip_excess > 0.0f);
    check_float(f.env.log.episode_return, f.rewards[BB_HOME]);
}

BB_TEST(puffer_reward_clip_nonzero_fraction_is_not_diluted_by_sparse_zeros) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    for (int i = 0; i < 100; i++) {
        f.rewards[BB_HOME] = f.rewards[BB_AWAY] = 0.0f;
        bbe_record_reward_emission(&f.env);
    }
    f.env.reward_win = 0.8f;
    f.env.match.score[BB_HOME] = 1;
    f.rewards[BB_HOME] = 0.4f;
    f.rewards[BB_AWAY] = -0.4f;
    f.env.step_objective_reward[BB_HOME] = 0.4f;
    f.env.step_objective_reward[BB_AWAY] = -0.4f;

    bbe_finish_episode(&f.env);

    check_float(reward_clip_frac(&f.env.log), 2.0f / 202.0f);
    check_float(reward_clip_frac_nonzero(&f.env.log), 1.0f);
}

BB_TEST(puffer_reward_nonfinite_telemetry_sees_raw_nan_and_infinity) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.rewards[BB_HOME] = NAN;
    f.rewards[BB_AWAY] = INFINITY;

    bbe_finish_episode(&f.env);

    check_float(reward_nonfinite_frac(&f.env.log), 1.0f);
    check_float(f.env.log.reward_nonfinite_episodes, 1.0f);
    check_float(reward_clip_frac(&f.env.log), 0.0f);
    check_float(f.env.log.reward_clip_episodes, 0.0f);
    check_float(f.env.log.reward_episode_abs_max_mean, 0.0f);
}

BB_TEST(puffer_reward_clip_threshold_is_strictly_above_one) {
    RewardFixture exact;
    setup_env_buffers(&exact);
    exact.env.reward_configured = 1;
    exact.rewards[BB_HOME] = 1.0f;
    exact.rewards[BB_AWAY] = -1.0f;
    exact.env.step_objective_reward[BB_HOME] = 1.0f;
    exact.env.step_objective_reward[BB_AWAY] = -1.0f;
    bbe_finish_episode(&exact.env);
    check_float(reward_clip_frac(&exact.env.log), 0.0f);
    check_float(exact.env.log.reward_clip_episodes, 0.0f);
    check_float(exact.env.log.reward_episode_abs_max_mean, 1.0f);

    RewardFixture over;
    setup_env_buffers(&over);
    over.env.reward_configured = 1;
    float just_over = nextafterf(1.0f, INFINITY);
    over.rewards[BB_HOME] = just_over;
    over.rewards[BB_AWAY] = -just_over;
    over.env.step_objective_reward[BB_HOME] = just_over;
    over.env.step_objective_reward[BB_AWAY] = -just_over;
    bbe_finish_episode(&over.env);
    check_float(reward_clip_frac(&over.env.log), 1.0f);
    check_float(over.env.log.reward_clip_episodes, 1.0f);
    BB_CHECK(over.env.log.reward_clip_excess > 0.0f);
    check_float(over.env.log.reward_episode_abs_max_mean, just_over);
}

BB_TEST(puffer_reward_clip_fraction_is_emission_weighted_across_episodes) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    for (int i = 0; i < 100; i++) {
        f.rewards[BB_HOME] = f.rewards[BB_AWAY] = 0.0f;
        bbe_record_reward_emission(&f.env);
    }
    f.env.reward_win = 0.8f;
    f.env.match.score[BB_HOME] = 1;
    f.rewards[BB_HOME] = 0.4f;
    f.rewards[BB_AWAY] = -0.4f;
    f.env.step_objective_reward[BB_HOME] = 0.4f;
    f.env.step_objective_reward[BB_AWAY] = -0.4f;
    bbe_finish_episode(&f.env);

    // A second two-sample unclipped episode must contribute by emission
    // count, not receive equal weight with the preceding 202-sample episode.
    f.env.reward_win = 0.0f;
    f.rewards[BB_HOME] = f.rewards[BB_AWAY] = 0.0f;
    bbe_finish_episode(&f.env);

    check_float(f.env.log.n, 2.0f);
    check_float(f.env.log.reward_samples, 204.0f);
    check_float(f.env.log.reward_clipped_samples, 2.0f);
    check_float(reward_clip_frac(&f.env.log), 2.0f / 204.0f);
}

BB_TEST(puffer_reward_block_buckets_match_predecision_terms) {
    RewardFixture f;
    setup_env_buffers(&f);
    Bloodbowl* env = &f.env;
    env->reward_configured = 1;
    env->reward_k_kd = 0.10f;
    env->reward_k_value = 0.50f;
    env->reward_k_ball = 0.15f;
    env->reward_k_self_injury = 0.07f;
    env->reward_k_turnover = 0.15f;
    env->reward_k_seq = 0.03f;

    fx_match_midturn(&env->match, BB_HOME, 0);
    int attacker = fx_lineman(&env->match, BB_HOME, 0, 10, 5);
    int defender = fx_lineman(&env->match, BB_AWAY, 0, 11, 5);
    fx_lineman(&env->match, BB_HOME, 1, 3, 3); // pending safe activation
    fx_lineman(&env->match, BB_AWAY, 1, 23, 12);
    fx_ball_held(&env->match, defender);
    bb_rng_seed(&env->rng, 1234, 1);
    bb_advance(&env->match, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = env->match.active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = BB_AWAY;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = env->match.score[0];
    env->score_prev[1] = env->score_start[1] = env->match.score[1];
    bbe_emit_all(env);

    step_action(&f, (bb_action){BB_A_ACTIVATE, attacker, 0, 0});
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_BLOCK, 0, 0});

    bb_blockev ev;
    bb_block_ev(&env->match, attacker, defender, 0, NULL, &ev);
    float exposure = env->reward_k_kd * ev.p_def_down +
                     env->reward_k_value * ev.p_def_removed *
                         player_cost_100k(&env->match, defender) +
                     env->reward_k_ball * ev.p_ball_out;
    float self_injury = env->reward_k_self_injury * ev.p_att_removed *
                        player_cost_100k(&env->match, attacker);
    float turnover = env->reward_k_turnover * ev.p_turnover;
    int pending = 0;
    for (int s = 0; s < BB_TEAM_SLOTS; s++) {
        if (s == attacker) continue;
        const bb_player* p = &env->match.players[s];
        pending += p->location == BB_LOC_ON_PITCH &&
                   p->stance == BB_STANCE_STANDING &&
                   !(p->flags & BB_PF_USED);
    }
    float sequence = env->reward_k_seq * ev.p_turnover * (float)pending;

    step_action(&f, (bb_action){BB_A_BLOCK_TARGET, 0, 11, 5});

    check_float(env->step_reward_component[BB_HOME]
                                          [BBE_REWARD_BLOCK_EXPOSURE],
                exposure);
    check_float(env->step_reward_component[BB_AWAY]
                                          [BBE_REWARD_BLOCK_EXPOSURE],
                -exposure);
    check_float(env->step_reward_component[BB_HOME]
                                          [BBE_REWARD_BLOCK_SELF_INJURY],
                -self_injury);
    check_float(env->step_reward_component[BB_HOME]
                                          [BBE_REWARD_BLOCK_TURNOVER],
                -turnover);
    check_float(env->step_reward_component[BB_HOME]
                                          [BBE_REWARD_BLOCK_SEQUENCE],
                -sequence);
}

BB_TEST(puffer_reward_component_ledger_classifies_draw_result) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_draw = -0.10f;

    bbe_finish_episode(&f.env);

    check_float(f.env.log.reward_component[BBE_REWARD_RESULT_DRAW], -0.10f);
    check_float(f.env.log.reward_component[BBE_REWARD_RESULT_WINLOSS], 0.0f);
    check_float(f.env.log.episode_return, -0.10f);
    check_float(f.env.log.reward_postclip_return, -0.10f);
}

BB_TEST(puffer_reward_component_ledger_flags_objective_scratch_bypass) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.match.score[BB_HOME] = 1;
    f.env.step_objective_reward[BB_HOME] = 0.40f;
    f.env.step_objective_reward[BB_AWAY] = -0.40f;

    bbe_finish_episode(&f.env);

    BB_CHECK(f.env.log.reward_component_mismatch_samples >= 2.0f);
    check_float(f.env.log.reward_component[BBE_REWARD_TOUCHDOWN], 0.40f);
}

BB_TEST(puffer_reward_component_ledger_reconciles_real_c_step_r0_rollout) {
    RewardFixture f;
    setup_env_buffers(&f);
    Bloodbowl* env = &f.env;
    env->seed = 4242;
    env->reward_configured = 1;
    env->reward_td = 0.40f;
    env->reward_win = 0.60f;
    env->reward_draw = 0.0f;
    env->reward_ball_gain = 0.05f;
    env->reward_dist_ball = 0.02f;
    env->reward_dist_endzone = 0.04f;
    env->reward_k_kd = 0.10f;
    env->reward_k_value = 0.50f;
    env->reward_k_ball = 0.15f;
    env->reward_k_seq = 0.03f;
    env->reward_k_turnover = 0.15f;
    env->reward_possession = 0.03f;
    env->reward_rush_cost = 0.015f;
    c_reset(env);

    bb_rng policy_rng;
    bb_rng_seed(&policy_rng, 0xC0FFEE, 9);
    int episodes = 0;
    while (episodes < 20) {
        step_random_masked(&f, &policy_rng);
        episodes += f.terminals[BB_HOME] != 0.0f;
    }

    check_float(env->log.n, 20.0f);
    check_float(env->log.reward_component_mismatch_samples, 0.0f);
    check_float(env->log.reward_component_nonfinite_samples, 0.0f);
    float component_sum = env->log.reward_component_residual;
    float shaped_abs = 0.0f;
    for (int c = 0; c < BBE_REWARD_COMPONENT_COUNT; c++) {
        component_sum += env->log.reward_component[c];
        if (c != BBE_REWARD_TOUCHDOWN && c != BBE_REWARD_RESULT_WINLOSS &&
            c != BBE_REWARD_RESULT_DRAW) {
            shaped_abs += fabsf(env->log.reward_component[c]);
        }
    }
    BB_CHECK(shaped_abs > 0.0f); // non-vacuous R0 shaping coverage
    BB_CHECK(fabsf(component_sum - env->log.episode_return) < 0.001f);
    BB_CHECK(fabsf(env->log.episode_return -
                       env->log.reward_clip_signed_delta -
                       env->log.reward_postclip_return) < 0.001f);
}

BB_TEST(puffer_reward_component_ledger_commits_nonterminal_emissions) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;

    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_DISTANCE_BALL, 0.20f);
    bbe_reward_add(&f.env, BB_AWAY, BBE_REWARD_DISTANCE_BALL, -0.20f);

    check_float(f.rewards[BB_HOME], 0.20f);
    check_float(f.env.ep_return[BB_HOME], 0.20f);
    check_float(f.env.step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL],
                0.20f);

    bbe_record_reward_emission(&f.env);
    check_float(f.env.ep_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL],
                0.20f);
    check_float(f.env.ep_reward_postclip_return[BB_HOME], 0.20f);
    check_float(f.env.ep_reward_component_residual[BB_HOME], 0.0f);
    BB_CHECK_EQ(f.env.ep_reward_component_mismatch_samples, 0);

    // Model the next c_step's begin state before ending the episode.
    f.rewards[BB_HOME] = f.rewards[BB_AWAY] = 0.0f;
    memset(f.env.step_reward_component, 0,
           sizeof(f.env.step_reward_component));
    f.env.step_return_base[BB_HOME] = f.env.ep_return[BB_HOME];
    f.env.step_return_base[BB_AWAY] = f.env.ep_return[BB_AWAY];
    bbe_finish_episode(&f.env);

    check_float(
        f.env.log.reward_component[BBE_REWARD_DISTANCE_BALL], 0.20f);
    check_float(f.env.log.reward_postclip_return, 0.20f);
    check_float(f.env.log.reward_clip_signed_delta, 0.0f);
    check_float(f.env.log.episode_return, 0.20f);
}

BB_TEST(puffer_reward_component_ledger_discards_terminal_shaping_once) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_win = 0.60f;
    f.env.match.score[BB_HOME] = 1;
    f.env.match.score[BB_AWAY] = 0;

    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_DISTANCE_ENDZONE, 0.415f);
    bbe_reward_add(&f.env, BB_AWAY, BBE_REWARD_DISTANCE_ENDZONE, -0.415f);
    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_TOUCHDOWN, 0.40f);
    bbe_reward_add(&f.env, BB_AWAY, BBE_REWARD_TOUCHDOWN, -0.40f);
    f.env.step_objective_reward[BB_HOME] = 0.40f;
    f.env.step_objective_reward[BB_AWAY] = -0.40f;

    bbe_finish_episode(&f.env);

    check_float(f.rewards[BB_HOME], 1.0f);
    check_float(f.rewards[BB_AWAY], -1.0f);
    check_float(
        f.env.log.reward_component[BBE_REWARD_DISTANCE_ENDZONE], 0.0f);
    check_float(f.env.log.reward_component[BBE_REWARD_TOUCHDOWN], 0.40f);
    check_float(f.env.log.reward_component[BBE_REWARD_RESULT_WINLOSS],
                0.60f);
    check_float(f.env.log.reward_terminal_suppressed_signed, 0.415f);
    check_float(f.env.log.reward_terminal_suppressed_abs, 0.415f);
    check_float(f.env.log.reward_component_residual, 0.0f);
    check_float(f.env.log.reward_postclip_return, 1.0f);
    check_float(f.env.log.episode_return, 1.0f);
}

BB_TEST(puffer_reward_component_ledger_reconciles_signed_clipping) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_win = 0.80f;
    f.env.match.score[BB_HOME] = 1;
    f.env.match.score[BB_AWAY] = 0;

    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_TOUCHDOWN, 0.40f);
    bbe_reward_add(&f.env, BB_AWAY, BBE_REWARD_TOUCHDOWN, -0.40f);
    f.env.step_objective_reward[BB_HOME] = 0.40f;
    f.env.step_objective_reward[BB_AWAY] = -0.40f;
    bbe_finish_episode(&f.env);

    check_float(f.env.log.episode_return, 1.20f);
    check_float(f.env.log.reward_postclip_return, 1.0f);
    check_float(f.env.log.reward_clip_signed_delta, 0.20f);
    check_float(f.env.log.reward_component[BBE_REWARD_TOUCHDOWN] +
                    f.env.log.reward_component[BBE_REWARD_RESULT_WINLOSS] +
                    f.env.log.reward_component_residual -
                    f.env.log.reward_clip_signed_delta,
                f.env.log.reward_postclip_return);
}

BB_TEST(puffer_reward_component_ledger_detects_direct_write_bypass) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;

    f.rewards[BB_HOME] += 0.25f;
    f.env.ep_return[BB_HOME] += 0.25f;
    bbe_record_reward_emission(&f.env);

    BB_CHECK_EQ(f.env.ep_reward_component_mismatch_samples, 1);
    check_float(f.env.ep_reward_component_residual[BB_HOME], 0.25f);
}

BB_TEST(puffer_reward_component_ledger_contains_nonfinite_components) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;

    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_RUSH, NAN);
    bbe_record_reward_emission(&f.env);
    BB_CHECK(f.env.ep_reward_component_nonfinite_samples > 0);
    check_float(f.env.ep_reward_component[BB_HOME][BBE_REWARD_RUSH], 0.0f);

    // Terminal authority suppresses the poisoned incidental step and keeps the
    // durable component log finite.
    f.env.step_return_base[BB_HOME] = 0.0f;
    f.env.step_return_base[BB_AWAY] = 0.0f;
    bbe_finish_episode(&f.env);
    BB_CHECK(isfinite(
        f.env.log.reward_component[BBE_REWARD_RUSH]));
    BB_CHECK(f.env.log.reward_component_nonfinite_samples > 0.0f);
}

BB_TEST(puffer_reward_component_ledger_resets_with_episode_return) {
    RewardFixture f;
    setup_env_buffers(&f);
    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_POSSESSION, 0.03f);
    bbe_record_reward_emission(&f.env);
    BB_CHECK(f.env.ep_reward_component[BB_HOME][BBE_REWARD_POSSESSION] !=
             0.0f);

    bbe_reset_match(&f.env);

    check_float(f.env.ep_return[BB_HOME], 0.0f);
    check_float(
        f.env.ep_reward_component[BB_HOME][BBE_REWARD_POSSESSION], 0.0f);
    check_float(f.env.step_reward_component[BB_HOME][BBE_REWARD_POSSESSION],
                0.0f);
    check_float(f.env.ep_reward_postclip_return[BB_HOME], 0.0f);
    check_float(f.env.ep_reward_component_residual[BB_HOME], 0.0f);
    BB_CHECK_EQ(f.env.ep_reward_component_mismatch_samples, 0);
    BB_CHECK_EQ(f.env.ep_reward_component_nonfinite_samples, 0);
}

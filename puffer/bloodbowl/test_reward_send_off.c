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
    f.env.ep_return[BB_HOME] = 0.4f;
    f.env.ep_return[BB_AWAY] = -0.4f;

    bbe_finish_episode(&f.env);

    check_float(reward_clip_frac(&f.env.log), 1.0f);
    check_float(f.env.log.reward_clip_episodes, 1.0f);
    check_float(f.env.log.reward_nonfinite_episodes, 0.0f);
    check_float(f.env.log.reward_clip_excess, 0.4f);
    check_float(f.env.log.reward_episode_abs_max_mean, 1.2f);
    check_float(reward_nonfinite_frac(&f.env.log), 0.0f);
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

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

enum {
    PASS_INTERCEPTOR_NEAR = 0,
    PASS_INTERCEPTOR_FAR = 1,
    PASS_THROWER = BB_TEAM_SLOTS,
    PASS_RECEIVER = BB_TEAM_SLOTS + 1,
};

static void build_pass_settlement_env_with_interceptors(
        RewardFixture* f, const uint8_t* dice, int n_dice,
        bool add_interceptors) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    bb_match* m = &env->match;
    env->reward_ball_gain = 0.05f;
    env->reward_ball_loss = -0.06f;
    fx_match_midturn(m, BB_AWAY, 0);
    BB_CHECK_EQ(fx_lineman(m, BB_AWAY, 0, 10, 7), PASS_THROWER);
    BB_CHECK_EQ(fx_lineman(m, BB_AWAY, 1, 16, 7), PASS_RECEIVER);
    if (add_interceptors) {
        // Slot 0 is encountered first along the thrower-to-target ruler.
        BB_CHECK_EQ(fx_lineman(m, BB_HOME, 0, 12, 7),
                    PASS_INTERCEPTOR_NEAR);
        BB_CHECK_EQ(fx_lineman(m, BB_HOME, 1, 13, 7),
                    PASS_INTERCEPTOR_FAR);
    }
    fx_ball_held(m, PASS_THROWER);

    bb_rng_script(&env->rng, dice, n_dice);
    BB_CHECK_EQ(bb_advance(m, &env->rng), BB_STATUS_DECISION);
    bbe_refresh_legal(env);
    env->prev_active_team = m->active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = m->score[0];
    env->score_prev[1] = env->score_start[1] = m->score[1];
    bbe_start_ball_possession(env, BB_AWAY, 10, 7);
    bbe_emit_all(env);
}

static void build_pass_settlement_env(RewardFixture* f,
                                      const uint8_t* dice, int n_dice) {
    build_pass_settlement_env_with_interceptors(f, dice, n_dice, true);
}

static void drive_pass_to_interception_choice(RewardFixture* f) {
    step_action(f, (bb_action){BB_A_ACTIVATE, PASS_THROWER, 0, 0});
    step_action(f, (bb_action){BB_A_DECLARE, BB_ACT_PASS, 0, 0});
    step_action(f, (bb_action){BB_A_PASS_TARGET, 0, 16, 7});
}

static void check_no_ball_transfer_components(const RewardFixture* f) {
    for (int team = 0; team < BBE_AGENTS; team++) {
        check_float(
            f->env.step_reward_component[team][BBE_REWARD_BALL_GAIN], 0.0f);
        check_float(
            f->env.step_reward_component[team][BBE_REWARD_BALL_LOSS], 0.0f);
    }
}

BB_TEST(puffer_pass_completed_same_team_is_one_continuous_possession) {
    RewardFixture f;
    static const uint8_t dice[] = {6, 3}; // accurate pass; receiver catches
    build_pass_settlement_env(&f, dice, 2);

    drive_pass_to_interception_choice(&f);
    BB_CHECK_EQ(f.env.match.decision_team, BB_HOME);
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.match.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(f.env.match.ball.x, 10); // release square until choice settles
    BB_CHECK_EQ(f.env.match.ball.y, 7);
    BB_CHECK_EQ(f.env.match.players[PASS_THROWER].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(f.env.match.players[PASS_RECEIVER].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 0.0f);
    BB_CHECK_EQ(f.env.poss_last_x, 10);
    BB_CHECK_EQ(f.env.poss_last_y, 7);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(bbe_dist_fetch(&f.env.match, BB_HOME), -1);
    BB_CHECK_EQ(bbe_dist_fetch(&f.env.match, BB_AWAY), -1);

    // Both egocentric observations expose the same semantic state. The ball
    // position mirrors, while the pending target remains separately encoded.
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF], BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF + 1], 11);
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF + 2], 8);
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF + 9], 17);
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF + 12], 8);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF], BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF + 1], 16);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF + 2], 8);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF + 9], 10);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF + 12], 8);

    step_action(&f, (bb_action){BB_A_CHOOSE_OPTION, 0xFE, 0, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, PASS_RECEIVER);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 6.0f);
    BB_CHECK_EQ(f.env.poss_last_x, 16);
    BB_CHECK_EQ(f.env.poss_last_y, 7);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 2);
}

BB_TEST(puffer_pass_no_interceptor_catch_retry_stays_one_possession) {
    RewardFixture f;
    static const uint8_t dice[] = {
        6, // accurate pass
        1, // receiver Catch fails and opens the skill re-roll window
        3, // Catch skill re-roll succeeds
    };
    build_pass_settlement_env_with_interceptors(&f, dice, 3, false);
    fx_give_skill(&f.env.match, PASS_RECEIVER, BB_SK_CATCH);
    bbe_emit_all(&f.env);

    drive_pass_to_interception_choice(&f);
    BB_CHECK_EQ(f.env.match.status, BB_STATUS_DECISION);
    BB_CHECK_EQ(f.env.match.decision_team, BB_AWAY);
    BB_CHECK(fx_find(
        &f.env.match,
        (bb_action){BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0}) >= 0);
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.match.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(f.env.match.ball.x, 16);
    BB_CHECK_EQ(f.env.match.ball.y, 7);
    BB_CHECK_EQ(f.env.match.players[PASS_THROWER].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(f.env.match.players[PASS_RECEIVER].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 6.0f);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(bbe_dist_fetch(&f.env.match, BB_HOME), -1);
    BB_CHECK_EQ(bbe_dist_fetch(&f.env.match, BB_AWAY), -1);
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF], BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF + 1], 17);
    BB_CHECK_EQ(f.env.obs_ptr[BB_HOME][BBE_CTX_OFF + 2], 8);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF], BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF + 1], 10);
    BB_CHECK_EQ(f.env.obs_ptr[BB_AWAY][BBE_CTX_OFF + 2], 8);

    step_action(&f, (bb_action){
        BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, PASS_RECEIVER);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 6.0f);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 3);

    // An unrelated legal step must not replay the catch as a second transfer.
    BB_CHECK(fx_find(
        &f.env.match, (bb_action){BB_A_END_TURN, 0, 0, 0}) >= 0);
    step_action(&f, (bb_action){BB_A_END_TURN, 0, 0, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, PASS_RECEIVER);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 6.0f);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 3);
}

BB_TEST(puffer_pass_interception_rewards_only_when_possession_settles) {
    RewardFixture f;
    static const uint8_t dice[] = {6, 6}; // accurate; chosen interception succeeds
    build_pass_settlement_env(&f, dice, 2);

    drive_pass_to_interception_choice(&f);
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_float(f.env.poss_path, 0.0f);
    check_no_ball_transfer_components(&f);

    step_action(&f, (bb_action){BB_A_CHOOSE_OPTION, 0, 0, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, PASS_INTERCEPTOR_NEAR);
    BB_CHECK_EQ(f.env.possessor, BB_HOME);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_float(f.env.ep_ball_path_sum, 2.0f);
    check_float(f.env.poss_path, 0.0f);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_BALL_LOSS], -0.06f);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_BALL_GAIN], 0.05f);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_BALL_LOSS], 0.0f);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_BALL_GAIN], 0.0f);
    check_float(f.rewards[BB_AWAY], -0.06f);
    check_float(f.rewards[BB_HOME], 0.05f);

    // A later unrelated policy step must not book the same transfer twice.
    step_action(&f,
                (bb_action){BB_A_ACTIVATE, PASS_INTERCEPTOR_NEAR, 0, 0});
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.rewards[BB_HOME], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 2);
}

BB_TEST(puffer_pass_loose_ball_rewards_one_loss_at_final_settlement) {
    RewardFixture f;
    static const uint8_t dice[] = {
        6, // accurate pass
        1, // receiver Catch fails
        5, // Bounce (+1,0) comes to rest at (17,7)
    };
    build_pass_settlement_env(&f, dice, 3);

    drive_pass_to_interception_choice(&f);
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_IN_AIR);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);

    step_action(&f, (bb_action){BB_A_CHOOSE_OPTION, 0xFE, 0, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(f.env.match.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(f.env.match.ball.x, 17);
    BB_CHECK_EQ(f.env.match.ball.y, 7);
    BB_CHECK_EQ(f.env.possessor, -1);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_float(f.env.ep_ball_path_sum, 7.0f);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_BALL_LOSS], -0.06f);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_BALL_GAIN], 0.0f);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_BALL_GAIN], 0.0f);
    check_float(f.rewards[BB_AWAY], -0.06f);
    check_float(f.rewards[BB_HOME], 0.0f);

    step_action(&f,
                (bb_action){BB_A_ACTIVATE, PASS_INTERCEPTOR_NEAR, 0, 0});
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.rewards[BB_HOME], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 3);
}

BB_TEST(puffer_pass_airborne_exact_pbrs_does_not_activate_fetch_regime) {
    RewardFixture f;
    static const uint8_t dice[] = {6, 3};
    build_pass_settlement_env(&f, dice, 2);
    Bloodbowl* env = &f.env;
    env->reward_dist_ball = 0.01f;
    env->reward_dist_endzone = 0.01f;
    env->reward_dist_pbrs_gamma = 0.99f;
    for (int team = 0; team < BBE_AGENTS; team++) {
        env->pot_fetch_prev[team] =
            bbe_potential(env->reward_dist_ball,
                          bbe_dist_fetch(&env->match, team));
        env->pot_carry_prev[team] =
            bbe_potential(env->reward_dist_endzone,
                          bbe_dist_carry(&env->match, team));
    }
    float carry_before = env->pot_carry_prev[BB_AWAY];

    drive_pass_to_interception_choice(&f);
    BB_CHECK_EQ(env->match.ball.state, BB_BALL_IN_AIR);
    BB_CHECK_EQ(bbe_dist_fetch(&env->match, BB_HOME), -1);
    BB_CHECK_EQ(bbe_dist_fetch(&env->match, BB_AWAY), -1);
    check_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL], 0.0f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_BALL], 0.0f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        -carry_before);
    check_no_ball_transfer_components(&f);

    step_action(&f, (bb_action){BB_A_CHOOSE_OPTION, 0xFE, 0, 0});
    float carry_after =
        bbe_potential(env->reward_dist_endzone,
                      bbe_dist_carry(&env->match, BB_AWAY));
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_BALL], 0.0f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        env->reward_dist_pbrs_gamma * carry_after);
    check_no_ball_transfer_components(&f);
}

enum {
    HANDOFF_HOME_REBOUND = 0,
    HANDOFF_CARRIER = BB_TEAM_SLOTS,
    HANDOFF_RECEIVER = BB_TEAM_SLOTS + 1,
    HANDOFF_AWAY_REBOUND = BB_TEAM_SLOTS + 2,
};

static void build_handoff_settlement_env(
        RewardFixture* f, const uint8_t* dice, int n_dice,
        int rebound_team) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    bb_match* m = &env->match;
    env->reward_ball_gain = 0.05f;
    env->reward_ball_loss = -0.06f;
    fx_match_midturn(m, BB_AWAY, 0);
    BB_CHECK_EQ(fx_lineman(m, BB_AWAY, 0, 10, 7), HANDOFF_CARRIER);
    BB_CHECK_EQ(fx_lineman(m, BB_AWAY, 1, 11, 7), HANDOFF_RECEIVER);
    fx_give_skill(m, HANDOFF_RECEIVER, BB_SK_CATCH);
    if (rebound_team == BB_AWAY) {
        BB_CHECK_EQ(
            fx_lineman(m, BB_AWAY, 2, 12, 7), HANDOFF_AWAY_REBOUND);
        fx_give_skill(m, HANDOFF_AWAY_REBOUND, BB_SK_CATCH);
        BB_CHECK_EQ(
            fx_lineman(m, BB_HOME, 0, 20, 2), HANDOFF_HOME_REBOUND);
    } else if (rebound_team == BB_HOME) {
        BB_CHECK_EQ(
            fx_player(m, BB_HOME, 0, 12, 7, 6, 3, 2, 3, 9),
            HANDOFF_HOME_REBOUND);
        fx_give_skill(m, HANDOFF_HOME_REBOUND, BB_SK_CATCH);
    } else {
        BB_CHECK_EQ(
            fx_lineman(m, BB_HOME, 0, 20, 2), HANDOFF_HOME_REBOUND);
    }
    fx_ball_held(m, HANDOFF_CARRIER);

    bb_rng_script(&env->rng, dice, n_dice);
    BB_CHECK_EQ(bb_advance(m, &env->rng), BB_STATUS_DECISION);
    bbe_refresh_legal(env);
    env->prev_active_team = m->active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = m->score[0];
    env->score_prev[1] = env->score_start[1] = m->score[1];
    bbe_start_ball_possession(env, BB_AWAY, 10, 7);
    bbe_emit_all(env);
}

static void drive_handoff_to_receiver_retry(RewardFixture* f) {
    step_action(f, (bb_action){BB_A_ACTIVATE, HANDOFF_CARRIER, 0, 0});
    step_action(f, (bb_action){BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0});
    step_action(f, (bb_action){BB_A_HANDOFF_TARGET, 0, 11, 7});
}

static int count_mask_bits(const unsigned char* mask, int n) {
    int count = 0;
    for (int i = 0; i < n; i++) count += mask[i] != 0;
    return count;
}

static void check_handoff_retry_observation(
        const RewardFixture* f, int tested_slot, int x, int y,
        int target, int decision_team) {
    const Bloodbowl* env = &f->env;
    const bb_match* m = &env->match;
    BB_CHECK_EQ(m->ball.state, BB_BALL_IN_AIR);
    BB_CHECK_EQ(m->ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(m->ball.x, x);
    BB_CHECK_EQ(m->ball.y, y);
    BB_CHECK_EQ(m->players[HANDOFF_CARRIER].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(m->players[HANDOFF_RECEIVER].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(m->players[tested_slot].flags & BB_PF_HAS_BALL, 0);
    BB_CHECK_EQ(m->active_team, BB_AWAY);
    BB_CHECK_EQ(m->decision_team, decision_team);
    BB_CHECK_EQ(m->turnover, 0);

    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        const unsigned char* obs = env->obs_ptr[agent];
        int ego_x = agent == BB_HOME ? x : BB_PITCH_LEN - 1 - x;
        BB_CHECK_EQ(obs[BBE_CTX_OFF], BB_BALL_IN_AIR);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 1], ego_x + 1);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 2], y + 1);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 3], 0);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 4], BB_PROC_TEST);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 5], 1);
        BB_CHECK_EQ(
            obs[BBE_CTX_OFF + 6], 1 + bbe_ego_slot(agent, tested_slot));
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 7], 0);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 8], target);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 10], decision_team == agent);
        BB_CHECK_EQ(obs[BBE_CTX_OFF + 11], BB_AWAY == agent);
        BB_CHECK_EQ(
            obs[BBE_SCALAR_OFF + BBE_S_ACT_KIND], BB_ACT_HANDOFF + 1);
        BB_CHECK_EQ(obs[BBE_SCALAR_OFF + 21], BB_TEST_CATCH + 1);
    }

    const unsigned char* decision_mask = env->action_mask_ptr[decision_team];
    BB_CHECK_EQ(
        count_mask_bits(decision_mask, BBE_HEAD_TYPE), 2);
    BB_CHECK(decision_mask[BB_A_USE_REROLL]);
    BB_CHECK(decision_mask[BB_A_DECLINE_REROLL]);
    BB_CHECK_EQ(
        count_mask_bits(decision_mask + BBE_HEAD_TYPE, BBE_HEAD_ARG), 2);
    BB_CHECK(decision_mask[BBE_HEAD_TYPE + BB_RR_SKILL]);
    BB_CHECK(decision_mask[BBE_HEAD_TYPE + 32]);
    BB_CHECK_EQ(
        count_mask_bits(
            decision_mask + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ),
        1);
    BB_CHECK(
        decision_mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390]);

    unsigned char effective[BBE_MASK_SIZE];
    bbe_fill_effective_action_mask(
        env, decision_team, BB_A_USE_REROLL, BB_RR_SKILL, effective);
    BB_CHECK_EQ(count_mask_bits(effective, BBE_HEAD_TYPE), 2);
    BB_CHECK(effective[BB_A_USE_REROLL]);
    BB_CHECK(effective[BB_A_DECLINE_REROLL]);
    BB_CHECK_EQ(
        count_mask_bits(effective + BBE_HEAD_TYPE, BBE_HEAD_ARG), 1);
    BB_CHECK(effective[BBE_HEAD_TYPE + BB_RR_SKILL]);
    BB_CHECK_EQ(
        count_mask_bits(
            effective + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ),
        1);
    BB_CHECK(effective[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390]);

    const unsigned char* waiting_mask =
        env->action_mask_ptr[1 - decision_team];
    BB_CHECK_EQ(count_mask_bits(waiting_mask, BBE_HEAD_TYPE), 1);
    BB_CHECK(waiting_mask[BB_A_NONE]);
    BB_CHECK_EQ(
        count_mask_bits(waiting_mask + BBE_HEAD_TYPE, BBE_HEAD_ARG), 1);
    BB_CHECK(waiting_mask[BBE_HEAD_TYPE + 32]);
    BB_CHECK_EQ(
        count_mask_bits(
            waiting_mask + BBE_HEAD_TYPE + BBE_HEAD_ARG, BBE_HEAD_SQ),
        1);
    BB_CHECK(waiting_mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390]);
}

static void enable_handoff_exact_pbrs(RewardFixture* f) {
    Bloodbowl* env = &f->env;
    env->reward_dist_ball = 0.01f;
    env->reward_dist_endzone = 0.01f;
    env->reward_dist_pbrs_gamma = 0.99f;
    for (int team = 0; team < BBE_AGENTS; team++) {
        env->pot_fetch_prev[team] =
            bbe_potential(env->reward_dist_ball,
                          bbe_dist_fetch(&env->match, team));
        env->pot_carry_prev[team] =
            bbe_potential(env->reward_dist_endzone,
                          bbe_dist_carry(&env->match, team));
    }
}

BB_TEST(puffer_handoff_receiver_retry_is_one_continuous_possession) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 3};
    build_handoff_settlement_env(&f, dice, 2, -1);

    drive_handoff_to_receiver_retry(&f);
    check_handoff_retry_observation(
        &f, HANDOFF_RECEIVER, 11, 7, 3, BB_AWAY);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 1.0f);
    BB_CHECK_EQ(f.env.poss_last_x, 11);
    BB_CHECK_EQ(f.env.poss_last_y, 7);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(bbe_dist_fetch(&f.env.match, BB_HOME), -1);
    BB_CHECK_EQ(bbe_dist_fetch(&f.env.match, BB_AWAY), -1);

    step_action(
        &f,
        (bb_action){
            BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, HANDOFF_RECEIVER);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 1.0f);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);

    step_action(
        &f, (bb_action){BB_A_ACTIVATE, HANDOFF_RECEIVER, 0, 0});
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_float(f.env.poss_path, 1.0f);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 2);
}

BB_TEST(puffer_handoff_same_team_rebound_remains_continuous) {
    RewardFixture f;
    static const uint8_t dice[] = {
        2, // receiver Catch fails
        5, // Bounce (+1,0) onto the Away rebound player
        2, // bounced Catch fails (needs 4+)
        4, // Catch-skill retry succeeds
    };
    build_handoff_settlement_env(&f, dice, 4, BB_AWAY);

    drive_handoff_to_receiver_retry(&f);
    check_handoff_retry_observation(
        &f, HANDOFF_RECEIVER, 11, 7, 3, BB_AWAY);
    check_float(f.env.poss_path, 1.0f);

    step_action(&f, (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0});
    check_handoff_retry_observation(
        &f, HANDOFF_AWAY_REBOUND, 12, 7, 4, BB_AWAY);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 2.0f);
    BB_CHECK_EQ(f.env.poss_last_x, 12);
    BB_CHECK_EQ(f.env.poss_last_y, 7);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);

    step_action(
        &f,
        (bb_action){
            BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, HANDOFF_AWAY_REBOUND);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 2.0f);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    BB_CHECK_EQ(f.env.match.turnovers_completed[BB_AWAY], 0);
    BB_CHECK_EQ(f.env.rng.script_pos, 4);

    step_action(
        &f, (bb_action){BB_A_ACTIVATE, HANDOFF_AWAY_REBOUND, 0, 0});
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_float(f.env.poss_path, 2.0f);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 4);
}

BB_TEST(puffer_handoff_opponent_rebound_settles_one_transfer) {
    RewardFixture f;
    static const uint8_t dice[] = {
        2, // receiver Catch fails
        5, // Bounce (+1,0) onto the Home rebound player
        2, // bounced Catch fails
        4, // Home Catch-skill retry succeeds
    };
    build_handoff_settlement_env(&f, dice, 4, BB_HOME);

    drive_handoff_to_receiver_retry(&f);
    step_action(&f, (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0});
    check_handoff_retry_observation(
        &f, HANDOFF_HOME_REBOUND, 12, 7, 4, BB_HOME);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 2.0f);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);

    step_action(
        &f,
        (bb_action){
            BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, HANDOFF_HOME_REBOUND);
    BB_CHECK_EQ(f.env.possessor, BB_HOME);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_float(f.env.ep_ball_path_sum, 2.0f);
    check_float(f.env.poss_path, 0.0f);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_BALL_LOSS], -0.06f);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_BALL_GAIN], 0.05f);
    check_float(f.rewards[BB_AWAY], -0.06f);
    check_float(f.rewards[BB_HOME], 0.05f);
    BB_CHECK_EQ(f.env.match.turnovers_completed[BB_AWAY], 1);

    step_action(
        &f, (bb_action){BB_A_ACTIVATE, HANDOFF_HOME_REBOUND, 0, 0});
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.rewards[BB_HOME], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 4);
}

BB_TEST(puffer_handoff_loose_ball_settles_once_at_final_bounce) {
    RewardFixture f;
    static const uint8_t dice[] = {
        2, // receiver Catch fails
        5, // Bounce (+1,0) comes to rest at (12,7)
    };
    build_handoff_settlement_env(&f, dice, 2, -1);

    drive_handoff_to_receiver_retry(&f);
    check_handoff_retry_observation(
        &f, HANDOFF_RECEIVER, 11, 7, 3, BB_AWAY);
    step_action(&f, (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_ON_GROUND);
    BB_CHECK_EQ(f.env.match.ball.carrier, BB_NO_PLAYER);
    BB_CHECK_EQ(f.env.match.ball.x, 12);
    BB_CHECK_EQ(f.env.match.ball.y, 7);
    BB_CHECK_EQ(f.env.possessor, -1);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_float(f.env.ep_ball_path_sum, 2.0f);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_BALL_LOSS], -0.06f);
    check_float(
        f.env.step_reward_component[BB_HOME][BBE_REWARD_BALL_GAIN], 0.0f);
    check_float(
        f.env.step_reward_component[BB_AWAY][BBE_REWARD_BALL_GAIN], 0.0f);
    check_float(f.rewards[BB_AWAY], -0.06f);
    check_float(f.rewards[BB_HOME], 0.0f);
    BB_CHECK_EQ(f.env.match.turnovers_completed[BB_AWAY], 1);

    step_action(
        &f, (bb_action){BB_A_ACTIVATE, HANDOFF_HOME_REBOUND, 0, 0});
    BB_CHECK_EQ(f.env.ep_ball_possessions, 1);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    check_float(f.rewards[BB_HOME], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 2);
}

BB_TEST(puffer_handoff_atomic_success_is_a_continuous_negative_control) {
    RewardFixture f;
    static const uint8_t dice[] = {3};
    build_handoff_settlement_env(&f, dice, 1, -1);
    f.env.match.players[HANDOFF_RECEIVER].skills = (bb_skillset){0};
    bbe_emit_all(&f.env); // keep the cached observation skill row coherent

    step_action(
        &f, (bb_action){BB_A_ACTIVATE, HANDOFF_CARRIER, 0, 0});
    step_action(
        &f, (bb_action){BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0});
    step_action(
        &f, (bb_action){BB_A_HANDOFF_TARGET, 0, 11, 7});
    BB_CHECK(!bb_rng_error(&f.env.rng));
    BB_CHECK_EQ(f.env.match.ball.state, BB_BALL_HELD);
    BB_CHECK_EQ(f.env.match.ball.carrier, HANDOFF_RECEIVER);
    BB_CHECK_EQ(f.env.possessor, BB_AWAY);
    check_float(f.env.poss_path, 1.0f);
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 1);

    step_action(
        &f, (bb_action){BB_A_ACTIVATE, HANDOFF_RECEIVER, 0, 0});
    BB_CHECK_EQ(f.env.ep_ball_possessions, 0);
    check_float(f.env.poss_path, 1.0f);
    check_no_ball_transfer_components(&f);
    check_float(f.rewards[BB_HOME], 0.0f);
    check_float(f.rewards[BB_AWAY], 0.0f);
    BB_CHECK_EQ(f.env.rng.script_pos, 1);
}

BB_TEST(puffer_handoff_same_team_rebound_exact_pbrs_uses_actual_catcher) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 5, 2, 4};
    build_handoff_settlement_env(&f, dice, 4, BB_AWAY);
    enable_handoff_exact_pbrs(&f);
    Bloodbowl* env = &f.env;
    float carry_before = env->pot_carry_prev[BB_AWAY];
    check_float(carry_before, 0.15f);

    drive_handoff_to_receiver_retry(&f);
    check_handoff_retry_observation(
        &f, HANDOFF_RECEIVER, 11, 7, 3, BB_AWAY);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        -0.15f);
    check_float(env->pot_fetch_prev[BB_HOME], 0.0f);
    check_float(env->pot_fetch_prev[BB_AWAY], 0.0f);
    check_float(env->pot_carry_prev[BB_HOME], 0.0f);
    check_float(env->pot_carry_prev[BB_AWAY], 0.0f);
    check_no_ball_transfer_components(&f);

    step_action(&f, (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0});
    check_handoff_retry_observation(
        &f, HANDOFF_AWAY_REBOUND, 12, 7, 4, BB_AWAY);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        0.0f);
    check_float(env->pot_fetch_prev[BB_HOME], 0.0f);
    check_float(env->pot_fetch_prev[BB_AWAY], 0.0f);
    check_float(env->pot_carry_prev[BB_HOME], 0.0f);
    check_float(env->pot_carry_prev[BB_AWAY], 0.0f);
    check_no_ball_transfer_components(&f);

    step_action(
        &f,
        (bb_action){
            BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0});
    float carry_after =
        bbe_potential(
            env->reward_dist_endzone,
            bbe_dist_carry(&env->match, BB_AWAY));
    check_float(carry_after, 0.13f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        0.1287f);
    check_float(env->pot_carry_prev[BB_AWAY], carry_after);
    check_float(env->pot_fetch_prev[BB_HOME], 0.0f);
    check_float(env->pot_fetch_prev[BB_AWAY], 0.0f);
    check_no_ball_transfer_components(&f);
}

BB_TEST(puffer_handoff_final_ground_exact_pbrs_activates_fetch_at_settlement) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 5};
    build_handoff_settlement_env(&f, dice, 2, -1);
    enable_handoff_exact_pbrs(&f);
    Bloodbowl* env = &f.env;
    float carry_before = env->pot_carry_prev[BB_AWAY];

    drive_handoff_to_receiver_retry(&f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        -carry_before);
    check_float(env->pot_fetch_prev[BB_HOME], 0.0f);
    check_float(env->pot_fetch_prev[BB_AWAY], 0.0f);

    step_action(&f, (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0});
    float home_fetch =
        bbe_potential(
            env->reward_dist_ball,
            bbe_dist_fetch(&env->match, BB_HOME));
    float away_fetch =
        bbe_potential(
            env->reward_dist_ball,
            bbe_dist_fetch(&env->match, BB_AWAY));
    check_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_BALL],
        env->reward_dist_pbrs_gamma * home_fetch);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_BALL],
        env->reward_dist_pbrs_gamma * away_fetch);
    check_float(env->pot_fetch_prev[BB_HOME], home_fetch);
    check_float(env->pot_fetch_prev[BB_AWAY], away_fetch);
    check_float(env->pot_carry_prev[BB_HOME], 0.0f);
    check_float(env->pot_carry_prev[BB_AWAY], 0.0f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_BALL_LOSS], -0.06f);
    check_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_BALL_GAIN], 0.0f);
}

BB_TEST(puffer_handoff_opponent_rebound_exact_pbrs_settles_once) {
    RewardFixture f;
    static const uint8_t dice[] = {2, 5, 2, 4};
    build_handoff_settlement_env(&f, dice, 4, BB_HOME);
    enable_handoff_exact_pbrs(&f);
    Bloodbowl* env = &f.env;
    float carry_before = env->pot_carry_prev[BB_AWAY];

    drive_handoff_to_receiver_retry(&f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        -carry_before);
    step_action(&f, (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0});
    check_handoff_retry_observation(
        &f, HANDOFF_HOME_REBOUND, 12, 7, 4, BB_HOME);
    check_float(env->pot_fetch_prev[BB_HOME], 0.0f);
    check_float(env->pot_fetch_prev[BB_AWAY], 0.0f);
    check_float(env->pot_carry_prev[BB_HOME], 0.0f);
    check_float(env->pot_carry_prev[BB_AWAY], 0.0f);

    step_action(
        &f,
        (bb_action){
            BB_A_USE_REROLL, BB_RR_SKILL, BB_SK_CATCH, 0});
    float home_carry =
        bbe_potential(
            env->reward_dist_endzone,
            bbe_dist_carry(&env->match, BB_HOME));
    check_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_DISTANCE_ENDZONE],
        env->reward_dist_pbrs_gamma * home_carry);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_DISTANCE_ENDZONE],
        0.0f);
    check_float(env->pot_carry_prev[BB_HOME], home_carry);
    check_float(env->pot_carry_prev[BB_AWAY], 0.0f);
    check_float(
        env->step_reward_component[BB_AWAY][BBE_REWARD_BALL_LOSS], -0.06f);
    check_float(
        env->step_reward_component[BB_HOME][BBE_REWARD_BALL_GAIN], 0.05f);
    BB_CHECK_EQ(env->ep_ball_possessions, 1);
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

BB_TEST(puffer_reward_clip_threshold_derives_both_pbrs_forms) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_td = 0.4f;
    f.env.reward_win = 0.6f;

    // No distance channel: the objective stack alone.
    check_float(bbe_reward_clip_threshold(&f.env), 1.0f);

    // A larger draw penalty than win bonus still contributes only once --
    // bbe_finish_episode applies exactly one of the two.
    f.env.reward_draw = 0.5f;
    check_float(bbe_reward_clip_threshold(&f.env), 1.0f);
    f.env.reward_draw = 0.0f;

    // Legacy raw-delta form: a distance emission and the objective stack can
    // never co-fire (the legacy path skips its emission whenever a team
    // scored, and the terminal suppresses it), so the bound is their MAX.
    // 25 * 0.04 = 1.0 for the r0 family, which is why the historical
    // hardcoded 1.0 was correct for every legacy manifest.
    f.env.reward_dist_ball = 0.02f;
    f.env.reward_dist_endzone = 0.04f;
    check_float(bbe_reward_clip_threshold(&f.env), 1.0f);
    f.env.reward_dist_endzone = 0.06f;
    check_float(bbe_reward_clip_threshold(&f.env), 1.5f);
    f.env.reward_dist_endzone = 0.04f;

    // Exact PBRS: the payback ADDS to the terminal stack.
    f.env.reward_dist_pbrs_gamma = 0.995f;
    check_float(bbe_reward_clip_threshold(&f.env), 2.5f);

    // Every shipped manifest stays far inside the trainer's guard.
    BB_CHECK(bbe_reward_envelope_valid(&f.env));
    BB_CHECK(BBE_TRAINER_REWARD_CLAMP == 8.0f);
}

BB_TEST(puffer_reward_envelope_must_fit_inside_the_trainer_clamp) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_td = 1.0f;
    f.env.reward_win = 1.0f;
    f.env.reward_dist_pbrs_gamma = 0.995f;
    f.env.reward_dist_ball = 0.1f;
    f.env.reward_dist_endzone = 0.1f;
    // 1.0 + 1.0 + 25*(0.1 + 0.1) = 7.0
    check_float(bbe_reward_clip_threshold(&f.env), 7.0f);
    BB_CHECK(bbe_reward_envelope_valid(&f.env));

    // Each coefficient is individually legal under the per-channel [-1,1] rule,
    // yet the stack now exceeds the guard and the trainer would truncate a
    // legitimate emission.
    f.env.reward_dist_endzone = 0.2f;
    check_float(bbe_reward_clip_threshold(&f.env), 9.5f);
    BB_CHECK(bbe_reward_config_scalars_valid(&f.env, NULL));
    BB_CHECK(!bbe_reward_envelope_valid(&f.env));
}

BB_TEST(puffer_exact_pbrs_potential_coefficients_must_keep_phi_nonnegative) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_dist_ball = 0.02f;
    f.env.reward_dist_endzone = 0.04f;

    // Legacy form is Phi = -k*d, a different object: its historical validation
    // behaviour is preserved exactly, negative coefficients included.
    f.env.reward_dist_pbrs_gamma = 0.0f;
    f.env.reward_dist_ball = -0.02f;
    BB_CHECK(bbe_reward_potential_sign_valid(&f.env));

    // On the exact path a negative coefficient makes Phi <= 0, which inverts
    // the sign argument the whole channel rests on.
    f.env.reward_dist_pbrs_gamma = 0.995f;
    BB_CHECK(!bbe_reward_potential_sign_valid(&f.env));
    f.env.reward_dist_ball = 0.02f;
    BB_CHECK(bbe_reward_potential_sign_valid(&f.env));
    f.env.reward_dist_endzone = -0.04f;
    BB_CHECK(!bbe_reward_potential_sign_valid(&f.env));
    f.env.reward_dist_endzone = 0.04f;
    BB_CHECK(bbe_reward_potential_sign_valid(&f.env));

    // And the invariant itself holds across the whole legal distance range,
    // inactive regimes included.
    BB_CHECK(bbe_potential(0.04f, -1) == 0.0f);
    for (int d = 0; d <= BB_PITCH_LEN - 1; d++) {
        BB_CHECK(bbe_potential(0.02f, d) >= 0.0f);
        BB_CHECK(bbe_potential(0.04f, d) >= 0.0f);
    }
    check_float(bbe_potential(0.02f, 0), 0.5f);
    check_float(bbe_potential(0.02f, BB_PITCH_LEN - 1), 0.0f);
}

BB_TEST(puffer_reward_clip_telemetry_sees_terminal_stack) {
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    // Declared envelope is 0.2 + 0.8 = 1.0 (D234: derived from the scalars,
    // not a literal). The injected objective is twice reward_td -- the shape a
    // double-score accounting bug would take -- so the terminal emission
    // breaches the design envelope by 0.2 per agent and must be flagged.
    f.env.reward_td = 0.2f;
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

BB_TEST(puffer_reward_clip_threshold_is_strictly_above_the_derived_envelope) {
    // The boundary is the DERIVED envelope, not a literal 1.0 (D234). These
    // scalars derive exactly 1.0 -- reward_td 1.0, drawn game so the bonus is
    // reward_draw 0.0 -- which keeps the historical nextafterf boundary while
    // pinning it to the derivation instead of a constant.
    RewardFixture exact;
    setup_env_buffers(&exact);
    exact.env.reward_configured = 1;
    exact.env.reward_td = 1.0f;
    check_float(bbe_reward_clip_threshold(&exact.env), 1.0f);
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
    over.env.reward_td = 1.0f;
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

// D234 regression for the breach the live screen actually produced.
//
// Stage the terminal state of a step in which the OPPONENT scored while the
// ball was ON_GROUND beforehand, so the exact-PBRS fetch channel is live. The
// conceding agent's terminal stack is -reward_td - reward_win = -1.0 exactly,
// and the mandatory payback -Phi_fetch(s_T-1) lands on that same emission.
// With reward_dist_ball 0.02 and a nearest standing teammate at Chebyshev
// distance `fetch_dist`, the payback is -0.02*(25 - fetch_dist): exactly the
// observed 0.02*{1,2,3,4} excess quantization, and |raw| = 1.08 at dist 21.
//
// Slot 0 (HOME) is the loser on purpose: reward_postclip_return and
// reward_clip_signed_delta are logged from slot 0 only, so putting the breach
// there makes every clip counter discriminating.
static void build_conceded_score_with_live_fetch(RewardFixture* f,
                                                 int fetch_dist) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    env->reward_configured = 1;
    env->reward_td = 0.4f;
    env->reward_win = 0.6f;
    env->reward_draw = 0.0f;
    env->reward_dist_ball = 0.02f;
    env->reward_dist_endzone = 0.04f;
    env->reward_dist_pbrs_gamma = 0.995f;
    env->match.score[BB_HOME] = 0;
    env->match.score[BB_AWAY] = 1;

    // The scoring step as c_step leaves it. Scoring sends the ball OFF_PITCH,
    // so Phi(s_T) is 0 on both channels: the step emission is gamma*0 - Phi,
    // and pot_*_prev has already been advanced to Phi(s_T) = 0. Terminal
    // rebuild then computes kept = step_emission - gamma*pot_prev = -Phi.
    float phi_fetch = bbe_potential(env->reward_dist_ball, fetch_dist);
    for (int a = 0; a < BBE_AGENTS; a++) {
        float td = a == BB_AWAY ? 0.4f : -0.4f;
        env->step_objective_reward[a] = td;
        env->step_reward_component[a][BBE_REWARD_TOUCHDOWN] = td;
        env->step_reward_component[a][BBE_REWARD_DISTANCE_BALL] = -phi_fetch;
        env->pot_fetch_prev[a] = 0.0f;
        env->pot_carry_prev[a] = 0.0f;
        env->ep_return[a] = td - phi_fetch;
        f->rewards[a] = td - phi_fetch;
    }
}

BB_TEST(puffer_terminal_pbrs_payback_on_a_conceded_score_is_not_a_clip) {
    RewardFixture f;
    build_conceded_score_with_live_fetch(&f, 21);

    bbe_finish_episode(&f.env);

    // The payback survives into the emission on both sides, and the leak is
    // ONE-SIDED: the winner banks 0.92 and stays inside 1.0, only the loser
    // crosses it.
    check_float(f.rewards[BB_HOME], -1.08f);
    check_float(f.rewards[BB_AWAY], 0.92f);
    check_float(f.env.log.reward_episode_abs_max_mean, 1.08f);

    // A legitimate emission under this manifest: the derived envelope is
    // 0.4 + 0.6 + 25*(0.02 + 0.04) = 2.5, so nothing is flagged.
    check_float(bbe_reward_clip_threshold(&f.env), 2.5f);
    check_float(f.env.log.reward_clipped_samples, 0.0f);
    check_float(f.env.log.reward_clip_excess, 0.0f);
    check_float(f.env.log.reward_clip_episodes, 0.0f);
    check_float(f.env.log.reward_clip_terminal_samples, 0.0f);
    check_float(reward_clip_frac(&f.env.log), 0.0f);
    // The D190 identity: nothing was destroyed, so postclip == raw.
    check_float(f.env.log.reward_clip_signed_delta, 0.0f);
    check_float(f.env.log.reward_postclip_return, -1.08f);
    check_float(f.env.log.episode_return, -1.08f);
}

BB_TEST(puffer_terminal_pbrs_payback_quantization_never_registers_excess) {
    // The live artifact's per-event excess was 0.02*{1,2,3,4}; each of those
    // four distances must be clean, not merely the largest one.
    for (int n = 1; n <= 4; n++) {
        RewardFixture f;
        build_conceded_score_with_live_fetch(&f, 25 - n);

        bbe_finish_episode(&f.env);

        check_float(f.rewards[BB_HOME], -1.0f - 0.02f * (float)n);
        check_float(f.env.log.reward_clipped_samples, 0.0f);
        check_float(f.env.log.reward_clip_excess, 0.0f);
        check_float(f.env.log.reward_clip_signed_delta, 0.0f);
    }
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
    // Declare the channel this fixture emits from, so the derived clip
    // envelope (D234) covers it: legacy raw-delta form, 25 * 0.02 = 0.5.
    f.env.reward_dist_ball = 0.02f;

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
    // Declared envelope 0.40 + 0.60 = 1.0 (D234), which is exactly the
    // terminal stack this fixture composes: nothing here is a breach.
    f.env.reward_td = 0.40f;
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
    // Declared envelope 0.20 + 0.80 = 1.0 (D234). The injected objective is
    // twice reward_td, so the terminal stack breaches by 0.20 and the signed
    // ledger identity has something real to reconcile.
    f.env.reward_td = 0.20f;
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

// ---------------------------------------------------------------------------
// Exact-PBRS distance shaping (reward_dist_pbrs_gamma > 0).
//
// The legacy form set each potential to NaN whenever its regime went inactive
// and overwrote prev with NaN, so the baseline re-anchored on every possession
// gap: advances were paid and drops across a gap were never charged. These two
// tests pin the property that fixes it.
// ---------------------------------------------------------------------------

BB_TEST(distance_potential_is_total_and_nonnegative) {
    // Inactive regimes must have a VALUE, not NaN. That is what lets a regime
    // exit be charged instead of silently re-anchoring the baseline.
    check_float(bbe_potential(0.04f, -1), 0.0f);
    // A zero coefficient contributes nothing even when the regime is active.
    check_float(bbe_potential(0.0f, 7), 0.0f);
    // Phi rises toward the goal and is non-negative across the whole pitch,
    // which is what makes the closed-cycle bound below hold.
    check_float(bbe_potential(0.04f, BB_PITCH_LEN - 1), 0.0f);
    check_float(bbe_potential(0.04f, 0), 0.04f * (float)(BB_PITCH_LEN - 1));
    BB_CHECK(bbe_potential(0.04f, 5) > bbe_potential(0.04f, 6));
    for (int d = 0; d < BB_PITCH_LEN; d++) {
        BB_CHECK(bbe_potential(0.04f, d) >= 0.0f);
    }
}

BB_TEST(distance_pbrs_closed_cycle_cannot_pay_while_legacy_does) {
    // The farm cycle the legacy form rewards: gain the ball 10 squares out,
    // advance 5, lose it, regain it at the SAME place, advance 5 again. The
    // state returns to where it started, so an honest potential must not pay.
    const float k = 0.04f;
    const int cycle[] = {-1, 10, 9, 8, 7, 6, 5, -1, 10, 9, 8, 7, 6, 5, -1};
    const int n = (int)(sizeof(cycle) / sizeof(cycle[0]));

    // Legacy: emission skipped whenever either side is NaN, prev overwritten
    // with NaN, so both advances are paid in full and neither drop is charged.
    float legacy_total = 0.0f;
    float prev = NAN;
    for (int i = 0; i < n; i++) {
        float cur = cycle[i] < 0 ? NAN : -k * (float)cycle[i];
        if (!isnan(cur) && !isnan(prev)) legacy_total += cur - prev;
        prev = cur;
    }
    BB_CHECK(legacy_total > 0.35f);   // 2 x 5 squares x 0.04 = 0.40

    // Exact PBRS at gamma=1: a closed cycle telescopes to exactly zero.
    float pbrs_total = 0.0f;
    float phi_prev = bbe_potential(k, cycle[0]);
    for (int i = 1; i < n; i++) {
        float phi = bbe_potential(k, cycle[i]);
        pbrs_total += 1.0f * phi - phi_prev;
        phi_prev = phi;
    }
    BB_CHECK(fabsf(pbrs_total) < 1e-6f);

    // And at the real gamma < 1 it is NON-POSITIVE for any closed cycle, since
    // sum(gamma*Phi' - Phi) = (gamma-1) * sum(Phi) <= 0 when Phi >= 0. So the
    // cycle can never be farmed at any length, not merely at this one.
    for (int gi = 0; gi < 3; gi++) {
        const float gam = (float)(0.9 + 0.045 * gi);   // 0.900, 0.945, 0.990
        float total = 0.0f;
        float pp = bbe_potential(k, cycle[0]);
        for (int i = 1; i < n; i++) {
            float phi = bbe_potential(k, cycle[i]);
            total += gam * phi - pp;
            pp = phi;
        }
        BB_CHECK(total <= 0.0f);
    }
}

BB_TEST(distance_pbrs_charges_the_drop_that_legacy_ignored) {
    // A possession loss at distance d must cost the progress it gave up. Under
    // the legacy form this transition emitted nothing at all.
    const float k = 0.04f;
    const int d = 6;
    const float gam = 0.995f;

    float phi_held = bbe_potential(k, d);
    float phi_lost = bbe_potential(k, -1);
    BB_CHECK(phi_held > 0.0f);
    check_float(phi_lost, 0.0f);

    float drop = gam * phi_lost - phi_held;
    BB_CHECK(drop < 0.0f);                       // charged, not free
    check_float(drop, -phi_held);

    // In-air limbo is the same kind of gap, so a completed pass is charged the
    // same way rather than earning nothing and silently re-anchoring.
    float regain = gam * bbe_potential(k, d) - phi_lost;
    BB_CHECK(regain > 0.0f);
    BB_CHECK(fabsf(drop + regain) < k);          // gap round-trip is ~neutral
}

BB_TEST(distance_pbrs_terminal_payback_survives_terminal_suppression) {
    // The terminal emission of a potential channel is gamma*0 - Phi(s): the
    // mandatory payback of shaping already granted on the way to the goal.
    // Terminal composition otherwise discards every incidental component on the
    // final action, which would keep all the positives and drop only the
    // repayment. Measured at -0.292757 per episode on a 2M probe before this
    // exemption existed, against a 0.6 win bonus, so it is not a rounding issue.
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_win = 0.60f;
    f.env.reward_dist_pbrs_gamma = 0.995f;
    f.env.match.score[BB_HOME] = 1;
    f.env.match.score[BB_AWAY] = 0;

    const float payback = -0.25f;
    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_TOUCHDOWN, 0.40f);
    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_DISTANCE_ENDZONE, payback);
    // A genuinely incidental term on the same step must still be suppressed.
    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_BALL_GAIN, 0.05f);
    f.env.step_objective_reward[BB_HOME] = 0.40f;
    f.env.step_objective_reward[BB_AWAY] = 0.0f;
    bbe_finish_episode(&f.env);

    // Payback kept, in the ledger and in the effective return.
    check_float(f.env.log.reward_component[BBE_REWARD_DISTANCE_ENDZONE],
                payback);
    // Incidental ball-gain on the terminal action still dropped.
    check_float(f.env.log.reward_component[BBE_REWARD_BALL_GAIN], 0.0f);
    // Suppression telemetry must exclude the payback, or it would double-count
    // as both "kept" and "suppressed".
    check_float(f.env.log.reward_terminal_suppressed_signed, 0.05f);
}

BB_TEST(distance_legacy_terminal_composition_is_unchanged) {
    // With the knob off, terminal composition must behave exactly as it always
    // did: a distance component landing on the terminal action is incidental and
    // is suppressed like everything else.
    RewardFixture f;
    setup_env_buffers(&f);
    f.env.reward_configured = 1;
    f.env.reward_win = 0.60f;
    f.env.reward_dist_pbrs_gamma = 0.0f;
    f.env.match.score[BB_HOME] = 1;
    f.env.match.score[BB_AWAY] = 0;

    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_TOUCHDOWN, 0.40f);
    bbe_reward_add(&f.env, BB_HOME, BBE_REWARD_DISTANCE_ENDZONE, -0.25f);
    f.env.step_objective_reward[BB_HOME] = 0.40f;
    f.env.step_objective_reward[BB_AWAY] = 0.0f;
    bbe_finish_episode(&f.env);

    check_float(f.env.log.reward_component[BBE_REWARD_DISTANCE_ENDZONE], 0.0f);
    check_float(f.env.log.reward_terminal_suppressed_signed, -0.25f);
}

// --- BB2025 Stalling telemetry (bb_stall.h) ---------------------------------
// The engine records stalls through a thread-local sink that c_step points at
// the env being stepped; these tests prove the env half of that wiring — the
// sink is attached during a real step, the counts land in the env's tally, and
// bbe_finish_episode publishes them (and the T1-T6 rate) into the Log.

// An eligible HOME carrier one dice-free square from the end zone on team turn
// `turn`, with a spare team-mate so the turn stays open.
static int build_stall_env(RewardFixture* f, int turn, const uint8_t* dice,
                           int n_dice) {
    setup_env_buffers(f);
    Bloodbowl* env = &f->env;
    bb_match* m = &env->match;
    fx_match_midturn(m, BB_HOME, 0);
    m->turn[BB_HOME] = (uint8_t)(turn - 1); // turn_start advances to `turn`
    int carrier = fx_lineman(m, BB_HOME, 0, 24, 7);
    fx_lineman(m, BB_HOME, 1, 3, 3);
    fx_lineman(m, BB_AWAY, 0, 17, 9);
    fx_ball_held(m, carrier);

    bb_rng_script(&env->rng, dice, n_dice);
    bb_advance(m, &env->rng);
    bbe_refresh_legal(env);
    env->prev_active_team = m->active_team;
    env->pending_pickup_slot = -1;
    env->pending_gfi_slot = -1;
    env->pending_dodge_slot = -1;
    env->possessor = BB_HOME;
    env->pot_fetch_prev[0] = env->pot_fetch_prev[1] = NAN;
    env->pot_carry_prev[0] = env->pot_carry_prev[1] = NAN;
    env->score_prev[0] = env->score_start[0] = m->score[0];
    env->score_prev[1] = env->score_start[1] = m->score[1];
    bb_stall_reset(&env->ep_stall);
    bb_stall_attach(0); // c_step must attach it itself
    bbe_emit_all(env);
    return carrier;
}

BB_TEST(puffer_stall_telemetry_reaches_the_log) {
    RewardFixture f;
    static const uint8_t dice[] = {1, 1, 1, 4}; // crowd acts, armour, bounce
    int carrier = build_stall_env(&f, 1, dice, 4);

    step_action(&f, (bb_action){BB_A_ACTIVATE, (uint8_t)carrier, 0, 0});
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0});
    step_action(&f, (bb_action){BB_A_END_ACTIVATION, 0, 0, 0});

    // The rule fired...
    BB_CHECK_EQ(f.env.match.players[carrier].stance, BB_STANCE_PRONE);
    // ...and c_step's attach put the counts in THIS env.
    BB_CHECK_EQ(f.env.ep_stall.rolls[BB_HOME][0], 1);
    BB_CHECK_EQ(f.env.ep_stall.acted[BB_HOME][0], 1);
    BB_CHECK_EQ(f.env.ep_stall.turnovers[BB_HOME][0], 1);
    BB_CHECK_EQ(f.env.ep_stall.turn_ends[BB_HOME][0], 1);
    BB_CHECK_EQ(bb_stall_sum(&f.env.ep_stall, BB_STALL_ROLLS, BB_AWAY, 1,
                             BB_STALL_TURNS), 0);

    bbe_finish_episode(&f.env);

    check_float(f.env.log.stall_rolls, 1.0f);
    check_float(f.env.log.stall_rolls_t0, 1.0f);
    check_float(f.env.log.stall_rolls_t1, 0.0f);
    check_float(f.env.log.stall_crowd_acted, 1.0f);
    check_float(f.env.log.stall_turnovers, 1.0f);
    check_float(f.env.log.stall_turnovers_t0, 1.0f);
    check_float(f.env.log.stall_turnovers_t1, 0.0f);
    check_float(f.env.log.stall_rolls_turn1_6, 1.0f);
    check_float(f.env.log.stall_turnovers_turn1_6, 1.0f);
    check_float(f.env.log.stall_turns_turn1_6, 1.0f);
    check_float(f.env.log.stall_rate_turn1_6, 1.0f);   // 1 stall / 1 team turn
    check_float(f.env.log.stall_rate_turn1_6_t0, 1.0f);
    check_float(f.env.log.stall_rate_turn1_6_t1, 0.0f);
    check_float(f.env.log.stall_rolls_by_turn[0], 1.0f);
    for (int i = 1; i < BB_STALL_TURNS; i++) {
        check_float(f.env.log.stall_rolls_by_turn[i], 0.0f);
    }
    // The episode tally is cleared for the next episode (finish resets).
    BB_CHECK_EQ(bb_stall_sum(&f.env.ep_stall, BB_STALL_ROLLS, -1, 1,
                             BB_STALL_TURNS), 0);
}

// A turn-7 stall is counted (the die is consumed) but must stay OUT of the
// T1-T6 gate band and its rate.
BB_TEST(puffer_stall_telemetry_keeps_late_turns_out_of_the_gate_band) {
    RewardFixture f;
    static const uint8_t dice[] = {6}; // cannot reach turn 7
    int carrier = build_stall_env(&f, 7, dice, 1);
    BB_CHECK_EQ(f.env.match.turn[BB_HOME], 7);

    step_action(&f, (bb_action){BB_A_ACTIVATE, (uint8_t)carrier, 0, 0});
    step_action(&f, (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0});
    step_action(&f, (bb_action){BB_A_END_ACTIVATION, 0, 0, 0});

    BB_CHECK_EQ(f.env.match.players[carrier].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(f.env.ep_stall.rolls[BB_HOME][6], 1);
    BB_CHECK_EQ(f.env.ep_stall.acted[BB_HOME][6], 0);

    bbe_finish_episode(&f.env);

    check_float(f.env.log.stall_rolls, 1.0f);
    check_float(f.env.log.stall_crowd_acted, 0.0f);
    check_float(f.env.log.stall_turnovers, 0.0f);
    check_float(f.env.log.stall_rolls_turn1_6, 0.0f);
    check_float(f.env.log.stall_rate_turn1_6, 0.0f);
    check_float(f.env.log.stall_rolls_by_turn[6], 1.0f);
}

// ---------------------------------------------------------------------------
// Terminal payback on the TRUNCATION path, driven through the real c_step
// emission block rather than by hand-injecting a component.
//
// The exact invariant: with Phi >= 0, gamma <= 1 and Phi(terminal) = 0, an
// episode's total for each potential channel is
//     (gamma-1) * sum(Phi_intermediate) - Phi(s_0)  <=  0
// so a NON-POSITIVE episode total is necessary for the shaping to be a
// potential at all. The bug made it positive: `decisions >= max_decisions`
// truncates mid-drive with the ball still HELD, and the terminal step kept the
// ordinary gamma*Phi(s_T) - Phi(s_T-1) instead of the payback -Phi(s_T-1), so
// the accumulated potential was never repaid. Natural ends hid it because they
// set the ball OFF_PITCH first, making Phi(s_T) already 0.
// ---------------------------------------------------------------------------

BB_TEST(distance_pbrs_terminal_removes_the_gamma_phi_term) {
    // The step emission is gamma*Phi(s_T) - Phi(s_T-1). PBRS needs
    // Phi(terminal) = 0, so a terminal must emit -Phi(s_T-1); the composition
    // gets there by REMOVING gamma*Phi(s_T). This pins that arithmetic.
    //
    // Why it matters only on truncation: every natural end sets the ball
    // OFF_PITCH before this code runs, so Phi(s_T) is already 0 and the
    // subtraction is a no-op. The `decisions >= max_decisions` truncation ends
    // mid-drive with the ball typically HELD, so Phi(s_T) > 0 -- and terminal is
    // flagged 1.0, so PPO does not bootstrap the debt away either. Truncation
    // still pays the full result bonus, so forgiving the debt made "pad
    // decisions to the cap while parked deep with the ball" profitable.
    const float GAM = 0.995f;
    const float PHI_T = 0.40f;       // ball still held at the cut: Phi(s_T) > 0
    const float STEP_EMISSION = -0.05f;

    RewardFixture f;
    setup_env_buffers(&f);
    Bloodbowl* env = &f.env;
    env->reward_configured = 1;
    env->reward_dist_endzone = 0.04f;
    env->reward_dist_pbrs_gamma = GAM;
    env->reward_win = 0.60f;
    env->match.score[BB_HOME] = 1;
    env->match.score[BB_AWAY] = 0;

    // Phi(s_T) as the emission block left it, and this step's ordinary emission.
    env->pot_carry_prev[BB_HOME] = PHI_T;
    env->pot_fetch_prev[BB_HOME] = 0.0f;
    bbe_reward_add(env, BB_HOME, BBE_REWARD_DISTANCE_ENDZONE, STEP_EMISSION);
    bbe_reward_add(env, BB_HOME, BBE_REWARD_TOUCHDOWN, 0.40f);
    env->step_objective_reward[BB_HOME] = 0.40f;
    env->step_objective_reward[BB_AWAY] = 0.0f;
    bbe_finish_episode(env);

    // The kept channel must be the step emission MINUS gamma*Phi(s_T).
    check_float(env->log.reward_component[BBE_REWARD_DISTANCE_ENDZONE],
                STEP_EMISSION - GAM * PHI_T);
    // Which is strictly more negative than the unpaid version: a build that
    // forgets the subtraction keeps STEP_EMISSION and is in credit by gamma*Phi.
    BB_CHECK(env->log.reward_component[BBE_REWARD_DISTANCE_ENDZONE]
             < STEP_EMISSION - 0.5f * GAM * PHI_T);
}

BB_TEST(distance_pbrs_natural_end_zeroes_phi_before_the_payback) {
    // The reason the truncation bug was invisible: every natural end routes
    // through touchdown_advance / end_drive_advance, which set the ball
    // OFF_PITCH (engine/src/proc_match.c) BEFORE this reward code runs. So
    // Phi(s_T) is already 0 there and removing gamma*Phi(s_T) is a no-op.
    // Pin that, so a change to the engine's end-of-drive ball handling cannot
    // silently reintroduce a debt-forgiving terminal.
    RewardFixture f;
    setup_env_buffers(&f);
    Bloodbowl* env = &f.env;
    env->reward_configured = 1;
    env->reward_dist_endzone = 0.04f;
    env->reward_dist_pbrs_gamma = 0.995f;
    env->match.status = BB_STATUS_MATCH_OVER;
    env->match.ball.state = BB_BALL_OFF_PITCH;

    // Phi is zero for an off-pitch ball, so the potential channels contribute
    // nothing at a natural terminal however deep the carrier had been.
    check_float(bbe_potential(env->reward_dist_endzone, bbe_dist_carry(&env->match, BB_HOME)), 0.0f);
    BB_CHECK_EQ(bbe_dist_carry(&env->match, BB_HOME), -1);
}

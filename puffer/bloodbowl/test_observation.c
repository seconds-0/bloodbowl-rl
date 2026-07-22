#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"

typedef struct {
    Bloodbowl env;
    uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    float actions[BBE_AGENTS * 3];
    unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    float rewards[BBE_AGENTS];
    float terminals[BBE_AGENTS];
} ObservationFixture;

static void observation_fixture_init(ObservationFixture* f) {
    memset(f, 0, sizeof *f);
    f->env.num_agents = BBE_AGENTS;
    f->env.match.ball.carrier = BB_NO_PLAYER;
    f->env.match.decision_team = BB_HOME;
    f->env.match.active_team = BB_HOME;
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        f->env.obs_ptr[agent] = f->obs + agent * BBE_OBS_SIZE;
        f->env.action_ptr[agent] = f->actions + agent * 3;
        f->env.action_mask_ptr[agent] = f->masks + agent * BBE_MASK_SIZE;
        f->env.reward_ptr[agent] = f->rewards + agent;
        f->env.terminal_ptr[agent] = f->terminals + agent;
    }
}

static void encode_both(ObservationFixture* f) {
    bbe_compute_tz(&f->env);
    bbe_encode_obs(&f->env, BB_HOME);
    bbe_encode_obs(&f->env, BB_AWAY);
}

static uint16_t block_data(int face0, int face1, int face2, int ndice) {
    return (uint16_t)(face0 | (face1 << 3) | (face2 << 6) |
                      ((ndice - 1) << 9));
}

static int byte_diff_count(const uint8_t* a, const uint8_t* b, size_t n) {
    int diffs = 0;
    for (size_t i = 0; i < n; i++) diffs += a[i] != b[i];
    return diffs;
}

BB_TEST(observation_block_faces_are_public_at_reroll_and_choice_windows) {
    BB_CHECK_EQ(BBE_OBS_VERSION, 5);
    for (int phase = 1; phase <= 2; phase++) {
        ObservationFixture f;
        observation_fixture_init(&f);
        f.env.match.stack_top = 1;
        f.env.match.stack[0] = (bb_frame){
            BB_PROC_BLOCK, (uint8_t)phase, 0, 16, 0, 0,
            block_data(BB_BD_ATTACKER_DOWN, BB_BD_PUSH_1, BB_BD_POW, 3),
        };
        encode_both(&f);

        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            const uint8_t* ctx = f.env.obs_ptr[agent] + BBE_CTX_OFF;
            BB_CHECK_EQ(ctx[13], BB_BD_ATTACKER_DOWN);
            BB_CHECK_EQ(ctx[14], BB_BD_PUSH_1);
            BB_CHECK_EQ(ctx[15], BB_BD_POW);
        }
        BB_CHECK_EQ(memcmp(f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF + 13,
                           f.env.obs_ptr[BB_AWAY] + BBE_CTX_OFF + 13, 3),
                    0);

        uint8_t before[BBE_OBS_SIZE];
        memcpy(before, f.env.obs_ptr[BB_HOME], sizeof before);
        f.env.match.stack[0].data =
            block_data(BB_BD_BOTH_DOWN, BB_BD_STUMBLE, BB_BD_PUSH_2, 3);
        encode_both(&f);
        BB_CHECK_EQ(byte_diff_count(before, f.env.obs_ptr[BB_HOME],
                                    BBE_OBS_SIZE),
                    3);
        const uint8_t* ctx = f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
        BB_CHECK_EQ(ctx[13], BB_BD_BOTH_DOWN);
        BB_CHECK_EQ(ctx[14], BB_BD_STUMBLE);
        BB_CHECK_EQ(ctx[15], BB_BD_PUSH_1);
    }
}

BB_TEST(observation_block_face_slots_zero_after_dice_count) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 1;
    f.env.match.stack[0] = (bb_frame){
        BB_PROC_BLOCK, 2, 0, 16, 0, 0,
        block_data(BB_BD_POW, BB_BD_STUMBLE, BB_BD_BOTH_DOWN, 1),
    };
    encode_both(&f);
    const uint8_t* ctx = f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
    BB_CHECK_EQ(ctx[13], BB_BD_POW);
    BB_CHECK_EQ(ctx[14], 0);
    BB_CHECK_EQ(ctx[15], 0);

    f.env.match.stack[0].phase = 4;
    encode_both(&f);
    ctx = f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
    BB_CHECK_EQ(ctx[13], 0);
    BB_CHECK_EQ(ctx[14], 0);
    BB_CHECK_EQ(ctx[15], 0);
}

BB_TEST(observation_test_kind_and_active_movement_survive_nested_window) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.players[0].moved = 4;
    f.env.match.players[0].rushes = 1;
    f.env.match.stack_top = 2;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 0, BB_ACT_MOVE, 8, 6, 0};
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 1, 0, BB_TEST_DODGE, 3, 0, 0};

    for (int kind = 0; kind < BB_TEST_KIND_COUNT; kind++) {
        f.env.match.stack[1].b = (uint8_t)kind;
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            const uint8_t* scalar =
                f.env.obs_ptr[agent] + BBE_SCALAR_OFF;
            BB_CHECK_EQ(scalar[19], 5);
            BB_CHECK_EQ(scalar[20], 2);
            BB_CHECK_EQ(scalar[21], kind + 1);
        }
    }

    f.env.match.stack[1].b = BB_TEST_DODGE;
    encode_both(&f);
    const uint8_t* home = f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
    const uint8_t* away = f.env.obs_ptr[BB_AWAY] + BBE_CTX_OFF;
    const uint8_t* scalar;
    BB_CHECK_EQ(home[9], 9);
    BB_CHECK_EQ(home[12], 7);
    BB_CHECK_EQ(away[9], BB_PITCH_LEN - 8);
    BB_CHECK_EQ(away[12], 7);

    f.env.match.stack_top = 1;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 0, BB_ACT_MOVE, 8, 6, 0};
    encode_both(&f);
    scalar = f.env.obs_ptr[BB_HOME] + BBE_SCALAR_OFF;
    BB_CHECK_EQ(scalar[19], 5);
    BB_CHECK_EQ(scalar[20], 2);
    BB_CHECK_EQ(scalar[21], 0);

    f.env.match.stack_top = 1;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_TEST, 1, 0, BB_TEST_PICKUP, 3, 0, 0};
    encode_both(&f);
    scalar = f.env.obs_ptr[BB_HOME] + BBE_SCALAR_OFF;
    BB_CHECK_EQ(scalar[19], 0);
    BB_CHECK_EQ(scalar[20], 0);
    BB_CHECK_EQ(scalar[21], BB_TEST_PICKUP + 1);
}

BB_TEST(observation_ball_coordinates_require_an_on_pitch_square) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.ball.state = BB_BALL_ON_GROUND;
    f.env.match.ball.x = 4;
    f.env.match.ball.y = 7;
    encode_both(&f);
    const uint8_t* home = f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
    const uint8_t* away = f.env.obs_ptr[BB_AWAY] + BBE_CTX_OFF;
    BB_CHECK_EQ(home[1], 5);
    BB_CHECK_EQ(home[2], 8);
    BB_CHECK_EQ(away[1], BB_PITCH_LEN - 4);
    BB_CHECK_EQ(away[2], 8);

    static const uint8_t invalid_xy[][2] = {
        {BB_PITCH_LEN, 0}, {0, BB_PITCH_WID}, {0xFF, 0xFF},
    };
    for (size_t i = 0; i < sizeof invalid_xy / sizeof invalid_xy[0]; i++) {
        f.env.match.ball.x = invalid_xy[i][0];
        f.env.match.ball.y = invalid_xy[i][1];
        encode_both(&f);
        home = f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
        away = f.env.obs_ptr[BB_AWAY] + BBE_CTX_OFF;
        BB_CHECK_EQ(home[1], 0);
        BB_CHECK_EQ(home[2], 0);
        BB_CHECK_EQ(away[1], 0);
        BB_CHECK_EQ(away[2], 0);
    }

    f.env.match.ball.state = BB_BALL_OFF_PITCH;
    f.env.match.ball.x = 2;
    f.env.match.ball.y = 3;
    encode_both(&f);
    home = f.env.obs_ptr[BB_HOME] + BBE_CTX_OFF;
    away = f.env.obs_ptr[BB_AWAY] + BBE_CTX_OFF;
    BB_CHECK_EQ(home[1], 0);
    BB_CHECK_EQ(home[2], 0);
    BB_CHECK_EQ(away[1], 0);
    BB_CHECK_EQ(away[2], 0);
}

BB_TEST(touchback_fallback_squares_project_and_decode_uniquely) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.n_legal = 2;
    f.env.legal[0] = (bb_action){BB_A_TOUCHBACK, 0xFF, 2, 4};
    f.env.legal[1] = (bb_action){BB_A_TOUCHBACK, 0xFF, 9, 11};
    bbe_fill_mask(&f.env, BB_HOME);

    BB_CHECK_EQ(f.env.legal_arg[0], 32);
    BB_CHECK_EQ(f.env.legal_arg[1], 32);
    BB_CHECK_EQ(f.env.legal_sq[0], 4 * BB_PITCH_LEN + 2);
    BB_CHECK_EQ(f.env.legal_sq[1], 11 * BB_PITCH_LEN + 9);
    BB_CHECK(f.env.legal_sq[0] != f.env.legal_sq[1]);

    float heads[3] = {BB_A_TOUCHBACK, 32,
                      (float)(11 * BB_PITCH_LEN + 9)};
    bb_action picked = bbe_decode(&f.env, BB_HOME, heads);
    BB_CHECK(bb_action_eq(picked, f.env.legal[1]));
    BB_CHECK_EQ(f.env.illegal, 0);

    f.env.match.decision_team = BB_AWAY;
    bbe_fill_mask(&f.env, BB_AWAY);
    BB_CHECK_EQ(f.env.legal_sq[0],
                4 * BB_PITCH_LEN + (BB_PITCH_LEN - 1 - 2));
    BB_CHECK_EQ(f.env.legal_sq[1],
                11 * BB_PITCH_LEN + (BB_PITCH_LEN - 1 - 9));
}

BB_TEST(touchback_player_recipients_remain_exactly_addressable) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.n_legal = 2;
    f.env.legal[0] = (bb_action){BB_A_TOUCHBACK, 0, 0, 0};
    f.env.legal[1] = (bb_action){BB_A_TOUCHBACK, 1, 0, 0};
    bbe_fill_mask(&f.env, BB_HOME);

    BB_CHECK_EQ(f.env.legal_sq[0], 390);
    BB_CHECK_EQ(f.env.legal_sq[1], 390);
    float heads[3] = {BB_A_TOUCHBACK, 1, 390};
    bb_action picked = bbe_decode(&f.env, BB_HOME, heads);
    BB_CHECK(bb_action_eq(picked, f.env.legal[1]));
    BB_CHECK_EQ(f.env.illegal, 0);
}

BB_TEST(policy_decode_rejects_marginally_legal_jointly_invalid_tuple) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.n_legal = 2;
    f.env.legal[0] = (bb_action){BB_A_SPECIAL_TARGET, 0, 2, 4};
    f.env.legal[1] = (bb_action){BB_A_SPECIAL_TARGET, 1, 9, 11};
    bbe_fill_mask(&f.env, BB_HOME);

    // Every component is marginally enabled, but this cross-product tuple was
    // never offered by the engine. The policy path must not silently execute
    // either neighboring legal action.
    float heads[3] = {BB_A_SPECIAL_TARGET, 0,
                      (float)(11 * BB_PITCH_LEN + 9)};
    bb_action picked = bbe_decode(&f.env, BB_HOME, heads);
    BB_CHECK_EQ(picked.type, BB_A_NONE);
    BB_CHECK_EQ(f.env.illegal, 1);
}

BB_TEST(exact_support_conditions_each_head_and_canonicalizes_inactive_heads) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.n_legal = 4;
    f.env.legal[0] = (bb_action){BB_A_SPECIAL_TARGET, 0, 2, 4};
    f.env.legal[1] = (bb_action){BB_A_SPECIAL_TARGET, 1, 9, 11};
    f.env.legal[2] = (bb_action){BB_A_END_TURN, 0, 0, 0};
    f.env.legal[3] = (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0};
    bbe_fill_mask(&f.env, BB_HOME);

    unsigned char effective[BBE_MASK_SIZE];
    bbe_fill_effective_action_mask(&f.env, BB_HOME, BB_A_SPECIAL_TARGET, 0,
                                   effective);
    BB_CHECK(effective[BB_A_SPECIAL_TARGET]);
    BB_CHECK(effective[BB_A_END_TURN]);
    BB_CHECK(effective[BB_A_DECLINE_REROLL]);
    BB_CHECK(effective[BBE_HEAD_TYPE + 0]);
    BB_CHECK(effective[BBE_HEAD_TYPE + 1]);
    BB_CHECK(!effective[BBE_HEAD_TYPE + 32]);
    BB_CHECK(effective[BBE_HEAD_TYPE + BBE_HEAD_ARG +
                       4 * BB_PITCH_LEN + 2]);
    BB_CHECK(!effective[BBE_HEAD_TYPE + BBE_HEAD_ARG +
                        11 * BB_PITCH_LEN + 9]);

    bbe_fill_effective_action_mask(&f.env, BB_HOME, BB_A_END_TURN, 32,
                                   effective);
    int arg_bits = 0, square_bits = 0;
    for (int i = 0; i < BBE_HEAD_ARG; i++)
        arg_bits += effective[BBE_HEAD_TYPE + i] != 0;
    for (int i = 0; i < BBE_HEAD_SQ; i++)
        square_bits += effective[BBE_HEAD_TYPE + BBE_HEAD_ARG + i] != 0;
    BB_CHECK_EQ(arg_bits, 1);
    BB_CHECK(effective[BBE_HEAD_TYPE + 32]);
    BB_CHECK_EQ(square_bits, 1);
    BB_CHECK(effective[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390]);
}

BB_TEST(policy_decode_rejects_nonfinite_fractional_and_out_of_range_heads) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.n_legal = 1;
    f.env.legal[0] = (bb_action){BB_A_END_TURN, 0, 0, 0};
    bbe_fill_mask(&f.env, BB_HOME);

    float malformed[][3] = {
        {NAN, 32, 390},
        {INFINITY, 32, 390},
        {-INFINITY, 32, 390},
        {BB_A_END_TURN, NAN, 390},
        {BB_A_END_TURN, 32, NAN},
        {BB_A_END_TURN + 0.5f, 32, 390},
        {BB_A_END_TURN, 31.5f, 390},
        {BB_A_END_TURN, 32, 389.5f},
        {BB_A_END_TURN, 32, 391},
        {-1, 32, 390},
    };
    bb_match before = f.env.match;
    bb_action legal_before = f.env.legal[0];
    for (size_t i = 0; i < sizeof malformed / sizeof malformed[0]; i++) {
        bb_action picked = bbe_decode(&f.env, BB_HOME, malformed[i]);
        BB_CHECK_EQ(picked.type, BB_A_NONE);
        BB_CHECK_EQ(memcmp(&f.env.match, &before, sizeof before), 0);
        BB_CHECK(bb_action_eq(f.env.legal[0], legal_before));
    }
    BB_CHECK_EQ(f.env.illegal,
                (int)(sizeof malformed / sizeof malformed[0]));
}

BB_TEST(policy_decode_rejects_distinct_engine_actions_with_same_projection) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.n_legal = 2;
    f.env.legal[0] = (bb_action){BB_A_END_TURN, 0, 0, 0};
    f.env.legal[1] = (bb_action){BB_A_END_TURN, 1, 0, 0};
    bbe_fill_mask(&f.env, BB_HOME);

    float heads[3] = {BB_A_END_TURN, 32, 390};
    bb_action picked = bbe_decode(&f.env, BB_HOME, heads);
    BB_CHECK_EQ(picked.type, BB_A_NONE);
    BB_CHECK_EQ(f.env.illegal, 1);

    // Exact duplicate enumeration does not create semantic ambiguity.
    f.env.legal[1] = f.env.legal[0];
    bbe_fill_mask(&f.env, BB_HOME);
    picked = bbe_decode(&f.env, BB_HOME, heads);
    BB_CHECK(bb_action_eq(picked, f.env.legal[0]));
    BB_CHECK_EQ(f.env.illegal, 1);
}

BB_TEST(push_square_keeps_crowd_and_chain_variant_in_argument_head) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.n_legal = 2;
    // A boundary chain-push fixture can offer these at the same clipped
    // square. The raw arg changes engine behavior and must remain semantic.
    f.env.legal[0] = (bb_action){BB_A_PUSH_SQUARE, 1, 0, 4};
    f.env.legal[1] = (bb_action){BB_A_PUSH_SQUARE, 2, 0, 4};
    bbe_fill_mask(&f.env, BB_HOME);

    BB_CHECK_EQ(f.env.legal_arg[0], 1);
    BB_CHECK_EQ(f.env.legal_arg[1], 2);
    int square = 4 * BB_PITCH_LEN;
    float crowd[3] = {BB_A_PUSH_SQUARE, 1, (float)square};
    float chain[3] = {BB_A_PUSH_SQUARE, 2, (float)square};
    BB_CHECK(bb_action_eq(bbe_decode(&f.env, BB_HOME, crowd),
                          f.env.legal[0]));
    BB_CHECK(bb_action_eq(bbe_decode(&f.env, BB_HOME, chain),
                          f.env.legal[1]));
    BB_CHECK_EQ(f.env.illegal, 0);
}

BB_TEST(macro_step_requires_canonical_inactive_argument) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.status = BB_STATUS_DECISION;
    f.env.match.stack_top = 1;
    f.env.match.stack[0] = (bb_frame){BB_PROC_MOVE, 0, 0, 0, 0, 0, 0};
    f.env.match.players[0].x = 1;
    f.env.match.players[0].y = 1;
    f.env.n_legal = 1;
    f.env.legal[0] = (bb_action){BB_A_STEP, 0, 2, 1};
    f.env.macro_moves = 1;
    f.env.reach_mover = 0;
    for (int i = 0; i < BB_PITCH_LEN * BB_PITCH_WID; i++)
        f.env.reach_parent[i] = -1;
    int source = 1 * BB_PITCH_LEN + 1;
    int first = 1 * BB_PITCH_LEN + 2;
    int destination = 1 * BB_PITCH_LEN + 3;
    f.env.reach_parent[first] = source;
    f.env.reach_parent[destination] = first;
    bbe_fill_mask(&f.env, BB_HOME);

    float canonical[3] = {BB_A_STEP, 32, (float)destination};
    bb_action picked = bbe_decode(&f.env, BB_HOME, canonical);
    BB_CHECK_EQ(picked.type, BB_A_STEP);
    BB_CHECK_EQ(picked.x, 2);
    BB_CHECK_EQ(picked.y, 1);
    BB_CHECK_EQ(f.env.illegal, 0);

    f.env.macro_len = 0;
    float polluted[3] = {BB_A_STEP, 0, (float)destination};
    picked = bbe_decode(&f.env, BB_HOME, polluted);
    BB_CHECK_EQ(picked.type, BB_A_NONE);
    BB_CHECK_EQ(f.env.illegal, 1);
}

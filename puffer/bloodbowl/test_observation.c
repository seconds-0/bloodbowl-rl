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

// obs-v6 fixtures. The fixture memset leaves every player at
// BB_LOC_ON_PITCH/BB_STANCE_STANDING on square (0,0) (both enums are 0), which
// makes candidate enumerations degenerate. Clear the squad first, then place
// exactly the players a window needs, keeping match.grid consistent so
// bb_slot_at / bb_tackle_zones agree with players[].
static void obs_clear_pitch(ObservationFixture* f) {
    memset(f->env.match.grid, 0, sizeof f->env.match.grid);
    for (int slot = 0; slot < BB_NUM_PLAYERS; slot++) {
        f->env.match.players[slot].location = BB_LOC_RESERVES;
    }
}

static void obs_place(ObservationFixture* f, int slot, int x, int y) {
    bb_player* p = &f->env.match.players[slot];
    p->location = BB_LOC_ON_PITCH;
    p->stance = BB_STANCE_STANDING;
    p->flags = 0;
    p->x = (uint8_t)x;
    p->y = (uint8_t)y;
    p->ma = 6;
    p->st = 3;
    p->ag = 3;
    p->pa = 3;
    p->av = 9;
    f->env.match.grid[x][y] = (uint8_t)(slot + 1);
}

static const uint8_t* obs_scalars(ObservationFixture* f, int agent) {
    return f->env.obs_ptr[agent] + BBE_SCALAR_OFF;
}

static const uint8_t* obs_ctx(ObservationFixture* f, int agent) {
    return f->env.obs_ptr[agent] + BBE_CTX_OFF;
}

BB_TEST(observation_block_faces_are_public_at_reroll_and_choice_windows) {
    BB_CHECK_EQ(BBE_OBS_VERSION, 6);
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
    // A collision must be distinguishable from a tuple that simply was not
    // offered: both are fatal, but only this one means the action encoding is
    // non-injective over the legal set, and c_step reports them differently.
    BB_CHECK_EQ(f.env.illegal_projection_collision, 1);

    // Exact duplicate enumeration does not create semantic ambiguity.
    f.env.illegal_projection_collision = 0;
    f.env.legal[1] = f.env.legal[0];
    bbe_fill_mask(&f.env, BB_HOME);
    picked = bbe_decode(&f.env, BB_HOME, heads);
    BB_CHECK(bb_action_eq(picked, f.env.legal[0]));
    BB_CHECK_EQ(f.env.illegal, 1);
    BB_CHECK_EQ(f.env.illegal_projection_collision, 0);
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

// ===== obs-v6 decision-window bytes ==========================================
// One test per new byte, each asserting BOTH the live reading and the
// off-window zero, and each checked from both agent views so an egocentric
// remap error cannot hide. Every one of these was watched to fail against a
// deliberately broken encoder before being accepted (D230).

BB_TEST(observation_v6_scalar_layout_is_the_documented_tail) {
    // The byte layout is part of the ABI: obs offsets 806..831, OBS_SIZE
    // unchanged so none of the three sync points move.
    BB_CHECK_EQ(BBE_OBS_VERSION, 6);
    BB_CHECK_EQ(BBE_OBS_SIZE, 2782);
    BB_CHECK_EQ(BBE_SCALAR_OFF, 784);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_WINDOW_FLAGS, 806);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_ACT_KIND, 807);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_CAS_ROLL_A, 808);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_CAS_ROLL_B, 809);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_STACK_FLAGS, 810);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_PLACEMENT_BUDGET, 811);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_MOVE_TARGET, 812);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_KTM_USED, 813);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_OPTION_TABLE, 816);
    BB_CHECK_EQ(BBE_SCALAR_OFF + BBE_S_OPTION_TABLE + BBE_S_OPTION_SLOTS,
                BBE_TZ_OFF);
    BB_CHECK_EQ(BBE_TZ_OFF, 832);
}

BB_TEST(observation_pass_interception_options_name_their_candidates) {
    ObservationFixture f;
    observation_fixture_init(&f);
    obs_clear_pitch(&f);
    // Home slot 3 throws from (4,7) to (12,7). Two away players stand on the
    // ruler line and exert tackle zones, so interception_candidates returns
    // them in MARCH order -- nearest the thrower first, regardless of slot id.
    obs_place(&f, 3, 4, 7);
    obs_place(&f, 20, 7, 7);
    obs_place(&f, 18, 9, 7);
    f.env.match.stack_top = 1;
    f.env.match.stack[0] = (bb_frame){BB_PROC_PASS, 2, 3, 0, 12, 7, 0};
    encode_both(&f);

    const uint8_t* home = obs_scalars(&f, BB_HOME);
    const uint8_t* away = obs_scalars(&f, BB_AWAY);
    BB_CHECK_EQ(home[BBE_S_OPTION_TABLE + 0], 1 + 20);
    BB_CHECK_EQ(home[BBE_S_OPTION_TABLE + 1], 1 + 18);
    BB_CHECK_EQ(home[BBE_S_OPTION_TABLE + 2], 0);
    BB_CHECK_EQ(away[BBE_S_OPTION_TABLE + 0],
                1 + (20 ^ BB_TEAM_SLOTS));
    BB_CHECK_EQ(away[BBE_S_OPTION_TABLE + 1],
                1 + (18 ^ BB_TEAM_SLOTS));
    BB_CHECK_EQ(away[BBE_S_OPTION_TABLE + 2], 0);
    // The pass target square rides the generalized consequence square, so the
    // ruler path is reconstructible.
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 13);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 8);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[9], BB_PITCH_LEN - 12);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[12], 8);
    // The accurate/inaccurate latch sets the interception modifier.
    BB_CHECK_EQ(home[BBE_S_WINDOW_FLAGS], 0);
    f.env.match.stack[0].data = 0x100;
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_WINDOW_FLAGS],
                BBE_WF_PASS_INACCURATE);
    BB_CHECK_EQ(obs_scalars(&f, BB_AWAY)[BBE_S_WINDOW_FLAGS],
                BBE_WF_PASS_INACCURATE);

    // Off-window: the same frame at a non-interception phase publishes no
    // option table (phase 2 is the only PASS decision).
    f.env.match.stack[0].phase = 3;
    f.env.match.stack[0].data = 0;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        const uint8_t* scalar = obs_scalars(&f, agent);
        for (int i = 0; i < BBE_S_OPTION_SLOTS; i++) {
            BB_CHECK_EQ(scalar[BBE_S_OPTION_TABLE + i], 0);
        }
        BB_CHECK_EQ(obs_ctx(&f, agent)[9], 0);
        BB_CHECK_EQ(obs_ctx(&f, agent)[12], 0);
    }
}

BB_TEST(observation_high_kick_options_name_their_candidates) {
    ObservationFixture f;
    observation_fixture_init(&f);
    obs_clear_pitch(&f);
    // Away kicks; the ball is airborne over an empty square in the receiving
    // (home) half. Two unmarked standing home players are the candidates.
    f.env.match.ball.state = BB_BALL_IN_AIR;
    f.env.match.ball.x = 5;
    f.env.match.ball.y = 6;
    obs_place(&f, 2, 3, 3);
    obs_place(&f, 9, 8, 9);
    f.env.match.stack_top = 1;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_KICKOFF, 4, BB_AWAY, 0, 0, 0, 0};
    encode_both(&f);

    const uint8_t* home = obs_scalars(&f, BB_HOME);
    const uint8_t* away = obs_scalars(&f, BB_AWAY);
    BB_CHECK_EQ(home[BBE_S_OPTION_TABLE + 0], 1 + 2);
    BB_CHECK_EQ(home[BBE_S_OPTION_TABLE + 1], 1 + 9);
    BB_CHECK_EQ(home[BBE_S_OPTION_TABLE + 2], 0);
    BB_CHECK_EQ(away[BBE_S_OPTION_TABLE + 0], 1 + (2 ^ BB_TEAM_SLOTS));
    BB_CHECK_EQ(away[BBE_S_OPTION_TABLE + 1], 1 + (9 ^ BB_TEAM_SLOTS));
    // Marking one of them removes it from the engine's enumeration, so the
    // table must shrink with it rather than going stale.
    obs_place(&f, 25, 4, 4);
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_OPTION_TABLE + 0], 1 + 9);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_OPTION_TABLE + 1], 0);
}

BB_TEST(observation_push_window_flags_expose_pow_blitz_and_stand_firm) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 1;
    // PUSH phase 3 = the follow-up decision; x/y are the vacated square.
    f.env.match.stack[0] = (bb_frame){BB_PROC_PUSH, 3, 1, 17, 6, 8, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_WINDOW_FLAGS], 0);
    }

    f.env.match.stack[0].data = PSH_POW;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_WINDOW_FLAGS],
                    BBE_WF_PUSH_POW);
    }

    // PSH_CROWD and PSH_MOVED are derivable from the board and must NOT leak
    // into the flags byte; the three that are not derivable must all appear.
    f.env.match.stack[0].data =
        PSH_POW | PSH_FROM_BLITZ | PSH_SF_DECLINED | PSH_CROWD | PSH_MOVED;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_WINDOW_FLAGS],
                    BBE_WF_PUSH_POW | BBE_WF_PUSH_FROM_BLITZ |
                        BBE_WF_PUSH_SF_DECLINED);
    }
    // The vacated square is published at phase 3 and only at phase 3.
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 7);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 9);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[9], BB_PITCH_LEN - 6);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[12], 9);
    for (int phase = 0; phase <= 4; phase++) {
        if (phase == 3) continue;
        f.env.match.stack[0].phase = (uint8_t)phase;
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            // The flags stay live at every PUSH phase (POW decides the
            // outcome of the square choice too); only the square is gated.
            BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_WINDOW_FLAGS],
                        BBE_WF_PUSH_POW | BBE_WF_PUSH_FROM_BLITZ |
                            BBE_WF_PUSH_SF_DECLINED);
            BB_CHECK_EQ(obs_ctx(&f, agent)[9], 0);
            BB_CHECK_EQ(obs_ctx(&f, agent)[12], 0);
        }
    }
    // A non-PUSH, non-PASS frame carrying the same data bits must not leak.
    f.env.match.stack[0] = (bb_frame){BB_PROC_BLOCK, 1, 1, 17, 6, 8,
                                      PSH_POW | PSH_FROM_BLITZ};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_WINDOW_FLAGS], 0);
    }
}

BB_TEST(observation_declared_action_kind_rides_the_nearest_activation) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 1;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 0, BB_ACT_BLITZ, 0, 0, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_ACT_KIND],
                    BB_ACT_BLITZ + 1);
    }

    // A nested resolution frame must not hide the declaration: this is the
    // whole point (an ATTACKER_DOWN inside a blitz is a different decision).
    f.env.match.stack_top = 2;
    f.env.match.stack[1] = (bb_frame){BB_PROC_BLOCK, 1, 0, 16, 0, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_ACT_KIND], BB_ACT_BLITZ + 1);
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 0, BB_TEST_DODGE, 3, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_ACT_KIND], BB_ACT_BLITZ + 1);

    // Every kind round-trips, so the byte is the kind and not a blitz flag.
    f.env.match.stack_top = 1;
    for (int kind = 0; kind < BB_ACT_KIND_COUNT; kind++) {
        f.env.match.stack[0] =
            (bb_frame){BB_PROC_MOVE, 1, 0, (uint8_t)kind, 0, 0, 0};
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_ACT_KIND], kind + 1);
        }
    }

    // ACTIVATION's negatrait gate re-roll window (phase 2) has the declared
    // kind in b as well.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_ACTIVATION, 2, 0, BB_ACT_FOUL, 0, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_ACT_KIND], BB_ACT_FOUL + 1);

    // ACTIVATION phase 0 is the DECLARE window itself: b is still the
    // push-time zero, which would read as a declared BB_ACT_MOVE.
    f.env.match.stack[0].phase = 0;
    f.env.match.stack[0].b = 0;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_ACT_KIND], 0);
    }

    // Windows no activation owns stay zero.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_SETUP, 0, BB_HOME, 0, 0, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_ACT_KIND], 0);
    f.env.match.stack_top = 0;
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_ACT_KIND], 0);
}

BB_TEST(observation_casualty_rolls_only_in_the_apothecary_windows) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 1;
    // Phase 1 = APOTHECARY use/decline: roll A is in x, and y is still 0
    // because the second roll does not exist yet.
    f.env.match.stack[0] = (bb_frame){BB_PROC_CASUALTY, 1, 5, 1, 11, 0, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_A], 11);
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_B], 0);
    }
    // Phase 2 = pick roll A or roll B; both must be visible or the choice is
    // blind. bb_casualty_table is monotone, so raw rolls are learnable: 4 is
    // Badly Hurt (Reserves) and 11 is not.
    f.env.match.stack[0] = (bb_frame){BB_PROC_CASUALTY, 2, 5, 1, 11, 4, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_A], 11);
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_B], 4);
    }
    BB_CHECK_EQ(bb_casualty_table[4], BB_CAS_BADLY_HURT);
    BB_CHECK(bb_casualty_table[11] != BB_CAS_BADLY_HURT);

    // Phase 0 is not a decision and its y carries causer+1, not a roll.
    f.env.match.stack[0] = (bb_frame){BB_PROC_CASUALTY, 0, 5, 1, 0, 6, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_A], 0);
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_B], 0);
    }
    // Another proc's x/y are squares or payloads and must not leak as rolls.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_TEST, 1, 5, BB_TEST_DODGE, 11, 4, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_A], 0);
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_CAS_ROLL_B], 0);
    }
}

BB_TEST(observation_stack_flags_expose_turnover_and_kickoff_context) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 1;
    f.env.match.stack[0] = (bb_frame){BB_PROC_PUSH, 3, 1, 17, 6, 8, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_STACK_FLAGS], 0);
    }
    // The crowd-push follow-up really is surfaced with the turn already lost.
    f.env.match.turnover = 1;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_STACK_FLAGS],
                    BBE_SF_TURNOVER);
    }

    // A Charge! activation: the KICKOFF frame is buried below the top.
    f.env.match.turnover = 0;
    f.env.match.stack_top = 2;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_KICKOFF, 7, BB_HOME, 0, 3, 0, 0};
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_ACTIVATION, 0, 4, 0, 1, 0, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_STACK_FLAGS],
                    BBE_SF_KICKOFF | BBE_SF_KICKOFF_CHARGE);
    }
    // A non-Charge kickoff phase is in the kickoff but not in the charge, and
    // team re-rolls are unavailable there.
    f.env.match.stack[0].phase = 5;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_STACK_FLAGS],
                    BBE_SF_KICKOFF);
    }
}

BB_TEST(observation_placement_budget_counts_down_per_window) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 1;
    // SETUP: data is the action counter against SETUP_ACTION_BUDGET.
    f.env.match.stack[0] = (bb_frame){BB_PROC_SETUP, 0, BB_HOME, 0, 0, 0, 3};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_PLACEMENT_BUDGET],
                    SETUP_ACTION_BUDGET - 3 + 1);
    }
    // Budget exhausted encodes as 1, distinct from the 0 that means "this is
    // not a placement window at all".
    f.env.match.stack[0].data = SETUP_ACTION_BUDGET;
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_PLACEMENT_BUDGET], 1);
    f.env.match.stack[0].data = SETUP_ACTION_BUDGET + 7; // clamped, never wraps
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_PLACEMENT_BUDGET], 1);
    // Second team's setup runs at phase 1 with a reset counter.
    f.env.match.stack[0] = (bb_frame){BB_PROC_SETUP, 1, BB_HOME, 0, 0, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_PLACEMENT_BUDGET],
                SETUP_ACTION_BUDGET + 1);

    // KICKOFF Solid Defence (5) / Quick Snap (6): x = fresh-pick budget,
    // data = already-selected bitmask, exactly the kickoff_legal predicate.
    for (int phase = 5; phase <= 6; phase++) {
        f.env.match.stack[0] = (bb_frame){BB_PROC_KICKOFF, (uint8_t)phase,
                                          BB_HOME, 0, 5, 24, 0x000B};
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_PLACEMENT_BUDGET],
                        5 - 3 + 1);
        }
    }
    // KICKOFF Charge! (7): x is the remaining activation count directly.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_KICKOFF, 7, BB_HOME, 0, 2, 0, 0xFFFF};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_PLACEMENT_BUDGET], 3);

    // Non-placement windows stay zero, including other KICKOFF phases whose
    // x/y mean something else entirely.
    static const uint8_t quiet_phases[] = {0, 2, 3, 4};
    for (size_t i = 0; i < sizeof quiet_phases / sizeof quiet_phases[0]; i++) {
        f.env.match.stack[0] = (bb_frame){BB_PROC_KICKOFF, quiet_phases[i],
                                          BB_HOME, 0, 9, 9, 0};
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_PLACEMENT_BUDGET], 0);
        }
    }
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 0, BB_ACT_MOVE, 9, 9, 24};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_PLACEMENT_BUDGET], 0);
}

BB_TEST(observation_move_target_slot_only_when_the_stash_is_live) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 1;
    // TTM: BB_A_SPECIAL_TARGET arg=7 stashes the mate in data bits 9-13 and
    // reuses MV_BLOCK_DONE as "mate picked" (move_legal:455). The NEXT
    // decision picks a landing square among ~60 and needs to know who is
    // being thrown.
    f.env.match.stack[0] = (bb_frame){BB_PROC_MOVE, 1, 2, BB_ACT_TTM, 0, 0,
                                      (uint16_t)(MV_BLOCK_DONE | (7u << 9))};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_MOVE_TARGET], 1 + 7);
    BB_CHECK_EQ(obs_scalars(&f, BB_AWAY)[BBE_S_MOVE_TARGET],
                1 + (7 ^ BB_TEAM_SLOTS));
    f.env.match.stack[0].b = BB_ACT_KTM;
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_MOVE_TARGET], 1 + 7);

    // Same stash bits, mate NOT yet picked: nothing is stashed, so slot 0
    // must not be reported.
    f.env.match.stack[0].data = (uint16_t)(7u << 9);
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_MOVE_TARGET], 0);
    }
    // A BLOCK/BLITZ declaration sets MV_BLOCK_DONE for a completed block, not
    // a mate pick: the bits are stale there.
    f.env.match.stack[0].b = BB_ACT_BLOCK;
    f.env.match.stack[0].data = (uint16_t)(MV_BLOCK_DONE | (7u << 9));
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_MOVE_TARGET], 0);

    // Blitz/stab rush-for-block: MV_BLOCK_RUSH is set together with the stash.
    f.env.match.stack_top = 2;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 1, BB_ACT_BLITZ, 4, 5,
                   (uint16_t)(MV_AWAIT_TEST | MV_RUSH_PEND | MV_BLOCK_RUSH |
                              (19u << 9))};
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 1, BB_TEST_RUSH, 2, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_MOVE_TARGET], 1 + 19);
    BB_CHECK_EQ(obs_scalars(&f, BB_AWAY)[BBE_S_MOVE_TARGET],
                1 + (19 ^ BB_TEAM_SLOTS));

    // Jump-Up prone block: MV_STAND_PEND plus a nested BB_TEST_GENERIC.
    f.env.match.stack[0] = (bb_frame){BB_PROC_MOVE, 1, 1, BB_ACT_BLOCK, 8, 6,
                                      (uint16_t)(MV_STAND_PEND | (5u << 9))};
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 1, BB_TEST_GENERIC, 3, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_MOVE_TARGET], 1 + 5);

    // The MA<3 stand-up sets MV_STAND_PEND but never writes the stash, and it
    // pushes BB_TEST_STANDUP rather than GENERIC.
    f.env.match.stack[1].b = BB_TEST_STANDUP;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_MOVE_TARGET], 0);
    }
    // BB_A_JUMP parks a RUSH COUNT in the same bits 9-13. Reading it as a
    // player slot would invent a target out of a dice budget.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 1, BB_ACT_MOVE, 8, 6,
                   (uint16_t)(MV_JUMP | MV_AWAIT_TEST | MV_RUSH_PEND |
                              (2u << 9))};
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 1, BB_TEST_RUSH, 2, 0, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_MOVE_TARGET], 0);
    }
    // No MOVE frame at all: nothing to stash.
    f.env.match.stack_top = 1;
    f.env.match.stack[0] = (bb_frame){BB_PROC_PUSH, 3, 1, 17, 6, 8, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_MOVE_TARGET], 0);
}

BB_TEST(observation_ktm_used_completes_the_once_per_turn_latches) {
    ObservationFixture f;
    observation_fixture_init(&f);
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_KTM_USED], 0);
    }
    f.env.match.ktm_used = 1;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        // Single active-team flag, like s[8..13]; disambiguated by ctx[11].
        BB_CHECK_EQ(obs_scalars(&f, agent)[BBE_S_KTM_USED], 1);
        BB_CHECK_EQ(obs_scalars(&f, agent)[12], 0); // ttm_used is separate
    }
    f.env.match.ttm_used = 1;
    encode_both(&f);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[12], 1);
    BB_CHECK_EQ(obs_scalars(&f, BB_HOME)[BBE_S_KTM_USED], 1);
}

// THE negative test. Section 7 of the inventory: "That stale-square case is
// the one way this batch can silently ship a lie." proc_move.c's MA<3
// stand-up and the Jump-Up prone-block BB_TEST_GENERIC both push their TEST
// without writing the parent MOVE frame's x/y, so that square holds whatever
// an earlier step left there. Publishing it would name a destination the
// engine will never move the player to.
BB_TEST(observation_pending_square_stays_zero_when_the_move_frame_is_stale) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.players[1].moved = 4;
    f.env.match.stack_top = 2;
    // A MOVE frame whose x/y hold an EARLIER destination (8,6) -- exactly the
    // shape a stand-up or Jump-Up block leaves behind mid-activation.
    f.env.match.stack[0] = (bb_frame){BB_PROC_MOVE, 1, 1, BB_ACT_MOVE, 8, 6,
                                      MV_STAND_PEND};
    static const int stale_kinds[] = {BB_TEST_STANDUP, BB_TEST_GENERIC};
    for (size_t i = 0; i < sizeof stale_kinds / sizeof stale_kinds[0]; i++) {
        f.env.match.stack[1] = (bb_frame){BB_PROC_TEST, 0, 1,
                                          (uint8_t)stale_kinds[i], 4, 0, 0};
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            const uint8_t* ctx = obs_ctx(&f, agent);
            BB_CHECK_EQ(ctx[9], 0);
            BB_CHECK_EQ(ctx[12], 0);
            // The rest of the window is still described, so the zero above is
            // a deliberate gate and not an empty fixture.
            BB_CHECK_EQ(ctx[8], 4);
            BB_CHECK_EQ(obs_scalars(&f, agent)[21], stale_kinds[i] + 1);
        }
    }
    // Positive control on the SAME frame: a live kind does publish it, so the
    // zeroes above cannot be an accident of the fixture.
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 1, BB_TEST_DODGE, 4, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 9);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 7);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[9], BB_PITCH_LEN - 8);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[12], 7);
}

BB_TEST(observation_pending_square_generalizes_to_the_live_windows) {
    ObservationFixture f;
    observation_fixture_init(&f);
    f.env.match.stack_top = 2;
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 1, BB_ACT_MOVE, 8, 6, 0};
    // proc_move.c writes f->x/f->y before pushing each of these three, so the
    // destination is live. Rush is roughly as common as Dodge and a failed
    // rush drops the player at the destination and turns the ball over.
    static const int live_kinds[] = {BB_TEST_DODGE, BB_TEST_RUSH,
                                     BB_TEST_JUMP};
    for (size_t i = 0; i < sizeof live_kinds / sizeof live_kinds[0]; i++) {
        f.env.match.stack[1] = (bb_frame){BB_PROC_TEST, 0, 1,
                                          (uint8_t)live_kinds[i], 3, 0, 0};
        encode_both(&f);
        BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 9);
        BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 7);
        BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[9], BB_PITCH_LEN - 8);
        BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[12], 7);
    }
    // Kinds whose consequence is not the parent MOVE's square stay zero.
    static const int quiet_kinds[] = {BB_TEST_PICKUP, BB_TEST_CATCH,
                                      BB_TEST_LONER, BB_TEST_TTM};
    for (size_t i = 0; i < sizeof quiet_kinds / sizeof quiet_kinds[0]; i++) {
        f.env.match.stack[1] = (bb_frame){BB_PROC_TEST, 0, 1,
                                          (uint8_t)quiet_kinds[i], 3, 0, 0};
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            BB_CHECK_EQ(obs_ctx(&f, agent)[9], 0);
            BB_CHECK_EQ(obs_ctx(&f, agent)[12], 0);
        }
    }
    // A parent MOVE for a DIFFERENT player is not this test's parent.
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 1, BB_TEST_RUSH, 3, 0, 0};
    f.env.match.stack[0].a = 2;
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 0);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 0);

    // BB_TEST_PASS's consequence is the PASS frame's target square.
    f.env.match.stack[0] = (bb_frame){BB_PROC_PASS, 1, 1, 0, 11, 4, 0};
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 1, BB_TEST_PASS, 4, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 12);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 5);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[9], BB_PITCH_LEN - 11);
    BB_CHECK_EQ(obs_ctx(&f, BB_AWAY)[12], 5);
    // BB_TEST_PASS under a MOVE parent is not a shape the engine produces;
    // the gate is on the parent proc, not the kind alone.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 1, BB_ACT_PASS, 11, 4, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 0);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 0);

    // Off-pitch/garbage frame squares zero out exactly like the ball coords.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_MOVE, 1, 1, BB_ACT_MOVE, 0xFF, 0xFF, 0};
    f.env.match.stack[1] =
        (bb_frame){BB_PROC_TEST, 0, 1, BB_TEST_DODGE, 3, 0, 0};
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[9], 0);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[12], 0);
}

BB_TEST(observation_activation_gate_target_is_visible_at_its_reroll_window) {
    ObservationFixture f;
    observation_fixture_init(&f);
    obs_clear_pitch(&f);
    obs_place(&f, 4, 6, 5);
    bb_add_skill(&f.env.match.players[4].skills, BB_SK_BONE_HEAD);
    f.env.match.stack_top = 1;
    // Phase 2 = the negatrait gate re-roll window. proc_turn.c keeps nothing
    // in the frame, so the encoder re-derives from the same pure helpers.
    f.env.match.stack[0] =
        (bb_frame){BB_PROC_ACTIVATION, 2, 4, BB_ACT_MOVE, 0, 0, 0};
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_ctx(&f, agent)[8], 2); // Bone Head is 2+
    }
    // Unchannelled Fury is 4+ with a +2 modifier for a declared Block/Blitz,
    // so the byte must move with the declaration, not just the skill.
    obs_place(&f, 5, 6, 7);
    bb_add_skill(&f.env.match.players[5].skills, BB_SK_UNCHANNELLED_FURY);
    f.env.match.stack[0].a = 5;
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[8], 4);
    f.env.match.stack[0].b = BB_ACT_BLITZ;
    encode_both(&f);
    for (int agent = 0; agent < BBE_AGENTS; agent++) {
        BB_CHECK_EQ(obs_ctx(&f, agent)[8], 2);
    }
    // A player with no gate trait, and the DECLARE window itself, stay zero.
    f.env.match.stack[0].a = 4;
    f.env.match.stack[0].b = BB_ACT_MOVE;
    f.env.match.stack[0].phase = 0;
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[8], 0);
    f.env.match.stack[0].phase = 2;
    f.env.match.stack[0].a = 6; // reserves, no skills
    encode_both(&f);
    BB_CHECK_EQ(obs_ctx(&f, BB_HOME)[8], 0);
}

BB_TEST(observation_v6_slack_bytes_stay_zero_at_every_window) {
    ObservationFixture f;
    observation_fixture_init(&f);
    obs_clear_pitch(&f);
    obs_place(&f, 3, 4, 7);
    obs_place(&f, 20, 7, 7);
    f.env.match.turnover = 1;
    f.env.match.ktm_used = 1;
    f.env.match.ball.state = BB_BALL_IN_AIR;
    f.env.match.ball.x = 5;
    f.env.match.ball.y = 6;
    // The 2 bytes of slack (s[30], s[31]) are reserved for a future revision
    // and must read zero under every window the encoder handles, otherwise a
    // later reader would inherit garbage rather than a clean reservation.
    static const bb_frame windows[] = {
        {BB_PROC_PASS, 2, 3, 0, 12, 7, 0x100},
        {BB_PROC_PUSH, 3, 3, 20, 6, 8, PSH_POW | PSH_FROM_BLITZ},
        {BB_PROC_CASUALTY, 2, 3, 1, 11, 4, 0},
        {BB_PROC_SETUP, 0, BB_HOME, 0, 0, 0, 3},
        {BB_PROC_KICKOFF, 4, BB_AWAY, 0, 0, 0, 0},
        {BB_PROC_KICKOFF, 7, BB_HOME, 0, 3, 0, 0},
        {BB_PROC_MOVE, 1, 3, BB_ACT_TTM, 0, 0,
         (uint16_t)(MV_BLOCK_DONE | (7u << 9))},
        {BB_PROC_TEST, 0, 3, BB_TEST_DODGE, 3, 0, 0},
        {BB_PROC_ACTIVATION, 2, 3, BB_ACT_BLITZ, 0, 0, 0},
        {BB_PROC_FOUL, 2, 3, 20, 0, 0, 0},
    };
    for (size_t i = 0; i < sizeof windows / sizeof windows[0]; i++) {
        f.env.match.stack_top = 1;
        f.env.match.stack[0] = windows[i];
        encode_both(&f);
        for (int agent = 0; agent < BBE_AGENTS; agent++) {
            const uint8_t* scalar = obs_scalars(&f, agent);
            BB_CHECK_EQ(scalar[30], 0);
            BB_CHECK_EQ(scalar[31], 0);
        }
    }
}

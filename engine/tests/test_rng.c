#include "bb/bb_rng.h"
#include "bb_test.h"

BB_TEST(rng_deterministic_same_seed) {
    bb_rng a, b;
    bb_rng_seed(&a, 42, 1);
    bb_rng_seed(&b, 42, 1);
    for (int i = 0; i < 1000; i++) BB_CHECK_EQ(bb_d6(&a), bb_d6(&b));
}

BB_TEST(rng_streams_differ) {
    bb_rng a, b;
    bb_rng_seed(&a, 42, 1);
    bb_rng_seed(&b, 42, 2);
    int same = 0;
    for (int i = 0; i < 1000; i++) same += (bb_d6(&a) == bb_d6(&b));
    BB_CHECK(same < 400); // independent streams: ~1/6 collisions expected
}

BB_TEST(rng_range_and_uniformity) {
    bb_rng r;
    bb_rng_seed(&r, 7, 0);
    int counts[17] = {0};
    const int N = 160000;
    for (int i = 0; i < N; i++) {
        int v = bb_d16(&r);
        BB_CHECK(v >= 1 && v <= 16);
        counts[v]++;
    }
    // Loose uniformity: each face within 10% of expectation (N/16 = 10000).
    for (int f = 1; f <= 16; f++) {
        BB_CHECK(counts[f] > 9000 && counts[f] < 11000);
    }
}

BB_TEST(rng_script_mode_replays_exact_values) {
    static const uint8_t script[] = {3, 6, 1, 16, 2};
    bb_rng r;
    bb_rng_script(&r, script, 5);
    BB_CHECK_EQ(bb_d6(&r), 3);
    BB_CHECK_EQ(bb_d6(&r), 6);
    BB_CHECK_EQ(bb_d6(&r), 1);
    BB_CHECK_EQ(bb_d16(&r), 16);
    BB_CHECK_EQ(bb_d3(&r), 2);
    BB_CHECK(!bb_rng_error(&r));
}

BB_TEST(rng_script_exhaustion_is_sticky_error) {
    static const uint8_t script[] = {4};
    bb_rng r;
    bb_rng_script(&r, script, 1);
    BB_CHECK_EQ(bb_d6(&r), 4);
    bb_d6(&r);
    BB_CHECK(bb_rng_error(&r));
}

BB_TEST(rng_script_out_of_range_is_error) {
    static const uint8_t script[] = {7}; // 7 on a d6
    bb_rng r;
    bb_rng_script(&r, script, 1);
    bb_d6(&r);
    BB_CHECK(bb_rng_error(&r));
}

static void count_sink(void* user, int sides, int value) {
    (void)sides; (void)value;
    (*(int*)user)++;
}

BB_TEST(rng_sink_observes_every_roll) {
    bb_rng r;
    bb_rng_seed(&r, 1, 1);
    int n = 0;
    bb_rng_set_sink(&r, count_sink, &n);
    bb_2d6(&r);
    bb_d16(&r);
    BB_CHECK_EQ(n, 3);
}

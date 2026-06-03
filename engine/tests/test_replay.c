#include "bb/bb_replay.h"
#include "bb/bb_rng.h"
#include "bb_test.h"

BB_TEST(replay_roundtrip) {
    const char* path = "/tmp/bb_test_replay.jsonl";
    bb_replay_writer w;
    BB_CHECK_EQ(bb_replay_open(&w, path), 0);
    bb_replay_init_record(&w, 3, 7, 123456789ULL);
    bb_action a1 = { BB_A_ACTIVATE, 5, 0, 0 };
    bb_action a2 = { BB_A_STEP, 0, 12, 7 };
    bb_replay_action(&w, a1);
    bb_replay_dice(&w, 6, 4);
    bb_replay_dice(&w, 16, 13);
    bb_replay_action(&w, a2);
    bb_replay_end_record(&w, 2, 1);
    bb_replay_close(&w);

    FILE* f = fopen(path, "r");
    BB_CHECK(f != 0);
    char buf[4096];
    size_t n = fread(buf, 1, sizeof buf, f);
    fclose(f);

    bb_replay_reader r;
    bb_replay_reader_init(&r, buf, n);
    bb_record rec;

    BB_CHECK(bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_INIT);
    BB_CHECK_EQ(rec.home_team_id, 3);
    BB_CHECK_EQ(rec.away_team_id, 7);
    BB_CHECK(rec.seed == 123456789ULL);
    BB_CHECK_EQ(rec.version, BB_REPLAY_VERSION);

    BB_CHECK(bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_ACTION);
    BB_CHECK(bb_action_eq(rec.action, a1));

    BB_CHECK(bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_DICE);
    BB_CHECK_EQ(rec.sides, 6);
    BB_CHECK_EQ(rec.value, 4);

    BB_CHECK(bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_DICE);
    BB_CHECK_EQ(rec.sides, 16);
    BB_CHECK_EQ(rec.value, 13);

    BB_CHECK(bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_ACTION);
    BB_CHECK(bb_action_eq(rec.action, a2));

    BB_CHECK(bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_END);
    BB_CHECK_EQ(rec.home_score, 2);
    BB_CHECK_EQ(rec.away_score, 1);

    BB_CHECK(!bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_EOF);
    remove(path);
}

BB_TEST(replay_action_pack_roundtrip) {
    for (int t = 0; t < BB_A_TYPE_COUNT; t++) {
        bb_action a = { (uint8_t)t, 200, 25, 14 };
        bb_action b = bb_action_unpack(bb_action_pack(a));
        BB_CHECK(bb_action_eq(a, b));
    }
}

BB_TEST(replay_parse_error_on_garbage) {
    const char* junk = "{\"x\":1}\n";
    bb_replay_reader r;
    bb_replay_reader_init(&r, junk, 8);
    bb_record rec;
    BB_CHECK(!bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_PARSE_ERROR);
}

BB_TEST(replay_dice_sink_integration) {
    const char* path = "/tmp/bb_test_replay_sink.jsonl";
    bb_replay_writer w;
    BB_CHECK_EQ(bb_replay_open(&w, path), 0);

    bb_rng rng;
    bb_rng_seed(&rng, 9, 0);
    bb_rng_set_sink(&rng, bb_replay_dice_sink, &w);
    int rolled[3];
    for (int i = 0; i < 3; i++) rolled[i] = bb_d6(&rng);
    bb_replay_close(&w);

    FILE* f = fopen(path, "r");
    char buf[1024];
    size_t n = fread(buf, 1, sizeof buf, f);
    fclose(f);

    bb_replay_reader r;
    bb_replay_reader_init(&r, buf, n);
    bb_record rec;
    for (int i = 0; i < 3; i++) {
        BB_CHECK(bb_replay_next(&r, &rec));
        BB_CHECK_EQ(rec.type, BB_REC_DICE);
        BB_CHECK_EQ(rec.value, rolled[i]);
    }
    remove(path);
}

// INIT records carry file-derived team ids that flow into bb_team_defs[]
// lookups; the reader must reject out-of-range (or missing) ids, including
// values that would silently truncate through (int) casts (review Hd1).
BB_TEST(replay_init_rejects_out_of_range_team_ids) {
    const char* bad[] = {
        "{\"t\":\"init\",\"v\":1,\"home\":-1,\"away\":1,\"seed\":1}\n",
        "{\"t\":\"init\",\"v\":1,\"home\":1,\"away\":99,\"seed\":1}\n",   // away never checked before
        "{\"t\":\"init\",\"v\":1,\"home\":4294967299,\"away\":1,\"seed\":1}\n", // (int) truncates to 3
        "{\"t\":\"init\",\"v\":1,\"away\":1,\"seed\":1}\n",              // missing home
    };
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        bb_replay_reader r;
        bb_replay_reader_init(&r, bad[i], strlen(bad[i]));
        bb_record rec;
        BB_CHECK(!bb_replay_next(&r, &rec));
        BB_CHECK_EQ(rec.type, BB_REC_PARSE_ERROR);
    }
    // In-range ids still parse.
    const char* good = "{\"t\":\"init\",\"v\":1,\"home\":0,\"away\":29,\"seed\":7}\n";
    bb_replay_reader r;
    bb_replay_reader_init(&r, good, strlen(good));
    bb_record rec;
    BB_CHECK(bb_replay_next(&r, &rec));
    BB_CHECK_EQ(rec.type, BB_REC_INIT);
    BB_CHECK_EQ(rec.home_team_id, 0);
    BB_CHECK_EQ(rec.away_team_id, 29);
}

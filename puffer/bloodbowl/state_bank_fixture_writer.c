#include "bloodbowl.h"
#include "bb_fixtures.h"

/*
 * This fixture is deliberately authored as geometry plus an expected metric
 * table.  The generated-fixture Python oracle consumes the table; the native
 * loader independently derives the same strata from the serialized matches.
 * Neither side obtains its expected ordinals from the runtime index.
 */
enum {
    FIXTURE_RECORDS = 7,
    FIXTURE_FAMILIES = 4,
    FIXTURE_INELIGIBLE = -1,
};

typedef struct {
    uint32_t source_id;
    uint32_t command;
    int active_team;
    int turn;
    int ball_kind; /* 0 off-pitch, 1 held, 2 ground */
    int carrier_team;
    int carrier_x;
    int carrier_y;
    int receiver_x;
    int receiver_y;
    int ball_x;
    int ball_y;
    int expected[FIXTURE_FAMILIES];
    int mirror_ordinal;
} fixture_spec;

static const fixture_spec fixture_specs[FIXTURE_RECORDS] = {
    /*
     * Home/Away mirrors.  Both are endzone metric 5 and pass metric 3.
     * They also prove one record may inhabit more than one family.
     */
    {
        UINT32_C(0x01020301), UINT32_C(0x0a0b0c01),
        BB_HOME, 3, 1, BB_HOME, 20, 7, 23, 8, 0, 0,
        {5, FIXTURE_INELIGIBLE, FIXTURE_INELIGIBLE, 3}, 1,
    },
    {
        UINT32_C(0x01020302), UINT32_C(0x0a0b0c02),
        BB_AWAY, 3, 1, BB_AWAY, 5, 7, 2, 8, 0, 0,
        {5, FIXTURE_INELIGIBLE, FIXTURE_INELIGIBLE, 3}, 0,
    },
    /*
     * The nearest active player is exactly two squares from the loose ball.
     * Turn 1 also makes this a post-kick proxy record.
     */
    {
        UINT32_C(0x01020303), UINT32_C(0x0a0b0c03),
        BB_HOME, 1, 2, BB_HOME, 8, 7, -1, -1, 10, 7,
        {FIXTURE_INELIGIBLE, 2, 1, FIXTURE_INELIGIBLE}, -1,
    },
    /*
     * A deliberately thin maximum-turn/long-pickup record.
     */
    {
        UINT32_C(0x01020304), UINT32_C(0x0a0b0c04),
        BB_AWAY, 8, 2, BB_AWAY, 17, 7, -1, -1, 10, 7,
        {FIXTURE_INELIGIBLE, 7, 8, FIXTURE_INELIGIBLE}, -1,
    },
    /*
     * Carrier belongs to the non-active team: historical endzone semantics
     * still classify it, while pass semantics correctly do not.
     */
    {
        UINT32_C(0x01020305), UINT32_C(0x0a0b0c05),
        BB_AWAY, 4, 1, BB_HOME, 23, 6, -1, -1, 0, 0,
        {2, FIXTURE_INELIGIBLE, FIXTURE_INELIGIBLE, FIXTURE_INELIGIBLE}, -1,
    },
    /*
     * Long pass tier.  The held active carrier also has endzone metric 17.
     */
    {
        UINT32_C(0x01020306), UINT32_C(0x0a0b0c06),
        BB_HOME, 5, 1, BB_HOME, 8, 9, 15, 9, 0, 0,
        {17, FIXTURE_INELIGIBLE, FIXTURE_INELIGIBLE, 7}, -1,
    },
    /* Uniform-only record: no selector predicate has a finite metric. */
    {
        UINT32_C(0x01020307), UINT32_C(0x0a0b0c07),
        BB_HOME, 6, 0, BB_HOME, 7, 5, -1, -1, 0, 0,
        {
            FIXTURE_INELIGIBLE,
            FIXTURE_INELIGIBLE,
            FIXTURE_INELIGIBLE,
            FIXTURE_INELIGIBLE,
        },
        -1,
    },
};

static int fixture_write_le32(FILE* file, uint32_t value) {
    const uint8_t bytes[4] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
    };
    return fwrite(bytes, 1, sizeof bytes, file) == sizeof bytes ? 0 : -1;
}

static int fixture_build_match(const fixture_spec* spec, int ordinal,
                               bb_match* match) {
    fx_match_midturn(match, spec->active_team, 2);
    match->turn[spec->active_team] = (uint8_t)(spec->turn - 1);

    int carrier = fx_lineman(
        match, spec->carrier_team, 0, spec->carrier_x, spec->carrier_y);
    int other_team = 1 - spec->carrier_team;
    (void)fx_lineman(match, other_team, 0,
                     spec->carrier_team == BB_HOME ? 4 : 21, 3);
    if (spec->receiver_x >= 0) {
        (void)fx_lineman(match, spec->carrier_team, 1,
                         spec->receiver_x, spec->receiver_y);
    }
    if (spec->ball_kind == 1) {
        fx_ball_held(match, carrier);
    } else if (spec->ball_kind == 2) {
        fx_ball_ground(match, spec->ball_x, spec->ball_y);
    }

    bb_rng rng;
    bb_rng_seed(&rng, UINT64_C(0xB4A600) + (uint64_t)ordinal, 3);
    if (fx_run(match, &rng) != BB_STATUS_DECISION ||
        !bb_state_bank_boundary_valid(match)) {
        fprintf(stderr,
                "fixture record %d failed to reach an ordinary boundary\n",
                ordinal);
        return -1;
    }
    if (match->turn[match->active_team] != spec->turn) {
        fprintf(stderr,
                "fixture record %d turn mismatch: got %u expected %d\n",
                ordinal, match->turn[match->active_team], spec->turn);
        return -1;
    }
    bb_action legal[BB_LEGAL_MAX];
    int n_legal = bb_legal_actions(match, legal);
    if (n_legal <= 0 || n_legal > BB_LEGAL_MAX) {
        fprintf(stderr,
                "fixture record %d has no bounded legal-action surface\n",
                ordinal);
        return -1;
    }

    static const bbe_state_bank_selector_family families[FIXTURE_FAMILIES] = {
        BBE_STATE_BANK_SELECTOR_ENDZONE,
        BBE_STATE_BANK_SELECTOR_PICKUP,
        BBE_STATE_BANK_SELECTOR_POSTKICK,
        BBE_STATE_BANK_SELECTOR_PASS,
    };
    for (int family = 0; family < FIXTURE_FAMILIES; family++) {
        uint32_t observed = 0;
        int eligible = bbe_state_bank_metric(
            match, families[family], &observed);
        int expected = spec->expected[family];
        if ((expected < 0 && eligible) ||
            (expected >= 0 &&
             (!eligible || observed != (uint32_t)expected))) {
            fprintf(stderr,
                    "fixture record %d family %d metric mismatch: "
                    "eligible=%d observed=%u expected=%d\n",
                    ordinal, family, eligible, observed, expected);
            return -1;
        }
    }
    return 0;
}

static int fixture_write_expectations(const char* path) {
    FILE* file = fopen(path, "wb");
    if (file == NULL) {
        perror(path);
        return -1;
    }
    int failed = fprintf(
        file,
        "{\"families\":[\"endzone-maxdist\",\"pickup-maxdist\","
        "\"postkick-maxturn\",\"pass-maxrange\"],\"records\":[") < 0;
    for (int i = 0; i < FIXTURE_RECORDS && !failed; i++) {
        const fixture_spec* spec = &fixture_specs[i];
        if (i != 0 && fputc(',', file) == EOF) failed = 1;
        if (!failed &&
            fprintf(
                file,
                "{\"command\":%u,\"expected_metrics\":[%d,%d,%d,%d],"
                "\"half\":1,\"mirror_ordinal\":%d,\"ordinal\":%d,"
                "\"source_id\":%u,\"turn\":%d}",
                spec->command,
                spec->expected[0], spec->expected[1],
                spec->expected[2], spec->expected[3],
                spec->mirror_ordinal, i, spec->source_id, spec->turn) < 0) {
            failed = 1;
        }
    }
    if (!failed &&
        fprintf(file,
                "],\"schema\":\"bloodbowl-state-bank-fixture-v1\"}\n") < 0) {
        failed = 1;
    }
    int flush_failed = fflush(file) != 0;
    int close_failed = fclose(file) != 0;
    if (flush_failed || close_failed) failed = 1;
    if (failed) {
        fprintf(stderr, "failed to write fixture expectations\n");
        return -1;
    }
    return 0;
}

int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s OUTPUT.bbs OUTPUT.expected.json\n", argv[0]);
        return 2;
    }

    bb_match matches[FIXTURE_RECORDS];
    for (int i = 0; i < FIXTURE_RECORDS; i++) {
        if (fixture_build_match(&fixture_specs[i], i, &matches[i]) != 0) {
            return 1;
        }
    }

    FILE* file = fopen(argv[1], "wb");
    if (file == NULL) {
        perror(argv[1]);
        return 1;
    }
    int failed =
        fwrite("BBS1", 1, 4, file) != 4 ||
        fixture_write_le32(file, 1) != 0 ||
        fixture_write_le32(file, (uint32_t)sizeof(bb_match)) != 0 ||
        fixture_write_le32(file, bbe_state_fingerprint()) != 0;
    for (int i = 0; i < FIXTURE_RECORDS && !failed; i++) {
        const fixture_spec* spec = &fixture_specs[i];
        uint8_t metadata[BBE_STATE_BANK_REC_META] = {0};
        metadata[0] = (uint8_t)spec->source_id;
        metadata[1] = (uint8_t)(spec->source_id >> 8);
        metadata[2] = (uint8_t)(spec->source_id >> 16);
        metadata[3] = (uint8_t)(spec->source_id >> 24);
        metadata[4] = (uint8_t)spec->command;
        metadata[5] = (uint8_t)(spec->command >> 8);
        metadata[6] = (uint8_t)(spec->command >> 16);
        metadata[7] = (uint8_t)(spec->command >> 24);
        metadata[8] = matches[i].half;
        metadata[9] = matches[i].turn[matches[i].active_team];
        failed =
            fwrite(metadata, 1, sizeof metadata, file) != sizeof metadata ||
            fwrite(&matches[i], sizeof matches[i], 1, file) != 1;
    }
    int flush_failed = fflush(file) != 0;
    int close_failed = fclose(file) != 0;
    if (flush_failed || close_failed) failed = 1;
    if (failed) {
        fprintf(stderr, "failed to write deterministic BBS fixture\n");
        return 1;
    }
    return fixture_write_expectations(argv[2]) == 0 ? 0 : 1;
}

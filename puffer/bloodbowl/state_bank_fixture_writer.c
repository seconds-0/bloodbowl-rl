#include "bloodbowl.h"
#include "bb_fixtures.h"

static int fixture_write_le32(FILE* file, uint32_t value) {
    const uint8_t bytes[4] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
    };
    return fwrite(bytes, 1, sizeof bytes, file) == sizeof bytes ? 0 : -1;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s OUTPUT.bbs\n", argv[0]);
        return 2;
    }
    bb_match match;
    fx_match_midturn(&match, BB_HOME, 2);
    fx_lineman(&match, BB_HOME, 0, 8, 7);
    fx_lineman(&match, BB_AWAY, 0, 17, 7);
    bb_rng rng;
    bb_rng_seed(&rng, 0xB4A6u, 3);
    if (fx_run(&match, &rng) != BB_STATUS_DECISION ||
        !bb_state_bank_boundary_valid(&match)) {
        fprintf(stderr, "failed to construct deterministic boundary fixture\n");
        return 1;
    }
    bb_action legal[BB_LEGAL_MAX];
    int n_legal = bb_legal_actions(&match, legal);
    if (n_legal <= 0 || n_legal > BB_LEGAL_MAX) {
        fprintf(stderr, "fixture has no bounded legal-action surface\n");
        return 1;
    }

    FILE* file = fopen(argv[1], "wb");
    if (file == NULL) {
        perror(argv[1]);
        return 1;
    }
    uint8_t metadata[BBE_STATE_BANK_REC_META] = {0};
    metadata[0] = 0x04;
    metadata[1] = 0x03;
    metadata[2] = 0x02;
    metadata[3] = 0x01;
    metadata[4] = 0x0d;
    metadata[5] = 0x0c;
    metadata[6] = 0x0b;
    metadata[7] = 0x0a;
    metadata[8] = match.half;
    metadata[9] = match.turn[match.active_team];
    int failed =
        fwrite("BBS1", 1, 4, file) != 4 ||
        fixture_write_le32(file, 1) != 0 ||
        fixture_write_le32(file, (uint32_t)sizeof match) != 0 ||
        fixture_write_le32(file, bbe_state_fingerprint()) != 0 ||
        fwrite(metadata, 1, sizeof metadata, file) != sizeof metadata ||
        fwrite(&match, sizeof match, 1, file) != 1 ||
        fflush(file) != 0;
    if (fclose(file) != 0) failed = 1;
    if (failed) {
        fprintf(stderr, "failed to write deterministic BBS fixture\n");
        return 1;
    }
    return 0;
}

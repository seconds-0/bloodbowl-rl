// Measure how much of a BBS1 state bank the backplay curriculum can actually
// reach, per the sampler in puffer/bloodbowl/bloodbowl.h.
//
// Why this exists: the backplay rejection sampler tries 256 uniform draws for a
// standing carrier within demo_endzone_maxdist of their endzone and, on
// exhaustion, SILENTLY keeps the last uniform draw. demo_fallbacks is NOT
// incremented on that path (bloodbowl.h:2150 fires only for a record that is not
// a live decision state), so a bank whose near-endzone tier is thin turns the
// stage knob into a no-op while every integrity counter still reads zero. The
// only way to know the ladder is real is to measure the tier before training.
//
// Reads headers only -- no engine objects needed:
//   make backplay-coverage
//   ./build/bank_backplay_coverage validation/states/bank.bbs

#include "bb/bb_match.h"
#include "bb/bb_proc.h"

#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { HEADER_BYTES = 16, META_BYTES = 12, TRIES = 256 };

static uint32_t little_u32(const uint8_t* b) {
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) |
           ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

// The live decision-state test that decides demo_started vs demo_fallbacks.
static int is_live_decision(const bb_match* m) {
    return m->status == BB_STATUS_DECISION && m->stack_top > 0;
}

// Exactly the backplay predicate from bloodbowl.h: standing on-pitch carrier
// holding the ball, within maxdist of THEIR OWN endzone.
static int backplay_hit(const bb_match* m, int maxdist) {
    int c = m->ball.carrier;
    if (m->ball.state != BB_BALL_HELD || c == BB_NO_PLAYER) return 0;
    const bb_player* cp = &m->players[c];
    if (cp->location != BB_LOC_ON_PITCH) return 0;
    if (cp->stance != BB_STANCE_STANDING) return 0;
    int d = cp->x - bb_endzone_x(BB_TEAM_OF(c));
    if (d < 0) d = -d;
    return d <= maxdist;
}

static int carrier_distance(const bb_match* m) {
    int c = m->ball.carrier;
    if (m->ball.state != BB_BALL_HELD || c == BB_NO_PLAYER) return -1;
    const bb_player* cp = &m->players[c];
    if (cp->location != BB_LOC_ON_PITCH) return -1;
    if (cp->stance != BB_STANCE_STANDING) return -1;
    int d = cp->x - bb_endzone_x(BB_TEAM_OF(c));
    return d < 0 ? -d : d;
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <bank.bbs>\n", argv[0]);
        return 2;
    }
    FILE* f = fopen(argv[1], "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", argv[1]); return 2; }

    uint8_t header[HEADER_BYTES];
    if (fread(header, 1, HEADER_BYTES, f) != HEADER_BYTES) {
        fprintf(stderr, "truncated header\n"); return 2;
    }
    if (memcmp(header, "BBS1", 4) != 0) {
        fprintf(stderr, "bad BBS1 magic\n"); return 2;
    }
    uint32_t version = little_u32(header + 4);
    uint32_t match_size = little_u32(header + 8);
    if (version != 1) { fprintf(stderr, "unsupported version %u\n", version); return 2; }
    if (match_size != (uint32_t)sizeof(bb_match)) {
        fprintf(stderr, "bank match_size %u != local sizeof(bb_match) %zu "
                        "(ABI mismatch; rebuild against this bank's engine)\n",
                match_size, sizeof(bb_match));
        return 2;
    }

    const size_t stride = META_BYTES + sizeof(bb_match);
    if (fseek(f, 0, SEEK_END) != 0) { fprintf(stderr, "seek failed\n"); return 2; }
    long end = ftell(f);
    long payload = end - HEADER_BYTES;
    if (payload < 0 || (size_t)payload % stride != 0) {
        fprintf(stderr, "payload %ld is not a whole number of %zu-byte records\n",
                payload, stride);
        return 2;
    }
    long n = payload / (long)stride;
    if (fseek(f, HEADER_BYTES, SEEK_SET) != 0) { fprintf(stderr, "seek failed\n"); return 2; }

    static const int RUNGS[] = {6, 9, 12, 18, 26};
    const int NRUNGS = (int)(sizeof(RUNGS) / sizeof(RUNGS[0]));
    long hits[8] = {0};
    long live = 0, held_standing = 0;
    long dist_hist[BB_PITCH_LEN + 1];
    memset(dist_hist, 0, sizeof(dist_hist));

    uint8_t* meta = (uint8_t*)malloc(META_BYTES);
    bb_match* m = (bb_match*)malloc(sizeof(bb_match));
    if (!meta || !m) { fprintf(stderr, "oom\n"); return 2; }

    for (long i = 0; i < n; i++) {
        if (fread(meta, 1, META_BYTES, f) != META_BYTES) {
            fprintf(stderr, "truncated meta at record %ld\n", i); return 2;
        }
        if (fread(m, 1, sizeof(bb_match), f) != sizeof(bb_match)) {
            fprintf(stderr, "truncated match at record %ld\n", i); return 2;
        }
        if (is_live_decision(m)) live++;
        int d = carrier_distance(m);
        if (d >= 0) {
            held_standing++;
            if (d <= BB_PITCH_LEN) dist_hist[d]++;
        }
        for (int r = 0; r < NRUNGS; r++) {
            if (backplay_hit(m, RUNGS[r])) hits[r]++;
        }
    }
    fclose(f);

    printf("bank                 %s\n", argv[1]);
    printf("records              %ld\n", n);
    printf("live decision states %ld  (%.2f%%)\n", live, 100.0 * (double)live / (double)n);
    printf("standing held carrier%ld  (%.2f%%)\n", held_standing,
           100.0 * (double)held_standing / (double)n);
    printf("pitch length         %d  (endzone distance 0..%d)\n",
           BB_PITCH_LEN, BB_PITCH_LEN - 1);
    printf("\n");
    printf("%-9s %10s %9s  %s\n", "maxdist", "records", "fraction",
           "P(all 256 tries miss) = silent no-op rate");
    for (int r = 0; r < NRUNGS; r++) {
        double p = (double)hits[r] / (double)n;
        double miss = pow(1.0 - p, (double)TRIES);
        printf("%-9d %10ld %8.4f%%  %.6g\n", RUNGS[r], hits[r], 100.0 * p, miss);
    }
    printf("\ncarrier endzone-distance histogram (standing held carriers only)\n");
    long cum = 0;
    for (int d = 0; d <= BB_PITCH_LEN; d++) {
        if (dist_hist[d] == 0) continue;
        cum += dist_hist[d];
        printf("  d=%-3d %8ld   cum %8ld  (%.2f%% of bank)\n",
               d, dist_hist[d], cum, 100.0 * (double)cum / (double)n);
    }
    return 0;
}

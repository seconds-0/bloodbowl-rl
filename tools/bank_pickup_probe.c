// bank_pickup_probe.c — measure pickup-curriculum viability on a demo bank.
// Histograms ball state across the bank and, for loose balls, the Chebyshev
// distance from the loose ball to the nearest STANDING player of the
// team-to-move — the exact predicate bbe_reset_match uses for the pickup
// curriculum (D64). Compile-validates the predicate field access too.
//
//   cc -std=c11 -Iengine/include tools/bank_pickup_probe.c -o /tmp/bpp \
//      && /tmp/bpp validation/states/bank.bbs
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "bb/bb_match.h"

int main(int argc, char** argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s bank.bbs\n", argv[0]); return 2; }
    FILE* f = fopen(argv[1], "rb");
    if (!f) { perror("open"); return 1; }
    uint8_t hdr[16];
    if (fread(hdr, 1, 16, f) != 16 || memcmp(hdr, "BBS1", 4) != 0) {
        fprintf(stderr, "bad magic\n"); return 1; }
    uint32_t ver, msz, fp;
    memcpy(&ver, hdr + 4, 4); memcpy(&msz, hdr + 8, 4); memcpy(&fp, hdr + 12, 4);
    printf("header: version=%u match_size=%u (local sizeof=%zu) engine_fp=0x%08x\n",
           ver, msz, sizeof(bb_match), fp);
    if (msz != sizeof(bb_match)) {
        fprintf(stderr, "WARNING: match_size %u != local sizeof(bb_match) %zu — "
                "bank built by a different engine ABI; distances may be garbage.\n",
                msz, (size_t)sizeof(bb_match));
    }
    size_t stride = 12 + (size_t)msz;
    long ballstate[4] = {0};
    long total = 0, loose = 0;
    long hit[16]; memset(hit, 0, sizeof hit);  // hit[d] = loose with a mover within d
    bb_match m;
    uint8_t meta[12];
    while (fread(meta, 1, 12, f) == 12) {
        if (msz == sizeof(bb_match)) {
            if (fread(&m, sizeof(bb_match), 1, f) != 1) break;
        } else { fseek(f, msz, SEEK_CUR); continue; }
        total++;
        if (m.ball.state < 4) ballstate[m.ball.state]++;
        if (m.ball.state != BB_BALL_ON_GROUND) continue;
        loose++;
        int bx = m.ball.x, by = m.ball.y, at = m.active_team;
        int best = 99;
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (BB_TEAM_OF(s) != at) continue;
            const bb_player* p = &m.players[s];
            if (p->location != BB_LOC_ON_PITCH || p->stance != BB_STANCE_STANDING)
                continue;
            int dx = (int)p->x - bx; if (dx < 0) dx = -dx;
            int dy = (int)p->y - by; if (dy < 0) dy = -dy;
            int d = dx > dy ? dx : dy;
            if (d < best) best = d;
        }
        for (int d = 0; d < 16; d++) if (best <= d) hit[d]++;
    }
    fclose(f);
    printf("\n%ld states  |  ball: off=%ld ground=%ld held=%ld air=%ld\n",
           total, ballstate[0], ballstate[1], ballstate[2], ballstate[3]);
    printf("loose-ball states: %ld (%.1f%% of bank)\n", loose, 100.0*loose/total);
    printf("\nloose ball w/ a STANDING team-to-move player within maxdist:\n");
    for (int d = 2; d <= 12; d += 2)
        printf("  maxdist %2d:  %5ld states  (%.2f%% of bank, %.1f%% of loose)\n",
               d, hit[d], 100.0*hit[d]/total, loose? 100.0*hit[d]/loose : 0.0);
    return 0;
}

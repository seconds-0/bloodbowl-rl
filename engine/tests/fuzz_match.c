// fuzz_match.c — libFuzzer harness over the whole engine (validation layer 4).
//
// Input bytes drive the init mode, the RNG seed and every coach decision:
// byte 0 selects the init path (even = bb_match_init default squads, odd =
// bb_match_init_random procgen — the exact path every training reset uses,
// review Hd2); each decision then consumes one byte as an index into the
// legal-action list. Crashes, ASan/UBSan reports, mask-soundness violations
// (BB_STATUS_ERROR after a legal apply) and non-termination are all bugs.
//
// Build: make fuzz   (clang only; needs -fsanitize=fuzzer)
// Run:   ./build/fuzz/bb_fuzz -max_total_time=1800 engine/tests/corpus/
#include "bb/bb_match.h"
#include "bb/gen_teams.h"
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size);

int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    if (size < 11) return 0;
    uint64_t seed = 0;
    for (int i = 1; i < 9; i++) seed = (seed << 8) | data[i];
    size_t pos = 11;

    static bb_match m; // static: 3KB+ struct, avoid fuzzer stack pressure
    if (data[0] & 1) {
        // Procgen init: 11-14-player squads, advancement skills, pre-game
        // casualties, 2-4 re-rolls — states default squads never reach.
        bb_rng pg;
        bb_rng_seed(&pg, seed ^ 0x9E3779B97F4A7C15ULL,
                    ((uint64_t)data[9] << 8) | data[10]);
        bb_match_init_random(&m, &pg);
    } else {
        int home = data[9] % BB_TEAM_COUNT;
        int away = data[10] % BB_TEAM_COUNT;
        bb_match_init(&m, home, away);
    }
    bb_rng rng;
    bb_rng_seed(&rng, seed, 7);

    bb_status st = bb_advance(&m, &rng);
    int steps = 0;
    while (st == BB_STATUS_DECISION && steps < 100000) {
        static bb_action legal[BB_LEGAL_MAX];
        int n = bb_legal_actions(&m, legal);
        if (n <= 0) abort(); // decision with no legal actions = engine bug
        uint8_t b = pos < size ? data[pos++] : (uint8_t)(steps * 2654435761u >> 24);
        st = bb_apply(&m, legal[b % (uint32_t)n], &rng);
        if (st == BB_STATUS_ERROR) abort(); // legal action must never error
        // Core invariants (mirror test_match.c).
        if (m.ball.state == BB_BALL_HELD) {
            if (m.ball.carrier == BB_NO_PLAYER) abort();
            const bb_player* c = &m.players[m.ball.carrier];
            if (c->location != BB_LOC_ON_PITCH) abort();
            if (!(c->flags & BB_PF_HAS_BALL)) abort();
            if (m.ball.x != c->x || m.ball.y != c->y) abort();
        }
        steps++;
    }
    if (st == BB_STATUS_DECISION) abort(); // non-termination within bound
    return 0;
}

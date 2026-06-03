// fuzz_match.c — libFuzzer harness over the whole engine (validation layer 4).
//
// Input bytes drive both the RNG seed and every coach decision: each decision
// consumes one byte as an index into the legal-action list. Crashes, ASan/UBSan
// reports, mask-soundness violations (BB_STATUS_ERROR after a legal apply) and
// non-termination are all bugs.
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
    if (size < 10) return 0;
    uint64_t seed = 0;
    for (int i = 0; i < 8; i++) seed = (seed << 8) | data[i];
    int home = data[8] % BB_TEAM_COUNT;
    int away = data[9] % BB_TEAM_COUNT;
    size_t pos = 10;

    static bb_match m; // static: 3KB+ struct, avoid fuzzer stack pressure
    bb_match_init(&m, home, away);
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
        steps++;
    }
    if (st == BB_STATUS_DECISION) abort(); // non-termination within bound
    return 0;
}

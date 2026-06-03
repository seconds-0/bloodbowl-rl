// coverage_report.c — rule-coverage report (validation layer 6).
// Plays random matches across every team pairing and reports which skills'
// effects fired. Build: part of `make coverage`.
#include "bb/bb_match.h"
#include "bb/bb_hooks.h"
#include "bb/gen_teams.h"
#include "../engine/tests/bb_fixtures.h"
#include <stdio.h>

int main(void) {
    int games = 0;
    for (int h = 0; h < BB_TEAM_COUNT; h++) {
        for (int rep = 0; rep < 6; rep++) {
            int a = (h * 7 + rep * 11 + 3) % BB_TEAM_COUNT;
            bb_match m;
            bb_match_init(&m, h, a);
            bb_rng rng, pick;
            bb_rng_seed(&rng, 0xC0FFEE + (uint64_t)h * 100 + rep, 1);
            bb_rng_seed(&pick, (uint64_t)h * 31 + rep, 2);
            bb_status st = bb_advance(&m, &rng);
            int steps = 0;
            while (st == BB_STATUS_DECISION && steps < 100000) {
                static bb_action legal[BB_LEGAL_MAX];
                int n = bb_legal_actions(&m, legal);
                if (n <= 0) break;
                st = bb_apply(&m, legal[fx_pick_smart(&m, legal, n, &pick)], &rng);
                steps++;
            }
            games++;
        }
    }
    int exercised = 0, registered = 0;
    printf("=== unexercised skills (of those with registered hooks) ===\n");
    for (int i = 0; i < BB_SKILL_COUNT; i++) {
        bool has_hook = bb_hooks[i].mod || bb_hooks[i].aura ||
                        bb_hooks[i].reroll_kinds || bb_hooks[i].activate_gate ||
                        bb_hooks[i].push_flags || bb_hooks[i].st_mod_blitz ||
                        bb_hooks[i].armour_mod || bb_hooks[i].injury_mod;
        if (!has_hook) continue;
        registered++;
        if (bb_skill_exercised[i]) exercised++;
        else printf("  %s\n", bb_skill_defs[i].id);
    }
    printf("%d games; %d/%d registered-hook skills exercised\n", games, exercised, registered);
    printf("(inline-implemented skills — block/wrestle/frenzy/etc — are not yet instrumented)\n");
    return 0;
}

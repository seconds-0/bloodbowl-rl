// gen_goldens.c — regenerate golden replay traces (validation layer 5).
//
// Plays seeded random matches and records them in the engine replay format.
// Goldens are committed; test_golden.c re-simulates them and fails on any
// behavioral change. Regenerate ONLY deliberately: make goldens
#include "bb/bb_match.h"
#include "bb/bb_replay.h"
#include "bb/gen_teams.h"
#include "../engine/tests/bb_fixtures.h"
#include <stdio.h>

#define N_GOLDENS 8

int main(int argc, char** argv) {
    const char* dir = argc > 1 ? argv[1] : "engine/tests/golden";
    static const int matchups[N_GOLDENS][2] = {
        {BB_TEAM_HUMAN, BB_TEAM_ORC},  {BB_TEAM_DWARF, BB_TEAM_SKAVEN},
        {BB_TEAM_WOOD_ELF, BB_TEAM_LIZARDMEN}, {BB_TEAM_GOBLIN, BB_TEAM_HALFLING},
        {BB_TEAM_AMAZON, BB_TEAM_NORSE}, {BB_TEAM_DARK_ELF, BB_TEAM_HIGH_ELF},
        {BB_TEAM_KHORNE, BB_TEAM_NURGLE}, {BB_TEAM_OGRE, BB_TEAM_SNOTLING},
    };
    for (int g = 0; g < N_GOLDENS; g++) {
        char path[512];
        snprintf(path, sizeof path, "%s/golden_%02d.jsonl", dir, g);
        bb_replay_writer w;
        if (bb_replay_open(&w, path) != 0) {
            fprintf(stderr, "cannot open %s\n", path);
            return 1;
        }
        uint64_t seed = 0xB10DB071ull + (uint64_t)g * 7919;
        bb_replay_init_record(&w, matchups[g][0], matchups[g][1], seed);

        bb_match m;
        bb_match_init(&m, matchups[g][0], matchups[g][1]);
        bb_rng rng, pick;
        bb_rng_seed(&rng, seed, 1);
        bb_rng_seed(&pick, seed ^ 0x5EED, 2);
        bb_rng_set_sink(&rng, bb_replay_dice_sink, &w);

        bb_status st = bb_advance(&m, &rng);
        int steps = 0;
        while (st == BB_STATUS_DECISION && steps < 200000) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            if (n <= 0) break;
            bb_action a = legal[fx_pick_smart(&m, legal, n, &pick)];
            bb_replay_action(&w, a);
            st = bb_apply(&m, a, &rng);
            steps++;
        }
        bb_replay_end_record(&w, m.score[0], m.score[1]);
        bb_replay_close(&w);
        if (st != BB_STATUS_MATCH_OVER) {
            fprintf(stderr, "golden %d did not complete (status %d)\n", g, st);
            return 1;
        }
        printf("golden_%02d.jsonl: %s vs %s, %d decisions, %d-%d\n", g,
               bb_team_defs[matchups[g][0]].display, bb_team_defs[matchups[g][1]].display,
               steps, m.score[0], m.score[1]);
    }
    return 0;
}

// test_golden.c — golden-trace regression (validation layer 5).
//
// Re-simulates every committed replay in engine/tests/golden/: the recorded
// dice become a script, the recorded actions are applied at each decision.
// Any rules-behavior change breaks alignment (illegal action, script
// misalignment, score mismatch) and fails here. Regenerate deliberately with
// `make goldens` when a rules change is intended.
//
// This is the same injection mechanism the FUMBBL differential harness uses.
#include "bb/bb_match.h"
#include "bb/bb_replay.h"
#include "bb_test.h"
#include <dirent.h>
#include <stdlib.h>
#include <string.h>

#define MAX_DICE 65536
#define MAX_ACTS 65536

static int resim_golden(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) return -1;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char* buf = malloc((size_t)len + 1);
    if (fread(buf, 1, (size_t)len, f) != (size_t)len) {
        fclose(f);
        free(buf);
        return -2;
    }
    fclose(f);

    static uint8_t dice[MAX_DICE];
    static uint32_t acts[MAX_ACTS];
    int n_dice = 0, n_acts = 0;
    bb_record rec;
    bb_replay_reader r;
    bb_replay_reader_init(&r, buf, (size_t)len);

    int home = -1, away = -1, end_home = -1, end_away = -1;
    while (bb_replay_next(&r, &rec)) {
        switch (rec.type) {
            case BB_REC_INIT:
                home = rec.home_team_id;
                away = rec.away_team_id;
                break;
            case BB_REC_DICE:
                if (n_dice < MAX_DICE) dice[n_dice++] = (uint8_t)rec.value;
                break;
            case BB_REC_ACTION:
                if (n_acts < MAX_ACTS) acts[n_acts++] = bb_action_pack(rec.action);
                break;
            default:
                break;
        }
    }
    if (rec.type == BB_REC_PARSE_ERROR) {
        free(buf);
        return -3;
    }
    // Reread for the end record values (reader is single-pass; rescan).
    bb_replay_reader_init(&r, buf, (size_t)len);
    while (bb_replay_next(&r, &rec)) {
        if (rec.type == BB_REC_END) {
            end_home = rec.home_score;
            end_away = rec.away_score;
        }
    }
    free(buf);
    if (home < 0 || end_home < 0) return -4;

    bb_match m;
    bb_match_init(&m, home, away);
    bb_rng rng;
    bb_rng_script(&rng, dice, n_dice);

    bb_status st = bb_advance(&m, &rng);
    int ai = 0;
    while (st == BB_STATUS_DECISION && ai < n_acts) {
        st = bb_apply(&m, bb_action_unpack(acts[ai++]), &rng);
        if (bb_rng_error(&rng)) return -5; // dice misalignment
        if (st == BB_STATUS_ERROR) return -6; // recorded action now illegal
    }
    if (st != BB_STATUS_MATCH_OVER) return -7;
    if (ai != n_acts) return -8; // leftover recorded actions
    if (m.score[0] != end_home || m.score[1] != end_away) return -9;
    return 0;
}

BB_TEST(golden_traces_resimulate_exactly) {
    DIR* d = opendir("engine/tests/golden");
    if (!d) {
        printf("  (no goldens directory — skipping; run `make goldens`)\n");
        return;
    }
    struct dirent* e;
    int found = 0;
    while ((e = readdir(d))) {
        if (!strstr(e->d_name, ".jsonl")) continue;
        char path[512];
        snprintf(path, sizeof path, "engine/tests/golden/%s", e->d_name);
        int rc = resim_golden(path);
        if (rc != 0) printf("  golden %s rc=%d\n", e->d_name, rc);
        BB_CHECK_EQ(rc, 0);
        found++;
    }
    closedir(d);
    if (found == 0) printf("  (golden directory empty — run `make goldens`)\n");
}

// dist_dump.c — empirical dice-path frequency tables (validation layer 2).
//
// Generates outcome distributions DIRECTLY from the engine's own dice paths
// via isolated micro-simulations (scripted positions from
// engine/tests/bb_fixtures.h, PRNG dice through bb_rng), plus a small batch
// of full random matches (fx_pick_smart) as a whole-engine d6 sanity stream.
// Prints one JSON object of raw COUNTS to stdout; validation/conformance.py
// chi-squares them against exact probabilities.
//
// Micro-scenarios (every die observed through a bb_rng sink; outcomes
// classified from the resulting match STATE, with a sink-vs-state
// cross-check counted in xcheck_mismatch — conformance fails if nonzero):
//
//   block_1d        equal-ST lineman block: 1 block die, face recorded
//   block_2d        ST4 attacker: 2 block dice, joint face pair recorded
//   armour_av<N>    BB_PROC_ARMOUR pushed directly on a prone AV-N victim,
//                   no modifiers: broken <=> 2d6 >= N
//   injury_normal   BB_PROC_INJURY on a prone lineman: stun 2-7 / KO 8-9 /
//                   casualty 10-12 (apothecary stock zeroed)
//   injury_stunty   same victim with BB_SK_STUNTY: stun 2-6 / KO 7-8 /
//                   badly-hurt 9 / casualty 10-12
//   casualty        BB_PROC_CASUALTY directly: D16 -> band via
//                   bb_casualty_table (1-8 BH, 9-10 SH, 11-12 SI, 13-14 LI,
//                   15-16 DEAD)
//   dodge_ag3_tz0   real MOVE action leaving one TZ, 0 TZ at destination:
//                   d6 vs 3+ (nat 1 fails, nat 6 passes)
//   dodge_ag3_tz1   same with 1 TZ at the destination square: d6 vs 4+
//   rush_2plus      real MOVE second step beyond MA=1: rush d6 vs 2+
//
// NOT covered here (honest gaps, see validation/README.md): pass/catch/
// interception paths, kickoff scatter geometry, reroll-modified compound
// paths (dodge+team-reroll, blocks with Block/Brawler/MB/Claw stacks).
//
// Build (links engine objects directly — constructor-registered skill hooks
// would be dropped from a static archive, same as the Makefile 'coverage'
// target):
//   cc -std=c11 -O2 -Iengine/include tools/dist_dump.c build/main/obj/*.o \
//      -o build/dist_dump
// Run:  ./build/dist_dump [base_trials=60000] [seed=1234] [matches=20]
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/gen_teams.h"
#include "bb/gen_tables.h"
#include "../engine/tests/bb_fixtures.h"
#include <stdio.h>
#include <stdlib.h>

// --- dice sink ----------------------------------------------------------------
#define SINK_MAX 64

typedef struct {
    int n;
    int sides[SINK_MAX];
    int vals[SINK_MAX];
} sink_buf;

static void sink_record(void* user, int sides, int value) {
    sink_buf* b = (sink_buf*)user;
    if (b->n < SINK_MAX) {
        b->sides[b->n] = sides;
        b->vals[b->n] = value;
    }
    b->n++;
}

static int sink_count_sides(const sink_buf* b, int sides) {
    int c = 0, n = b->n < SINK_MAX ? b->n : SINK_MAX;
    for (int i = 0; i < n; i++) c += b->sides[i] == sides;
    return c;
}

// histogram sink for full random matches
typedef struct {
    long by_sides[20];   // index = sides (3,6,8,16 used)
    long d6_faces[7];
} hist_sink;

static void sink_hist(void* user, int sides, int value) {
    hist_sink* h = (hist_sink*)user;
    if (sides >= 0 && sides < 20) h->by_sides[sides]++;
    if (sides == 6 && value >= 1 && value <= 6) h->d6_faces[value]++;
}

// --- shared fixture helpers ----------------------------------------------------

static bb_status apply4(bb_match* m, bb_rng* rng, int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return bb_apply(m, a, rng);
}

// Attacker (team 0) at (10,5) vs victim (team 1) at (11,5); far-away spares
// keep both team turns alive. att_st sets the attacker's strength.
static void block_fixture(bb_match* m, int att_st) {
    fx_match_midturn(m, BB_HOME, 0);
    fx_player(m, 0, 0, 10, 5, 6, att_st, 3, 4, 9);
    fx_lineman(m, 1, 0, 11, 5);
    fx_lineman(m, 0, 1, 2, 2);
    fx_lineman(m, 1, 1, 23, 12);
}

// Drive to the choose-die decision of a block; returns # block dice rolled
// (sink), or -1 on unexpected status.
static int run_block_to_pool(bb_match* m, bb_rng* rng) {
    if (fx_run(m, rng) != BB_STATUS_DECISION) return -1;
    if (apply4(m, rng, BB_A_ACTIVATE, 0, 0, 0) != BB_STATUS_DECISION) return -1;
    if (apply4(m, rng, BB_A_DECLARE, BB_ACT_BLOCK, 0, 0) != BB_STATUS_DECISION) return -1;
    if (apply4(m, rng, BB_A_BLOCK_TARGET, 0, 11, 5) != BB_STATUS_DECISION) return -1;
    return 0;
}

// --- scenarios -----------------------------------------------------------------

typedef struct {
    long n;             // completed trials
    long errors;        // engine status errors / unexpected decision flow
    long xcheck;        // sink-derived expectation disagreed with state
} trial_stats;

static void scen_block_1d(long n, uint64_t seed, long faces[7], trial_stats* ts) {
    bb_rng rng;
    bb_rng_seed(&rng, seed, 101);
    sink_buf buf;
    bb_rng_set_sink(&rng, sink_record, &buf);
    for (long t = 0; t < n; t++) {
        bb_match m;
        block_fixture(&m, 3);
        buf.n = 0;
        if (run_block_to_pool(&m, &rng) != 0 || buf.n != 1 || buf.sides[0] != 6) {
            ts->errors++;
            continue;
        }
        faces[buf.vals[0]]++;
        ts->n++;
    }
}

static void scen_block_2d(long n, uint64_t seed, long pairs[7][7], trial_stats* ts) {
    bb_rng rng;
    bb_rng_seed(&rng, seed, 102);
    sink_buf buf;
    bb_rng_set_sink(&rng, sink_record, &buf);
    for (long t = 0; t < n; t++) {
        bb_match m;
        block_fixture(&m, 4); // ST4 vs ST3 -> 2 dice, attacker chooses
        buf.n = 0;
        if (run_block_to_pool(&m, &rng) != 0 || buf.n != 2) {
            ts->errors++;
            continue;
        }
        pairs[buf.vals[0]][buf.vals[1]]++;
        ts->n++;
    }
}

// Victim prone on pitch; push `proc` directly; advance to the next decision.
// Returns the victim slot, or -1 on bad status.
static int run_direct_proc(bb_match* m, bb_rng* rng, int proc, int av, int stunty) {
    fx_match_midturn(m, BB_HOME, 0);
    fx_lineman(m, 0, 1, 2, 2);                       // active-team decision anchor
    int v = fx_player(m, 1, 0, 20, 10, 6, 3, 3, 4, av);
    m->players[v].stance = BB_STANCE_PRONE;
    if (stunty) fx_give_skill(m, v, BB_SK_STUNTY);
    bb_push(m, (bb_proc)proc, v, 0, 0, 0);
    if (fx_run(m, rng) != BB_STATUS_DECISION) return -1;
    return v;
}

static void scen_armour(long n, uint64_t seed, int av, long* broken, long* held,
                        trial_stats* ts) {
    bb_rng rng;
    bb_rng_seed(&rng, seed, 200 + (uint64_t)av);
    sink_buf buf;
    bb_rng_set_sink(&rng, sink_record, &buf);
    for (long t = 0; t < n; t++) {
        bb_match m;
        buf.n = 0;
        int v = run_direct_proc(&m, &rng, BB_PROC_ARMOUR, av, 0);
        if (v < 0 || buf.n < 2) {
            ts->errors++;
            continue;
        }
        bool state_broken = !(m.players[v].location == BB_LOC_ON_PITCH &&
                              m.players[v].stance == BB_STANCE_PRONE);
        bool dice_broken = buf.vals[0] + buf.vals[1] >= av;
        if (state_broken != dice_broken) ts->xcheck++;
        if (state_broken) (*broken)++; else (*held)++;
        ts->n++;
    }
}

// bands: [0]=stun [1]=ko [2]=badly-hurt(stunty 9 band) [3]=casualty-roll
static void scen_injury(long n, uint64_t seed, int stunty, long bands[4],
                        long sum_hist[13], long cas16[17], trial_stats* ts) {
    bb_rng rng;
    bb_rng_seed(&rng, seed, stunty ? 301 : 300);
    sink_buf buf;
    bb_rng_set_sink(&rng, sink_record, &buf);
    for (long t = 0; t < n; t++) {
        bb_match m;
        buf.n = 0;
        int v = run_direct_proc(&m, &rng, BB_PROC_INJURY, 9, stunty);
        if (v < 0 || buf.n < 2) {
            ts->errors++;
            continue;
        }
        int total = buf.vals[0] + buf.vals[1];
        sum_hist[total]++;
        int d16s = sink_count_sides(&buf, 16);
        int band;
        if (fx_stunned(&m, v) && m.players[v].location == BB_LOC_ON_PITCH) {
            band = 0;
        } else if (m.players[v].location == BB_LOC_KO) {
            band = 1;
        } else if (m.players[v].location == BB_LOC_CAS) {
            band = d16s > 0 ? 3 : 2;   // casualty roll vs straight stunty BH
        } else {
            ts->errors++;
            continue;
        }
        bands[band]++;
        if (d16s > 0) {
            // record the casualty die (the only d16 in the stream)
            int nrec = buf.n < SINK_MAX ? buf.n : SINK_MAX;
            for (int i = 0; i < nrec; i++) {
                if (buf.sides[i] == 16) cas16[buf.vals[i]]++;
            }
        }
        // cross-check band against the raw 2d6 sum
        int expect;
        if (stunty) expect = total <= 6 ? 0 : (total <= 8 ? 1 : (total == 9 ? 2 : 3));
        else        expect = total <= 7 ? 0 : (total <= 9 ? 1 : 3);
        if (expect != band) ts->xcheck++;
        ts->n++;
    }
}

// bands by bb_cas outcome enum (0..4)
static void scen_casualty(long n, uint64_t seed, long bands[5], long d16_hist[17],
                          trial_stats* ts) {
    bb_rng rng;
    bb_rng_seed(&rng, seed, 400);
    sink_buf buf;
    bb_rng_set_sink(&rng, sink_record, &buf);
    for (long t = 0; t < n; t++) {
        bb_match m;
        buf.n = 0;
        int v = run_direct_proc(&m, &rng, BB_PROC_CASUALTY, 9, 0);
        if (v < 0 || sink_count_sides(&buf, 16) != 1 ||
            m.players[v].location != BB_LOC_CAS) {
            ts->errors++;
            continue;
        }
        int roll = 0;
        int nrec = buf.n < SINK_MAX ? buf.n : SINK_MAX;
        for (int i = 0; i < nrec; i++) {
            if (buf.sides[i] == 16) roll = buf.vals[i];
        }
        d16_hist[roll]++;
        int band = m.players[v].spp_game;   // = bb_casualty_table[roll]
        if (band < 0 || band > 4 || band != bb_casualty_table[roll]) {
            ts->xcheck++;
            continue;
        }
        bands[band]++;
        ts->n++;
    }
}

// Real MOVE activation: mover at (10,5) marked by an opponent at (11,5),
// steps to (9,5). tz_dest=1 adds an opponent at (8,5) marking only the
// destination. Mover MA=ma (ma>=1: first step is a plain dodge; rush variant
// uses ma=1 and a second step).
static void scen_dodge(long n, uint64_t seed, int tz_dest, long* pass, long* fail,
                       trial_stats* ts) {
    bb_rng rng;
    bb_rng_seed(&rng, seed, 500 + (uint64_t)tz_dest);
    sink_buf buf;
    bb_rng_set_sink(&rng, sink_record, &buf);
    for (long t = 0; t < n; t++) {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mv = fx_lineman(&m, 0, 0, 10, 5);
        fx_lineman(&m, 1, 0, 11, 5);                  // marks the origin
        if (tz_dest) fx_lineman(&m, 1, 2, 8, 5);      // marks (9,5) only
        fx_lineman(&m, 0, 1, 2, 2);
        fx_lineman(&m, 1, 1, 23, 12);
        buf.n = 0;
        if (fx_run(&m, &rng) != BB_STATUS_DECISION ||
            apply4(&m, &rng, BB_A_ACTIVATE, mv, 0, 0) != BB_STATUS_DECISION ||
            apply4(&m, &rng, BB_A_DECLARE, BB_ACT_MOVE, 0, 0) != BB_STATUS_DECISION ||
            apply4(&m, &rng, BB_A_STEP, 0, 9, 5) != BB_STATUS_DECISION ||
            buf.n < 1 || buf.sides[0] != 6) {
            ts->errors++;
            continue;
        }
        // NB: a failed dodge can knock the mover off the pitch (KO/CAS), and
        // bb_remove_from_pitch resets stance to STANDING — check location too.
        bool ok = m.players[mv].stance == BB_STANCE_STANDING &&
                  m.players[mv].location == BB_LOC_ON_PITCH;
        int die = buf.vals[0], target = 3 + tz_dest;
        bool die_ok = die != 1 && (die == 6 || die >= target);
        if (ok != die_ok) ts->xcheck++;
        if (ok) (*pass)++; else (*fail)++;
        ts->n++;
    }
}

// Rush (2+): MA=1 mover, no tackle zones anywhere; second step exceeds MA.
static void scen_rush(long n, uint64_t seed, long* pass, long* fail, trial_stats* ts) {
    bb_rng rng;
    bb_rng_seed(&rng, seed, 600);
    sink_buf buf;
    bb_rng_set_sink(&rng, sink_record, &buf);
    for (long t = 0; t < n; t++) {
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mv = fx_player(&m, 0, 0, 10, 5, 1, 3, 3, 4, 9); // MA 1
        fx_lineman(&m, 0, 1, 2, 2);
        fx_lineman(&m, 1, 1, 23, 12);
        buf.n = 0;
        if (fx_run(&m, &rng) != BB_STATUS_DECISION ||
            apply4(&m, &rng, BB_A_ACTIVATE, mv, 0, 0) != BB_STATUS_DECISION ||
            apply4(&m, &rng, BB_A_DECLARE, BB_ACT_MOVE, 0, 0) != BB_STATUS_DECISION ||
            apply4(&m, &rng, BB_A_STEP, 0, 9, 5) != BB_STATUS_DECISION ||
            buf.n != 0 ||                                  // free step, no dice
            apply4(&m, &rng, BB_A_STEP, 0, 8, 5) != BB_STATUS_DECISION ||
            buf.n < 1 || buf.sides[0] != 6) {
            ts->errors++;
            continue;
        }
        bool ok = m.players[mv].stance == BB_STANCE_STANDING &&
                  m.players[mv].location == BB_LOC_ON_PITCH;
        int die = buf.vals[0];
        bool die_ok = die != 1 && (die == 6 || die >= 2);
        if (ok != die_ok) ts->xcheck++;
        if (ok) (*pass)++; else (*fail)++;
        ts->n++;
    }
}

// --- full random matches (whole-engine dice stream sanity) ----------------------

static void random_matches(int games, uint64_t seed, hist_sink* h,
                           long* completed, long* decisions) {
    for (int g = 0; g < games; g++) {
        bb_match m;
        bb_match_init(&m, g % BB_TEAM_COUNT, (g * 7 + 3) % BB_TEAM_COUNT);
        bb_rng rng, pick;
        bb_rng_seed(&rng, seed + (uint64_t)g, 1);
        bb_rng_seed(&pick, seed * 31 + (uint64_t)g, 2);
        bb_rng_set_sink(&rng, sink_hist, h);
        bb_status st = bb_advance(&m, &rng);
        long steps = 0;
        while (st == BB_STATUS_DECISION && steps < 100000) {
            static bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            if (n <= 0) break;
            st = bb_apply(&m, legal[fx_pick_smart(&m, legal, n, &pick)], &rng);
            steps++;
        }
        *decisions += steps;
        if (st == BB_STATUS_MATCH_OVER) (*completed)++;
    }
}

// --- JSON output -----------------------------------------------------------------

static void emit_stats(const char* indent, const trial_stats* ts) {
    printf("%s\"trials\": %ld, \"errors\": %ld, \"xcheck_mismatch\": %ld",
           indent, ts->n, ts->errors, ts->xcheck);
}

int main(int argc, char** argv) {
    long base = argc > 1 ? atol(argv[1]) : 60000;
    uint64_t seed = argc > 2 ? (uint64_t)atoll(argv[2]) : 1234;
    int games = argc > 3 ? atoi(argv[3]) : 20;
    if (base < 1) base = 1;

    printf("{\n");
    printf("  \"base_trials\": %ld, \"seed\": %llu, \"matches\": %d,\n",
           base, (unsigned long long)seed, games);

    // block 1d
    {
        long faces[7] = {0};
        trial_stats ts = {0};
        scen_block_1d(base, seed, faces, &ts);
        printf("  \"block_1d\": {");
        emit_stats("", &ts);
        printf(", \"faces\": [%ld, %ld, %ld, %ld, %ld, %ld]},\n",
               faces[1], faces[2], faces[3], faces[4], faces[5], faces[6]);
    }
    // block 2d (joint face pairs, row-major die0 x die1)
    {
        long pairs[7][7] = {{0}};
        trial_stats ts = {0};
        scen_block_2d(base, seed, pairs, &ts);
        printf("  \"block_2d\": {");
        emit_stats("", &ts);
        printf(", \"pairs\": [");
        for (int i = 1; i <= 6; i++) {
            for (int j = 1; j <= 6; j++) {
                printf("%ld%s", pairs[i][j], (i == 6 && j == 6) ? "" : ", ");
            }
        }
        printf("]},\n");
    }
    // armour by AV
    printf("  \"armour\": {\n");
    for (int av = 7; av <= 11; av++) {
        long broken = 0, held = 0;
        trial_stats ts = {0};
        scen_armour(base / 2, seed, av, &broken, &held, &ts);
        printf("    \"av%d\": {", av);
        emit_stats("", &ts);
        printf(", \"broken\": %ld, \"held\": %ld}%s\n", broken, held,
               av == 11 ? "" : ",");
    }
    printf("  },\n");
    // injury normal + stunty
    long cas16_pool[17] = {0};   // d16s observed inside injury scenarios
    for (int stunty = 0; stunty <= 1; stunty++) {
        long bands[4] = {0}, sum_hist[13] = {0};
        trial_stats ts = {0};
        scen_injury(stunty ? base * 3 / 2 : base, seed, stunty, bands, sum_hist,
                    cas16_pool, &ts);
        printf("  \"injury_%s\": {", stunty ? "stunty" : "normal");
        emit_stats("", &ts);
        printf(", \"stun\": %ld, \"ko\": %ld, \"bh\": %ld, \"cas\": %ld,\n",
               bands[0], bands[1], bands[2], bands[3]);
        printf("    \"sum_2d6\": [");
        for (int s = 2; s <= 12; s++) printf("%ld%s", sum_hist[s], s == 12 ? "" : ", ");
        printf("]},\n");
    }
    // dedicated casualty scenario
    {
        long bands[5] = {0}, d16[17] = {0};
        trial_stats ts = {0};
        scen_casualty(base, seed, bands, d16, &ts);
        printf("  \"casualty\": {");
        emit_stats("", &ts);
        printf(",\n    \"badly_hurt\": %ld, \"seriously_hurt\": %ld, "
               "\"serious_injury\": %ld, \"lasting_injury\": %ld, \"dead\": %ld,\n",
               bands[0], bands[1], bands[2], bands[3], bands[4]);
        printf("    \"d16\": [");
        for (int r = 1; r <= 16; r++) printf("%ld%s", d16[r], r == 16 ? "" : ", ");
        printf("]},\n");
    }
    // dodge 0/1 TZ + rush
    for (int tz = 0; tz <= 1; tz++) {
        long pass = 0, fail = 0;
        trial_stats ts = {0};
        scen_dodge(base / 2, seed, tz, &pass, &fail, &ts);
        printf("  \"dodge_ag3_tz%d\": {", tz);
        emit_stats("", &ts);
        printf(", \"pass\": %ld, \"fail\": %ld},\n", pass, fail);
    }
    {
        long pass = 0, fail = 0;
        trial_stats ts = {0};
        scen_rush(base / 2, seed, &pass, &fail, &ts);
        printf("  \"rush_2plus\": {");
        emit_stats("", &ts);
        printf(", \"pass\": %ld, \"fail\": %ld},\n", pass, fail);
    }
    // full random matches
    {
        hist_sink h = {{0}, {0}};
        long completed = 0, decisions = 0;
        random_matches(games, seed, &h, &completed, &decisions);
        printf("  \"random_matches\": {\"games\": %d, \"completed\": %ld, "
               "\"decisions\": %ld,\n", games, completed, decisions);
        printf("    \"dice_by_sides\": {\"d3\": %ld, \"d6\": %ld, \"d8\": %ld, "
               "\"d16\": %ld},\n", h.by_sides[3], h.by_sides[6], h.by_sides[8],
               h.by_sides[16]);
        printf("    \"d6_faces\": [%ld, %ld, %ld, %ld, %ld, %ld]}\n",
               h.d6_faces[1], h.d6_faces[2], h.d6_faces[3], h.d6_faces[4],
               h.d6_faces[5], h.d6_faces[6]);
    }
    printf("}\n");
    return 0;
}

// End-to-end engine tests: full random-agent matches must complete without
// errors, deterministically, with invariants holding at every decision point.
#include "bb/bb_match.h"
#include "bb/bb_hooks.h"
#include "bb/gen_teams.h"
#include "bb_fixtures.h"
#include "bb_test.h"
#include <string.h>

// Setup-aware action picker: random play cannot stumble into a legal
// formation (exactly 11 placed, 3+ on LoS, <=2 per wide zone), so during the
// setup phase the agent (a) takes SETUP_DONE the moment it is legal, and
// (b) places reserves on the line of scrimmage first, then centre-field
// squares. Everything else is uniform random — exactly how an RL policy would
// face the env.
static int pick_action(const bb_match* m, bb_action* legal, int n, bb_rng* pick) {
    for (int i = 0; i < n; i++) {
        if (legal[i].type == BB_A_SETUP_DONE) return i;
    }
    bool in_setup = n > 0 && (legal[0].type == BB_A_SETUP_PLACE || legal[0].type == BB_A_SETUP_REMOVE);
    if (in_setup) {
        // Prefer: place a RESERVES player onto the LoS centre; then any centre
        // (non-wide-zone) square in their half.
        int best = -1;
        for (int i = 0; i < n; i++) {
            if (legal[i].type != BB_A_SETUP_PLACE) continue;
            if (m->players[legal[i].arg].location != BB_LOC_RESERVES) continue;
            bool los = (legal[i].x == 12 || legal[i].x == 13) && legal[i].y >= 4 && legal[i].y <= 10;
            bool centre = legal[i].y >= 4 && legal[i].y <= 10;
            if (los) return i;
            if (centre && best < 0) best = i;
        }
        if (best >= 0) return best;
    }
    return (int)(bb_rng_next(pick) % (uint32_t)n);
}

// Play a full match with both coaches picking uniformly random legal actions.
// Returns the final status; asserts engine invariants at every decision.
static bb_status play_random_match(uint64_t seed, bb_match* out, int* decisions) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    bb_rng rng, pick;
    bb_rng_seed(&rng, seed, 1);
    bb_rng_seed(&pick, seed ^ 0xABCDEF, 2);

    bb_status st = bb_advance(&m, &rng);
    int n_decisions = 0;
    while (st == BB_STATUS_DECISION && n_decisions < 200000) {
        bb_action legal[BB_LEGAL_MAX];
        int n = bb_legal_actions(&m, legal);
        BB_CHECK(n > 0);
        if (n <= 0) break;

        // Invariants at every decision point:
        // ball carrier consistency
        if (m.ball.state == BB_BALL_HELD) {
            BB_CHECK(m.ball.carrier != BB_NO_PLAYER);
            const bb_player* c = &m.players[m.ball.carrier];
            BB_CHECK(c->location == BB_LOC_ON_PITCH);
            BB_CHECK(c->flags & BB_PF_HAS_BALL);
            BB_CHECK_EQ(m.ball.x, c->x);
            BB_CHECK_EQ(m.ball.y, c->y);
        }
        // grid <-> player position consistency
        int on_grid = 0;
        for (int x = 0; x < BB_PITCH_LEN; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                int s = m.grid[x][y] ? m.grid[x][y] - 1 : -1;
                if (s >= 0) {
                    on_grid++;
                    BB_CHECK_EQ(m.players[s].location, BB_LOC_ON_PITCH);
                    BB_CHECK_EQ(m.players[s].x, x);
                    BB_CHECK_EQ(m.players[s].y, y);
                }
            }
        }
        int on_pitch = 0;
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (m.players[s].location == BB_LOC_ON_PITCH) on_pitch++;
        }
        BB_CHECK_EQ(on_grid, on_pitch);

        int i = pick_action(&m, legal, n, &pick);
        st = bb_apply(&m, legal[i], &rng);
        n_decisions++;
    }
    if (out) *out = m;
    if (decisions) *decisions = n_decisions;
    return st;
}

BB_TEST(match_random_game_completes) {
    bb_match m;
    int decisions = 0;
    bb_status st = play_random_match(1234, &m, &decisions);
    BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
    BB_CHECK(decisions > 50);
    BB_CHECK(m.turn[0] >= 8);
    BB_CHECK(m.turn[1] >= 8);
    BB_CHECK_EQ(m.half, 2);
}

BB_TEST(match_many_seeds_complete) {
    for (uint64_t seed = 1; seed <= 25; seed++) {
        bb_status st = play_random_match(seed * 7919, 0, 0);
        BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
        if (st != BB_STATUS_MATCH_OVER) {
            printf("  seed %llu failed\n", (unsigned long long)seed);
            break;
        }
    }
}

BB_TEST(match_deterministic_replay) {
    bb_match m1, m2;
    int d1, d2;
    bb_status s1 = play_random_match(42, &m1, &d1);
    bb_status s2 = play_random_match(42, &m2, &d2);
    BB_CHECK_EQ(s1, s2);
    BB_CHECK_EQ(d1, d2);
    BB_CHECK_EQ(m1.score[0], m2.score[0]);
    BB_CHECK_EQ(m1.score[1], m2.score[1]);
    BB_CHECK_EQ(memcmp(&m1, &m2, sizeof(bb_match)), 0);
}

BB_TEST(match_init_well_formed) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    int avail[2] = {0, 0};
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        if (m.players[s].location == BB_LOC_RESERVES) avail[BB_TEAM_OF(s)]++;
    }
    BB_CHECK(avail[0] >= 11);
    BB_CHECK(avail[1] >= 11);
}

// The RL observation has exactly 12 skill-id slots per player
// (BBE_SKILL_SLOTS); procgen advancement must never exceed that or the env
// silently drops skills from the obs (Codex review HIGH, 2026-06-03).
BB_TEST(match_procgen_skill_cap) {
    for (uint64_t seed = 1; seed <= 200; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 977, 9);
        bb_match_init_random(&m, &pg);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (m.players[s].location == BB_LOC_ABSENT) continue;
            int n = 0;
            for (int sk = bb_next_skill(&m.players[s].skills, 0); sk >= 0;
                 sk = bb_next_skill(&m.players[s].skills, sk + 1)) {
                n++;
            }
            BB_CHECK(n <= 12);
            if (n > 12) return;
        }
    }
}

BB_TEST(match_procgen_games_complete) {
    for (uint64_t seed = 1; seed <= 12; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 31337, 9);
        bb_match_init_random(&m, &pg);
        bb_rng rng, pick;
        bb_rng_seed(&rng, seed, 1);
        bb_rng_seed(&pick, seed ^ 0xFACE, 2);
        bb_status st = bb_advance(&m, &rng);
        int steps = 0;
        while (st == BB_STATUS_DECISION && steps < 200000) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            BB_CHECK(n > 0);
            if (n <= 0) break;
            st = bb_apply(&m, legal[fx_pick_smart(&m, legal, n, &pick)], &rng);
            steps++;
        }
        BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
        if (st != BB_STATUS_MATCH_OVER) {
            printf("  procgen seed %llu failed (teams %d vs %d)\n",
                   (unsigned long long)seed, m.team_id[0], m.team_id[1]);
            break;
        }
    }
}

// bb_fixtures self-test (review T1): fx_player's memset left the fresh
// player looking ON_PITCH at (0,0), so bb_place's stale-square cleanup wiped
// grid[0][0] on every fixture placement — silently corrupting any test that
// stations a player at the origin.
BB_TEST(fixtures_player_at_origin_survives_later_placements) {
    bb_match m;
    fx_match_midturn(&m, 0, 0);
    int a = fx_lineman(&m, 0, 0, 0, 0);
    int b = fx_lineman(&m, 0, 1, 5, 5);
    int c = fx_lineman(&m, 1, 0, 20, 10);
    BB_CHECK_EQ(bb_slot_at(&m, 0, 0), a);
    BB_CHECK_EQ(bb_slot_at(&m, 5, 5), b);
    BB_CHECK_EQ(bb_slot_at(&m, 20, 10), c);
    BB_CHECK_EQ(m.players[a].location, BB_LOC_ON_PITCH);
}

// bb_match_init indexes bb_team_defs[] with its team ids; out-of-range ids
// (file-derived, e.g. replay INIT records) must be rejected, not looked up
// out of bounds (review Hd1).
BB_TEST(match_init_rejects_out_of_range_team_ids) {
    bb_match m;
    bb_match_init(&m, -1, BB_TEAM_ORC);
    BB_CHECK_EQ(m.status, BB_STATUS_ERROR);
    BB_CHECK_EQ(bb_advance(&m, 0), BB_STATUS_ERROR); // stays in ERROR
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_COUNT);
    BB_CHECK_EQ(m.status, BB_STATUS_ERROR);
    bb_match_init(&m, 0x7FFFFFFF, 0);
    BB_CHECK_EQ(m.status, BB_STATUS_ERROR);
    // Boundary ids are valid.
    bb_match_init(&m, 0, BB_TEAM_COUNT - 1);
    BB_CHECK_EQ(m.status, BB_STATUS_RUNNING);
}

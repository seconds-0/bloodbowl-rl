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

// bb_apply_trusted is the RL binding's fast path (no legal-set
// re-validation; ~20% of env-step time). For every LEGAL action it must be
// bit-identical to checked bb_apply — state, rng stream, and status — or the
// binding's trajectories silently diverge from every validation layer that
// replays through bb_apply. Differential over full matches.
BB_TEST(apply_trusted_matches_checked_apply) {
    for (uint64_t seed = 1; seed <= 6; seed++) {
        bb_match m;
        bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
        bb_rng rng, pick;
        bb_rng_seed(&rng, seed * 104729, 1);
        bb_rng_seed(&pick, seed ^ 0xD1FF, 2);
        bb_status st = bb_advance(&m, &rng);
        int steps = 0;
        while (st == BB_STATUS_DECISION && steps < 200000) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            BB_CHECK(n > 0);
            if (n <= 0) break;
            bb_action a = legal[fx_pick_smart(&m, legal, n, &pick)];
            bb_match mt;
            bb_rng rt;
            memcpy(&mt, &m, sizeof m);
            memcpy(&rt, &rng, sizeof rng);
            st = bb_apply(&m, a, &rng);
            bb_status st_t = bb_apply_trusted(&mt, a, &rt);
            BB_CHECK_EQ(st, st_t);
            BB_CHECK_EQ(memcmp(&m, &mt, sizeof(bb_match)), 0);
            BB_CHECK_EQ(memcmp(&rng, &rt, sizeof(bb_rng)), 0);
            if (st != st_t || memcmp(&m, &mt, sizeof(bb_match)) != 0) return;
            steps++;
        }
        BB_CHECK_EQ(st, BB_STATUS_MATCH_OVER);
    }
}

// Misusing the trusted path must degrade to BB_STATUS_ERROR (the binding's
// defensive-reset trigger), never UB on a stale frame.
BB_TEST(apply_trusted_guards_non_decision) {
    bb_match m;
    bb_match_init(&m, BB_TEAM_HUMAN, BB_TEAM_ORC);
    bb_rng rng;
    bb_rng_seed(&rng, 7, 1);
    // Status is RUNNING (no decision demanded yet).
    bb_status st = bb_apply_trusted(&m, (bb_action){BB_A_NONE, 0, 0, 0}, &rng);
    BB_CHECK_EQ(st, BB_STATUS_ERROR);
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

static bb_skillset base_position_skills(const bb_position_def* pd) {
    bb_skillset s;
    memset(&s, 0, sizeof s);
    for (int i = 0; i < pd->num_skills; i++) bb_add_skill(&s, pd->skills[i]);
    return s;
}

static int procgen_squad_total(const bb_match* m, int team) {
    int n = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (m->players[s].location != BB_LOC_ABSENT) n++;
    }
    return n;
}

static void check_procgen_structure(const bb_match* m) {
    for (int t = 0; t < 2; t++) {
        int counts[BB_MAX_POSITIONS] = {0};
        const bb_team_def* td = &bb_team_defs[m->team_id[t]];
        int total = 0;
        for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
            const bb_player* p = &m->players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            BB_CHECK(p->position_id < td->num_positions);
            if (p->position_id < td->num_positions) counts[p->position_id]++;
            total++;
        }
        BB_CHECK(total >= 11);
        BB_CHECK(total <= 14);
        for (int pi = 0; pi < td->num_positions; pi++) {
            BB_CHECK(counts[pi] <= td->positions[pi].qty_max);
        }
    }
}

static int procgen_count_skills(const bb_skillset* s) {
    int n = 0;
    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
    return n;
}

static int procgen_rng_same_state(const bb_rng* a, const bb_rng* b) {
    return a->state == b->state && a->inc == b->inc &&
           a->script == b->script && a->script_len == b->script_len &&
           a->script_pos == b->script_pos && a->mode == b->mode &&
           a->error == b->error && a->sink == b->sink &&
           a->sink_user == b->sink_user;
}

static void check_procgen_grants_in_mask(const bb_match* m, int secondary_only) {
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ABSENT) continue;
        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
        const bb_position_def* pd = &td->positions[p->position_id];
        bb_skillset base = base_position_skills(pd);
        uint8_t want = secondary_only && pd->secondary_mask ? pd->secondary_mask : pd->primary_mask;
        if (!want) want = secondary_only ? pd->primary_mask : pd->secondary_mask;
        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
             sk = bb_next_skill(&p->skills, sk + 1)) {
            if (bb_has_skill(&base, sk)) continue;
            uint8_t cat = bb_skill_defs[sk].category;
            BB_CHECK(cat < BB_CAT_COUNT);
            BB_CHECK(want & (1 << cat));
            if (!(want & (1 << cat))) {
                printf("  team %d pos %d skill %d cat %d want 0x%x\n",
                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat, want);
                return;
            }
        }
    }
}

static int procgen_find_secondary_only_teams(int* out, int cap) {
    int n = 0;
    for (int t = 0; t < BB_TEAM_COUNT; t++) {
        const bb_team_def* td = &bb_team_defs[t];
        int has_secondary_only = 0;
        for (int pi = 0; pi < td->num_positions; pi++) {
            const bb_position_def* pd = &td->positions[pi];
            if (pd->primary_mask == 0 && pd->secondary_mask != 0) {
                has_secondary_only = 1;
                break;
            }
        }
        if (has_secondary_only && n < cap) out[n++] = t;
    }
    return n;
}

static int procgen_check_secondary_only_grants(const bb_match* m) {
    int seen = 0;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ABSENT) continue;
        const bb_team_def* td = &bb_team_defs[m->team_id[BB_TEAM_OF(s)]];
        const bb_position_def* pd = &td->positions[p->position_id];
        if (pd->primary_mask != 0) continue;
        bb_skillset base = base_position_skills(pd);
        for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
             sk = bb_next_skill(&p->skills, sk + 1)) {
            if (bb_has_skill(&base, sk)) continue;
            uint8_t cat = bb_skill_defs[sk].category;
            BB_CHECK(cat < BB_CAT_COUNT);
            BB_CHECK(pd->secondary_mask & (1 << cat));
            if (!(pd->secondary_mask & (1 << cat))) {
                printf("  team %d pos %d skill %d cat %d secondary 0x%x\n",
                       m->team_id[BB_TEAM_OF(s)], p->position_id, sk, cat,
                       pd->secondary_mask);
                return seen;
            }
            seen = 1;
        }
    }
    return seen;
}

BB_TEST(match_procgen_default_params_match_legacy_api) {
    bb_procgen_params pp = bb_procgen_params_default();
    for (uint64_t seed = 1; seed <= 300; seed++) {
        bb_match a, b;
        bb_rng r1, r2;
        bb_rng_seed(&r1, seed * 0x515A5EEDu, 17 + seed);
        bb_rng_seed(&r2, seed * 0x515A5EEDu, 17 + seed);
        bb_match_init_random(&a, &r1);
        bb_match_init_random_p(&b, &r2, &pp);
        BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
        BB_CHECK(procgen_rng_same_state(&r1, &r2));
        if (memcmp(&a, &b, sizeof(bb_match)) != 0 ||
            !procgen_rng_same_state(&r1, &r2)) {
            printf("  seed %llu failed\n", (unsigned long long)seed);
            break;
        }
    }
}

BB_TEST(match_procgen_secondary_only_positions_inert_at_defaults) {
    int teams[BB_TEAM_COUNT];
    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
    BB_CHECK(nteams >= 2);
    if (nteams < 2) {
        printf("  found %d teams with secondary-only positions\n", nteams);
        return;
    }

    bb_procgen_params pp = bb_procgen_params_default();
    for (uint64_t seed = 1; seed <= 100; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 2654435761u, 53 + seed);
        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &m.players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
            const bb_position_def* pd = &td->positions[p->position_id];
            if (pd->primary_mask != 0) continue;
            bb_skillset base = base_position_skills(pd);
            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
            if (memcmp(&p->skills, &base, sizeof(bb_skillset)) != 0) {
                printf("  seed %llu team %d pos %d gained at defaults\n",
                       (unsigned long long)seed, m.team_id[BB_TEAM_OF(s)],
                       p->position_id);
                return;
            }
        }
    }
}

BB_TEST(match_procgen_secondary_only_positions_advance_with_pct) {
    int teams[BB_TEAM_COUNT];
    int nteams = procgen_find_secondary_only_teams(teams, BB_TEAM_COUNT);
    BB_CHECK(nteams >= 2);
    if (nteams < 2) {
        printf("  found %d teams with secondary-only positions\n", nteams);
        return;
    }

    bb_procgen_params pp = {11, 3, 0.5f};
    int seen = 0;
    for (uint64_t seed = 1; seed <= 2000 && !seen; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 11400714819323198485ull, 59 + seed);
        bb_match_init_forced_p(&m, &pg, teams[0], teams[1], -1, &pp);
        seen = procgen_check_secondary_only_grants(&m);
    }
    BB_CHECK(seen);
    if (!seen) printf("  no secondary-only position advanced within 2000 seeds\n");
}

BB_TEST(match_procgen_skillups_off_keeps_base_skills) {
    bb_procgen_params pp = {0, 2, 0.0f};
    for (uint64_t seed = 1; seed <= 50; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 2654435761u, 23);
        bb_match_init_random_p(&m, &pg, &pp);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &m.players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
            bb_skillset base = base_position_skills(&td->positions[p->position_id]);
            BB_CHECK_EQ(memcmp(&p->skills, &base, sizeof(bb_skillset)), 0);
        }
    }
}

BB_TEST(match_procgen_primary_only_uses_primary_categories) {
    bb_procgen_params pp = {11, 3, 0.0f};
    for (uint64_t seed = 1; seed <= 250; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 7919, 29);
        bb_match_init_random_p(&m, &pg, &pp);
        check_procgen_grants_in_mask(&m, 0);
    }
}

BB_TEST(match_procgen_secondary_only_uses_secondary_or_primary_fallback) {
    bb_procgen_params pp = {11, 3, 1.0f};
    for (uint64_t seed = 1; seed <= 250; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 104729, 31);
        bb_match_init_random_p(&m, &pg, &pp);
        check_procgen_grants_in_mask(&m, 1);
    }
}

BB_TEST(match_procgen_skillups_reach_full_learnable_catalogue) {
    bb_procgen_params pp = {11, 3, 0.5f};
    uint8_t seen[BB_NUM_SKILLS] = {0};
    int nseen = 0;
    for (uint64_t seed = 1; seed <= 10000 && nseen < BB_NUM_SKILLS; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, 0xC0FFEEu + seed * 17, 37);
        bb_match_init_random_p(&m, &pg, &pp);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &m.players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
            const bb_position_def* pd = &td->positions[p->position_id];
            bb_skillset base = base_position_skills(pd);
            for (int sk = bb_next_skill(&p->skills, 0); sk >= 0;
                 sk = bb_next_skill(&p->skills, sk + 1)) {
                if (sk >= BB_NUM_SKILLS || bb_has_skill(&base, sk)) continue;
                if (!seen[sk]) {
                    seen[sk] = 1;
                    nseen++;
                }
            }
        }
    }
    BB_CHECK_EQ(nseen, BB_NUM_SKILLS);
    if (nseen != BB_NUM_SKILLS) {
        for (int sk = 0; sk < BB_NUM_SKILLS; sk++) {
            if (!seen[sk]) printf("  missing skill %d (%s)\n", sk, bb_skill_defs[sk].id);
        }
    }
}

BB_TEST(match_procgen_cranked_params_respect_cap_and_structure) {
    bb_procgen_params pp = {16, 12, 0.5f};
    for (uint64_t seed = 1; seed <= 200; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 16127, 41);
        bb_match_init_random_p(&m, &pg, &pp);
        check_procgen_structure(&m);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            if (m.players[s].location == BB_LOC_ABSENT) continue;
            BB_CHECK(procgen_count_skills(&m.players[s].skills) <= 12);
        }
        BB_CHECK(procgen_squad_total(&m, BB_HOME) >= 11);
        BB_CHECK(procgen_squad_total(&m, BB_AWAY) >= 11);
    }
}

BB_TEST(match_procgen_params_are_deterministic) {
    bb_procgen_params pp = {11, 3, 0.35f};
    bb_match a, b;
    bb_rng r1, r2;
    bb_rng_seed(&r1, 0x12345678u, 43);
    bb_rng_seed(&r2, 0x12345678u, 43);
    bb_match_init_random_p(&a, &r1, &pp);
    bb_match_init_random_p(&b, &r2, &pp);
    BB_CHECK_EQ(memcmp(&a, &b, sizeof(bb_match)), 0);
    BB_CHECK(procgen_rng_same_state(&r1, &r2));
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

// bb_aura_skills must agree exactly with the registered aura hooks — it is
// the fast-path mask that lets bb_hook_mods skip players with no aura skills;
// a divergence would silently disable (or fail to skip) an aura (review P2).
BB_TEST(aura_mask_matches_registered_aura_hooks) {
    for (int sk = 0; sk < BB_SKILL_COUNT; sk++) {
        BB_CHECK_EQ(bb_has_skill(&bb_aura_skills, sk), bb_hooks[sk].aura != 0);
    }
    // Sanity: the known aura carriers are in the mask.
    BB_CHECK(bb_has_skill(&bb_aura_skills, BB_SK_DISTURBING_PRESENCE));
    BB_CHECK(bb_has_skill(&bb_aura_skills, BB_SK_TITCHY));
    BB_CHECK(bb_has_skill(&bb_aura_skills, BB_SK_PREHENSILE_TAIL));
}

// Procgen players must carry the roster's parameterized skill values
// (Loner X+, Bloodlust X+) exactly as bb_match_init players do — the lineman
// top-up path used to drop them (review LOW). Latent until a roster's first
// position carries Loner/Bloodlust; this pins the invariant for every slot.
BB_TEST(match_procgen_keeps_roster_skill_values) {
    for (uint64_t seed = 1; seed <= 60; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 1237, 11);
        bb_match_init_random(&m, &pg);
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &m.players[s];
            if (p->location == BB_LOC_ABSENT) continue;
            const bb_team_def* td = &bb_team_defs[m.team_id[BB_TEAM_OF(s)]];
            const bb_position_def* pd = &td->positions[p->position_id];
            int want_loner = 4, want_bloodlust = 0;
            for (int k = 0; k < pd->num_skills; k++) {
                if (pd->skill_values[k] <= 0) continue;
                if (pd->skills[k] == BB_SK_LONER) want_loner = pd->skill_values[k];
                if (pd->skills[k] == BB_SK_BLOODLUST) want_bloodlust = pd->skill_values[k];
            }
            BB_CHECK_EQ(p->p_loner, want_loner);
            BB_CHECK_EQ(p->p_bloodlust, want_bloodlust);
            if (p->p_loner != want_loner || p->p_bloodlust != want_bloodlust) return;
        }
    }
}

// Pre-game injuries are dealt to DISTINCT players (review LOW): sampling the
// raw slot range with replacement could hit the same player twice. At seed
// 49 / stream 5 the home squad rolled 2 injuries but the old code
// double-picked one player, leaving a single casualty.
BB_TEST(match_procgen_pregame_injuries_without_replacement) {
    bb_match m;
    bb_rng pg;
    bb_rng_seed(&pg, 49, 5);
    bb_match_init_random(&m, &pg);
    int cas = 0;
    for (int s = 0; s < BB_TEAM_SLOTS; s++) {
        if (m.players[s].location == BB_LOC_CAS) cas++;
    }
    BB_CHECK_EQ(cas, 2);
    // Invariants: at most 2 pre-game casualties, and at least 11 healthy
    // players always remain.
    for (uint64_t seed = 1; seed <= 200; seed++) {
        bb_rng pg2;
        bb_rng_seed(&pg2, seed, 5);
        bb_match_init_random(&m, &pg2);
        for (int t = 0; t < 2; t++) {
            int ncas = 0, healthy = 0;
            for (int s = t * BB_TEAM_SLOTS; s < (t + 1) * BB_TEAM_SLOTS; s++) {
                if (m.players[s].location == BB_LOC_CAS) ncas++;
                if (m.players[s].location == BB_LOC_RESERVES) healthy++;
            }
            BB_CHECK(ncas <= 2);
            BB_CHECK(healthy >= 11);
        }
    }
}

// Holdout / fixed-matchup procgen controls (generalization experiments).
BB_TEST(match_procgen_forced_and_excluded) {
    for (uint64_t seed = 1; seed <= 40; seed++) {
        bb_match m;
        bb_rng pg;
        bb_rng_seed(&pg, seed * 4241, 9);
        // Pin home to team 5, exclude team 7 from the random away draw.
        bb_match_init_forced(&m, &pg, 5, -1, 7);
        BB_CHECK_EQ(m.team_id[0], 5);
        BB_CHECK(m.team_id[1] != 7);
        // Fully pinned matchup.
        bb_match_init_forced(&m, &pg, 12, 26, -1);
        BB_CHECK_EQ(m.team_id[0], 12);
        BB_CHECK_EQ(m.team_id[1], 26);
    }
}

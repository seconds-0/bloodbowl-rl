// bb_procgen.c — procedural match generation for RL training.
//
// Every reset samples a fresh matchup: random rosters, squad compositions,
// advancement skills and re-roll counts, drawn from the codegen'd team
// definitions. This is what forces the policy to generalize across the
// trillions of team states instead of memorizing one matchup.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"
#include "bb/gen_teams.h"
#include <string.h>

// Uniform integer in [0, n) from the procgen stream.
static int pg_pick(bb_rng* rng, int n) {
    return n > 0 ? (int)(bb_rng_next(rng) % (uint32_t)n) : 0;
}

// Total-skill cap for procgen players. The RL observation encodes skills as
// a fixed list of 12 id slots (puffer/bloodbowl/bloodbowl.h BBE_SKILL_SLOTS);
// the largest base roster list is 10, so capping advancement at 12 keeps the
// obs lossless. Raise both together if star players ever exceed this.
#define PG_MAX_SKILLS 12

static int pg_skill_count(const bb_skillset* s) {
    int n = 0;
    for (int sk = bb_next_skill(s, 0); sk >= 0; sk = bb_next_skill(s, sk + 1)) n++;
    return n;
}

static float pg_float01(bb_rng* rng) {
    return (float)(bb_rng_next(rng) >> 8) * (1.0f / 16777216.0f);
}

bb_procgen_params bb_procgen_params_default(void) {
    return (bb_procgen_params){4, 2, 0.0f};
}

// Build one team's squad: positionals first (random counts within limits),
// topped up with the first listed position; then configured random
// advancement skills from primary/secondary categories.
static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng,
                          const bb_procgen_params* pp) {
    const bb_team_def* td = &bb_team_defs[team_id];
    int base = team * BB_TEAM_SLOTS;
    int n = 0;
    int counts[BB_MAX_POSITIONS] = {0};

    // Roster size 11-14.
    int squad = 11 + pg_pick(rng, 4);

    // Fill positional slots (positions[1..]) with random counts.
    for (int pi = td->num_positions - 1; pi >= 1 && n < squad; pi--) {
        const bb_position_def* pd = &td->positions[pi];
        int want = pg_pick(rng, pd->qty_max + 1);
        while (want-- > 0 && n < squad) {
            // init_player_from_position equivalent (kept local to this TU):
            bb_player* p = &m->players[base + n];
            memset(p, 0, sizeof(*p));
            p->ma = pd->ma;
            p->st = pd->st;
            p->ag = pd->ag;
            p->pa = pd->pa;
            p->av = pd->av;
            p->position_id = (uint8_t)pi;
            p->location = BB_LOC_RESERVES;
            p->stance = BB_STANCE_STANDING;
            p->p_loner = 4;
            for (int s = 0; s < pd->num_skills; s++) {
                bb_add_skill(&p->skills, pd->skills[s]);
                int v = pd->skill_values[s];
                if (v > 0) {
                    if (pd->skills[s] == BB_SK_LONER) p->p_loner = (int8_t)v;
                    if (pd->skills[s] == BB_SK_BLOODLUST) p->p_bloodlust = (int8_t)v;
                }
            }
            counts[pi]++;
            n++;
        }
    }
    // Top up with the first-listed position (linemen).
    while (n < squad) {
        const bb_position_def* pd = &td->positions[0];
        bb_player* p = &m->players[base + n];
        memset(p, 0, sizeof(*p));
        p->ma = pd->ma;
        p->st = pd->st;
        p->ag = pd->ag;
        p->pa = pd->pa;
        p->av = pd->av;
        p->position_id = 0;
        p->location = BB_LOC_RESERVES;
        p->stance = BB_STANCE_STANDING;
        p->p_loner = 4;
        for (int s = 0; s < pd->num_skills; s++) {
            bb_add_skill(&p->skills, pd->skills[s]);
            // Keep the roster's parameterized skill values, like the
            // positional path above — dropping them left p_bloodlust 0
            // (gate silently inert) and p_loner at the default (review LOW).
            int v = pd->skill_values[s];
            if (v > 0) {
                if (pd->skills[s] == BB_SK_LONER) p->p_loner = (int8_t)v;
                if (pd->skills[s] == BB_SK_BLOODLUST) p->p_bloodlust = (int8_t)v;
            }
        }
        n++;
    }
    for (int s = n; s < BB_TEAM_SLOTS; s++) {
        memset(&m->players[base + s], 0, sizeof(bb_player));
        m->players[base + s].location = BB_LOC_ABSENT;
    }

    // Advancement: players gain random skills from configured category access
    // (the 2D6 random-skill table run "fairly" via the procgen stream).
    int advanced = pp->skillup_max_players > 0 ? pg_pick(rng, pp->skillup_max_players + 1) : 0;
    for (int i = 0; i < advanced; i++) {
        int who = base + pg_pick(rng, n);
        bb_player* p = &m->players[who];
        const bb_position_def* pd = &td->positions[p->position_id];
        uint8_t access = pd->primary_mask;
        if (pp->skillup_secondary_pct > 0.0f) access |= pd->secondary_mask;
        if (!access) continue;
        int gains = pp->skillup_max_each >= 1 ? 1 + pg_pick(rng, pp->skillup_max_each) : 0;
        for (int g = 0; g < gains; g++) {
            if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
            uint8_t mask = pd->primary_mask;
            if (pp->skillup_secondary_pct > 0.0f &&
                pg_float01(rng) < pp->skillup_secondary_pct) {
                mask = pd->secondary_mask;
            }
            if (!mask) {
                mask = (mask == pd->primary_mask) ? pd->secondary_mask : pd->primary_mask;
            }
            if (!mask) continue;
            // Pick a random category bit.
            int cats[BB_CAT_COUNT];
            int nc = 0;
            for (int c = 0; c < BB_CAT_COUNT; c++) {
                if (mask & (1 << c)) cats[nc++] = c;
            }
            int cat = cats[pg_pick(rng, nc)];
            int sk = bb_random_skill_table[cat][pg_pick(rng, 12)];
            bb_add_skill(&p->skills, sk);
        }
    }

    // Pre-game injuries: 0-2 players start in the casualty box (simulating
    // league attrition) — only if the squad stays >= 11. Picks are WITHOUT
    // replacement: sampling the raw slot range could hit the same player
    // twice, under-delivering 2-casualty squads ~7-9% (review LOW).
    int hurt = pg_pick(rng, 3);
    for (int i = 0; i < hurt && n - i > 11; i++) {
        int pick = pg_pick(rng, n - i); // index among the still-healthy
        for (int s = base; s < base + n; s++) {
            if (m->players[s].location == BB_LOC_CAS) continue;
            if (pick-- == 0) {
                m->players[s].location = BB_LOC_CAS;
                break;
            }
        }
    }
}

static void pg_init_match(bb_match* m, bb_rng* rng, int home, int away,
                          const bb_procgen_params* pp) {
    m->team_id[BB_HOME] = (uint8_t)home;
    m->team_id[BB_AWAY] = (uint8_t)away;
    procgen_squad(m, BB_HOME, home, rng, pp);
    procgen_squad(m, BB_AWAY, away, rng, pp);
    for (int t = 0; t < 2; t++) {
        m->rerolls[t] = m->rerolls_start[t] = (uint8_t)(2 + pg_pick(rng, 3));
        m->apothecary[t] = bb_team_defs[m->team_id[t]].apothecary ? 1 : 0;
    }
    m->half = 1;
    m->ball.state = BB_BALL_OFF_PITCH;
    m->ball.carrier = BB_NO_PLAYER;
    m->status = BB_STATUS_RUNNING;
    bb_push(m, BB_PROC_MATCH, 0, 0, 0, 0);
}

void bb_match_init_random(bb_match* m, bb_rng* rng) {
    bb_procgen_params pp = bb_procgen_params_default();
    bb_match_init_random_p(m, rng, &pp);
}

void bb_match_init_random_p(bb_match* m, bb_rng* rng, const bb_procgen_params* pp) {
    memset(m, 0, sizeof(*m));
    int home = pg_pick(rng, BB_TEAM_COUNT);
    int away = pg_pick(rng, BB_TEAM_COUNT);
    pg_init_match(m, rng, home, away, pp);
}

// Holdout / fixed-matchup variant: home/away >= 0 pin that side's team;
// exclude >= 0 redraws any random side that lands on the excluded id (the
// held-out-team generalization experiments train with exclude set and
// evaluate with force_* set).
void bb_match_init_forced(bb_match* m, bb_rng* rng, int home, int away, int exclude) {
    bb_procgen_params pp = bb_procgen_params_default();
    bb_match_init_forced_p(m, rng, home, away, exclude, &pp);
}

void bb_match_init_forced_p(bb_match* m, bb_rng* rng, int home, int away, int exclude,
                            const bb_procgen_params* pp) {
    memset(m, 0, sizeof(*m));
    int h = home;
    while (h < 0 || (home < 0 && h == exclude)) {
        h = pg_pick(rng, BB_TEAM_COUNT);
        if (home < 0 && h == exclude) h = -1;
    }
    int a = away;
    while (a < 0 || (away < 0 && a == exclude)) {
        a = pg_pick(rng, BB_TEAM_COUNT);
        if (away < 0 && a == exclude) a = -1;
    }
    pg_init_match(m, rng, h, a, pp);
}

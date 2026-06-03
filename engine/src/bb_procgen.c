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

// Build one team's squad: positionals first (random counts within limits),
// topped up with the first listed position; 0-4 players get 1-2 random
// advancement skills from their primary categories.
static void procgen_squad(bb_match* m, int team, int team_id, bb_rng* rng) {
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
        }
        n++;
    }
    for (int s = n; s < BB_TEAM_SLOTS; s++) {
        memset(&m->players[base + s], 0, sizeof(bb_player));
        m->players[base + s].location = BB_LOC_ABSENT;
    }

    // Advancement: 0-4 players gain 1-2 random skills from a primary category
    // (the 2D6 random-skill table run "fairly" via the procgen stream).
    int advanced = pg_pick(rng, 5);
    for (int i = 0; i < advanced; i++) {
        int who = base + pg_pick(rng, n);
        bb_player* p = &m->players[who];
        const bb_position_def* pd = &td->positions[p->position_id];
        if (!pd->primary_mask) continue;
        int gains = 1 + pg_pick(rng, 2);
        for (int g = 0; g < gains; g++) {
            if (pg_skill_count(&p->skills) >= PG_MAX_SKILLS) break;
            // Pick a random primary category bit.
            int cats[BB_CAT_COUNT];
            int nc = 0;
            for (int c = 0; c < BB_CAT_COUNT; c++) {
                if (pd->primary_mask & (1 << c)) cats[nc++] = c;
            }
            int cat = cats[pg_pick(rng, nc)];
            int sk = bb_random_skill_table[cat][pg_pick(rng, 12)];
            bb_add_skill(&p->skills, sk);
        }
    }

    // Pre-game injuries: 0-2 players start in the casualty box (simulating
    // league attrition) — only if the squad stays >= 11.
    int hurt = pg_pick(rng, 3);
    for (int i = 0; i < hurt && n - i > 11; i++) {
        m->players[base + pg_pick(rng, n)].location = BB_LOC_CAS;
    }
}

void bb_match_init_random(bb_match* m, bb_rng* rng) {
    memset(m, 0, sizeof(*m));
    int home = pg_pick(rng, BB_TEAM_COUNT);
    int away = pg_pick(rng, BB_TEAM_COUNT);
    m->team_id[BB_HOME] = (uint8_t)home;
    m->team_id[BB_AWAY] = (uint8_t)away;
    procgen_squad(m, BB_HOME, home, rng);
    procgen_squad(m, BB_AWAY, away, rng);
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

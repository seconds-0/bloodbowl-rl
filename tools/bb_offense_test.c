// bb_offense_test.c -- rigorous behavioral validation of the scripted cage
// offense bot before it is used as a defense-training opponent.
// Three tests (Alex): (1) vs nonfunctional opponents — does it march + score?
// (2) does it play defense at all? (3) two deterministic bots vs each other —
// terminate? both score? degenerate?
#include <stdio.h>
#include <string.h>
#include "bloodbowl.h"

static int act_in_legal(bb_action a, const bb_action* l, int n) {
    for (int i = 0; i < n; i++) if (bb_action_eq(a, l[i])) return 1;
    return 0;
}

// PASSIVE opponent: do nothing useful — confirm setup, then end the turn ASAP.
// Forced sub-decisions (rerolls/skills/pushes) fall back to legal[0].
static bb_action passive_pick(const bb_match* m, const bb_action* l, int n) {
    (void)m;
    for (int i = 0; i < n; i++) if (l[i].type == BB_A_END_TURN) return l[i];
    for (int i = 0; i < n; i++) if (l[i].type == BB_A_SETUP_DONE) return l[i];
    for (int i = 0; i < n; i++) if (l[i].type == BB_A_END_ACTIVATION) return l[i];
    return l[0];
}

static bb_action random_pick(bb_rng* r, const bb_action* l, int n) {
    return l[(int)(bb_rng_next(r) % (unsigned)n)];
}

typedef enum { OPP_PASSIVE, OPP_RANDOM, OPP_OFFENSE } opp_t;

typedef struct {
    int games, finished, home_td_games, away_td_games, both_td_games;
    long home_tds, away_tds;
    int home_shutout;          // games HOME (offense bot) scored 0
    int max_decisions_hit;     // non-termination signature
    // defense probe: offense bot's decisions while NOT the ball-holding team
    long def_decisions, def_endturn;
} stats_t;

static void run(opp_t opp, int games, unsigned seed0, stats_t* st) {
    memset(st, 0, sizeof *st);
    st->games = games;
    int off = BB_HOME; // offense bot is always HOME
    for (int g = 0; g < games; g++) {
        bb_rng pg, dice, rnd;
        bb_rng_seed(&pg, 0x0FFEA500u + (uint64_t)g * 9973u, 11);
        bb_rng_seed(&dice, 0x0FFED1CEu + (uint64_t)g * 7919u + seed0, 1);
        bb_rng_seed(&rnd, 0x0BADF00Du + (uint64_t)g * 6271u + seed0, 5);
        bb_match m;
        bb_procgen_params pp = bb_procgen_params_default();
        bb_match_init_random_p(&m, &pg, &pp);
        bb_advance(&m, &dice);
        int d = 0;
        while (m.status == BB_STATUS_DECISION && d < BBE_MAX_DECISIONS) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            if (n <= 0) { fprintf(stderr, "no legal\n"); return; }
            bb_action pick;
            if (m.decision_team == off) {
                pick = bbe_offense_bot_pick(&m, legal, n);
            } else {
                pick = opp == OPP_PASSIVE ? passive_pick(&m, legal, n)
                     : opp == OPP_RANDOM  ? random_pick(&rnd, legal, n)
                                          : bbe_offense_bot_pick(&m, legal, n);
            }
            if (!act_in_legal(pick, legal, n)) { fprintf(stderr,"illegal pick t=%d\n",pick.type); return; }
            // Defense probe: when the offense bot is deciding and does NOT hold
            // the ball, is it doing something or just ending the turn?
            if (m.decision_team == off) {
                int holder = (m.ball.state == BB_BALL_HELD && m.ball.carrier < BB_NUM_PLAYERS)
                                 ? BB_TEAM_OF(m.ball.carrier) : -1;
                if (holder != off) {
                    st->def_decisions++;
                    if (pick.type == BB_A_END_TURN) st->def_endturn++;
                }
            }
            bb_apply(&m, pick, &dice);
            if (m.status == BB_STATUS_ERROR) { fprintf(stderr,"engine error\n"); return; }
            d++;
        }
        if (m.status == BB_STATUS_MATCH_OVER) st->finished++;
        if (d >= BBE_MAX_DECISIONS) st->max_decisions_hit++;
        st->home_tds += m.score[0]; st->away_tds += m.score[1];
        if (m.score[0] > 0) st->home_td_games++;
        if (m.score[1] > 0) st->away_td_games++;
        if (m.score[0] > 0 && m.score[1] > 0) st->both_td_games++;
        if (m.score[0] == 0) st->home_shutout++;
    }
}

static void report(const char* name, const stats_t* s) {
    printf("\n[%s] games=%d finished=%d non_term(hit_cap)=%d\n",
           name, s->games, s->finished, s->max_decisions_hit);
    printf("  HOME(offense bot): tds=%ld (%.2f/game)  scored-in %d/%d games  shutout %d/%d\n",
           s->home_tds, (double)s->home_tds/s->games, s->home_td_games, s->games,
           s->home_shutout, s->games);
    printf("  AWAY(%s): tds=%ld (%.2f/game)  scored-in %d/%d games  both-scored %d\n",
           name, s->away_tds, (double)s->away_tds/s->games, s->away_td_games, s->games,
           s->both_td_games);
    if (s->def_decisions)
        printf("  DEFENSE PROBE (offense bot w/o ball): %ld decisions, %.1f%% immediate END_TURN\n",
               s->def_decisions, 100.0*s->def_endturn/s->def_decisions);
}

int main(void) {
    stats_t s;
    run(OPP_PASSIVE, 300, 0, &s); report("vs PASSIVE", &s);
    run(OPP_RANDOM,  300, 1, &s); report("vs RANDOM", &s);
    run(OPP_OFFENSE, 300, 2, &s); report("offense_bot vs offense_bot", &s);
    printf("\nPASS CRITERIA: vs PASSIVE/RANDOM -> high HOME td/game, low shutout, finished==games, non_term==0; "
           "bot-vs-bot -> finished==games, both teams score in a healthy fraction.\n");
    return 0;
}

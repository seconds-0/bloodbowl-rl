/* Measure decision-time credit assignment on complete legal scripted games.
 * This is an environment diagnostic, not a learned-policy performance result.
 * cc -O2 -std=c11 -Iengine/include -Ipuffer/bloodbowl \
 *    tools/decision_clock_probe.c -lm -o /tmp/decision_clock_probe
 */
#include <stdio.h>
#include <stdint.h>
#include "bloodbowl.h"

static int holder(const bb_match* m) {
    return m->ball.state == BB_BALL_HELD && m->ball.carrier < BB_NUM_PLAYERS
        ? BB_TEAM_OF(m->ball.carrier) : -1;
}

static int in_support(bb_action action, const bb_action* legal, int n) {
    for (int i = 0; i < n; i++) if (bb_action_eq(action, legal[i])) return 1;
    return 0;
}

int main(void) {
    const uint64_t first_seed = UINT64_C(910001);
    const int games_per_matchup = 32;
    printf("{\"schema\":\"decision-clock-v1\",\"first_seed\":%llu,"
           "\"games_per_matchup\":%d,\"games\":[\n",
           (unsigned long long)first_seed, games_per_matchup);
    int first = 1;
    for (int home_style = 0; home_style < 2; home_style++) {
        for (int away_style = 0; away_style < 2; away_style++) {
            for (int game = 0; game < games_per_matchup; game++) {
                uint64_t seed = first_seed + (uint64_t)game;
                bb_rng roster_rng, dice;
                bb_rng_seed(&roster_rng, seed * UINT64_C(9973), 11);
                bb_rng_seed(&dice, seed * UINT64_C(7919), 1);
                bb_match m;
                bb_procgen_params pp = bb_procgen_params_default();
                bb_match_init_random_p(&m, &roster_rng, &pp);
                bb_advance(&m, &dice);
                int decisions = 0, forced = 0, choices[2] = {0, 0};
                int gain_at[2] = {-1, -1};
                int decision_delays[64], choice_delays[64], n_delays = 0;
                int choice_at[2] = {0, 0};
                while (m.status == BB_STATUS_DECISION && decisions < BBE_MAX_DECISIONS) {
                    bb_action legal[BB_LEGAL_MAX];
                    int n = bb_legal_actions(&m, legal);
                    if (n <= 0) return 2;
                    int side = m.decision_team;
                    int before_holder = holder(&m);
                    int score[2] = {m.score[0], m.score[1]};
                    if (n == 1) forced++;
                    else choices[side]++;
                    int style = side == BB_HOME ? home_style : away_style;
                    bb_action action = style
                        ? bbe_offense_bot_pick(&m, legal, n)
                        : bbe_contact_bot_pick(&m, legal, n);
                    if (!in_support(action, legal, n)) return 3;
                    bb_apply(&m, action, &dice);
                    decisions++;
                    if (m.status == BB_STATUS_ERROR) return 4;
                    int after_holder = holder(&m);
                    for (int team = 0; team < 2; team++) {
                        if (m.score[team] > score[team] && gain_at[team] >= 0) {
                            if (n_delays == 64) return 5;
                            decision_delays[n_delays] = decisions - gain_at[team];
                            choice_delays[n_delays] = choices[team] - choice_at[team];
                            n_delays++;
                        }
                        if (after_holder != team) gain_at[team] = -1;
                        else if (before_holder != team) {
                            gain_at[team] = decisions;
                            choice_at[team] = choices[team];
                        }
                    }
                }
                if (m.status != BB_STATUS_MATCH_OVER) return 6;
                printf("%s{\"seed\":%llu,\"home_style\":%d,\"away_style\":%d,"
                       "\"decisions\":%d,\"forced_decisions\":%d,"
                       "\"home_choices\":%d,\"away_choices\":%d,"
                       "\"home_tds\":%d,\"away_tds\":%d,\"possession_to_td_decisions\":[",
                       first ? "" : ",\n", (unsigned long long)seed,
                       home_style, away_style, decisions, forced,
                       choices[0], choices[1], m.score[0], m.score[1]);
                first = 0;
                for (int i = 0; i < n_delays; i++)
                    printf("%s%d", i ? "," : "", decision_delays[i]);
                printf("],\"possession_to_td_own_choices\":[");
                for (int i = 0; i < n_delays; i++)
                    printf("%s%d", i ? "," : "", choice_delays[i]);
                printf("]}");
            }
        }
    }
    printf("\n],\"completed_games\":%d,\"errors\":0}\n", 4 * games_per_matchup);
    return 0;
}

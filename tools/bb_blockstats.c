// bb_blockstats.c - snapshot block-tier/assist stats for normalized FUMBBL JSONL.
//
// This intentionally does not replay the game. It tracks the recorded player
// positions/states, reconstructs a minimal bb_match at each blockChoice, and
// calls the real engine bb_count_assists() for assist eligibility.
#include "bb/bb_proc.h"
#include "bb/bb_hooks.h"
#include "bb/bb_skills.h"
#include "bb/gen_skills.h"

#include <ctype.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LINE 131072
#define MAX_PLAYERS 128

typedef struct {
    char id[64];
    int team;
    int ma, st, ag, pa, av;
    bb_skillset skills;
    int x, y;
    int state; // 0 standing, 1 prone, 2 stunned, 3 reserves, 4 KO, 5 CAS, 6 sent-off
    bool known;
} player_rec;

typedef struct {
    long files_total, files_used, malformed;
    long blocks_total, blocks_skipped;
    long engine_tier_mismatch;
    long count[5], carrier[5], offassist_sum[5], defassist_sum[5];
    double game_carrier_frac_sum[5];
    double game_offassist_mean_sum[5];
    double game_defassist_mean_sum[5];
} stats;

typedef struct {
    player_rec p[MAX_PLAYERS];
    int n;
    char last_actor[64];
    char last_action[64];
    char carrier[64];
} game;

static double frac(long num, long den);
static double mean_game(double sum, long games);

static const char* find_key(const char* s, const char* key) {
    char pat[96];
    snprintf(pat, sizeof pat, "\"%s\":", key);
    size_t plen = strlen(pat);
    int depth = 0;
    bool in_str = false;
    for (const char* p = s; *p; p++) {
        if (in_str) {
            if (*p == '\\' && p[1]) p++;
            else if (*p == '"') in_str = false;
            continue;
        }
        if (*p == '"') {
            if (depth == 1 && strncmp(p + 1, pat + 1, plen - 1) == 0) {
                return p + plen;
            }
            in_str = true;
            continue;
        }
        if (*p == '{' || *p == '[') depth++;
        else if (*p == '}' || *p == ']') depth--;
    }
    return NULL;
}

static const char* span(const char* p) {
    char open = *p, close = open == '{' ? '}' : ']';
    int depth = 0;
    bool in_str = false;
    for (; *p; p++) {
        if (in_str) {
            if (*p == '\\' && p[1]) p++;
            else if (*p == '"') in_str = false;
            continue;
        }
        if (*p == '"') in_str = true;
        else if (*p == open) depth++;
        else if (*p == close && --depth == 0) return p + 1;
    }
    return p;
}

static const char* obj_value(const char* s, const char* key) {
    const char* p = find_key(s, key);
    if (!p) return NULL;
    while (*p == ' ') p++;
    return *p == '{' ? p : NULL;
}

static long jint(const char* s, const char* key, long dflt) {
    const char* p = find_key(s, key);
    if (!p) return dflt;
    while (*p == ' ' || *p == '"') p++;
    return strtol(p, NULL, 10);
}

static bool jbool(const char* s, const char* key, bool dflt) {
    const char* p = find_key(s, key);
    if (!p) return dflt;
    while (*p == ' ') p++;
    if (strncmp(p, "true", 4) == 0) return true;
    if (strncmp(p, "false", 5) == 0) return false;
    return dflt;
}

static int jstr(const char* s, const char* key, char* out, int cap) {
    const char* p = find_key(s, key);
    if (!p) return 0;
    while (*p == ' ') p++;
    if (*p != '"') return 0;
    p++;
    int n = 0;
    while (*p && *p != '"' && n < cap - 1) {
        if (*p == '\\' && p[1]) p++;
        out[n++] = *p++;
    }
    out[n] = 0;
    return 1;
}

static int jxy(const char* s, const char* key, int* x, int* y) {
    const char* p = find_key(s, key);
    if (!p) return 0;
    while (*p == ' ') p++;
    if (*p != '[') return 0;
    p++;
    *x = (int)strtol(p, (char**)&p, 10);
    while (*p == ' ' || *p == ',') p++;
    *y = (int)strtol(p, NULL, 10);
    return 1;
}

static void slugify(const char* in, char* out, int cap) {
    int n = 0;
    bool paren = false;
    for (const char* p = in; *p && n < cap - 1; p++) {
        if (*p == '(') paren = true;
        else if (*p == ')') paren = false;
        else if (!paren && isalnum((unsigned char)*p)) {
            out[n++] = (char)tolower((unsigned char)*p);
        }
    }
    out[n] = 0;
}

static int skill_id_for_name(const char* name) {
    char want[96], have[96];
    slugify(name, want, sizeof want);
    if (!want[0] || want[0] == '+') return -1;
    for (int i = 0; i < BB_SKILL_COUNT; i++) {
        slugify(bb_skill_defs[i].display, have, sizeof have);
        if (strcmp(want, have) == 0) return i;
    }
    return -1;
}

static int state_from_base(long base) {
    switch (base) {
        case 1: return 0; // standing
        case 3:
        case 11: return 1; // prone
        case 4: return 2; // stunned
        case 9: return 3; // reserves
        case 5: return 4; // KO
        case 6:
        case 7:
        case 8: return 5; // CAS
        case 13: return 6; // sent off
        default: return -1; // transient: keep last stable state
    }
}

static player_rec* find_player(game* g, const char* id) {
    for (int i = 0; i < g->n; i++) {
        if (strcmp(g->p[i].id, id) == 0) return &g->p[i];
    }
    return NULL;
}

static player_rec* standing_player_at(game* g, int x, int y) {
    player_rec* found = NULL;
    for (int i = 0; i < g->n; i++) {
        player_rec* pr = &g->p[i];
        if (pr->x != x || pr->y != y || pr->state != 0) continue;
        if (found) return NULL;
        found = pr;
    }
    return found;
}

static player_rec* add_player(game* g, const char* id, int team) {
    player_rec* p = find_player(g, id);
    if (p) return p;
    if (g->n >= MAX_PLAYERS) return NULL;
    p = &g->p[g->n++];
    memset(p, 0, sizeof *p);
    snprintf(p->id, sizeof p->id, "%s", id);
    p->team = team;
    p->ma = 5;
    p->st = 3;
    p->ag = 3;
    p->pa = 0;
    p->av = 8;
    p->x = p->y = -1;
    p->state = 3;
    p->known = true;
    return p;
}

static void parse_skills(player_rec* pr, const char* pobj) {
    const char* p = find_key(pobj, "skills");
    if (!p) return;
    while (*p == ' ') p++;
    if (*p != '[') return;
    const char* end = span(p);
    for (const char* q = p + 1; q < end; q++) {
        if (*q != '"') continue;
        q++;
        char name[128];
        int n = 0;
        while (q < end && *q != '"' && n < (int)sizeof name - 1) {
            if (*q == '\\' && q[1]) q++;
            name[n++] = *q++;
        }
        name[n] = 0;
        int sid = skill_id_for_name(name);
        if (sid >= 0) bb_add_skill(&pr->skills, sid);
    }
}

static void parse_team_players(game* g, const char* team_obj, int team) {
    const char* pa = find_key(team_obj, "players");
    if (!pa) return;
    while (*pa == ' ') pa++;
    if (*pa != '[') return;
    const char* end = span(pa);
    for (const char* p = pa + 1; p < end;) {
        while (p < end && *p != '{') p++;
        if (p >= end) break;
        const char* pe = span(p);
        char pobj[8192];
        int len = (int)(pe - p);
        if (len >= (int)sizeof pobj) len = sizeof pobj - 1;
        memcpy(pobj, p, len);
        pobj[len] = 0;
        char id[64];
        if (jstr(pobj, "playerId", id, sizeof id)) {
            player_rec* pr = add_player(g, id, team);
            if (pr) {
                pr->ma = (int)jint(pobj, "ma", pr->ma);
                pr->st = (int)jint(pobj, "st", pr->st);
                pr->ag = (int)jint(pobj, "ag", pr->ag);
                pr->pa = (int)jint(pobj, "pa", pr->pa);
                pr->av = (int)jint(pobj, "av", pr->av);
                parse_skills(pr, pobj);
            }
        }
        p = pe;
    }
}

static int parse_meta(game* g, const char* line) {
    const char* home = obj_value(line, "teamHome");
    const char* away = obj_value(line, "teamAway");
    if (!home || !away) return -1;
    char hbuf[65536], abuf[65536];
    int hl = (int)(span(home) - home);
    int al = (int)(span(away) - away);
    if (hl >= (int)sizeof hbuf) hl = sizeof hbuf - 1;
    if (al >= (int)sizeof abuf) al = sizeof abuf - 1;
    memcpy(hbuf, home, hl);
    hbuf[hl] = 0;
    memcpy(abuf, away, al);
    abuf[al] = 0;
    parse_team_players(g, hbuf, BB_HOME);
    parse_team_players(g, abuf, BB_AWAY);
    return g->n > 0 ? 0 : -1;
}

static void apply_formation(game* g, const char* line) {
    const char* po = obj_value(line, "players");
    if (!po) return;
    for (int i = 0; i < g->n; i++) {
        g->p[i].x = g->p[i].y = -1;
        if (g->p[i].state < 3) g->p[i].state = 3;
    }
    const char* end = span(po);
    const char* p = po + 1;
    while (p < end) {
        while (p < end && *p != '"') p++;
        if (p >= end) break;
        p++;
        char id[64];
        int n = 0;
        while (p < end && *p != '"' && n < (int)sizeof id - 1) id[n++] = *p++;
        id[n] = 0;
        while (p < end && *p != '[') p++;
        if (p >= end) break;
        p++;
        int x = (int)strtol(p, (char**)&p, 10);
        while (*p == ' ' || *p == ',') p++;
        int y = (int)strtol(p, (char**)&p, 10);
        player_rec* pr = find_player(g, id);
        if (pr) {
            pr->x = x;
            pr->y = y;
            if (pr->state >= 3) pr->state = 0;
        }
    }
}

static int cmp_player_ptr(const void* a, const void* b) {
    const player_rec* pa = *(const player_rec* const*)a;
    const player_rec* pb = *(const player_rec* const*)b;
    return strcmp(pa->id, pb->id);
}

static int reconstruct_match(game* g, const char* att_id, const char* def_id,
                             bb_match* m, int* att_slot, int* def_slot,
                             int* carrier_slot) {
    memset(m, 0, sizeof *m);
    for (int s = 0; s < BB_NUM_PLAYERS; s++) m->players[s].location = BB_LOC_ABSENT;
    player_rec* side[2][MAX_PLAYERS];
    int ns[2] = {0, 0};
    for (int i = 0; i < g->n; i++) {
        player_rec* pr = &g->p[i];
        if (pr->x < 0 || pr->x >= BB_PITCH_LEN || pr->y < 0 || pr->y >= BB_PITCH_WID) continue;
        if (pr->state < 0 || pr->state >= 3) continue;
        if (pr->team < 0 || pr->team > 1) continue;
        side[pr->team][ns[pr->team]++] = pr;
    }
    for (int t = 0; t < 2; t++) qsort(side[t], ns[t], sizeof side[t][0], cmp_player_ptr);
    player_rec* att = find_player(g, att_id);
    player_rec* def = find_player(g, def_id);
    if (!att || !def || att->team == def->team) return -1;
    *att_slot = *def_slot = *carrier_slot = -1;
    for (int t = 0; t < 2; t++) {
        int out = 0;
        for (int pass = 0; pass < 2; pass++) {
            for (int i = 0; i < ns[t] && out < BB_TEAM_SLOTS; i++) {
                player_rec* pr = side[t][i];
                bool mandatory = (pr == att || pr == def ||
                                  (g->carrier[0] && strcmp(pr->id, g->carrier) == 0));
                if ((pass == 0) != mandatory) continue;
                int slot = t * BB_TEAM_SLOTS + out++;
                bb_player* bp = &m->players[slot];
                bp->skills = pr->skills;
                bp->ma = (int8_t)pr->ma;
                bp->st = (int8_t)pr->st;
                bp->ag = (int8_t)pr->ag;
                bp->pa = (int8_t)pr->pa;
                bp->av = (int8_t)pr->av;
                bp->location = BB_LOC_ON_PITCH;
                bp->stance = pr->state == 0 ? BB_STANCE_STANDING :
                             (pr->state == 1 ? BB_STANCE_PRONE : BB_STANCE_STUNNED);
                bp->x = (uint8_t)pr->x;
                bp->y = (uint8_t)pr->y;
                m->grid[bp->x][bp->y] = (uint8_t)(slot + 1);
                if (pr == att) *att_slot = slot;
                if (pr == def) *def_slot = slot;
                if (g->carrier[0] && strcmp(pr->id, g->carrier) == 0) {
                    *carrier_slot = slot;
                    bp->flags |= BB_PF_HAS_BALL;
                    m->ball.state = BB_BALL_HELD;
                    m->ball.carrier = (uint8_t)slot;
                    m->ball.x = bp->x;
                    m->ball.y = bp->y;
                }
            }
        }
    }
    if (*att_slot < 0 || *def_slot < 0) return -1;
    m->active_team = BB_TEAM_OF(*att_slot);
    if (m->ball.state != BB_BALL_HELD) m->ball.carrier = BB_NO_PLAYER;
    return 0;
}

static int tier_for(const bb_match* m, int att, int def, bool is_blitz, int* off, int* dff) {
    int st_a = m->players[att].st + bb_count_assists(m, att, def);
    int st_d = m->players[def].st + bb_count_assists(m, def, att);
    if (is_blitz) st_a += bb_hook_st_mod_blitz(m, att);
    if (off) *off = bb_count_assists(m, att, def);
    if (dff) *dff = bb_count_assists(m, def, att);
    int nd = 1;
    bool red = false;
    if (st_a > st_d) nd = st_a > 2 * st_d ? 3 : 2;
    else if (st_d > st_a) {
        nd = st_d > 2 * st_a ? 3 : 2;
        red = true;
    }
    return nd == 1 ? 0 : (nd == 2 ? (red ? 3 : 1) : (red ? 4 : 2));
}

static int tier_from_record(const char* line) {
    int nd = (int)jint(line, "nrOfDice", 1);
    bool red = jbool(line, "defenderChooses", false);
    return nd == 1 ? 0 : (nd == 2 ? (red ? 3 : 1) : (red ? 4 : 2));
}

static void update_trackers(game* g, const char* line) {
    char type[32], report[64], id[64];
    if (!jstr(line, "type", type, sizeof type)) return;
    report[0] = 0;
    jstr(line, "report", report, sizeof report);
    if (strcmp(type, "formation") == 0) {
        apply_formation(g, line);
    } else if (strcmp(type, "move") == 0 && jstr(line, "player", id, sizeof id)) {
        int x, y;
        if (jxy(line, "to", &x, &y)) {
            player_rec* pr = find_player(g, id);
            if (pr) {
                pr->x = x;
                pr->y = y;
                if (x < 0 || x >= BB_PITCH_LEN || y < 0 || y >= BB_PITCH_WID) pr->state = 3;
            }
        }
    } else if (strcmp(type, "state") == 0 && jstr(line, "player", id, sizeof id)) {
        player_rec* pr = find_player(g, id);
        int st = state_from_base(jint(line, "base", -1));
        if (pr && st >= 0) {
            pr->state = st;
            if (st >= 3) {
                pr->x = pr->y = -1;
            }
            if (strcmp(g->carrier, id) == 0 && st != 0) g->carrier[0] = 0;
        }
    } else if (strcmp(type, "action") == 0 && strcmp(report, "playerAction") == 0) {
        if (jstr(line, "actingPlayerId", id, sizeof id)) {
            snprintf(g->last_actor, sizeof g->last_actor, "%s", id);
        }
        if (!jstr(line, "playerAction", g->last_action, sizeof g->last_action)) {
            g->last_action[0] = 0;
        }
    } else if (strcmp(type, "dice") == 0 &&
               (strcmp(report, "pickUpRoll") == 0 || strcmp(report, "catchRoll") == 0)) {
        if (jbool(line, "successful", false) && jstr(line, "playerId", id, sizeof id)) {
            snprintf(g->carrier, sizeof g->carrier, "%s", id);
        }
    } else if (strcmp(type, "event") == 0 && strcmp(report, "handOver") == 0) {
        g->carrier[0] = 0;
    } else if (strcmp(type, "event") == 0 && strcmp(report, "startHalf") == 0) {
        g->carrier[0] = 0;
    } else if (strcmp(type, "event") == 0 && strcmp(report, "turnEnd") == 0) {
        char scorer[64];
        if (jstr(line, "playerIdTouchdown", scorer, sizeof scorer)) {
            g->carrier[0] = 0;
        }
    } else if (strcmp(type, "ball") == 0) {
        char mode[32];
        int x, y;
        mode[0] = 0;
        jstr(line, "mode", mode, sizeof mode);
        if (strcmp(mode, "touchback") == 0 && jxy(line, "at", &x, &y)) {
            player_rec* pr = standing_player_at(g, x, y);
            if (pr) snprintf(g->carrier, sizeof g->carrier, "%s", pr->id);
            else g->carrier[0] = 0;
        }
    } else if (strcmp(type, "dice") == 0 && strcmp(report, "passRoll") == 0) {
        g->carrier[0] = 0;
    }
}

static int measure_block(game* g, const char* line, stats* S) {
    char def_id[64];
    if (!g->last_actor[0] || !jstr(line, "defenderId", def_id, sizeof def_id)) {
        S->blocks_skipped++;
        return -1;
    }
    bb_match m;
    int att, def, carrier;
    if (reconstruct_match(g, g->last_actor, def_id, &m, &att, &def, &carrier) != 0) {
        S->blocks_skipped++;
        return -1;
    }
    bool is_blitz = strstr(g->last_action, "blitz") != NULL ||
                    strstr(g->last_action, "Blitz") != NULL;
    int off = 0, dff = 0;
    int engine_tier = tier_for(&m, att, def, is_blitz, &off, &dff);
    if (engine_tier != tier_from_record(line)) S->engine_tier_mismatch++;
    S->blocks_total++;
    S->count[engine_tier]++;
    S->offassist_sum[engine_tier] += off;
    S->defassist_sum[engine_tier] += dff;
    if (carrier >= 0 && def == carrier) S->carrier[engine_tier]++;
    return 0;
}

static int process_file(const char* path, stats* S) {
    FILE* f = fopen(path, "r");
    if (!f) {
        S->malformed++;
        return -1;
    }
    game g;
    memset(&g, 0, sizeof g);
    char line[MAX_LINE];
    if (!fgets(line, sizeof line, f) || parse_meta(&g, line) != 0) {
        fclose(f);
        S->malformed++;
        return -1;
    }
    long before = S->blocks_total;
    long before_count[5], before_carrier[5], before_off[5], before_def[5];
    for (int i = 0; i < 5; i++) {
        before_count[i] = S->count[i];
        before_carrier[i] = S->carrier[i];
        before_off[i] = S->offassist_sum[i];
        before_def[i] = S->defassist_sum[i];
    }
    while (fgets(line, sizeof line, f)) {
        char type[32], report[64];
        if (!jstr(line, "type", type, sizeof type)) continue;
        report[0] = 0;
        jstr(line, "report", report, sizeof report);
        if (strcmp(type, "action") == 0 && strcmp(report, "blockChoice") == 0) {
            measure_block(&g, line, S);
        }
        update_trackers(&g, line);
    }
    fclose(f);
    if (S->blocks_total > before) {
        S->files_used++;
        for (int i = 0; i < 5; i++) {
            long dc = S->count[i] - before_count[i];
            S->game_carrier_frac_sum[i] += frac(S->carrier[i] - before_carrier[i], dc);
            S->game_offassist_mean_sum[i] += frac(S->offassist_sum[i] - before_off[i], dc);
            S->game_defassist_mean_sum[i] += frac(S->defassist_sum[i] - before_def[i], dc);
        }
    }
    return 0;
}

static double frac(long num, long den) {
    return den > 0 ? (double)num / (double)den : 0.0;
}

static double mean_game(double sum, long games) {
    return games > 0 ? sum / (double)games : 0.0;
}

int main(int argc, char** argv) {
    stats S;
    memset(&S, 0, sizeof S);
    if (argc < 2) {
        fprintf(stderr, "usage: %s validation/normalized/*.jsonl\n", argv[0]);
        return 2;
    }
    for (int i = 1; i < argc; i++) {
        S.files_total++;
        process_file(argv[i], &S);
    }
    printf("{\"games_total\":%ld,\"games_used\":%ld,\"malformed_games\":%ld,"
           "\"blocks_total\":%ld,\"blocks_skipped\":%ld,"
           "\"engine_tier_mismatch\":%ld,\"tiers\":{",
           S.files_total, S.files_used, S.malformed, S.blocks_total,
           S.blocks_skipped, S.engine_tier_mismatch);
    const char* names[5] = {"1d", "2d", "3d", "2d-red", "3d-red"};
    for (int i = 0; i < 5; i++) {
        printf("%s\"%s\":{\"count\":%ld,\"carrier_count\":%ld,"
               "\"frac_vs_carrier\":%.9f,\"offassist_sum\":%ld,"
               "\"mean_offassist\":%.9f,\"defassist_sum\":%ld,"
               "\"mean_defassist\":%.9f}",
               i ? "," : "", names[i], S.count[i], S.carrier[i],
               frac(S.carrier[i], S.count[i]), S.offassist_sum[i],
               frac(S.offassist_sum[i], S.count[i]), S.defassist_sum[i],
               frac(S.defassist_sum[i], S.count[i]));
    }
    printf("},\"game_mean_tiers\":{");
    for (int i = 0; i < 5; i++) {
        printf("%s\"%s\":{\"frac_vs_carrier\":%.9f,"
               "\"mean_offassist\":%.9f,\"mean_defassist\":%.9f}",
               i ? "," : "", names[i],
               mean_game(S.game_carrier_frac_sum[i], S.files_used),
               mean_game(S.game_offassist_mean_sum[i], S.files_used),
               mean_game(S.game_defassist_mean_sum[i], S.files_used));
    }
    printf("}}\n");
    return 0;
}

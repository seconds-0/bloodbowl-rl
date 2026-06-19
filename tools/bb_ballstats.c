// bb_ballstats.c - replay one FUMBBL lockstep JSONL through the engine and
// emit ball-advancement stats that mirror the env telemetry.
//
// This is intentionally engine-only: it links the core bb_match objects and
// reimplements the tiny env ball-possession helpers against bb_match, without
// including puffer/bloodbowl/bloodbowl.h.
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/gen_skills.h"
#include "bb/gen_teams.h"

#include <ctype.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_LINE 65536
#define MAX_DICE 64

// --- tiny JSON field scanners (single-line objects from our own mapper) -----

static const char* ls_find_key(const char* s, const char* key) {
    char pat[64];
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
    return 0;
}

static long jint(const char* s, const char* key, long dflt) {
    const char* p = ls_find_key(s, key);
    if (!p) return dflt;
    while (*p == ' ' || *p == '"') p++;
    return strtol(p, 0, 10);
}

static int jstr(const char* s, const char* key, char* out, int cap) {
    const char* p = ls_find_key(s, key);
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

static int jarr(const char* s, const char* key, int* out, int cap) {
    const char* p = ls_find_key(s, key);
    if (!p) return 0;
    while (*p == ' ') p++;
    if (*p != '[') return 0;
    p++;
    int n = 0;
    while (*p && *p != ']' && n < cap) {
        while (*p == ' ' || *p == ',') p++;
        if (*p == ']') break;
        out[n++] = (int)strtol(p, (char**)&p, 10);
    }
    return n;
}

static const char* jobj(const char* s, const char* key) {
    const char* p = ls_find_key(s, key);
    if (!p) return 0;
    while (*p == ' ') p++;
    return *p == '{' ? p : 0;
}

static const char* span(const char* p) {
    char open = *p, close = (open == '{') ? '}' : ']';
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

static void json_escape(const char* in, char* out, int cap) {
    int n = 0;
    for (const char* p = in; *p && n < cap - 4; p++) {
        if (*p == '"' || *p == '\\') out[n++] = '\\';
        if ((unsigned char)*p < 0x20) continue;
        out[n++] = *p;
    }
    out[n] = 0;
}

// --- slug matching (race / skill names vs engine displays) ------------------

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

static int team_id_for_race(const char* race) {
    char want[64], have[64];
    slugify(race, want, sizeof want);
    for (int i = 0; i < BB_TEAM_COUNT; i++) {
        slugify(bb_team_defs[i].display, have, sizeof have);
        if (strcmp(want, have) == 0) return i;
    }
    return -1;
}

static int skill_id_for_name(const char* name) {
    char want[64], have[64];
    slugify(name, want, sizeof want);
    for (int i = 0; i < BB_SKILL_COUNT; i++) {
        slugify(bb_skill_defs[i].display, have, sizeof have);
        if (strcmp(want, have) == 0) return i;
    }
    return -1;
}

// --- ball tracking; mirrors puffer/bloodbowl/bloodbowl.h helpers -------------

typedef struct {
    int possessor;
    double poss_pickup_fwd;
    double poss_path;
    int poss_last_x;
    int poss_last_y;
    double fwd_sum;
    double path_sum;
    int possessions;
} ball_tracker;

static void bt_init(ball_tracker* bt) {
    memset(bt, 0, sizeof *bt);
    bt->possessor = -1;
    bt->poss_last_x = -1;
    bt->poss_last_y = -1;
}

static inline void bt_ball_xy(const bb_match* m, int* x, int* y) {
    if (m->ball.state == BB_BALL_HELD && m->ball.carrier < BB_NUM_PLAYERS) {
        const bb_player* c = &m->players[m->ball.carrier];
        *x = c->x;
        *y = c->y;
    } else {
        *x = m->ball.x;
        *y = m->ball.y;
    }
}

static inline int bt_forward_coord(int team, int x) {
    return bb_endzone_x(team) == 0 ? (BB_PITCH_LEN - 1) - x : x;
}

static inline int bt_cheb_dist(int x0, int y0, int x1, int y1) {
    int dx = x0 > x1 ? x0 - x1 : x1 - x0;
    int dy = y0 > y1 ? y0 - y1 : y1 - y0;
    return dx > dy ? dx : dy;
}

static void bt_start(ball_tracker* bt, int team, int x, int y) {
    bt->possessor = team;
    bt->poss_pickup_fwd = (double)bt_forward_coord(team, x);
    bt->poss_path = 0.0;
    bt->poss_last_x = x;
    bt->poss_last_y = y;
}

static void bt_end(ball_tracker* bt, int x, int y) {
    int team = bt->possessor;
    if (team < 0) return;
    if (bt->poss_last_x >= 0 && bt->poss_last_y >= 0) {
        bt->poss_path +=
            (double)bt_cheb_dist(bt->poss_last_x, bt->poss_last_y, x, y);
    }
    bt->fwd_sum += (double)bt_forward_coord(team, x) - bt->poss_pickup_fwd;
    bt->path_sum += bt->poss_path;
    bt->possessions++;
    bt->possessor = -1;
    bt->poss_pickup_fwd = 0.0;
    bt->poss_path = 0.0;
    bt->poss_last_x = -1;
    bt->poss_last_y = -1;
}

static void bt_update(ball_tracker* bt, const bb_match* m, bool scored) {
    int x, y;
    bt_ball_xy(m, &x, &y);
    if (bt->possessor >= 0 &&
        bt->poss_last_x >= 0 && bt->poss_last_y >= 0) {
        bt->poss_path +=
            (double)bt_cheb_dist(bt->poss_last_x, bt->poss_last_y, x, y);
        bt->poss_last_x = x;
        bt->poss_last_y = y;
    }

    if (m->ball.state == BB_BALL_HELD) {
        int cur = BB_TEAM_OF(m->ball.carrier);
        if (cur != bt->possessor) {
            if (bt->possessor >= 0) bt_end(bt, x, y);
            bt_start(bt, cur, x, y);
        }
        if (scored) bt_end(bt, x, y);
    } else if (m->ball.state == BB_BALL_ON_GROUND && bt->possessor >= 0) {
        bt_end(bt, x, y);
    } else if (m->ball.state == BB_BALL_OFF_PITCH && bt->possessor >= 0) {
        for (int i = 0; i < m->stack_top; i++) {
            if (m->stack[i].proc == BB_PROC_SETUP ||
                m->stack[i].proc == BB_PROC_KICKOFF) {
                bt_end(bt, x, y);
                break;
            }
        }
    }
}

// --- runner state ------------------------------------------------------------

typedef struct {
    char replay[64];
    bb_match m;
    ball_tracker ball;
    int ops_total;
    int ops_applied;
    int skips;
    int initialized;
    int failed;
    long fail_cmd;
    char fail_class[32];
    char fail_reason[256];
    int unmapped_skills;
    int prev_score[2];
    uint32_t last_turn_key;
    int team_turns;
} runner;

static const char* status_name(int st) {
    switch (st) {
        case BB_STATUS_RUNNING: return "RUNNING";
        case BB_STATUS_DECISION: return "DECISION";
        case BB_STATUS_MATCH_OVER: return "MATCH_OVER";
        case BB_STATUS_ERROR: return "ERROR";
    }
    return "?";
}

static void failf(runner* R, long cmd, const char* cls, const char* reason) {
    if (R->failed) return;
    R->failed = 1;
    R->fail_cmd = cmd;
    snprintf(R->fail_class, sizeof R->fail_class, "%s", cls);
    snprintf(R->fail_reason, sizeof R->fail_reason, "%s", reason);
}

static void on_transition(runner* R) {
    bool scored = R->m.score[0] != R->prev_score[0] ||
                  R->m.score[1] != R->prev_score[1];
    bt_update(&R->ball, &R->m, scored);
    R->prev_score[0] = R->m.score[0];
    R->prev_score[1] = R->m.score[1];
}

static void count_team_turn_boundary(runner* R) {
    const bb_match* m = &R->m;
    if (m->status != BB_STATUS_DECISION) return;
    bool in_turn = false;
    for (int i = 0; i < m->stack_top; i++) {
        if (m->stack[i].proc == BB_PROC_TEAM_TURN) {
            in_turn = true;
            break;
        }
    }
    if (!in_turn) return;
    uint32_t key = ((uint32_t)m->half << 24) |
                   ((uint32_t)m->active_team << 16) |
                   ((uint32_t)m->turn[0] << 8) |
                   (uint32_t)m->turn[1];
    if (key == R->last_turn_key) return;
    R->last_turn_key = key;
    R->team_turns++;
}

// --- init -------------------------------------------------------------------

static void init_side(runner* R, const char* obj, int team) {
    char buf[256];
    int tid = 0;
    if (jstr(obj, "race", buf, sizeof buf)) {
        int t = team_id_for_race(buf);
        if (t >= 0) tid = t;
    }
    R->m.team_id[team] = (uint8_t)tid;
    for (int s = 0; s < BB_TEAM_SLOTS; s++) {
        memset(&R->m.players[team * BB_TEAM_SLOTS + s], 0, sizeof(bb_player));
        R->m.players[team * BB_TEAM_SLOTS + s].location = BB_LOC_ABSENT;
    }
    const char* pa = ls_find_key(obj, "players");
    if (!pa) return;
    while (*pa == ' ') pa++;
    if (*pa != '[') return;
    const char* end = span(pa);
    const char* p = pa + 1;
    while (p < end) {
        while (p < end && *p != '{') p++;
        if (p >= end) break;
        const char* pe = span(p);
        char pobj[4096];
        int len = (int)(pe - p);
        if (len >= (int)sizeof pobj) len = sizeof pobj - 1;
        memcpy(pobj, p, len);
        pobj[len] = 0;
        long slot = jint(pobj, "slot", -1);
        if (slot >= 0 && slot < BB_TEAM_SLOTS) {
            bb_player* pl = &R->m.players[team * BB_TEAM_SLOTS + slot];
            memset(pl, 0, sizeof *pl);
            pl->ma = (int8_t)jint(pobj, "ma", 5);
            pl->st = (int8_t)jint(pobj, "st", 3);
            pl->ag = (int8_t)jint(pobj, "ag", 3);
            pl->pa = (int8_t)jint(pobj, "pa", 0);
            pl->av = (int8_t)jint(pobj, "av", 8);
            pl->location = BB_LOC_RESERVES;
            pl->stance = BB_STANCE_STANDING;
            pl->p_loner = 4;
            long pos = jint(pobj, "pos", -1);
            pl->position_id =
                (uint8_t)(pos >= 0 && pos < BB_MAX_POSITIONS ? pos : 0);
            const char* sa = ls_find_key(pobj, "skills");
            if (sa) {
                while (*sa == ' ') sa++;
                if (*sa == '[') {
                    const char* se = span(sa);
                    const char* q = sa;
                    while (q < se) {
                        while (q < se && *q != '"') q++;
                        if (q >= se) break;
                        char name[96];
                        int n = 0;
                        q++;
                        while (q < se && *q != '"' &&
                               n < (int)sizeof name - 1) {
                            if (*q == '\\' && q[1]) q++;
                            name[n++] = *q++;
                        }
                        name[n] = 0;
                        q++;
                        int sid = skill_id_for_name(name);
                        if (sid >= 0) bb_add_skill(&pl->skills, sid);
                        else R->unmapped_skills++;
                    }
                }
            }
            if (pos >= 0 && pos < bb_team_defs[tid].num_positions) {
                const bb_position_def* pd = &bb_team_defs[tid].positions[pos];
                for (int k = 0; k < pd->num_skills; k++) {
                    int v = pd->skill_values[k];
                    if (v > 0 && bb_has_skill(&pl->skills, pd->skills[k])) {
                        if (pd->skills[k] == BB_SK_LONER) pl->p_loner = (int8_t)v;
                        if (pd->skills[k] == BB_SK_BLOODLUST) {
                            pl->p_bloodlust = (int8_t)v;
                        }
                    }
                }
            }
        }
        p = pe;
    }
}

static int do_init(runner* R, const char* line) {
    memset(&R->m, 0, sizeof R->m);
    char rid[64];
    if (jstr(line, "replay", rid, sizeof rid)) {
        snprintf(R->replay, sizeof R->replay, "%s", rid);
    }
    const char* home = jobj(line, "home");
    const char* away = jobj(line, "away");
    if (!home || !away) return -1;
    char hbuf[32768], abuf[32768];
    int hl = (int)(span(home) - home), al = (int)(span(away) - away);
    if (hl >= (int)sizeof hbuf) hl = sizeof hbuf - 1;
    if (al >= (int)sizeof abuf) al = sizeof abuf - 1;
    memcpy(hbuf, home, hl);
    hbuf[hl] = 0;
    memcpy(abuf, away, al);
    abuf[al] = 0;
    init_side(R, hbuf, BB_HOME);
    init_side(R, abuf, BB_AWAY);
    int rr[2] = {3, 3}, apo[2] = {0, 0}, fans[2] = {0, 0};
    jarr(line, "rerolls", rr, 2);
    jarr(line, "apo", apo, 2);
    jarr(line, "fans", fans, 2);
    for (int t = 0; t < 2; t++) {
        R->m.rerolls[t] = R->m.rerolls_start[t] = (uint8_t)rr[t];
        R->m.apothecary[t] = (uint8_t)apo[t];
        R->m.fan_factor[t] = (uint8_t)fans[t];
    }
    R->m.half = 1;
    R->m.ball.state = BB_BALL_OFF_PITCH;
    R->m.ball.carrier = BB_NO_PLAYER;
    R->m.status = BB_STATUS_RUNNING;
    bb_push(&R->m, BB_PROC_MATCH, 0, 0, 0, 0);
    R->prev_score[0] = R->m.score[0];
    R->prev_score[1] = R->m.score[1];
    bt_init(&R->ball);
    return 0;
}

// --- transitions ------------------------------------------------------------

static int check_rng(runner* R, long cmd, const bb_rng* rng, bb_status st, int nd) {
    char reason[256];
    if (bb_rng_error(rng)) {
        snprintf(reason, sizeof reason,
                 "rng error after consuming %d dice from recorded len %d",
                 rng->script_pos, nd);
        failf(R, cmd, "dice", reason);
        return -1;
    }
    if (st == BB_STATUS_ERROR) {
        failf(R, cmd, "status", "engine status ERROR");
        return -1;
    }
    if (rng->script_pos != nd) {
        snprintf(reason, sizeof reason, "engine consumed %d dice; replay recorded %d",
                 rng->script_pos, nd);
        failf(R, cmd, "dice", reason);
        return -1;
    }
    return 0;
}

static int hk_index_for_slot(const bb_match* m, int gslot) {
    int kicking = -1;
    for (int i = 0; i < m->stack_top; i++) {
        if (m->stack[i].proc == BB_PROC_KICKOFF) kicking = m->stack[i].a;
    }
    if (kicking < 0) return -1;
    int receiving = 1 - kicking;
    int idx = 0;
    for (int s = receiving * BB_TEAM_SLOTS; s < (receiving + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location != BB_LOC_ON_PITCH) continue;
        if (p->stance != BB_STANCE_STANDING) continue;
        if (bb_is_marked(m, s)) continue;
        if (s == gslot) return idx;
        idx++;
    }
    return -1;
}

static int do_act(runner* R, const char* line, long cmd) {
    char reason[256];
    if (R->m.status != BB_STATUS_DECISION) {
        snprintf(reason, sizeof reason, "engine status %s, no decision pending",
                 status_name(R->m.status));
        failf(R, cmd, "status", reason);
        return -1;
    }
    bb_action a;
    a.type = (uint8_t)jint(line, "type", 0);
    a.arg = (uint8_t)jint(line, "arg", 0);
    a.x = (uint8_t)jint(line, "x", 0);
    a.y = (uint8_t)jint(line, "y", 0);
    int hk[2];
    if (a.type == BB_A_CHOOSE_OPTION && jarr(line, "hk", hk, 2) == 2) {
        int idx = hk_index_for_slot(&R->m, hk[0] * BB_TEAM_SLOTS + hk[1]);
        if (idx < 0) {
            failf(R, cmd, "illegal", "high-kick candidate not legal");
            return -1;
        }
        a.arg = (uint8_t)idx;
    }
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&R->m, legal);
    bool ok = false;
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(legal[i], a)) {
            ok = true;
            break;
        }
    }
    if (!ok) {
        snprintf(reason, sizeof reason,
                 "illegal action (%d,%d,%d,%d); %d legal actions",
                 a.type, a.arg, a.x, a.y, n);
        failf(R, cmd, "illegal", reason);
        return -1;
    }
    int dice[MAX_DICE];
    int nd = jarr(line, "dice", dice, MAX_DICE);
    uint8_t script[MAX_DICE];
    for (int i = 0; i < nd; i++) {
        script[i] = (uint8_t)(dice[i] < 0 ? 0 : (dice[i] > 255 ? 255 : dice[i]));
    }
    bb_rng rng;
    bb_rng_script(&rng, script, nd);
    bb_status st = bb_apply(&R->m, a, &rng);
    int rc = check_rng(R, cmd, &rng, st, nd);
    if (rc == 0) on_transition(R);
    return rc;
}

static int do_place(runner* R, const char* line, long cmd) {
    char reason[256];
    long team = jint(line, "team", 0), slot = jint(line, "slot", 0);
    long x = jint(line, "x", 0), y = jint(line, "y", 0);
    bb_action a = {BB_A_SETUP_PLACE, (uint8_t)(team * BB_TEAM_SLOTS + slot),
                   (uint8_t)x, (uint8_t)y};
    if (R->m.status != BB_STATUS_DECISION) {
        snprintf(reason, sizeof reason, "engine status %s during setup placement",
                 status_name(R->m.status));
        failf(R, cmd, "status", reason);
        return -1;
    }
    bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&R->m, legal);
    bool ok = false;
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(legal[i], a)) {
            ok = true;
            break;
        }
    }
    if (!ok) {
        snprintf(reason, sizeof reason,
                 "illegal setup placement team=%ld slot=%ld x=%ld y=%ld; %d legal",
                 team, slot, x, y, n);
        failf(R, cmd, "illegal", reason);
        return -1;
    }
    uint8_t script[MAX_DICE];
    bb_rng rng;
    bb_rng_script(&rng, script, 0);
    bb_status st = bb_apply(&R->m, a, &rng);
    int rc = check_rng(R, cmd, &rng, st, 0);
    if (rc == 0) on_transition(R);
    return rc;
}

static int engine_state_code(const bb_player* p) {
    switch (p->location) {
        case BB_LOC_ON_PITCH:
            if (p->stance == BB_STANCE_STANDING) return 0;
            if (p->stance == BB_STANCE_PRONE) return 1;
            return 2;
        case BB_LOC_RESERVES: return 3;
        case BB_LOC_KO: return 4;
        case BB_LOC_CAS: return 5;
        case BB_LOC_SENT_OFF: return 6;
        case BB_LOC_ABSENT: return 7;
    }
    return -1;
}

static int do_expect(runner* R, const char* line, long cmd) {
    char reason[256];
    const char* pa = ls_find_key(line, "players");
    if (pa) {
        while (*pa == ' ') pa++;
        if (*pa == '[') {
            const char* end = span(pa);
            const char* p = pa + 1;
            while (p < end) {
                while (p < end && *p != '[') p++;
                if (p >= end) break;
                const char* pe = span(p);
                int v[5] = {0, 0, 255, 255, -1};
                int n = 0;
                const char* q = p + 1;
                while (q < pe && n < 5) {
                    while (q < pe && (*q == ' ' || *q == ',')) q++;
                    if (*q == ']') break;
                    v[n++] = (int)strtol(q, (char**)&q, 10);
                }
                p = pe;
                if (n < 5) continue;
                int gslot = v[0] * BB_TEAM_SLOTS + v[1];
                if (gslot < 0 || gslot >= BB_NUM_PLAYERS) continue;
                const bb_player* pl = &R->m.players[gslot];
                int ecode = engine_state_code(pl);
                if (v[4] >= 0 && ecode >= 0 && ecode != v[4]) {
                    snprintf(reason, sizeof reason,
                             "player[%d,%d] state engine=%d replay=%d",
                             v[0], v[1], ecode, v[4]);
                    failf(R, cmd, "state", reason);
                    return -1;
                }
                if (v[2] != 255 && pl->location == BB_LOC_ON_PITCH &&
                    (pl->x != v[2] || pl->y != v[3])) {
                    snprintf(reason, sizeof reason,
                             "player[%d,%d] pos engine=%d,%d replay=%d,%d",
                             v[0], v[1], pl->x, pl->y, v[2], v[3]);
                    failf(R, cmd, "position", reason);
                    return -1;
                }
            }
        }
    }
    int ball[3] = {255, 255, -1};
    if (jarr(line, "ball", ball, 3) == 3 && ball[0] != 255) {
        int held = R->m.ball.state == BB_BALL_HELD;
        int onp = R->m.ball.state == BB_BALL_HELD ||
                  R->m.ball.state == BB_BALL_ON_GROUND;
        if (onp && (R->m.ball.x != ball[0] || R->m.ball.y != ball[1])) {
            snprintf(reason, sizeof reason, "ball engine=%d,%d replay=%d,%d",
                     R->m.ball.x, R->m.ball.y, ball[0], ball[1]);
            failf(R, cmd, "ball", reason);
            return -1;
        }
        if (ball[2] >= 0 && onp && held != ball[2]) {
            snprintf(reason, sizeof reason, "ball held engine=%d replay=%d",
                     held, ball[2]);
            failf(R, cmd, "ball", reason);
            return -1;
        }
    }
    int score[2];
    if (jarr(line, "score", score, 2) == 2) {
        if (R->m.score[0] != score[0] || R->m.score[1] != score[1]) {
            snprintf(reason, sizeof reason, "score engine=%d-%d replay=%d-%d",
                     R->m.score[0], R->m.score[1], score[0], score[1]);
            failf(R, cmd, "score", reason);
            return -1;
        }
    }
    return 0;
}

// --- output -----------------------------------------------------------------

static void print_result(const runner* R, const char* path) {
    char esc_path[1024], esc_replay[128], esc_class[64], esc_reason[512];
    json_escape(path, esc_path, sizeof esc_path);
    json_escape(R->replay, esc_replay, sizeof esc_replay);
    json_escape(R->fail_class, esc_class, sizeof esc_class);
    json_escape(R->fail_reason, esc_reason, sizeof esc_reason);
    printf("{\"replay\":\"%s\",\"path\":\"%s\",\"success\":%s,"
           "\"ops_total\":%d,\"ops_applied\":%d,\"skips\":%d,"
           "\"engine_status\":\"%s\",\"engine_score\":[%d,%d],"
           "\"team_turns\":%d,\"possessions\":%d,"
           "\"ball_fwd_adv\":%.9g,\"ball_path_len\":%.9g,"
           "\"unmapped_skills\":%d",
           esc_replay, esc_path, R->failed ? "false" : "true",
           R->ops_total, R->ops_applied, R->skips,
           status_name(R->m.status), R->m.score[0], R->m.score[1],
           R->team_turns, R->ball.possessions, R->ball.fwd_sum,
           R->ball.path_sum, R->unmapped_skills);
    if (R->failed) {
        printf(",\"fail_cmd\":%ld,\"fail_class\":\"%s\",\"fail_reason\":\"%s\"",
               R->fail_cmd, esc_class, esc_reason);
    }
    printf("}\n");
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: bb_ballstats <script.jsonl>\n");
        return 2;
    }
    const char* path = argv[1];
    FILE* f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return 2;
    }
    runner R;
    memset(&R, 0, sizeof R);
    snprintf(R.replay, sizeof R.replay, "?");
    bt_init(&R.ball);
    static char line[MAX_LINE];
    bool inited = false;
    long last_cmd = 0;
    while (fgets(line, sizeof line, f)) {
        size_t len = strlen(line);
        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r')) line[--len] = 0;
        if (!len) continue;
        char op[16];
        if (!jstr(line, "op", op, sizeof op)) continue;
        R.ops_total++;
        long cmd = jint(line, "cmd", last_cmd);
        last_cmd = cmd;
        if (strcmp(op, "skip") == 0) {
            R.skips++;
            R.ops_applied++;
            continue;
        }
        if (R.failed) continue;
        int rc = 0;
        if (strcmp(op, "init") == 0) {
            rc = do_init(&R, line);
            if (rc == 0) {
                inited = true;
                R.initialized = 1;
                int dice[MAX_DICE];
                int nd = jarr(line, "dice", dice, MAX_DICE);
                uint8_t script[MAX_DICE];
                for (int i = 0; i < nd; i++) script[i] = (uint8_t)dice[i];
                bb_rng rng;
                bb_rng_script(&rng, script, nd);
                bb_status st = bb_advance(&R.m, &rng);
                rc = check_rng(&R, cmd, &rng, st, nd);
                if (rc == 0) {
                    long w = jint(line, "weather", -1);
                    if (w >= 0 && R.m.weather != (uint8_t)w) {
                        char reason[128];
                        snprintf(reason, sizeof reason,
                                 "weather engine=%d replay=%ld", R.m.weather, w);
                        failf(&R, cmd, "state", reason);
                        rc = -1;
                    } else {
                        on_transition(&R);
                    }
                }
            } else {
                failf(&R, cmd, "status", "init op unparseable");
            }
        } else if (!inited) {
            failf(&R, cmd, "status", "op before init");
            rc = -1;
        } else if (strcmp(op, "place") == 0) {
            rc = do_place(&R, line, cmd);
        } else if (strcmp(op, "act") == 0) {
            rc = do_act(&R, line, cmd);
        } else if (strcmp(op, "expect") == 0) {
            rc = do_expect(&R, line, cmd);
        }
        if (rc == 0) {
            R.ops_applied++;
            count_team_turn_boundary(&R);
        }
    }
    fclose(f);
    if (!R.failed && !R.initialized) {
        failf(&R, last_cmd, "status", "missing init op");
    }
    if (!R.failed && R.m.status != BB_STATUS_MATCH_OVER) {
        failf(&R, last_cmd, "status", "replay ended before engine MATCH_OVER");
    }
    if (!R.failed && R.ball.possessor >= 0) {
        int x, y;
        bt_ball_xy(&R.m, &x, &y);
        bt_end(&R.ball, x, y);
    }
    print_result(&R, path);
    return 0;
}

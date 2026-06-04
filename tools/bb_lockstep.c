// bb_lockstep.c — FUMBBL->engine lockstep differential runner (layer 7, v0).
//
// Reads a lockstep script JSONL produced by validation/lockstep_map.py and
// replays it through the real engine: bb_match constructed from the init op,
// every act op legality-checked against bb_legal_actions and applied with its
// FUMBBL-recorded dice in a fresh bb_rng SCRIPT, every expect op diffed
// against engine state.
//
// DIVERGENCE IS DATA, NOT ERROR: the first divergence is reported as one
// machine-readable JSON line
//   {"replay":..,"cmd":..,"class":"position|state|ball|score|illegal|
//    dice_underrun|dice_overrun|status","ours":..,"theirs":..,"context":[..]}
// then a summary line {"summary":true,...} and exit 0. A full-consumption run
// emits only the summary.
//
// Op schema: see the header of validation/lockstep_map.py. Dice attached to an
// op are exactly the values the engine consumes during that op's
// apply+advance transition; init dice cover the very first bb_advance
// (pregame weather 2d6 + coin d2).
// Built as a single translation unit through the PufferLib env amalgamation
// (bloodbowl.h #includes every engine .c): the runner links no objects and
// gains the EXACT observation/mask encoders training uses (bbe_encode_obs,
// bbe_fill_mask, bbe_action_arg/bbe_action_sq) for --dump-pairs.
#include "bloodbowl.h"
#include <ctype.h>
#include <stdio.h>

#define MAX_LINE 65536
#define MAX_DICE 64
#define CTX_OPS 3

// --- tiny JSON field scanners (single-line objects from our own mapper) ------

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
            // top-level key match only (depth 1 = inside the op object)
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

// Parse an int array "key":[a,b,...]; returns count.
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

// Find the start of a top-level object value for `key` ("home"/"away").
static const char* jobj(const char* s, const char* key) {
    const char* p = ls_find_key(s, key);
    if (!p) return 0;
    while (*p == ' ') p++;
    return *p == '{' ? p : 0;
}

// Span of a {...} or [...] starting at p (returns one past the close).
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

// --- slug matching (race / skill names vs engine displays) -------------------

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

// --- runner state -------------------------------------------------------------

typedef struct {
    char replay[64];
    bb_match m;
    int ops_total, ops_applied, skips;
    int diverged;
    char ctx[CTX_OPS][512];
    int ctx_n;
    int unmapped_skills;
    // -v / --pad
    int verbose;
    int pad;
    long cur_cmd;
    int die_idx;
    int orig_nd;       // FUMBBL-recorded dice for the current op (pre-pad)
    const char* cur_op;
} runner;

static void ctx_push(runner* R, const char* line) {
    if (R->ctx_n < CTX_OPS) {
        snprintf(R->ctx[R->ctx_n++], sizeof R->ctx[0], "%s", line);
    } else {
        memmove(R->ctx[0], R->ctx[1], sizeof R->ctx[0] * (CTX_OPS - 1));
        snprintf(R->ctx[CTX_OPS - 1], sizeof R->ctx[0], "%s", line);
    }
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

static void report_divergence(runner* R, long cmd, const char* cls,
                              const char* ours, const char* theirs) {
    if (R->diverged) return;
    R->diverged = 1;
    char o[512], t[512], c[CTX_OPS][1024];
    json_escape(ours, o, sizeof o);
    json_escape(theirs, t, sizeof t);
    for (int i = 0; i < R->ctx_n; i++) json_escape(R->ctx[i], c[i], sizeof c[i]);
    printf("{\"replay\":\"%s\",\"cmd\":%ld,\"class\":\"%s\",\"ours\":\"%s\","
           "\"theirs\":\"%s\",\"context\":[",
           R->replay, cmd, cls, o, t);
    for (int i = 0; i < R->ctx_n; i++) {
        printf("%s\"%s\"", i ? "," : "", c[i]);
    }
    printf("]}\n");
}

// --- init -----------------------------------------------------------------------

static void init_side(runner* R, const char* obj, int team) {
    char buf[256];
    int tid = 0;
    if (jstr(obj, "race", buf, sizeof buf)) {
        int t = team_id_for_race(buf);
        if (t >= 0) tid = t;
    }
    R->m.team_id[team] = (uint8_t)tid;
    // Mark all slots absent, then fill from the players array.
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
            pl->position_id = (uint8_t)(pos >= 0 && pos < BB_MAX_POSITIONS ? pos : 0);
            // skills: array of canonical display names
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
                        while (q < se && *q != '"' && n < (int)sizeof name - 1) {
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
            // Parameterized skill values from the resolved roster position.
            if (pos >= 0 && pos < bb_team_defs[tid].num_positions) {
                const bb_position_def* pd = &bb_team_defs[tid].positions[pos];
                for (int k = 0; k < pd->num_skills; k++) {
                    int v = pd->skill_values[k];
                    if (v > 0 && bb_has_skill(&pl->skills, pd->skills[k])) {
                        if (pd->skills[k] == BB_SK_LONER) pl->p_loner = (int8_t)v;
                        if (pd->skills[k] == BB_SK_BLOODLUST) pl->p_bloodlust = (int8_t)v;
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
    // span-copy each side so nested key scans stay inside it
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
    int rr[2] = {3, 3}, apo[2] = {0, 0};
    jarr(line, "rerolls", rr, 2);
    jarr(line, "apo", apo, 2);
    for (int t = 0; t < 2; t++) {
        R->m.rerolls[t] = R->m.rerolls_start[t] = (uint8_t)rr[t];
        R->m.apothecary[t] = (uint8_t)apo[t];
    }
    R->m.half = 1;
    R->m.ball.state = BB_BALL_OFF_PITCH;
    R->m.ball.carrier = BB_NO_PLAYER;
    R->m.status = BB_STATUS_RUNNING;
    bb_push(&R->m, BB_PROC_MATCH, 0, 0, 0, 0);
    return 0;
}

// --- dice transitions --------------------------------------------------------------

static const char* PROC_NAMES[] = {
    "NONE", "MATCH", "PREGAME", "SETUP", "KICKOFF", "TEAM_TURN", "ACTIVATION",
    "MOVE", "DODGE", "RUSH", "PICKUP", "BLOCK", "PUSH", "KNOCKDOWN", "ARMOUR",
    "INJURY", "CASUALTY", "PASS", "CATCH", "SCATTER", "THROW_IN", "HANDOFF",
    "FOUL", "TTM", "TEST", "TOUCHDOWN", "TURNOVER", "END_DRIVE", "KO_RECOVERY",
};

static void print_stack(FILE* out, const bb_match* m) {
    for (int i = 0; i < m->stack_top; i++) {
        const bb_frame* f = &m->stack[i];
        fprintf(out, "%s%s.%d(%d,%d)", i ? ">" : "",
                f->proc < BB_PROC_COUNT ? PROC_NAMES[f->proc] : "?",
                f->phase, f->a, f->b);
    }
}

// -v dice sink: one stderr line per consumed die, tagged with the live proc
// stack at roll time. Dice past the FUMBBL-recorded count (--pad fillers)
// are flagged EXTRA — the first EXTRA line is the roll that would have
// underrun the script.
static void dice_sink(void* user, int sides, int value) {
    runner* R = user;
    fprintf(stderr, "[die] cmd=%ld op=%s #%d d%d=%d%s stack=",
            R->cur_cmd, R->cur_op ? R->cur_op : "?", R->die_idx, sides, value,
            R->die_idx >= R->orig_nd ? " EXTRA" : "");
    print_stack(stderr, &R->m);
    fprintf(stderr, "\n");
    R->die_idx++;
}

// Arm the rng for one op transition: verbose sink + --pad filler dice.
// Returns the script length actually installed (orig nd + pad).
static int arm_rng(runner* R, bb_rng* rng, uint8_t* script, int nd,
                   long cmd, const char* opname) {
    int total = nd;
    for (int i = 0; i < R->pad && total < MAX_DICE; i++) {
        script[total++] = 1; // valid face for every die type
    }
    bb_rng_script(rng, script, total);
    R->cur_cmd = cmd;
    R->cur_op = opname;
    R->die_idx = 0;
    R->orig_nd = nd;
    if (R->verbose) bb_rng_set_sink(rng, dice_sink, R);
    return total;
}

static const char* status_name(int st) {
    switch (st) {
        case BB_STATUS_RUNNING: return "RUNNING";
        case BB_STATUS_DECISION: return "DECISION";
        case BB_STATUS_MATCH_OVER: return "MATCH_OVER";
        case BB_STATUS_ERROR: return "ERROR";
    }
    return "?";
}

// Returns 0 ok; on divergence reports and returns -1.
// NOTE: bb_rng script exhaustion does NOT stop the engine (it feeds 1s and
// latches rng->error), so the rng error must be checked on every transition,
// not only when the status is ERROR. Under/overrun is judged against the
// FUMBBL-recorded count (R->orig_nd), not the --pad-extended script, so
// padding never changes what is reported.
static int check_transition(runner* R, long cmd, bb_rng* rng, bb_status st) {
    char ours[256], theirs[256];
    int nd = R->orig_nd;
    if (bb_rng_error(rng)) {
        if (rng->script_pos >= rng->script_len) {
            snprintf(ours, sizeof ours,
                     "engine demanded die %d of script len %d",
                     rng->script_pos, nd);
            snprintf(theirs, sizeof theirs, "FUMBBL recorded %d dice", nd);
            report_divergence(R, cmd, "dice_underrun", ours, theirs);
        } else {
            snprintf(ours, sizeof ours,
                     "die %d (value %d) out of range for the roll demanded",
                     rng->script_pos, rng->script[rng->script_pos - 1]);
            snprintf(theirs, sizeof theirs, "FUMBBL dice misattached");
            report_divergence(R, cmd, "dice_misfit", ours, theirs);
        }
        return -1;
    }
    if (rng->script_pos > nd) {
        snprintf(ours, sizeof ours, "engine demanded die %d of script len %d",
                 rng->script_pos, nd);
        snprintf(theirs, sizeof theirs, "FUMBBL recorded %d dice", nd);
        report_divergence(R, cmd, "dice_underrun", ours, theirs);
        return -1;
    }
    if (st == BB_STATUS_ERROR) {
        snprintf(ours, sizeof ours, "engine status ERROR");
        report_divergence(R, cmd, "status", ours, "transition expected to succeed");
        return -1;
    }
    if (rng->script_pos < nd) {
        snprintf(ours, sizeof ours, "engine consumed %d dice", rng->script_pos);
        snprintf(theirs, sizeof theirs, "FUMBBL recorded %d dice for this op",
                 nd);
        report_divergence(R, cmd, "dice_overrun", ours, theirs);
        return -1;
    }
    return 0;
}

// --- high kick candidate index (mirrors proc_match.c high_kick_candidates) -----

static int hk_index_for_slot(const bb_match* m, int gslot) {
    // KICKOFF frame: a = kicking team; phase 4 active.
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

// --- expect -------------------------------------------------------------------------

static int engine_state_code(const bb_player* p) {
    switch (p->location) {
        case BB_LOC_ON_PITCH:
            if (p->stance == BB_STANCE_STANDING) return 0;
            if (p->stance == BB_STANCE_PRONE) return 1;
            return 2; // stunned / stunned_used
        case BB_LOC_RESERVES: return 3;
        case BB_LOC_KO: return 4;
        case BB_LOC_CAS: return 5;
        case BB_LOC_SENT_OFF: return 6;
    }
    return -1;
}

static int do_expect(runner* R, const char* line, long cmd) {
    char ours[256], theirs[256];
    // players: [[t,s,x,y,st],...] — walk the array entry by entry.
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
                    snprintf(ours, sizeof ours, "player[%d,%d] state=%d",
                             v[0], v[1], ecode);
                    snprintf(theirs, sizeof theirs, "state=%d", v[4]);
                    report_divergence(R, cmd, "state", ours, theirs);
                    return -1;
                }
                if (v[2] != 255 && pl->location == BB_LOC_ON_PITCH &&
                    (pl->x != v[2] || pl->y != v[3])) {
                    snprintf(ours, sizeof ours, "player[%d,%d] at %d,%d",
                             v[0], v[1], pl->x, pl->y);
                    snprintf(theirs, sizeof theirs, "at %d,%d", v[2], v[3]);
                    report_divergence(R, cmd, "position", ours, theirs);
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
            snprintf(ours, sizeof ours, "ball at %d,%d (held=%d)",
                     R->m.ball.x, R->m.ball.y, held);
            snprintf(theirs, sizeof theirs, "ball at %d,%d (held=%d)",
                     ball[0], ball[1], ball[2]);
            report_divergence(R, cmd, "ball", ours, theirs);
            return -1;
        }
        if (ball[2] >= 0 && onp && held != ball[2]) {
            snprintf(ours, sizeof ours, "ball held=%d", held);
            snprintf(theirs, sizeof theirs, "ball held=%d", ball[2]);
            report_divergence(R, cmd, "ball", ours, theirs);
            return -1;
        }
    }
    int score[2];
    if (jarr(line, "score", score, 2) == 2) {
        if (R->m.score[0] != score[0] || R->m.score[1] != score[1]) {
            snprintf(ours, sizeof ours, "score %d-%d", R->m.score[0], R->m.score[1]);
            snprintf(theirs, sizeof theirs, "score %d-%d", score[0], score[1]);
            report_divergence(R, cmd, "score", ours, theirs);
            return -1;
        }
    }
    return 0;
}

// --- act ----------------------------------------------------------------------------

static int do_act(runner* R, const char* line, long cmd) {
    char ours[512], theirs[256];
    if (R->m.status != BB_STATUS_DECISION) {
        snprintf(ours, sizeof ours, "engine status %s, no decision pending",
                 status_name(R->m.status));
        snprintf(theirs, sizeof theirs, "act op type=%ld arg=%ld",
                 jint(line, "type", 0), jint(line, "arg", 0));
        report_divergence(R, cmd, "status", ours, theirs);
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
            snprintf(ours, sizeof ours, "player [%d,%d] not a High Kick candidate",
                     hk[0], hk[1]);
            report_divergence(R, cmd, "illegal", ours, "FUMBBL placed them under the ball");
            return -1;
        }
        a.arg = (uint8_t)idx;
    }
    static bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&R->m, legal);
    bool ok = false;
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(legal[i], a)) {
            ok = true;
            break;
        }
    }
    if (!ok) {
        int off = snprintf(ours, sizeof ours,
                           "action not legal; %d legal, first:", n);
        for (int i = 0; i < n && i < 5 && off < (int)sizeof ours - 24; i++) {
            off += snprintf(ours + off, sizeof ours - off, " (%d,%d,%d,%d)",
                            legal[i].type, legal[i].arg, legal[i].x, legal[i].y);
        }
        snprintf(theirs, sizeof theirs, "FUMBBL action (%d,%d,%d,%d)",
                 a.type, a.arg, a.x, a.y);
        report_divergence(R, cmd, "illegal", ours, theirs);
        return -1;
    }
    int dice[MAX_DICE];
    int nd = jarr(line, "dice", dice, MAX_DICE);
    uint8_t script[MAX_DICE];
    for (int i = 0; i < nd; i++) {
        script[i] = (uint8_t)(dice[i] < 0 ? 0 : (dice[i] > 255 ? 255 : dice[i]));
    }
    bb_rng rng;
    arm_rng(R, &rng, script, nd, cmd, "act");
    bb_status st = bb_apply(&R->m, a, &rng);
    return check_transition(R, cmd, &rng, st);
}

static int do_place(runner* R, const char* line, long cmd) {
    char ours[512], theirs[256];
    long team = jint(line, "team", 0), slot = jint(line, "slot", 0);
    long x = jint(line, "x", 0), y = jint(line, "y", 0);
    bb_action a = {BB_A_SETUP_PLACE, (uint8_t)(team * BB_TEAM_SLOTS + slot),
                   (uint8_t)x, (uint8_t)y};
    if (R->m.status != BB_STATUS_DECISION) {
        snprintf(ours, sizeof ours, "engine status %s during setup placement",
                 status_name(R->m.status));
        report_divergence(R, cmd, "status", ours, "place op");
        return -1;
    }
    static bb_action legal[BB_LEGAL_MAX];
    int n = bb_legal_actions(&R->m, legal);
    bool ok = false;
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(legal[i], a)) {
            ok = true;
            break;
        }
    }
    if (!ok) {
        snprintf(ours, sizeof ours, "SETUP_PLACE slot %ld.%ld -> %ld,%ld not legal "
                 "(%d legal actions)", team, slot, x, y, n);
        snprintf(theirs, sizeof theirs, "FUMBBL formation square");
        report_divergence(R, cmd, "illegal", ours, theirs);
        return -1;
    }
    bb_rng rng;
    uint8_t script[MAX_DICE];
    arm_rng(R, &rng, script, 0, cmd, "place");
    bb_status st = bb_apply(&R->m, a, &rng);
    return check_transition(R, cmd, &rng, st);
}

// --- trace (debug) -------------------------------------------------------------------

static void trace_state(const runner* R, long cmd, const char* op) {
    fprintf(stderr, "cmd=%ld %s st=%s act=%d turn=[%d,%d] stack=", cmd, op,
            status_name(R->m.status), R->m.active_team, R->m.turn[0],
            R->m.turn[1]);
    print_stack(stderr, &R->m);
    fprintf(stderr, "\n");
}

// --- main --------------------------------------------------------------------------

int main(int argc, char** argv) {
    runner R;
    memset(&R, 0, sizeof R);
    const char* path = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-v") == 0) R.verbose = 1;
        else if (strcmp(argv[i], "--pad") == 0 && i + 1 < argc) {
            R.pad = (int)strtol(argv[++i], 0, 10);
        } else path = argv[i];
    }
    if (!path) {
        fprintf(stderr,
                "usage: bb_lockstep [-v] [--pad N] <script.jsonl>\n"
                "  -v       stderr line per consumed die with the live proc stack\n"
                "  --pad N  append N filler dice (value 1) per op so the roll that\n"
                "           would underrun shows up as an EXTRA die in -v output;\n"
                "           reported divergences are unchanged\n");
        return 2;
    }
    FILE* f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return 2;
    }
    snprintf(R.replay, sizeof R.replay, "?");
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
            R.ops_applied++; // skips are accounted, not applied to the engine
            continue;
        }
        if (R.diverged) continue; // keep counting ops_total for % consumed
        int rc = 0;
        if (strcmp(op, "init") == 0) {
            rc = do_init(&R, line);
            if (rc == 0) {
                inited = true;
                int dice[MAX_DICE];
                int nd = jarr(line, "dice", dice, MAX_DICE);
                uint8_t script[MAX_DICE];
                for (int i = 0; i < nd; i++) script[i] = (uint8_t)dice[i];
                bb_rng rng;
                arm_rng(&R, &rng, script, nd, cmd, "init");
                bb_status st = bb_advance(&R.m, &rng);
                rc = check_transition(&R, cmd, &rng, st);
                if (rc == 0) {
                    long w = jint(line, "weather", -1);
                    if (w >= 0 && R.m.weather != (uint8_t)w) {
                        char ours[128], theirs[128];
                        snprintf(ours, sizeof ours, "weather=%d after pregame",
                                 R.m.weather);
                        snprintf(theirs, sizeof theirs, "FUMBBL weather=%ld", w);
                        report_divergence(&R, cmd, "state", ours, theirs);
                        rc = -1;
                    }
                }
            } else {
                report_divergence(&R, cmd, "status", "init op unparseable", line);
            }
        } else if (!inited) {
            report_divergence(&R, cmd, "status", "op before init", op);
            rc = -1;
        } else if (strcmp(op, "place") == 0) {
            rc = do_place(&R, line, cmd);
        } else if (strcmp(op, "act") == 0) {
            rc = do_act(&R, line, cmd);
        } else if (strcmp(op, "expect") == 0) {
            rc = do_expect(&R, line, cmd);
        }
        if (rc == 0) R.ops_applied++;
        if (getenv("BB_LOCKSTEP_TRACE")) trace_state(&R, cmd, op);
        ctx_push(&R, line);
    }
    fclose(f);
    double pct = R.ops_total ? 100.0 * R.ops_applied / R.ops_total : 0.0;
    printf("{\"summary\":true,\"replay\":\"%s\",\"ops_total\":%d,"
           "\"ops_applied\":%d,\"pct_consumed\":%.1f,\"skips\":%d,"
           "\"diverged\":%s,\"engine_score\":[%d,%d],\"engine_status\":\"%s\","
           "\"unmapped_skills\":%d}\n",
           R.replay, R.ops_total, R.ops_applied, pct, R.skips,
           R.diverged ? "true" : "false", R.m.score[0], R.m.score[1],
           status_name(R.m.status), R.unmapped_skills);
    return 0;
}

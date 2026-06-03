#include "bb/bb_replay.h"
#include "bb/gen_teams.h"
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

int bb_replay_open(bb_replay_writer* w, const char* path) {
    w->f = fopen(path, "w");
    return w->f ? 0 : -1;
}

void bb_replay_init_record(bb_replay_writer* w, int home, int away, uint64_t seed) {
    fprintf(w->f, "{\"t\":\"init\",\"v\":%d,\"home\":%d,\"away\":%d,\"seed\":%" PRIu64 "}\n",
            BB_REPLAY_VERSION, home, away, seed);
}

void bb_replay_action(bb_replay_writer* w, bb_action a) {
    fprintf(w->f, "{\"t\":\"a\",\"u\":%u}\n", bb_action_pack(a));
}

void bb_replay_dice(bb_replay_writer* w, int sides, int value) {
    fprintf(w->f, "{\"t\":\"d\",\"s\":%d,\"v\":%d}\n", sides, value);
}

void bb_replay_end_record(bb_replay_writer* w, int hs, int as) {
    fprintf(w->f, "{\"t\":\"end\",\"home_score\":%d,\"away_score\":%d}\n", hs, as);
}

void bb_replay_close(bb_replay_writer* w) {
    if (w->f) fclose(w->f);
    w->f = 0;
}

void bb_replay_dice_sink(void* user, int sides, int value) {
    bb_replay_dice((bb_replay_writer*)user, sides, value);
}

// --- Reader -------------------------------------------------------------------
// Minimal parser for the fixed JSONL schema above. Not a general JSON parser.

void bb_replay_reader_init(bb_replay_reader* r, const char* buf, size_t len) {
    r->buf = buf;
    r->len = len;
    r->pos = 0;
    r->line = 0;
}

// Find "key": in the current line segment; return pointer just past the colon,
// or NULL.
static const char* find_key(const char* s, const char* end, const char* key) {
    size_t klen = strlen(key);
    for (const char* p = s; p + klen + 3 <= end; p++) {
        if (p[0] == '"' && memcmp(p + 1, key, klen) == 0 && p[1 + klen] == '"') {
            const char* q = p + klen + 2;
            while (q < end && (*q == ' ' || *q == ':')) {
                if (*q == ':') return q + 1;
                q++;
            }
        }
    }
    return 0;
}

static int64_t parse_int(const char* p, const char* end) {
    while (p < end && (*p == ' ' || *p == '"')) p++;
    int neg = 0;
    if (p < end && *p == '-') { neg = 1; p++; }
    int64_t v = 0;
    while (p < end && *p >= '0' && *p <= '9') v = v * 10 + (*p++ - '0');
    return neg ? -v : v;
}

static uint64_t parse_u64(const char* p, const char* end) {
    while (p < end && (*p == ' ' || *p == '"')) p++;
    uint64_t v = 0;
    while (p < end && *p >= '0' && *p <= '9') v = v * 10 + (uint64_t)(*p++ - '0');
    return v;
}

bool bb_replay_next(bb_replay_reader* r, bb_record* out) {
    memset(out, 0, sizeof(*out));
    // Skip blank lines.
    while (r->pos < r->len && (r->buf[r->pos] == '\n' || r->buf[r->pos] == '\r')) r->pos++;
    if (r->pos >= r->len) {
        out->type = BB_REC_EOF;
        return false;
    }
    const char* s = r->buf + r->pos;
    const char* end = s;
    const char* lim = r->buf + r->len;
    while (end < lim && *end != '\n') end++;
    r->pos = (size_t)(end - r->buf) + 1;
    r->line++;

    const char* t = find_key(s, end, "t");
    if (!t) { out->type = BB_REC_PARSE_ERROR; return false; }
    while (t < end && (*t == ' ' || *t == '"')) t++;

    if (*t == 'i') { // init
        const char* p;
        int64_t home = -1, away = -1; // missing key = malformed init
        if ((p = find_key(s, end, "v")))    out->version = (int)parse_int(p, end);
        if ((p = find_key(s, end, "home"))) home = parse_int(p, end);
        if ((p = find_key(s, end, "away"))) away = parse_int(p, end);
        if ((p = find_key(s, end, "seed"))) out->seed = parse_u64(p, end);
        // Range-check before the int truncation: these ids flow straight into
        // bb_team_defs[] lookups via bb_match_init (review Hd1).
        if (home < 0 || home >= BB_TEAM_COUNT ||
            away < 0 || away >= BB_TEAM_COUNT) {
            out->type = BB_REC_PARSE_ERROR;
            return false;
        }
        out->home_team_id = (int)home;
        out->away_team_id = (int)away;
        out->type = BB_REC_INIT;
        return true;
    }
    if (*t == 'a') {
        out->type = BB_REC_ACTION;
        const char* p = find_key(s, end, "u");
        if (!p) { out->type = BB_REC_PARSE_ERROR; return false; }
        out->action = bb_action_unpack((uint32_t)parse_u64(p, end));
        return true;
    }
    if (*t == 'd') {
        out->type = BB_REC_DICE;
        const char* p;
        if ((p = find_key(s, end, "s"))) out->sides = (int)parse_int(p, end);
        if ((p = find_key(s, end, "v"))) out->value = (int)parse_int(p, end);
        if (out->sides <= 0 || out->value <= 0) { out->type = BB_REC_PARSE_ERROR; return false; }
        return true;
    }
    if (*t == 'e') {
        out->type = BB_REC_END;
        const char* p;
        if ((p = find_key(s, end, "home_score"))) out->home_score = (int)parse_int(p, end);
        if ((p = find_key(s, end, "away_score"))) out->away_score = (int)parse_int(p, end);
        return true;
    }
    out->type = BB_REC_PARSE_ERROR;
    return false;
}

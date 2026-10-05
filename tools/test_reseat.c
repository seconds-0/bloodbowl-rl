// test_reseat.c: turn-boundary re-seat (tools/bb_lockstep.c --reseat).
//
// Plays real engine matches with a seeded random coach, writes them out as
// lockstep scripts (init / act / expect ops, every die recorded, a seat on
// every team-turn boundary taken from the engine's own state), then checks:
//
//   1. A seat taken from a legally reached boundary rebuilds that boundary:
//      seat_build + seat_diff find no difference in any observed or rule-read
//      field, across many boundaries of several matches.
//   2. Forcing a re-seat at EVERY boundary of a clean script writes the same
//      records, byte for byte, as plain lockstep, and banks no state.
//   3. A script with one corrupted op: without --reseat it stops there, as it
//      always did; with --reseat it loses the rest of that team turn only,
//      and what it writes afterwards equals the clean run's records for the
//      same decisions.
//   4. Provenance: nothing after a re-seat reaches the .bbp shard or the .bbs
//      bank; re-seated records carry the BBR1 magic, their segment number and
//      how their span ended.
//   5. seat_build refuses seats that are out of range, self-contradictory or
//      describe a team turn the engine would never have opened.
//   6. An END_TURN op that names the team whose turn it closes is dropped when
//      the engine has already ended that turn, instead of ending the next
//      team's fresh turn (and recording a decision nobody made).
#define _POSIX_C_SOURCE 200809L

#define main bb_lockstep_cli_main
#include "bb_lockstep.c"
#undef main

#include <assert.h>
#include <sys/wait.h>
#include <unistd.h>

#define CHECK(cond) \
    do { \
        if (!(cond)) { \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
            exit(1); \
        } \
    } while (0)

#define REC_SIZE ((size_t)PD_REC_SIZE)
#define MAX_OPS 6000
#define WANT_BOUNDARIES 14

// --- script generation --------------------------------------------------------

typedef struct {
    int dice[MAX_DICE * 2];
    int n;
} dice_log;

static void log_die(void* user, int sides, int value) {
    (void)sides;
    dice_log* d = user;
    if (d->n < MAX_DICE * 2) d->dice[d->n] = value;
    d->n++;
}

static int put_dice(char* out, size_t cap, const dice_log* d) {
    int n = snprintf(out, cap, "\"dice\":[");
    for (int i = 0; i < d->n; i++) {
        n += snprintf(out + n, cap - n, "%s%d", i ? "," : "", d->dice[i]);
    }
    n += snprintf(out + n, cap - n, "]");
    return n;
}

static int put_side(char* out, size_t cap) {
    // Linemen, two Blitzers (Block, Tackle), two Catchers (Catch, Dodge), a
    // Thrower (Pass, Sure Hands): enough skills for re-roll windows to matter.
    static const struct {
        int pos, ma, st, ag, pa, av;
        const char* skills;
    } P[12] = {
        {0, 6, 3, 3, 4, 9, ""}, {0, 6, 3, 3, 4, 9, ""}, {0, 6, 3, 3, 4, 9, ""},
        {0, 6, 3, 3, 4, 9, ""}, {0, 6, 3, 3, 4, 9, ""}, {0, 6, 3, 3, 4, 9, ""},
        {4, 7, 3, 3, 4, 9, "\"Block\",\"Tackle\""},
        {4, 7, 3, 3, 4, 9, "\"Block\",\"Tackle\""},
        {2, 8, 3, 3, 4, 8, "\"Catch\",\"Dodge\""},
        {2, 8, 3, 3, 4, 8, "\"Catch\",\"Dodge\""},
        {3, 6, 3, 3, 3, 9, "\"Pass\",\"Sure Hands\""},
        {0, 6, 3, 3, 4, 9, ""},
    };
    int n = snprintf(out, cap, "{\"race\":\"Human\",\"players\":[");
    for (int i = 0; i < 12; i++) {
        n += snprintf(out + n, cap - n,
                      "%s{\"slot\":%d,\"pos\":%d,\"ma\":%d,\"st\":%d,\"ag\":%d,"
                      "\"pa\":%d,\"av\":%d,\"skills\":[%s]}",
                      i ? "," : "", i, P[i].pos, P[i].ma, P[i].st, P[i].ag,
                      P[i].pa, P[i].av, P[i].skills);
    }
    n += snprintf(out + n, cap - n, "]}");
    return n;
}

static int put_init(char* out, size_t cap, int seed, int weather, const dice_log* d) {
    int n = snprintf(out, cap, "{\"op\":\"init\",\"replay\":\"%d\",\"home\":", 7000 + seed);
    n += put_side(out + n, cap - n);
    n += snprintf(out + n, cap - n, ",\"away\":");
    n += put_side(out + n, cap - n);
    n += snprintf(out + n, cap - n,
                  ",\"receiving\":0,\"weather\":%d,\"rerolls\":[3,2],\"apo\":[1,1],"
                  "\"fans\":[2,1],", weather);
    n += put_dice(out + n, cap - n, d);
    n += snprintf(out + n, cap - n, "}");
    return n;
}

// The seat for a legally reached boundary, in the mapper's format, taken
// from the engine's own state: the truth a re-seat must reproduce.
static int put_seat(char* out, size_t cap, const bb_match* m, const bb_match* init) {
    int held = m->ball.state == BB_BALL_HELD;
    int n = snprintf(out, cap,
                     "\"seat\":{\"half\":%d,\"active\":%d,\"turn\":[%d,%d],"
                     "\"score\":[%d,%d],\"kick\":%d,\"h1kick\":%d,\"weather\":%d,"
                     "\"rr\":[%d,%d],\"bonus\":[%d,%d],\"apo\":[%d,%d],"
                     "\"bribes\":[%d,%d],\"eject\":[%d,%d],\"cheer\":[%d,%d],"
                     "\"ktm\":%d,\"tol\":0,\"rr_mirror\":[%d,%d],\"ball\":[%d,%d,%d],\"pl\":[",
                     m->half, m->active_team, m->turn[0], m->turn[1], m->score[0],
                     m->score[1], m->kicking_team,
                     (m->stack[0].data & MD_H1_KICKER) ? 1 : 0, m->weather,
                     m->rerolls[0], m->rerolls[1], m->bonus_rerolls[0],
                     m->bonus_rerolls[1], m->apothecary[0], m->apothecary[1],
                     m->bribes[0], m->bribes[1], m->coach_ejected[0],
                     m->coach_ejected[1], m->cheer_assist[0], m->cheer_assist[1],
                     m->ktm_used, m->rerolls[0], m->rerolls[1], m->ball.x,
                     m->ball.y, held);
    int first = 1;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ABSENT) continue;
        int on = p->location == BB_LOC_ON_PITCH;
        n += snprintf(out + n, cap - n, "%s[%d,%d,%d,%d,%d,%d,%d]", first ? "" : ",",
                      s, p->location, on ? p->x : 0, on ? p->y : 0,
                      on ? p->stance : 0, p->flags & ~BB_PF_HAS_BALL,
                      p->skill_rr_used);
        first = 0;
    }
    n += snprintf(out + n, cap - n, "],\"snack\":[");
    first = 1;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        int k = init->players[s].ma - m->players[s].ma;
        int k2 = init->players[s].av - m->players[s].av;
        if (k2 > k) k = k2;
        if (k <= 0) continue;
        n += snprintf(out + n, cap - n, "%s[%d,%d]", first ? "" : ",", s, k);
        first = 0;
    }
    n += snprintf(out + n, cap - n, "]}");
    return n;
}

typedef struct {
    char** line;      // every script line
    int* decision;    // decision index of an act line, else -1
    int n;
    int decisions, boundaries;
    int boundary_line[64];
} script;

static void add_line(script* S, const char* text, int decision) {
    CHECK(S->n < MAX_OPS);
    size_t len = strlen(text);
    S->line[S->n] = malloc(len + 1);
    CHECK(S->line[S->n] != NULL);
    memcpy(S->line[S->n], text, len + 1);
    S->decision[S->n] = decision;
    S->n++;
}

static uint32_t boundary_key(const bb_match* m) {
    return ((uint32_t)m->half << 24) | ((uint32_t)m->active_team << 16) |
           ((uint32_t)m->turn[0] << 8) | (uint32_t)m->turn[1];
}

// Returns false when the seeded match is unusable (an op needed more dice
// than a script line may carry): the caller tries the next seed.
static bool generate(script* S, int seed, int* audited) {
    static char buf[MAX_LINE];
    static runner G;
    memset(&G, 0, sizeof G);
    memset(S->decision, 0, sizeof(int) * MAX_OPS);
    S->n = S->decisions = S->boundaries = 0;
    dice_log none = {{0}, 0};
    put_init(buf, sizeof buf, seed, 2, &none);
    CHECK(do_init(&G, buf) == 0);
    bb_rng rng, pick;
    bb_rng_seed(&rng, (uint64_t)seed, 1);
    bb_rng_seed(&pick, (uint64_t)seed, 2);
    dice_log d = {{0}, 0};
    bb_rng_set_sink(&rng, log_die, &d);
    bb_advance(&G.m, &rng);
    put_init(buf, sizeof buf, seed, G.m.weather, &d);
    add_line(S, buf, -1);

    static bb_action legal[BB_LEGAL_MAX];
    bb_match prev_boundary;
    bool have_prev = false;
    uint32_t last_key = 0;
    long cmd = 1;
    while (G.m.status == BB_STATUS_DECISION && S->n < MAX_OPS - 4 &&
           S->boundaries < WANT_BOUNDARIES) {
        int nl = bb_legal_actions(&G.m, legal);
        CHECK(nl > 0);
        bb_action a = legal[bb_rng_next(&pick) % (uint32_t)nl];
        d.n = 0;
        bb_status st = bb_apply(&G.m, a, &rng);
        CHECK(st != BB_STATUS_ERROR);
        if (d.n > MAX_DICE - 2) return false;
        int n = snprintf(buf, sizeof buf,
                         "{\"op\":\"act\",\"cmd\":%ld,\"type\":%d,\"arg\":%d,"
                         "\"x\":%d,\"y\":%d,", cmd++, a.type, a.arg, a.x, a.y);
        n += put_dice(buf + n, sizeof buf - n, &d);
        snprintf(buf + n, sizeof buf - n, "}");
        add_line(S, buf, S->decisions++);
        if (!bb_state_bank_boundary_valid(&G.m) || boundary_key(&G.m) == last_key) {
            continue;
        }
        // A fresh team turn: the expect op with the engine's own seat.
        last_key = boundary_key(&G.m);
        n = snprintf(buf, sizeof buf, "{\"op\":\"expect\",\"cmd\":%ld,\"score\":[%d,%d],",
                     cmd++, G.m.score[0], G.m.score[1]);
        n += put_seat(buf + n, sizeof buf - n, &G.m, &G.init_m);
        snprintf(buf + n, sizeof buf - n, "}");
        CHECK(S->boundaries < 64);
        S->boundary_line[S->boundaries++] = S->n;
        add_line(S, buf, -1);

        // (1) the seat rebuilds this boundary from a carry one turn stale
        seat_rec s;
        seat_parse(buf, &s);
        CHECK(s.present && !s.refused);
        bb_match built;
        char why[64], diff[2048];
        int mask = 0;
        int rc = seat_build(&G, have_prev ? &prev_boundary : &G.m, &s, &built,
                            why, sizeof why);
        if (rc != 0) fprintf(stderr, "seat_build: %s (seed %d)\n", why, seed);
        CHECK(rc == 0);
        seat_diff(&G.m, &built, diff, sizeof diff, &mask);
        if (mask & (SD_HARD | SD_SOFT | SD_DERIVED)) {
            fprintf(stderr, "seed %d cmd %ld: seat differs from the engine: %s\n",
                    seed, cmd, diff);
        }
        CHECK((mask & (SD_HARD | SD_SOFT | SD_DERIVED)) == 0);
        CHECK(bb_state_bank_boundary_valid(&built));
        (*audited)++;
        prev_boundary = G.m;
        have_prev = true;
    }
    return S->boundaries >= 4;
}

// extra_before >= 0: write `extra` just before that line.
static void write_script_with(const script* S, const char* path, int corrupt_line,
                              int extra_before, const char* extra) {
    FILE* f = fopen(path, "w");
    CHECK(f != NULL);
    for (int i = 0; i < S->n; i++) {
        if (i == extra_before) fprintf(f, "%s\n", extra);
        if (i == corrupt_line) {
            // One die the engine will not consume: a dice_overrun stop.
            const char* dice = strstr(S->line[i], "\"dice\":[");
            CHECK(dice != NULL);
            dice += strlen("\"dice\":[");
            fwrite(S->line[i], 1, (size_t)(dice - S->line[i]), f);
            fprintf(f, "%s%s\n", *dice == ']' ? "6" : "6,", dice);
            continue;
        }
        fprintf(f, "%s\n", S->line[i]);
    }
    CHECK(fclose(f) == 0);
}

static void write_script(const script* S, const char* path, int corrupt_line) {
    write_script_with(S, path, corrupt_line, -1, "");
}

// --- running the CLI ----------------------------------------------------------

typedef struct {
    char summary[2048];
    bool wrong_team; // a divergence of class wrong_team was reported
} cli_out;

static void run_cli(cli_out* out, const char* dir, char* const args[], int nargs) {
    char cap[512];
    snprintf(cap, sizeof cap, "%s.stdout.txt", dir);
    fflush(stdout);
    pid_t pid = fork();
    CHECK(pid >= 0);
    if (pid == 0) {
        CHECK(freopen(cap, "w", stdout) != NULL);
        char* argv[16];
        argv[0] = "bb_lockstep";
        for (int i = 0; i < nargs; i++) argv[i + 1] = args[i];
        int rc = bb_lockstep_cli_main(nargs + 1, argv);
        fflush(stdout);
        _exit(rc);
    }
    int status = 0;
    CHECK(waitpid(pid, &status, 0) == pid);
    CHECK(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    FILE* f = fopen(cap, "r");
    CHECK(f != NULL);
    static char line[MAX_LINE];
    out->summary[0] = 0;
    out->wrong_team = false;
    while (fgets(line, sizeof line, f)) {
        if (strstr(line, "\"summary\":true")) {
            snprintf(out->summary, sizeof out->summary, "%s", line);
        }
        if (strstr(line, "\"class\":\"wrong_team\"")) out->wrong_team = true;
    }
    fclose(f);
    CHECK(out->summary[0] != 0);
}

static uint8_t* slurp(const char* path, size_t* len) {
    FILE* f = fopen(path, "rb");
    CHECK(f != NULL);
    CHECK(fseek(f, 0, SEEK_END) == 0);
    long n = ftell(f);
    CHECK(n >= 0 && fseek(f, 0, SEEK_SET) == 0);
    uint8_t* b = malloc((size_t)n + 1);
    CHECK(b != NULL);
    CHECK(fread(b, 1, (size_t)n, f) == (size_t)n);
    fclose(f);
    *len = (size_t)n;
    return b;
}

static size_t shard_records(const uint8_t* b, size_t len, const char* magic) {
    CHECK(len >= 16 && memcmp(b, magic, 4) == 0);
    CHECK(b[4] == 4 && b[5] == 0 && b[6] == 0 && b[7] == 0);
    CHECK((len - 16) % REC_SIZE == 0);
    return (len - 16) / REC_SIZE;
}

// Records equal apart from the provenance bytes (segment, span status).
static bool same_record(const uint8_t* a, const uint8_t* b) {
    return memcmp(a, b, 9) == 0 && memcmp(a + 12, b + 12, REC_SIZE - 12) == 0;
}

static void test_matches(const char* dir) {
    static char* lines[MAX_OPS];
    static int decision[MAX_OPS];
    script S = {lines, decision, 0, 0, 0, {0}};
    int usable = 0, audited = 0;
    char clean[512], broken[512], ref_bbp[512], ref_bbs[512], bbp[512], bbr[512], bbs[512];
    snprintf(clean, sizeof clean, "%s.clean.jsonl", dir);
    snprintf(broken, sizeof broken, "%s.broken.jsonl", dir);
    snprintf(ref_bbp, sizeof ref_bbp, "%s.ref.bbp", dir);
    snprintf(ref_bbs, sizeof ref_bbs, "%s.ref.bbs", dir);
    snprintf(bbp, sizeof bbp, "%s.out.bbp", dir);
    snprintf(bbr, sizeof bbr, "%s.out.bbr", dir);
    snprintf(bbs, sizeof bbs, "%s.out.bbs", dir);

    for (int seed = 1; seed <= 12 && usable < 4; seed++) {
        for (int i = 0; i < S.n; i++) free(S.line[i]);
        if (!generate(&S, seed, &audited)) continue;
        usable++;
        cli_out o;
        size_t ref_len, ref_s_len, len, rlen, slen;

        // Reference: plain lockstep over the clean script follows it all.
        write_script(&S, clean, -1);
        char* a0[] = {"--dump-pairs", ref_bbp, "--dump-states", ref_bbs, clean};
        run_cli(&o, dir, a0, 5);
        CHECK(strstr(o.summary, "\"diverged\":false") != NULL);
        uint8_t* ref = slurp(ref_bbp, &ref_len);
        uint8_t* ref_s = slurp(ref_bbs, &ref_s_len);
        size_t nref = shard_records(ref, ref_len, "BBP1");
        CHECK(nref == (size_t)S.decisions);
        size_t srec = 12 + sizeof(bb_match);
        CHECK((ref_s_len - 16) % srec == 0 && ref_s_len > 16);

        // (2) forced re-seat at every boundary: same records, nothing banked
        char* a1[] = {"--force-reseat", "--dump-pairs", bbp, "--dump-pairs-reseat",
                      bbr, "--dump-states", bbs, clean};
        run_cli(&o, dir, a1, 8);
        CHECK(strstr(o.summary, "\"diverged\":false") != NULL);
        CHECK(jint(o.summary, "reseats", -1) == S.boundaries);
        uint8_t* p = slurp(bbp, &len);
        uint8_t* r = slurp(bbr, &rlen);
        uint8_t* s = slurp(bbs, &slen);
        size_t np = shard_records(p, len, "BBP1");
        size_t nr = shard_records(r, rlen, "BBR1");
        CHECK(np + nr == nref && nr > 0);
        CHECK(memcmp(p, ref, 16 + np * REC_SIZE) == 0);
        for (size_t i = 0; i < nr; i++) {
            const uint8_t* rec = r + 16 + i * REC_SIZE;
            CHECK(same_record(rec, ref + 16 + (np + i) * REC_SIZE));
            CHECK((rec[9] | (rec[10] << 8)) >= 1); // segment number
        }
        CHECK(slen == 16); // every boundary was re-seated: no state banked
        free(p);
        free(r);
        free(s);

        // (3) one corrupted op in the third team turn
        int corrupt = S.boundary_line[1] + 1;
        while (corrupt < S.n && S.decision[corrupt] < 0) corrupt++;
        CHECK(corrupt < S.boundary_line[2]);
        int resume = S.boundary_line[2] + 1; // first op after the next boundary
        while (resume < S.n && S.decision[resume] < 0) resume++;
        CHECK(resume < S.n);
        size_t kept = (size_t)S.decision[corrupt];
        size_t first_after = (size_t)S.decision[resume];
        write_script(&S, broken, corrupt);

        char* a2[] = {"--dump-pairs", bbp, "--dump-states", bbs, broken};
        run_cli(&o, dir, a2, 5);
        CHECK(strstr(o.summary, "\"diverged\":true") != NULL);
        p = slurp(bbp, &len);
        CHECK(shard_records(p, len, "BBP1") == kept);
        CHECK(memcmp(p, ref, len) == 0);
        size_t plain_len = len, plain_slen;
        uint8_t* plain = p;
        uint8_t* plain_s = slurp(bbs, &plain_slen);

        char* a3[] = {"--reseat", "--dump-pairs", bbp, "--dump-pairs-reseat", bbr,
                      "--dump-states", bbs, broken};
        run_cli(&o, dir, a3, 8);
        CHECK(jint(o.summary, "divergences", -1) == 1);
        CHECK(jint(o.summary, "reseats", -1) == 1);
        CHECK(strstr(o.summary, "\"ended_lost\":false") != NULL);
        CHECK(jint(o.summary, "lost_decisions", -1) == (long)(first_after - kept));
        p = slurp(bbp, &len);
        r = slurp(bbr, &rlen);
        s = slurp(bbs, &slen);
        // (4) the prefix shard and the bank are what plain lockstep wrote
        CHECK(len == plain_len && memcmp(p, plain, len) == 0);
        CHECK(slen == plain_slen && memcmp(s, plain_s, slen) == 0);
        CHECK(slen <= ref_s_len && memcmp(s, ref_s, slen) == 0);
        nr = shard_records(r, rlen, "BBR1");
        CHECK(nr == nref - first_after);
        CHECK(jint(o.summary, "pairs_reseat", -1) == (long)nr);
        size_t closed = 0;
        for (size_t i = 0; i < nr; i++) {
            const uint8_t* rec = r + 16 + i * REC_SIZE;
            CHECK(same_record(rec, ref + 16 + (first_after + i) * REC_SIZE));
            CHECK(rec[9] == 1 && rec[10] == 0); // after the first recovery
            // the seats are the engine's own states: never a drift stamp
            CHECK(rec[11] == PD_SPAN_MATCH || rec[11] == PD_SPAN_OPEN);
            closed += rec[11] == PD_SPAN_MATCH;
        }
        CHECK(closed > 0);
        // every bank record precedes the corrupted op
        for (size_t i = 0; 16 + (i + 1) * srec <= slen; i++) {
            const uint8_t* rec = s + 16 + i * srec;
            uint32_t cmd = (uint32_t)rec[4] | ((uint32_t)rec[5] << 8) |
                           ((uint32_t)rec[6] << 16) | ((uint32_t)rec[7] << 24);
            CHECK((long)cmd < jint(S.line[corrupt], "cmd", -1));
        }
        free(p);
        free(r);
        free(s);
        free(plain);
        free(plain_s);

        // (6) a redundant END_TURN at a boundary: the engine is already in the
        // next team's turn. Tagged with the team it closes, it is dropped and
        // the run is the clean run. With dice it is a stop. Untagged (the old
        // script format) it ends the fresh turn and is recorded.
        seat_rec at;
        seat_parse(S.line[S.boundary_line[2]], &at);
        char extra[256];
        snprintf(extra, sizeof extra,
                 "{\"op\":\"act\",\"cmd\":%ld,\"type\":%d,\"arg\":0,\"x\":0,\"y\":0,"
                 "\"dice\":[],\"team\":%d}", jint(S.line[S.boundary_line[2]], "cmd", 0),
                 BB_A_END_TURN, 1 - at.active);
        write_script_with(&S, broken, -1, S.boundary_line[2], extra);
        char* a4[] = {"--seat-audit", "--dump-pairs", bbp, broken};
        run_cli(&o, dir, a4, 4);
        CHECK(strstr(o.summary, "\"diverged\":false") != NULL && !o.wrong_team);
        CHECK(jint(o.summary, "end_turn_dropped", -1) == 1);
        p = slurp(bbp, &len);
        CHECK(len == ref_len && memcmp(p, ref, len) == 0);
        free(p);
        snprintf(extra, sizeof extra,
                 "{\"op\":\"act\",\"cmd\":%ld,\"type\":%d,\"arg\":0,\"x\":0,\"y\":0,"
                 "\"dice\":[3],\"team\":%d}", jint(S.line[S.boundary_line[2]], "cmd", 0),
                 BB_A_END_TURN, 1 - at.active);
        write_script_with(&S, broken, -1, S.boundary_line[2], extra);
        run_cli(&o, dir, a4, 4);
        CHECK(strstr(o.summary, "\"diverged\":true") != NULL && o.wrong_team);
        p = slurp(bbp, &len);
        CHECK(len < ref_len && memcmp(p, ref, len) == 0); // no END_TURN record
        free(p);
        // Right team, but the engine is already in that team's NEXT turn (the
        // op closes turn n - 1, the engine is in turn n): dropped.
        snprintf(extra, sizeof extra,
                 "{\"op\":\"act\",\"cmd\":%ld,\"type\":%d,\"arg\":0,\"x\":0,\"y\":0,"
                 "\"dice\":[],\"team\":%d,\"half\":%d,\"turn\":%d}",
                 jint(S.line[S.boundary_line[2]], "cmd", 0), BB_A_END_TURN, at.active,
                 at.half, at.turn[at.active] - 1);
        write_script_with(&S, broken, -1, S.boundary_line[2], extra);
        run_cli(&o, dir, a4, 4);
        CHECK(strstr(o.summary, "\"diverged\":false") != NULL && !o.wrong_team);
        CHECK(jint(o.summary, "end_turn_dropped", -1) == 1);
        p = slurp(bbp, &len);
        CHECK(len == ref_len && memcmp(p, ref, len) == 0);
        free(p);
        // Right team, and the replay's counter is AHEAD of the engine's (the
        // op closes turn n + 1, the engine is in turn n): the engine is still
        // in the turn being closed, so the op is applied, as it always was.
        snprintf(extra, sizeof extra,
                 "{\"op\":\"act\",\"cmd\":%ld,\"type\":%d,\"arg\":0,\"x\":0,\"y\":0,"
                 "\"dice\":[],\"team\":%d,\"half\":%d,\"turn\":%d}",
                 jint(S.line[S.boundary_line[2]], "cmd", 0), BB_A_END_TURN, at.active,
                 at.half, at.turn[at.active] + 1);
        write_script_with(&S, broken, -1, S.boundary_line[2], extra);
        run_cli(&o, dir, a4, 4);
        CHECK(jint(o.summary, "end_turn_dropped", -1) == 0);
        p = slurp(bbp, &len);
        CHECK(len > 16 + (size_t)S.decision[resume] * REC_SIZE);
        CHECK(p[16 + (size_t)S.decision[resume] * REC_SIZE + REC_SIZE - 4] == BB_A_END_TURN);
        free(p);
        snprintf(extra, sizeof extra,
                 "{\"op\":\"act\",\"cmd\":%ld,\"type\":%d,\"arg\":0,\"x\":0,\"y\":0,"
                 "\"dice\":[]}", jint(S.line[S.boundary_line[2]], "cmd", 0), BB_A_END_TURN);
        write_script_with(&S, broken, -1, S.boundary_line[2], extra);
        run_cli(&o, dir, a4, 4);
        p = slurp(bbp, &len);
        size_t upto = 16 + (size_t)S.decision[resume] * REC_SIZE;
        CHECK(len > upto && memcmp(p, ref, upto) == 0);
        CHECK(p[upto + REC_SIZE - 4] == BB_A_END_TURN); // the unplayed turn, ended
        free(p);
        free(ref);
        free(ref_s);
    }
    for (int i = 0; i < S.n; i++) free(S.line[i]);
    CHECK(usable >= 3);
    CHECK(audited >= 3 * 4);
    printf("re-seat: %d matches, %d boundaries rebuilt exactly\n", usable, audited);
}

// --- seat_build refusals ------------------------------------------------------

static void expect_refused(const runner* R, const bb_match* carry, seat_rec s,
                           const char* want) {
    bb_match out;
    char why[64] = "";
    CHECK(seat_build(R, carry, &s, &out, why, sizeof why) == -1);
    if (strcmp(why, want) != 0) fprintf(stderr, "refused with %s, want %s\n", why, want);
    CHECK(strcmp(why, want) == 0);
}

static void test_refusals(void) {
    static char* lines[MAX_OPS];
    static int decision[MAX_OPS];
    script S = {lines, decision, 0, 0, 0, {0}};
    int audited = 0, seed = 1;
    while (!generate(&S, seed, &audited)) seed++;
    static runner R;
    memset(&R, 0, sizeof R);
    CHECK(do_init(&R, S.line[0]) == 0);
    seat_rec ok;
    seat_parse(S.line[S.boundary_line[1]], &ok);
    CHECK(ok.present && !ok.refused);
    bb_match out;
    char why[64];
    CHECK(seat_build(&R, &R.init_m, &ok, &out, why, sizeof why) == 0);
    CHECK(out.status == BB_STATUS_DECISION && out.stack_top == 2);
    CHECK(out.decision_team == ok.active && out.turnover == 0);

    seat_rec s = ok;
    s.present = 0;
    expect_refused(&R, &R.init_m, s, "no_seat");
    s = ok;
    s.refused = 1;
    snprintf(s.why, sizeof s.why, "more_than_11_on_pitch");
    expect_refused(&R, &R.init_m, s, "more_than_11_on_pitch");
    s = ok;
    s.half = 3;
    expect_refused(&R, &R.init_m, s, "scalar_out_of_range");
    s = ok;
    s.turn[0] = 9;
    expect_refused(&R, &R.init_m, s, "team_field_out_of_range");
    s = ok;
    s.bonus[0] = s.rr[0] + 1; // more drive-scoped re-rolls than re-rolls
    expect_refused(&R, &R.init_m, s, "team_field_out_of_range");

    int a = -1, b = -1; // two players on the pitch
    for (int i = 0; i < ok.npl; i++) {
        if (ok.pl[i][1] != BB_LOC_ON_PITCH) continue;
        if (a < 0) a = i;
        else if (b < 0) b = i;
    }
    CHECK(a >= 0 && b >= 0);
    s = ok;
    s.pl[b][2] = s.pl[a][2];
    s.pl[b][3] = s.pl[a][3];
    expect_refused(&R, &R.init_m, s, "player_square_invalid");
    s = ok;
    s.pl[a][0] = s.pl[b][0]; // the same roster slot twice
    expect_refused(&R, &R.init_m, s, "player_row_invalid");
    s = ok;
    s.pl[a][5] = 0x1000; // a flag bit the engine does not have
    expect_refused(&R, &R.init_m, s, "player_row_invalid");
    s = ok;
    s.npl--; // a roster player the seat forgot
    expect_refused(&R, &R.init_m, s, "roster_player_missing");
    s = ok;
    s.ball[0] = 26;
    expect_refused(&R, &R.init_m, s, "ball_off_pitch");
    s = ok;
    s.ball[2] = !s.ball[2]; // held on an empty square / loose under a player
    expect_refused(&R, &R.init_m, s, "ball_holder_mismatch");
    s = ok;
    s.ball[0] = s.pl[a][2];
    s.ball[1] = s.pl[a][3];
    s.ball[2] = 1;
    s.pl[a][4] = BB_STANCE_PRONE;
    expect_refused(&R, &R.init_m, s, "ball_under_downed_player");
    // Nobody on the active team can act: the engine would have ended that
    // turn by itself, so the decision state does not exist.
    s = ok;
    for (int i = 0; i < s.npl; i++) {
        if (BB_TEAM_OF(s.pl[i][0]) == s.active && s.pl[i][1] == BB_LOC_ON_PITCH) {
            s.pl[i][4] = BB_STANCE_STUNNED_USED;
        }
    }
    int at = -1; // keep the ball legal: put it on an empty square
    for (int x = 0; x < BB_PITCH_LEN && at < 0; x++) {
        bool empty = true;
        for (int i = 0; i < s.npl; i++) {
            if (s.pl[i][1] == BB_LOC_ON_PITCH && s.pl[i][2] == x && s.pl[i][3] == 7) {
                empty = false;
            }
        }
        if (empty) at = x;
    }
    CHECK(at >= 0);
    s.ball[0] = at;
    s.ball[1] = 7;
    s.ball[2] = 0;
    expect_refused(&R, &R.init_m, s, "no_activatable_player");

    // Rows are never completed with defaults: a short player row, a second
    // snack row for one player and a snack for an empty roster slot are all
    // refused.
    {
        static char line[MAX_LINE];
        const char* src = S.line[S.boundary_line[1]];
        const char* pl = strstr(src, "\"pl\":[[");
        CHECK(pl != NULL);
        const char* row_end = strchr(pl, ']');
        CHECK(row_end != NULL && row_end - src > 4);
        // drop the last number of the first player row
        const char* cut = row_end;
        while (cut[-1] != ',') cut--;
        snprintf(line, sizeof line, "%.*s%s", (int)(cut - 1 - src), src, row_end);
        seat_parse(line, &s);
        CHECK(s.present && s.refused && strcmp(s.why, "seat_unparseable") == 0);
    }
    {
        // a stray scalar among the rows, and a number no int should hold
        int rows[4][2];
        CHECK(jrows("{\"k\":[[1,2],[3,4]]}", "k", &rows[0][0], 2, 4) == 2);
        CHECK(jrows("{\"k\":[]}", "k", &rows[0][0], 2, 4) == 0);
        CHECK(jrows("{\"k\":[[1,2],42]}", "k", &rows[0][0], 2, 4) == -1);
        CHECK(jrows("{\"k\":[[1,4294967296]]}", "k", &rows[0][0], 2, 4) == -1);
        CHECK(jrows("{\"k\":[[1,2,3]]}", "k", &rows[0][0], 2, 4) == -1);
        CHECK(jrows("{\"k\":[[1]]}", "k", &rows[0][0], 2, 4) == -1);
        CHECK(jrows("{\"k\":[[1,2],[3,4],[5,6]]}", "k", &rows[0][0], 2, 2) == -1);
        CHECK(jrows("{\"other\":[[1,2]]}", "k", &rows[0][0], 2, 4) == -1);
    }
    s = ok;
    s.nsnack = 2;
    s.snack[0][0] = s.snack[1][0] = ok.pl[a][0];
    s.snack[0][1] = s.snack[1][1] = 1;
    expect_refused(&R, &R.init_m, s, "snack_row_invalid");
    s = ok;
    s.nsnack = 1;
    s.snack[0][0] = 15; // the fixture rosters fill slots 0..11 only
    s.snack[0][1] = 1;
    expect_refused(&R, &R.init_m, s, "snack_row_invalid");

    // A flag the seat claims is never trusted for the ball: HAS_BALL comes
    // from the ball's square alone.
    s = ok;
    for (int i = 0; i < s.npl; i++) s.pl[i][5] |= BB_PF_HAS_BALL;
    CHECK(seat_build(&R, &R.init_m, &s, &out, why, sizeof why) == 0);
    int holders = 0;
    for (int i = 0; i < BB_NUM_PLAYERS; i++) {
        holders += (out.players[i].flags & BB_PF_HAS_BALL) != 0;
    }
    CHECK(holders == (out.ball.state == BB_BALL_HELD ? 1 : 0));
    for (int i = 0; i < S.n; i++) free(S.line[i]);
    printf("re-seat: refusals ok\n");
}

int main(void) {
    // A unique path prefix: every file this test writes is "<prefix>.<name>".
    char dir[] = "/tmp/bb-reseat-XXXXXX";
    int fd = mkstemp(dir);
    CHECK(fd >= 0);
    close(fd);
    test_refusals();
    test_matches(dir);
    static const char* names[] = {"clean.jsonl", "broken.jsonl", "ref.bbp", "ref.bbs",
                                  "out.bbp", "out.bbr", "out.bbs", "stdout.txt"};
    for (size_t i = 0; i < sizeof names / sizeof names[0]; i++) {
        char path[512];
        snprintf(path, sizeof path, "%s.%s", dir, names[i]);
        unlink(path);
    }
    unlink(dir);
    return 0;
}

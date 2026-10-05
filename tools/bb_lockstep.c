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
#include <stdarg.h>
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
    const char* cur_line; // the op being processed (divergence reports)
    // --- turn-boundary re-seat (see the block comment above seat_rec) ---
    int reseat;        // --reseat: resume at the next seatable boundary
    int force_reseat;  // --force-reseat: rebuild the state at EVERY boundary
    int seat_audit;    // --seat-audit: rebuild, diff against the live state
    int mirror_resources; // --seat-mirror-resources (experiment, see usage)
    int lost;          // diverged and not yet re-seated (reseat mode)
    int segment;       // 0 = prefix; k = after the k-th re-seat
    int divergences;   // every divergence, not only the first
    int reseats, seat_refused, seat_failed;
    int syncs;         // boundary re-syncs inside re-seated provenance
    int end_turn_dropped;     // redundant END_TURN ops (the engine had ended it)
    int spans;         // boundary-to-boundary spans (~team turns), of which:
    int spans_aligned; // re-seated, closed, equal to the replay's seat
    int spans_mirror;  // closed against the mapper's mirror (prefix / no seat)
    int spans_drift;   // closed without a stop, but off the replay on the pitch
    int spans_soft_drift;     // ... or off in a resource / status / latch only
    int span_clean;    // nothing diverged since the last boundary
    long lost_decisions;      // act/place ops skipped while lost
    long span_lost;           // ... since the divergence that opened this gap
    char last_class[24];      // class of the divergence that opened this gap
    bb_match init_m;   // the match as the init op built it (statics only)
    bb_match prev_boundary;   // live state at the previous boundary (audit carry)
    int have_prev_boundary;
} runner;

static void ctx_copy(char dst[512], const char* line) {
    size_t n = strlen(line);
    if (n >= 512) n = 511;
    memcpy(dst, line, n);
    dst[n] = '\0';
}

static void ctx_push(runner* R, const char* line) {
    if (R->ctx_n < CTX_OPS) {
        ctx_copy(R->ctx[R->ctx_n++], line);
    } else {
        memmove(R->ctx[0], R->ctx[1], sizeof R->ctx[0] * (CTX_OPS - 1));
        ctx_copy(R->ctx[CTX_OPS - 1], line);
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
    // Without --reseat only the first divergence exists (nothing runs after
    // it). With it, every divergence is reported, tagged with its segment.
    if (R->diverged && !R->reseat) return;
    R->diverged = 1;
    R->divergences++;
    if (R->reseat) {
        R->lost = 1;
        R->span_lost = 0;
        snprintf(R->last_class, sizeof R->last_class, "%s", cls);
    }
    R->span_clean = 0;
    char o[512], t[512], c[CTX_OPS][1024];
    json_escape(ours, o, sizeof o);
    json_escape(theirs, t, sizeof t);
    for (int i = 0; i < R->ctx_n; i++) json_escape(R->ctx[i], c[i], sizeof c[i]);
    char opname[16] = "?";
    long op_type = -1, op_arg = -1;
    if (R->cur_line) {
        jstr(R->cur_line, "op", opname, sizeof opname);
        op_type = jint(R->cur_line, "type", -1);
        op_arg = jint(R->cur_line, "arg", -1);
    }
    printf("{\"replay\":\"%s\",\"cmd\":%ld,\"seg\":%d,\"class\":\"%s\","
           "\"op\":\"%s\",\"type\":%ld,\"arg\":%ld,"
           "\"ours\":\"%s\",\"theirs\":\"%s\",\"context\":[",
           R->replay, cmd, R->segment, cls, opname, op_type, op_arg, o, t);
    for (int i = 0; i < R->ctx_n; i++) {
        printf("%s\"%s\"", i ? "," : "", c[i]);
    }
    printf("]}\n");
}

// --- BC pair dump (--dump-pairs <out.bbp>) -----------------------------------
// .bbp format v4: binary, little-endian, written by this runner; consumed by
// training/bc_pretrain.py (extraction orchestrated by
// validation/extract_pairs.py). Also documented in validation/README.md.
// v4 identifies exact sequential action support and canonical inactive-head
// sentinels. v3 identifies obs-v5's semantic ABI at the same 2782-byte shape.
// Historical v2 spans obs-v3 (1612 B) and obs-v4 (2782 B); v1 carried 832 B.
// Readers size records from the header and include VERSION in lineage checks:
// v2/2782, v3/2782, and v4/2782 must never mix despite equal physical shape.
//
//   header (16 bytes):
//     magic     char[4]  "BBP1"
//     version   u32      4 (exact-action semantics; layout unchanged)
//     obs_size  u32      BBE_OBS_SIZE  (2782; historical v2 may also be 2782)
//     mask_size u32      BBE_MASK_SIZE (454)
//   record (12 + obs_size + mask_size + 4 = 3252 bytes), one per
//   successfully applied act/place op (a place op is a BB_A_SETUP_PLACE
//   action), for the DECIDING coach only:
//     replay_id u32      numeric FUMBBL replay id
//     cmd       u32      FUMBBL commandNr of the op
//     agent     u8       deciding team (0 home / 1 away); obs, mask and the
//                        action targets are in this agent's egocentric frame
//     pad       u8[3]    zero
//     obs       u8[2782] bbe_encode_obs at the decision, BEFORE the action
//     mask      u8[454]  exact masks used for this target: type support,
//                        arg conditioned on type, square on type+arg
//     type      u8       action-type head target (bb_action_type)
//     arg       u8       arg head target via bbe_action_arg (player slots
//                        ego-remapped like obs rows; 32 = sentinel)
//     sq        u16      square head target via bbe_action_sq (y*26 +
//                        mirrored-x for the away agent; 390 = none)
//
// The targets are the binding's OWN head projections of the applied
// bb_action — exactly what the policy heads must emit — never raw engine
// fields. A record is staged before bb_apply (the obs is the pre-action
// decision state) and committed only after the transition succeeds; nothing
// is written for ops at or beyond the first divergence, nor for an act op
// that carries "nopair":1.
//
// Encoder-cache coherence: the obs caches inside Bloodbowl are pure
// functions of the copied state — skill_rows are keyed by the player's
// skillset bytes (memcmp dirty-check in bbe_encode_obs), tz_scratch is
// recomputed by every bbe_emit_all, and legal_arg/legal_sq are filled by
// bbe_fill_mask from the legal list bbe_refresh_legal just enumerated — so
// mirroring the match with a plain struct copy per record is correct even
// across replays. ~1 match copy + 1 legal enumeration + 2 encodes per pair;
// measured ~2 ms total overhead across the 21-replay corpus.

// --- Re-seated pairs (--dump-pairs-reseat <out.bbr>) ---------------------------
// A record whose decision state descends from a turn-boundary re-seat is NEVER
// written to the .bbp shard. It goes to a second file with its own magic, so
// the BBP readers (training/bc_pretrain.py, validation/extract_pairs.py) refuse
// it outright and nobody can train on re-seated pairs by pointing a loader at
// the wrong directory:
//
//   header (16 bytes):  magic "BBR1", version u32 4, obs_size u32, mask_size u32
//   record: byte-for-byte the BBP v4 record, except that the three pad bytes
//           after `agent` carry provenance: segment u16 (1 = after the first
//           recovery of this replay, 2 = after the second, ...) and a status
//           byte saying how the record's span ended (PD_SPAN_* below).
//
// "Version 4" there means the observation, mask and target semantics are those
// of BBP v4. Without --dump-pairs-reseat, re-seated records are counted and
// dropped.

// How the boundary-to-boundary span a re-seated record sits in ended (the
// third pad byte of a .bbr record). Only PD_SPAN_MATCH says the engine, after
// playing the recorded actions and dice from the re-seated state, arrived at
// the state the replay records at the next boundary.
enum {
    PD_SPAN_OPEN = 0,   // lockstep stopped before the next boundary
    PD_SPAN_MATCH = 1,  // closed; the engine equalled the replay's boundary
                        // state in every field the seat carries
    PD_SPAN_DRIFT = 2,  // closed without a stop, but off the replay on the
                        // pitch (a square, stance, the ball, score, clock)
    PD_SPAN_MIRROR = 3, // closed against the mapper's mirror only (no seat)
    PD_SPAN_SOFT = 4,   // closed; the pitch matched, a resource, status or
                        // latch did not (re-rolls, Bribes, Distracted, ...)
    PD_SPAN_STATES = 5,
};
// PD_SPAN_MATCH is evidence about the END of the span only. A state that was
// wrong in the middle and right again at the boundary is not detected.

typedef struct {
    FILE* f;
    FILE* f_reseat;
    uint32_t replay_id;
    long pairs;
    long pairs_reseat;
    uint8_t* span;      // re-seated records of the span in progress
    size_t span_n, span_cap;
    long span_status[PD_SPAN_STATES]; // re-seated records by how their span ended
    int staged;
    // Staged record fields (committed only after the transition succeeds).
    uint32_t cmd;
    uint8_t agent;
    uint8_t obs[BBE_OBS_SIZE];
    uint8_t mask[BBE_MASK_SIZE];
    uint8_t a_type, a_arg;
    uint16_t a_sq;
    // Encoder shell: match mirrors the runner's bb_match per staged record.
    Bloodbowl env;
    uint8_t obs_buf[BBE_AGENTS * BBE_OBS_SIZE];
    unsigned char mask_buf[BBE_AGENTS * BBE_MASK_SIZE];
    float act_buf[BBE_AGENTS * 3];
    float rew_buf[BBE_AGENTS], term_buf[BBE_AGENTS];
} pair_dumper;

static pair_dumper PD; // static: Bloodbowl carries ~30KB of legal buffers

static void pd_u32_to(FILE* f, uint32_t v) {
    uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16),
                    (uint8_t)(v >> 24)};
    fwrite(b, 1, 4, f);
}

static FILE* pd_open_file(const char* path, const char* magic) {
    FILE* f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "cannot open %s for writing\n", path);
        exit(2);
    }
    fwrite(magic, 1, 4, f);
    pd_u32_to(f, 4); // v4: exact sequential action semantics; layout unchanged
    pd_u32_to(f, BBE_OBS_SIZE);
    pd_u32_to(f, BBE_MASK_SIZE);
    return f;
}

static void pd_init_env(void) {
    PD.env.num_agents = BBE_AGENTS;
    for (int a = 0; a < BBE_AGENTS; a++) {
        PD.env.obs_ptr[a] = PD.obs_buf + a * BBE_OBS_SIZE;
        PD.env.action_mask_ptr[a] = PD.mask_buf + a * BBE_MASK_SIZE;
        PD.env.action_ptr[a] = PD.act_buf + a * 3;
        PD.env.reward_ptr[a] = PD.rew_buf + a;
        PD.env.terminal_ptr[a] = PD.term_buf + a;
    }
}

static void pd_open_reseat(const char* path) {
    PD.f_reseat = pd_open_file(path, "BBR1");
    pd_init_env();
}

static void pd_open(const char* path) {
    PD.f = pd_open_file(path, "BBP1");
    pd_init_env();
}

// Stage one (obs, mask, action) record for the deciding side. Called AFTER
// the runner's legality check passed, BEFORE bb_apply.
static void pd_stage_prepared(const Bloodbowl* env, int agent, bb_action a,
                              long cmd) {
    PD.cmd = (uint32_t)cmd;
    PD.agent = (uint8_t)agent;
    memcpy(PD.obs, env->obs_ptr[agent], BBE_OBS_SIZE);
    PD.a_type = a.type;
    PD.a_arg = (uint8_t)bbe_action_arg(agent, a);
    PD.a_sq = (uint16_t)bbe_action_sq(agent, a);
    bbe_fill_effective_action_mask(env, agent, PD.a_type, PD.a_arg, PD.mask);
    PD.staged = 1;
}

static void pd_stage(runner* R, bb_action a, long cmd) {
    if (!PD.f && !PD.f_reseat) return;
    PD.env.match = R->m; // mirror the lockstep match into the env shell
    bbe_refresh_legal(&PD.env);
    bbe_emit_all(&PD.env); // the exact per-step encode training runs
    int agent = R->m.decision_team;
    pd_stage_prepared(&PD.env, agent, a, cmd);
}

#define PD_REC_SIZE (12 + BBE_OBS_SIZE + BBE_MASK_SIZE + 4)

static void pd_put_u32(uint8_t* b, uint32_t v) {
    b[0] = (uint8_t)v;
    b[1] = (uint8_t)(v >> 8);
    b[2] = (uint8_t)(v >> 16);
    b[3] = (uint8_t)(v >> 24);
}

// Write the buffered records of the span that just ended, stamped with how
// it ended. Prefix records are never buffered (they go straight to the .bbp).
static void pd_span_flush(int status) {
    for (size_t i = 0; i < PD.span_n; i++) {
        uint8_t* rec = PD.span + i * PD_REC_SIZE;
        rec[11] = (uint8_t)status;
        if (PD.f_reseat) fwrite(rec, 1, PD_REC_SIZE, PD.f_reseat);
    }
    PD.span_status[status % PD_SPAN_STATES] += (long)PD.span_n;
    PD.span_n = 0;
}

// segment 0 = prefix-aligned (the .bbp shard); segment k > 0 = after the k-th
// recovery (the .bbr shard, or counted and dropped when none was requested).
static void pd_commit_segment(int segment) {
    if (!PD.staged) return;
    PD.staged = 0;
    uint8_t head[12];
    pd_put_u32(head, PD.replay_id);
    pd_put_u32(head + 4, PD.cmd);
    int seg = segment > 0xFFFF ? 0xFFFF : segment;
    head[8] = PD.agent;
    head[9] = (uint8_t)seg;
    head[10] = (uint8_t)(seg >> 8);
    head[11] = 0;
    uint8_t tail[4] = {PD.a_type, PD.a_arg, (uint8_t)PD.a_sq, (uint8_t)(PD.a_sq >> 8)};
    if (segment > 0) {
        PD.pairs_reseat++;
        if (PD.span_n == PD.span_cap) {
            size_t cap = PD.span_cap ? PD.span_cap * 2 : 256;
            uint8_t* grown = realloc(PD.span, cap * PD_REC_SIZE);
            if (!grown) {
                fprintf(stderr, "out of memory buffering a re-seated span\n");
                exit(2);
            }
            PD.span = grown;
            PD.span_cap = cap;
        }
        uint8_t* rec = PD.span + PD.span_n++ * PD_REC_SIZE;
        memcpy(rec, head, 12);
        memcpy(rec + 12, PD.obs, BBE_OBS_SIZE);
        memcpy(rec + 12 + BBE_OBS_SIZE, PD.mask, BBE_MASK_SIZE);
        memcpy(rec + 12 + BBE_OBS_SIZE + BBE_MASK_SIZE, tail, 4);
        return;
    }
    if (!PD.f) return;
    PD.pairs++;
    fwrite(head, 1, 12, PD.f);
    fwrite(PD.obs, 1, BBE_OBS_SIZE, PD.f);
    fwrite(PD.mask, 1, BBE_MASK_SIZE, PD.f);
    fwrite(tail, 1, 4, PD.f);
}

static void pd_commit(void) {
    pd_commit_segment(0);
}

static void pd_abort(void) {
    PD.staged = 0;
}

// --- Demo-state dump (--dump-states <out.bbs>) ---------------------------------
// .bbs format v1: raw bb_match snapshots at team-turn boundaries, consumed by
// the env's demo-state reset curriculum (bbe_reset_match with
// demo_reset_pct > 0; corpus bank built by validation/build_state_bank.py).
// Also documented in validation/README.md.
//
//   header (16 bytes, little-endian):
//     magic      char[4] "BBS1"
//     version    u32     1
//     match_size u32     sizeof(bb_match) of the writing build
//     engine_fp  u32     bbe_state_fingerprint() (engine-compat stamp)
//   record (12 + match_size bytes):
//     replay_id  u32     numeric FUMBBL replay id
//     cmd        u32     FUMBBL commandNr of the op that reached the state
//     half       u8      match.half at the dumped decision
//     turn       u8      match.turn[match.active_team]
//     pad        u8[2]   zero
//     match      u8[match_size]  raw bb_match blob (host ABI — same-arch
//                        only; do_init zeroes the whole struct, so padding
//                        bytes are deterministic)
//
// One record per TEAM-TURN boundary successfully reached in lockstep: the
// first BB_STATUS_DECISION whose (half, active_team, turn[0], turn[1]) key
// differs from the last staged one, with a TEAM_TURN frame on the stack —
// i.e. the first decision of every team turn, which includes the first turn
// of every drive (post-kickoff). Only DECISION states are dumped (resumable
// points by definition). Records are STAGED at the boundary and committed
// once the NEXT op also applies cleanly — the mapper emits its expect diff
// at exactly these boundaries, so a state that diverges from FUMBBL is
// never banked; nothing at or beyond the first divergence is written.

typedef struct {
    FILE* f;
    uint32_t replay_id;
    long states;
    int staged;
    uint32_t last_key; // (half, active_team, turn[0], turn[1]) last staged
    uint32_t cmd;
    uint8_t half, turn;
    bb_match m;
} state_dumper;

static state_dumper SD;

static void sd_u32(uint32_t v) {
    uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16),
                    (uint8_t)(v >> 24)};
    fwrite(b, 1, 4, SD.f);
}

static void sd_open(const char* path) {
    SD.f = fopen(path, "wb");
    if (!SD.f) {
        fprintf(stderr, "cannot open %s for writing\n", path);
        exit(2);
    }
    fwrite("BBS1", 1, 4, SD.f);
    sd_u32(1);
    sd_u32((uint32_t)sizeof(bb_match));
    sd_u32(bbe_state_fingerprint());
}

static void sd_commit(void) {
    if (!SD.f || !SD.staged) return;
    SD.staged = 0;
    sd_u32(SD.replay_id);
    sd_u32(SD.cmd);
    uint8_t meta[4] = {SD.half, SD.turn, 0, 0};
    fwrite(meta, 1, 4, SD.f);
    fwrite(&SD.m, sizeof(bb_match), 1, SD.f);
    SD.states++;
}

// Called after every successfully applied op: commit the previously staged
// boundary (it just survived one more verified op), then stage a new record
// if this op crossed into a fresh team turn.
static void sd_on_op_applied(runner* R, long cmd) {
    if (!SD.f) return;
    // A re-seated state is built by writing fields, not reached through
    // bb_apply: it must never enter the state bank (AGENTS.md, "Replay and BC
    // contract"), and neither may anything staged before it.
    if (R->segment > 0) {
        SD.staged = 0;
        return;
    }
    sd_commit();
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
    uint32_t key = ((uint32_t)m->half << 24) | ((uint32_t)m->active_team << 16) |
                   ((uint32_t)m->turn[0] << 8) | (uint32_t)m->turn[1];
    if (key == SD.last_key) return;
    SD.last_key = key;
    SD.cmd = (uint32_t)cmd;
    SD.half = m->half;
    SD.turn = m->turn[m->active_team & 1];
    SD.m = *m;
    SD.staged = 1;
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
        PD.replay_id = (uint32_t)strtoul(rid, 0, 10);
        SD.replay_id = PD.replay_id;
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
    R->init_m = R->m; // rosters, re-roll complement, fans: a re-seat's statics
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

// --- Turn-boundary re-seat ---------------------------------------------------------
// PROTOTYPE, measurement only. Lockstep stops at the first point where the
// engine and the recorded FUMBBL game disagree, so one unmapped event costs the
// rest of the match. A re-seat resumes at the next team-turn boundary by
// putting the engine into the state FUMBBL recorded there (the "seat" object
// the mapper attaches to its expect op: validation/lockstep_map.py build_seat,
// folded from the replay's model-change log by validation/ffb_fold.py).
//
// THIS IS STATE SURGERY. A re-seated bb_match is written field by field, not
// reached through bb_apply from an engine initializer, which is exactly what
// AGENTS.md ("Replay and BC contract") and CLAUDE.md ("Authored drill bank")
// forbid for banked states. Therefore, by construction:
//   * no BBS record is written at or after a re-seat (sd_on_op_applied);
//   * no re-seated record enters a .bbp shard: they go to a separate file with
//     its own magic that the BBP readers refuse (pd_commit_segment);
//   * the surgery lives in this tool only. The engine gains no entry point.
// A re-seated state is used for ONE thing: computing the observation and the
// exact conditional masks of the human decisions that follow it.
//
// What the seat carries, and where the rest comes from (seat_build):
//   from the replay   every player's location, square, stance and status
//                     flags; the ball; half; both turn counters; score; whose
//                     turn starts; weather; both re-roll pools and their
//                     drive-scoped share; apothecaries; Bribes; the coach ban
//   derived by the    STUNNED versus STUNNED_USED; the kicking team now and
//   mapper            in half one; the latches the team not on turn keeps
//                     until its own next turn (USED, BLITZED, Pro, skill
//                     re-rolls spent); the pending Cheering Fans assist;
//                     Dodgy Snack debuffs; ktm_used
//   from the init op  skills, base characteristics, positions, Loner and
//                     Bloodlust values, re-roll complement, fan factor,
//                     team ids
//   set by rule       the two frames of a fresh team turn (MATCH phase 3,
//                     TEAM_TURN phase 1), DECISION for the active team, no
//                     turnover, the six per-turn action latches clear, and
//                     moved / rushes zero for everyone
//   carried, stale    step_count, turns_completed*, surfs, ret (bookkeeping
//                     no observation, mask or rule reads at a fresh turn)
// The "derived" rows are the guesses; --seat-audit measures how often each is
// wrong against states the engine reached legally. Known not reproduced:
// Rooted / Eye Gouged on a player who has left the pitch.

#define SEAT_BUF 16384
#define SEAT_COLS 7

typedef struct {
    int present;  // the expect op carried a seat object
    int refused;  // ... that says the engine cannot represent this boundary
    char why[64];
    int half, active, kick, h1kick, weather, ktm;
    int tol;      // the mapper knows its engine mirror is off the replay here
    // the mapper's own (engine-semantics) counts; -1 = not given
    int rr_mirror[2], bonus_mirror[2], apo_mirror[2];
    int turn[2], score[2], rr[2], bonus[2], apo[2], bribes[2], eject[2], cheer[2];
    int ball[3];
    int npl;
    // gslot, loc, x, y, stance, flags, skill_rr_used
    int pl[BB_NUM_PLAYERS][SEAT_COLS];
    int nsnack;
    int snack[BB_NUM_PLAYERS][2];      // gslot, count
} seat_rec;

// Parse "key":[[a,b,..],[..]] rows of exactly `cols` ints; returns the row
// count, or -1 when the key is missing, a row has another length or there are
// more than `cap` rows. A seat is written into the engine, so nothing here is
// filled in by default.
static int jrows(const char* s, const char* key, int* out, int cols, int cap) {
    const char* pa = ls_find_key(s, key);
    if (!pa) return -1;
    while (*pa == ' ') pa++;
    if (*pa != '[') return -1;
    const char* end = span(pa);
    const char* p = pa + 1;
    int rows = 0;
    for (;;) {
        // between rows: only separators, then a row or the end of the array
        while (p < end - 1 && (*p == ' ' || *p == ',')) p++;
        if (p >= end - 1) break;
        if (*p != '[' || rows == cap) return -1;
        const char* pe = span(p);
        const char* q = p + 1;
        int n = 0;
        while (q < pe) {
            while (q < pe && (*q == ' ' || *q == ',')) q++;
            if (*q == ']') break;
            char* stop;
            long v = strtol(q, &stop, 10);
            if (stop == q || n == cols || v < -1000000 || v > 1000000) return -1;
            out[rows * cols + n++] = (int)v;
            q = stop;
        }
        if (n != cols) return -1;
        rows++;
        p = pe;
    }
    return rows;
}

static void seat_parse(const char* line, seat_rec* s) {
    memset(s, 0, sizeof *s);
    const char* so = jobj(line, "seat");
    if (!so) return;
    static char buf[SEAT_BUF];
    int len = (int)(span(so) - so);
    if (len >= SEAT_BUF) {
        s->present = s->refused = 1;
        snprintf(s->why, sizeof s->why, "seat_too_long");
        return;
    }
    memcpy(buf, so, len);
    buf[len] = 0;
    s->present = 1;
    if (jstr(buf, "refuse", s->why, sizeof s->why)) {
        s->refused = 1;
        return;
    }
    s->half = (int)jint(buf, "half", -1);
    s->active = (int)jint(buf, "active", -1);
    s->kick = (int)jint(buf, "kick", -1);
    s->h1kick = (int)jint(buf, "h1kick", -1);
    s->weather = (int)jint(buf, "weather", -1);
    s->ktm = (int)jint(buf, "ktm", 0);
    s->tol = (int)jint(buf, "tol", 0);
    if (jarr(buf, "rr_mirror", s->rr_mirror, 2) != 2) {
        s->rr_mirror[0] = s->rr_mirror[1] = -1;
    }
    if (jarr(buf, "bonus_mirror", s->bonus_mirror, 2) != 2) {
        s->bonus_mirror[0] = s->bonus_mirror[1] = -1;
    }
    if (jarr(buf, "apo_mirror", s->apo_mirror, 2) != 2) {
        s->apo_mirror[0] = s->apo_mirror[1] = -1;
    }
    int ok = jarr(buf, "turn", s->turn, 2) == 2 &&
             jarr(buf, "score", s->score, 2) == 2 &&
             jarr(buf, "rr", s->rr, 2) == 2 &&
             jarr(buf, "bonus", s->bonus, 2) == 2 &&
             jarr(buf, "apo", s->apo, 2) == 2 &&
             jarr(buf, "bribes", s->bribes, 2) == 2 &&
             jarr(buf, "eject", s->eject, 2) == 2 &&
             jarr(buf, "cheer", s->cheer, 2) == 2 &&
             jarr(buf, "ball", s->ball, 3) == 3;
    s->npl = jrows(buf, "pl", &s->pl[0][0], SEAT_COLS, BB_NUM_PLAYERS);
    s->nsnack = jrows(buf, "snack", &s->snack[0][0], 2, BB_NUM_PLAYERS);
    if (!ok || s->npl < 0 || s->nsnack < 0) {
        s->refused = 1;
        s->npl = s->nsnack = 0;
        snprintf(s->why, sizeof s->why, "seat_unparseable");
    }
}

static bool seat_in(int v, int lo, int hi) {
    return v >= lo && v <= hi;
}

// Build the boundary state the seat describes into *out. `carry` supplies only
// the stale bookkeeping listed above. Returns 0, or -1 with a reason: a seat
// that is out of range, self-contradictory, fails the engine's own boundary
// validator, or describes a team turn the engine would never have opened is
// refused, never repaired.
static int seat_build(const runner* R, const bb_match* carry, const seat_rec* s,
                      bb_match* out, char* why, size_t cap) {
    if (!s->present || s->refused) {
        snprintf(why, cap, "%s", s->present ? s->why : "no_seat");
        return -1;
    }
    if (!seat_in(s->half, 1, 2) || !seat_in(s->active, 0, 1) ||
        !seat_in(s->kick, 0, 1) || !seat_in(s->h1kick, 0, 1) ||
        !seat_in(s->weather, 0, BB_WEATHER_BLIZZARD) || !seat_in(s->ktm, 0, 1)) {
        snprintf(why, cap, "scalar_out_of_range");
        return -1;
    }
    int rr[2], bonus[2], apo[2];
    for (int t = 0; t < 2; t++) {
        // --seat-mirror-resources: take re-rolls and apothecaries from the
        // mapper's own engine-semantics mirror instead of the replay, so the
        // ops that follow (which the mapper wrote against that mirror) meet
        // the windows they expect.
        bool mirror = R->mirror_resources && s->rr_mirror[t] >= 0 &&
                      s->bonus_mirror[t] >= 0 && s->apo_mirror[t] >= 0;
        rr[t] = mirror ? s->rr_mirror[t] : s->rr[t];
        bonus[t] = mirror ? s->bonus_mirror[t] : s->bonus[t];
        apo[t] = mirror ? s->apo_mirror[t] : s->apo[t];
        if (bonus[t] > rr[t]) bonus[t] = mirror ? rr[t] : bonus[t];
    }
    for (int t = 0; t < 2; t++) {
        if (!seat_in(s->turn[t], 0, 8) || !seat_in(s->score[t], 0, 255) ||
            !seat_in(rr[t], 0, 255) || !seat_in(bonus[t], 0, rr[t]) ||
            !seat_in(apo[t], 0, 255) || !seat_in(s->bribes[t], 0, 255) ||
            !seat_in(s->eject[t], 0, 1) || !seat_in(s->cheer[t], 0, 1)) {
            snprintf(why, cap, "team_field_out_of_range");
            return -1;
        }
    }
    bb_match n = R->init_m;
    // Stale bookkeeping: monotone counters and the last child result.
    n.step_count = carry->step_count;
    n.ret = carry->ret;
    for (int t = 0; t < 2; t++) {
        n.surfs[t] = carry->surfs[t];
        n.turns_completed[t] = carry->turns_completed[t];
        n.turns_completed_held[t] = carry->turns_completed_held[t];
        n.turnovers_completed[t] = carry->turnovers_completed[t];
    }
    memset(n.grid, 0, sizeof n.grid);
    bool seen[BB_NUM_PLAYERS] = {false};
    for (int i = 0; i < s->npl; i++) {
        const int* r = s->pl[i];
        int slot = r[0];
        if (!seat_in(slot, 0, BB_NUM_PLAYERS - 1) || seen[slot] ||
            n.players[slot].location == BB_LOC_ABSENT ||
            !seat_in(r[1], BB_LOC_ON_PITCH, BB_LOC_SENT_OFF) ||
            !seat_in(r[4], BB_STANCE_STANDING, BB_STANCE_STUNNED_USED) ||
            (r[5] & ~0x0FFF) != 0 || !seat_in(r[6], 0, 0xFFFF)) {
            snprintf(why, cap, "player_row_invalid");
            return -1;
        }
        seen[slot] = true;
        bb_player* p = &n.players[slot];
        p->location = (uint8_t)r[1];
        p->stance = BB_STANCE_STANDING;
        p->x = p->y = 0;
        // HAS_BALL is set from the ball below, never taken on trust. A player
        // who left the pitch keeps last turn's latches (the engine clears
        // them at their team's next turn start, not on removal).
        p->flags = (uint16_t)(r[5] & ~BB_PF_HAS_BALL & ~BB_PF_ACTIVATING);
        p->skill_rr_used = (uint16_t)r[6];
        if (r[1] != BB_LOC_ON_PITCH) continue;
        if (!bb_on_pitch_xy(r[2], r[3]) || n.grid[r[2]][r[3]] != 0) {
            snprintf(why, cap, "player_square_invalid");
            return -1;
        }
        p->x = (uint8_t)r[2];
        p->y = (uint8_t)r[3];
        p->stance = (uint8_t)r[4];
        n.grid[r[2]][r[3]] = (uint8_t)(slot + 1);
    }
    for (int slot = 0; slot < BB_NUM_PLAYERS; slot++) {
        if (n.players[slot].location != BB_LOC_ABSENT && !seen[slot]) {
            snprintf(why, cap, "roster_player_missing");
            return -1;
        }
    }
    bool snacked[BB_NUM_PLAYERS] = {false};
    for (int i = 0; i < s->nsnack; i++) {
        int slot = s->snack[i][0];
        if (!seat_in(slot, 0, BB_NUM_PLAYERS - 1) || snacked[slot] ||
            n.players[slot].location == BB_LOC_ABSENT ||
            !seat_in(s->snack[i][1], 1, 32)) {
            snprintf(why, cap, "snack_row_invalid");
            return -1;
        }
        snacked[slot] = true;
        bb_player* v = &n.players[slot];
        for (int k = 0; k < s->snack[i][1]; k++) { // kickoff_event, Dodgy Snack
            if (v->ma > 1) v->ma--;
            if (v->av > 3) v->av--;
        }
    }
    if (!bb_on_pitch_xy(s->ball[0], s->ball[1])) {
        snprintf(why, cap, "ball_off_pitch");
        return -1;
    }
    int at = n.grid[s->ball[0]][s->ball[1]];
    if ((s->ball[2] != 0) != (at != 0)) {
        snprintf(why, cap, "ball_holder_mismatch");
        return -1;
    }
    n.ball.x = (uint8_t)s->ball[0];
    n.ball.y = (uint8_t)s->ball[1];
    if (at) {
        if (n.players[at - 1].stance != BB_STANCE_STANDING) {
            snprintf(why, cap, "ball_under_downed_player");
            return -1;
        }
        n.ball.state = BB_BALL_HELD;
        n.ball.carrier = (uint8_t)(at - 1);
        n.players[at - 1].flags |= BB_PF_HAS_BALL;
    } else {
        n.ball.state = BB_BALL_ON_GROUND;
        n.ball.carrier = BB_NO_PLAYER;
    }
    n.half = (uint8_t)s->half;
    n.active_team = (uint8_t)s->active;
    n.kicking_team = (uint8_t)s->kick;
    n.weather = (uint8_t)s->weather;
    n.ktm_used = (uint8_t)s->ktm;
    n.blitz_used = n.pass_used = n.handoff_used = n.foul_used = 0;
    n.ttm_used = n.secure_used = 0;
    for (int t = 0; t < 2; t++) {
        n.turn[t] = (uint8_t)s->turn[t];
        n.score[t] = (uint8_t)s->score[t];
        n.rerolls[t] = (uint8_t)rr[t];
        n.bonus_rerolls[t] = (uint8_t)bonus[t];
        n.apothecary[t] = (uint8_t)apo[t];
        n.bribes[t] = (uint8_t)s->bribes[t];
        n.coach_ejected[t] = (uint8_t)s->eject[t];
        n.cheer_assist[t] = (uint8_t)s->cheer[t];
    }
    // A fresh team turn: MATCH in its turn loop, TEAM_TURN awaiting its first
    // activation (proc_match.c / proc_turn.c; the same two frames
    // bb_state_bank_boundary_valid demands).
    memset(n.stack, 0, sizeof n.stack);
    n.stack[0].proc = BB_PROC_MATCH;
    n.stack[0].phase = 3;
    n.stack[0].data = (uint16_t)(MD_H1_KICKER_SET | (s->h1kick ? MD_H1_KICKER : 0));
    n.stack[1].proc = BB_PROC_TEAM_TURN;
    n.stack[1].phase = 1;
    n.stack[1].a = (uint8_t)s->active;
    n.stack_top = 2;
    n.status = BB_STATUS_DECISION;
    n.decision_team = (uint8_t)s->active;
    n.turnover = 0;
    if (!bb_state_bank_boundary_valid(&n)) {
        snprintf(why, cap, "boundary_validator");
        return -1;
    }
    // The engine ends a team turn nobody can act in without asking: such a
    // decision state does not exist, so do not invent one.
    static bb_action legal[BB_LEGAL_MAX];
    int nl = bb_legal_actions(&n, legal);
    bool can_act = false;
    for (int i = 0; i < nl; i++) {
        if (legal[i].type == BB_A_ACTIVATE) can_act = true;
    }
    if (!can_act) {
        snprintf(why, cap, "no_activatable_player");
        return -1;
    }
    *out = n;
    return 0;
}

// Field-by-field difference between the engine's live state and a state
// built from the seat. Appends short tokens to `out`, returns their number
// and ORs each token's class into *mask. Player tokens carry both values so
// the audit can tell which way a field is wrong: "p.stance.own(L3/S1)" =
// live 3, seat 1.
enum {
    SD_HARD = 1,     // what the replay shows on the pitch: squares, location,
                     // stance, ball, score, half, turn counters, whose turn
    SD_SOFT = 2,     // replay-recorded resources and statuses: re-rolls,
                     // apothecaries, Bribes, weather, coach ban, Distracted /
                     // Rooted / Eye Gouged, Dodgy Snack characteristics
    SD_DERIVED = 4,  // mapper-derived engine latches (last turn's USED /
                     // BLITZED / Pro / skill re-rolls, Cheering Fans assist,
                     // ktm_used)
    SD_BOOK = 8,     // bookkeeping no observation, mask or rule reads before
                     // the engine itself resets it: moved / rushes of the
                     // team not on turn, step_count, turns_completed*, surfs,
                     // ret, spp_game
};

typedef struct {
    char* out;
    size_t cap, len;
    int n, mask;
} seat_diff_sink;

static void seat_tok(seat_diff_sink* k, int cls, const char* fmt, ...) {
    char tok[64];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(tok, sizeof tok, fmt, ap);
    va_end(ap);
    k->n++;
    k->mask |= cls;
    // one token per kind per boundary is enough for the rates
    size_t tl = strlen(tok);
    const char* hit = k->len ? strstr(k->out, tok) : 0;
    if (hit && (hit == k->out || hit[-1] == ',') &&
        (hit[tl] == ',' || hit[tl] == 0)) return;
    if (k->len + tl + 2 >= k->cap) return;
    if (k->len) k->out[k->len++] = ',';
    memcpy(k->out + k->len, tok, tl + 1);
    k->len += tl;
}

#define SEAT_CMP(cls, field, name) \
    do { \
        if (live->field != seat->field) \
            seat_tok(&k, cls, "%s(L%d/S%d)", name, (int)live->field, (int)seat->field); \
    } while (0)

static int seat_diff(const bb_match* live, const bb_match* seat, char* out,
                     size_t cap, int* mask) {
    static const char* FLAG[12] = {"USED", "ACTIVATING", "DISTRACTED", "HAS_BALL",
                                   "BLITZED", "ROOTED", "HYPNOTIZED", "SKILL_A",
                                   "SKILL_B", "SECURED", "NO_TZ", "EYE_GOUGED"};
    static const int FLAG_CLASS[12] = {SD_DERIVED, SD_HARD, SD_SOFT, SD_HARD,
                                       SD_DERIVED, SD_SOFT, SD_SOFT, SD_DERIVED,
                                       SD_DERIVED, SD_SOFT, SD_SOFT, SD_SOFT};
    seat_diff_sink k = {out, cap, 0, 0, 0};
    out[0] = 0;
    // BB_SEAT_DETAIL=1 (debugging): name the player slot in every token.
    bool detail = getenv("BB_SEAT_DETAIL") != 0;
    for (int i = 0; i < BB_NUM_PLAYERS; i++) {
        const bb_player* a = &live->players[i];
        const bb_player* b = &seat->players[i];
        char side[16];
        snprintf(side, sizeof side, detail ? "%s#%d" : "%s",
                 BB_TEAM_OF(i) == seat->active_team ? "own" : "opp", i);
        if (a->location != b->location) {
            seat_tok(&k, SD_HARD, "p.loc.%s(L%d/S%d)", side, a->location, b->location);
        } else if (a->location == BB_LOC_ON_PITCH && (a->x != b->x || a->y != b->y)) {
            seat_tok(&k, SD_HARD, "p.xy");
        }
        if (a->stance != b->stance) {
            seat_tok(&k, SD_HARD, "p.stance.%s(L%d/S%d)", side, a->stance, b->stance);
        }
        for (int bit = 0; bit < 12; bit++) {
            int la = (a->flags >> bit) & 1, lb = (b->flags >> bit) & 1;
            if (la != lb) {
                seat_tok(&k, FLAG_CLASS[bit], "p.flag.%s.%s(L%d/S%d)", FLAG[bit],
                         side, la, lb);
            }
        }
        if (a->ma != b->ma || a->av != b->av) seat_tok(&k, SD_SOFT, "p.ma_av");
        if (a->st != b->st || a->ag != b->ag || a->pa != b->pa) seat_tok(&k, SD_SOFT, "p.st_ag_pa");
        if (memcmp(&a->skills, &b->skills, sizeof a->skills) != 0) seat_tok(&k, SD_SOFT, "p.skills");
        if (a->moved != b->moved || a->rushes != b->rushes) seat_tok(&k, SD_BOOK, "p.moved_rushes.%s", side);
        if (a->skill_rr_used != b->skill_rr_used) seat_tok(&k, SD_DERIVED, "p.skill_rr_used.%s", side);
        if (a->spp_game != b->spp_game) seat_tok(&k, SD_BOOK, "p.spp_game");
        if (a->position_id != b->position_id || a->star_id != b->star_id ||
            a->niggling != b->niggling || a->p_loner != b->p_loner ||
            a->p_bloodlust != b->p_bloodlust) seat_tok(&k, SD_SOFT, "p.static");
    }
    SEAT_CMP(SD_HARD, ball.state, "ball.state");
    if (live->ball.x != seat->ball.x || live->ball.y != seat->ball.y) seat_tok(&k, SD_HARD, "ball.xy");
    SEAT_CMP(SD_HARD, ball.carrier, "ball.carrier");
    SEAT_CMP(SD_HARD, half, "half");
    SEAT_CMP(SD_HARD, active_team, "active_team");
    SEAT_CMP(SD_SOFT, kicking_team, "kicking_team");
    SEAT_CMP(SD_SOFT, weather, "weather");
    SEAT_CMP(SD_HARD, blitz_used, "blitz_used");
    SEAT_CMP(SD_HARD, pass_used, "pass_used");
    SEAT_CMP(SD_HARD, handoff_used, "handoff_used");
    SEAT_CMP(SD_HARD, foul_used, "foul_used");
    SEAT_CMP(SD_HARD, ttm_used, "ttm_used");
    SEAT_CMP(SD_DERIVED, ktm_used, "ktm_used");
    SEAT_CMP(SD_HARD, secure_used, "secure_used");
    for (int t = 0; t < 2; t++) {
        const char* side = t == seat->active_team ? "own" : "opp";
        if (live->turn[t] != seat->turn[t])
            seat_tok(&k, SD_HARD, "turn.%s(%+d)", side, (int)seat->turn[t] - (int)live->turn[t]);
        if (live->score[t] != seat->score[t]) seat_tok(&k, SD_HARD, "score");
        if (live->rerolls[t] != seat->rerolls[t])
            seat_tok(&k, SD_SOFT, "rerolls(%+d)", (int)seat->rerolls[t] - (int)live->rerolls[t]);
        if (live->rerolls_start[t] != seat->rerolls_start[t]) seat_tok(&k, SD_SOFT, "rerolls_start");
        if (live->bonus_rerolls[t] != seat->bonus_rerolls[t]) seat_tok(&k, SD_SOFT, "bonus_rerolls");
        if (live->apothecary[t] != seat->apothecary[t])
            seat_tok(&k, SD_SOFT, "apothecary(%+d)", (int)seat->apothecary[t] - (int)live->apothecary[t]);
        if (live->bribes[t] != seat->bribes[t])
            seat_tok(&k, SD_SOFT, "bribes(%+d)", (int)seat->bribes[t] - (int)live->bribes[t]);
        if (live->fan_factor[t] != seat->fan_factor[t]) seat_tok(&k, SD_SOFT, "fan_factor");
        if (live->cheer_assist[t] != seat->cheer_assist[t])
            seat_tok(&k, SD_DERIVED, "cheer_assist(L%d/S%d)", live->cheer_assist[t], seat->cheer_assist[t]);
        if (live->surfs[t] != seat->surfs[t]) seat_tok(&k, SD_BOOK, "surfs");
        if (live->coach_ejected[t] != seat->coach_ejected[t]) seat_tok(&k, SD_SOFT, "coach_ejected");
        if (live->team_id[t] != seat->team_id[t]) seat_tok(&k, SD_SOFT, "team_id");
        if (live->turns_completed[t] != seat->turns_completed[t] ||
            live->turns_completed_held[t] != seat->turns_completed_held[t] ||
            live->turnovers_completed[t] != seat->turnovers_completed[t])
            seat_tok(&k, SD_BOOK, "turns_completed");
    }
    SEAT_CMP(SD_HARD, stack_top, "stack_top");
    for (int i = 0; i < 2; i++) {
        const bb_frame* fa = &live->stack[i];
        const bb_frame* fb = &seat->stack[i];
        if (fa->proc != fb->proc || fa->phase != fb->phase || fa->data != fb->data ||
            fa->b != fb->b || fa->x != fb->x || fa->y != fb->y ||
            (i == 0 && fa->a != fb->a)) {  // TEAM_TURN.a is active_team, above
            seat_tok(&k, SD_HARD, "stack[%d](L%d.%d.%d/S%d.%d.%d)", i, fa->proc,
                     fa->phase, fa->data, fb->proc, fb->phase, fb->data);
        }
    }
    SEAT_CMP(SD_HARD, status, "status");
    SEAT_CMP(SD_HARD, decision_team, "decision_team");
    SEAT_CMP(SD_HARD, turnover, "turnover");
    if (live->ret != seat->ret) seat_tok(&k, SD_BOOK, "ret");
    if (live->step_count != seat->step_count) seat_tok(&k, SD_BOOK, "step_count");
    if (mask) *mask = k.mask;
    return k.n;
}

// What a human at this boundary could see in FUMBBL and the engine must agree
// on for the turn that follows to mean the same thing: the clock. Everything
// else the mirror-based expect op already compares (squares, stance class,
// ball, score).
static bool seat_clock_matches(const bb_match* m, const seat_rec* s) {
    return m->status == BB_STATUS_DECISION && m->stack_top == 2 &&
           m->stack[1].proc == BB_PROC_TEAM_TURN && m->stack[1].phase == 1 &&
           m->active_team == s->active && m->half == s->half &&
           m->turn[0] == s->turn[0] && m->turn[1] == s->turn[1];
}

// Recover from a loss: put the engine into the seat's state and open a new
// segment. Returns 0 on success; a seat that cannot be built leaves the
// runner lost.
static int seat_recover(runner* R, const seat_rec* s, const bb_match* carry,
                        long cmd, const char* cause) {
    char why[64];
    bb_match n;
    if (seat_build(R, carry, s, &n, why, sizeof why) != 0) {
        if (s->present && s->refused) R->seat_refused++;
        else R->seat_failed++;
        printf("{\"seat_skip\":true,\"replay\":\"%s\",\"cmd\":%ld,\"why\":\"%s\"}\n",
               R->replay, cmd, why);
        return -1;
    }
    R->m = n;
    R->lost = 0;
    R->segment++;
    R->reseats++;
    R->span_clean = 1;
    pd_abort();
    SD.staged = 0;
    printf("{\"reseat\":true,\"replay\":\"%s\",\"cmd\":%ld,\"seg\":%d,\"half\":%d,"
           "\"active\":%d,\"turn\":[%d,%d],\"cause\":\"%s\",\"lost_decisions\":%ld}\n",
           R->replay, cmd, R->segment, s->half, s->active, s->turn[0], s->turn[1],
           cause, R->span_lost);
    R->span_lost = 0;
    return 0;
}

static void seat_audit_line(const runner* R, long cmd, const seat_rec* s,
                            const bb_match* built, const char* fail) {
    if (fail) {
        printf("{\"audit\":true,\"replay\":\"%s\",\"cmd\":%ld,\"seg\":%d,"
               "\"build_fail\":\"%s\"}\n", R->replay, cmd, R->segment, fail);
        return;
    }
    char diff[2048];
    int mask = 0;
    int nd = seat_diff(&R->m, built, diff, sizeof diff, &mask);
    // rr_known: the re-roll difference is one the mapper's own mirror shares
    // with the engine (a rules or mapping difference it already models).
    bool rr_known = s->rr_mirror[0] == R->m.rerolls[0] &&
                    s->rr_mirror[1] == R->m.rerolls[1];
    printf("{\"audit\":true,\"replay\":\"%s\",\"cmd\":%ld,\"seg\":%d,\"n\":%d,"
           "\"mask\":%d,\"tol\":%d,\"rr_known\":%d,\"diff\":\"%s\"}\n",
           R->replay, cmd, R->segment, nd, mask, s->tol, rr_known ? 1 : 0, diff);
}

// Every expect op (= team-turn boundary) goes through here. Returns 0 when
// the op counts as applied.
//
// Prefix (segment 0): the mapper's mirror-based expect is the check, exactly
// as without --reseat; --reseat adds the clock check.
// Re-seated provenance (segment > 0) at a seatable boundary: the replay's own
// boundary state is BOTH the check and the next state. The span that just
// ended is stamped with how the engine compared with it (PD_SPAN_MATCH /
// _SOFT / _DRIFT); then the engine is re-synced to the seat so drift never
// carries into the next team turn.
static int on_expect(runner* R, const char* line, long cmd) {
    seat_rec s;
    seat_parse(line, &s);
    bool usable = s.present && !s.refused;
    char why[64];
    bb_match built;
    R->spans++;
    if (R->reseat && R->lost) {
        seat_recover(R, &s, &R->m, cmd, R->last_class);
        return -1;
    }
    if (R->reseat && R->segment > 0 && usable &&
        seat_build(R, &R->m, &s, &built, why, sizeof why) == 0) {
        char diff[2048];
        int mask = 0;
        if (R->mirror_resources) {
            // The stamp says how the engine compares with the REPLAY, also
            // when the next state is seated from the mapper's mirror.
            bb_match truth;
            R->mirror_resources = 0;
            int rc_truth = seat_build(R, &R->m, &s, &truth, why, sizeof why);
            R->mirror_resources = 1;
            diff[0] = 0;
            if (rc_truth == 0) seat_diff(&R->m, &truth, diff, sizeof diff, &mask);
            else mask = SD_SOFT;
        } else {
            seat_diff(&R->m, &built, diff, sizeof diff, &mask);
        }
        int status = (mask & SD_HARD) ? PD_SPAN_DRIFT
                     : (mask & (SD_SOFT | SD_DERIVED)) ? PD_SPAN_SOFT
                     : PD_SPAN_MATCH;
        pd_span_flush(status);
        if (status == PD_SPAN_MATCH) R->spans_aligned++;
        else if (status == PD_SPAN_SOFT) R->spans_soft_drift++;
        else R->spans_drift++;
        printf("{\"close\":true,\"replay\":\"%s\",\"cmd\":%ld,\"seg\":%d,"
               "\"status\":%d,\"mask\":%d,\"diff\":\"%s\"}\n",
               R->replay, cmd, R->segment, status, mask, diff);
        R->m = built;
        R->syncs++;
        R->span_clean = 1;
        R->prev_boundary = R->m;
        R->have_prev_boundary = 1;
        return 0;
    }
    int rc = do_expect(R, line, cmd);
    if (rc != 0) {
        pd_span_flush(PD_SPAN_OPEN);
        SD.staged = 0;
        if (R->reseat) seat_recover(R, &s, &R->m, cmd, R->last_class);
        return rc;
    }
    if (R->seat_audit && usable) {
        // Rebuild this boundary from a carry one team turn stale (what a real
        // re-seat after a lost turn would have) and diff against the state the
        // engine reached legally.
        const bb_match* carry = R->have_prev_boundary ? &R->prev_boundary : &R->m;
        if (seat_build(R, carry, &s, &built, why, sizeof why) != 0) {
            seat_audit_line(R, cmd, &s, 0, why);
        } else {
            seat_audit_line(R, cmd, &s, &built, 0);
        }
    }
    if (R->reseat && usable && !seat_clock_matches(&R->m, &s)) {
        // Squares, ball and score agree but the engine is in another team's
        // turn or another turn number: the ops that follow belong to a turn
        // the engine is not in.
        char ours[160], theirs[160];
        snprintf(ours, sizeof ours, "engine half %d active %d turn [%d,%d] status %s",
                 R->m.half, R->m.active_team, R->m.turn[0], R->m.turn[1],
                 status_name(R->m.status));
        snprintf(theirs, sizeof theirs, "half %d active %d turn [%d,%d]", s.half,
                 s.active, s.turn[0], s.turn[1]);
        report_divergence(R, cmd, "clock", ours, theirs);
        pd_span_flush(PD_SPAN_OPEN);
        SD.staged = 0;
        seat_recover(R, &s, &R->m, cmd, R->last_class);
        return -1;
    }
    // Passed the mapper's mirror check only (the prefix, or no seat here).
    if (R->span_clean) R->spans_mirror++;
    pd_span_flush(PD_SPAN_MIRROR);
    if (R->force_reseat && usable) {
        bb_match carry = R->have_prev_boundary ? R->prev_boundary : R->m;
        bb_match live = R->m;
        if (seat_build(R, &carry, &s, &built, why, sizeof why) == 0) {
            char diff[2048];
            int mask = 0;
            seat_diff(&live, &built, diff, sizeof diff, &mask);
            R->m = built;
            R->segment++;
            R->reseats++;
            SD.staged = 0;
            printf("{\"forced\":true,\"replay\":\"%s\",\"cmd\":%ld,\"seg\":%d,"
                   "\"tol\":%d,\"mask\":%d}\n", R->replay, cmd, R->segment, s.tol, mask);
        } else {
            R->seat_failed++;
            printf("{\"seat_skip\":true,\"replay\":\"%s\",\"cmd\":%ld,\"why\":\"%s\"}\n",
                   R->replay, cmd, why);
        }
        R->prev_boundary = live;
        R->have_prev_boundary = 1;
        R->span_clean = 1;
        return 0;
    }
    R->prev_boundary = R->m;
    R->have_prev_boundary = 1;
    R->span_clean = 1;
    return 0;
}

// --- act ----------------------------------------------------------------------------

static int do_act(runner* R, const char* line, long cmd) {
    char ours[512], theirs[256];
    // END_TURN is legal in every team turn (and in the Charge! loop), so
    // legality cannot show that the engine has already ended this turn by
    // itself and the op would end the NEXT turn, which nobody played. The
    // mapper names the turn it is closing (lockstep_map.py end_turn: team,
    // half and that team's turn number; "charge" for the Charge! loop). If
    // the engine has moved past that turn (another team's turn, a later
    // turn of the same team, or no team turn at all), an END_TURN without
    // dice is redundant and dropped (return 1); one with dice means the dice
    // were needed earlier, which is a stop. An engine whose counter is
    // BEHIND the replay's is still in the turn being closed: applied.
    long end_team = jint(line, "team", -1);
    long end_charge = jint(line, "charge", 0);
    if (jint(line, "type", 0) == BB_A_END_TURN && (end_team >= 0 || end_charge)) {
        long end_half = jint(line, "half", -1), end_turn = jint(line, "turn", -1);
        bool deciding = R->m.status == BB_STATUS_DECISION && R->m.stack_top > 0;
        int top_proc = deciding ? R->m.stack[R->m.stack_top - 1].proc : BB_PROC_NONE;
        bool ahead = end_half >= 0 && end_turn >= 0 &&
                     (R->m.half > end_half ||
                      (R->m.half == end_half && R->m.turn[end_team & 1] > end_turn));
        bool in_turn = end_charge
            ? top_proc == BB_PROC_KICKOFF
            : top_proc == BB_PROC_TEAM_TURN &&
              R->m.decision_team == (uint8_t)end_team && !ahead;
        if (!in_turn) {
            int unused[MAX_DICE];
            int waiting = jarr(line, "dice", unused, MAX_DICE);
            if (waiting == 0) {
                R->end_turn_dropped++;
                return 1;
            }
            snprintf(ours, sizeof ours, "engine is not waiting in that turn (half %d "
                     "decision team %d turns [%d,%d])", R->m.half,
                     R->m.decision_team, R->m.turn[0], R->m.turn[1]);
            snprintf(theirs, sizeof theirs, "END_TURN for team %ld half %ld turn %ld "
                     "with %d dice", end_team, end_half, end_turn, waiting);
            report_divergence(R, cmd, "wrong_team", ours, theirs);
            return -1;
        }
    }
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
    // BC pair: pre-action obs staged, committed on success. An op the mapper
    // flags "nopair" is applied but not recorded: its decision state holds a
    // value the replay never had (see the apothecary shortcut in the mapper).
    if (!jint(line, "nopair", 0)) pd_stage(R, a, cmd);
    bb_rng rng;
    arm_rng(R, &rng, script, nd, cmd, "act");
    bb_status st = bb_apply(&R->m, a, &rng);
    int rc = check_transition(R, cmd, &rng, st);
    if (rc == 0) pd_commit_segment(R->segment);
    else pd_abort();
    return rc;
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
    pd_stage(R, a, cmd); // BC pair: setup placements are decisions too
    bb_rng rng;
    uint8_t script[MAX_DICE];
    arm_rng(R, &rng, script, 0, cmd, "place");
    bb_status st = bb_apply(&R->m, a, &rng);
    int rc = check_transition(R, cmd, &rng, st);
    if (rc == 0) pd_commit_segment(R->segment);
    else pd_abort();
    return rc;
}

// --- trace (debug) -------------------------------------------------------------------

static void trace_state(const runner* R, long cmd, const char* op) {
    fprintf(stderr, "cmd=%ld %s st=%s act=%d turn=[%d,%d] stack=", cmd, op,
            status_name(R->m.status), R->m.active_team, R->m.turn[0],
            R->m.turn[1]);
    print_stack(stderr, &R->m);
    fprintf(stderr, "\n");
    if (getenv("BB_LOCKSTEP_BOARD")) {
        for (int s = 0; s < BB_NUM_PLAYERS; s++) {
            const bb_player* p = &R->m.players[s];
            if (p->location != BB_LOC_ON_PITCH) continue;
            fprintf(stderr, "  [%d,%d] at %d,%d st=%d%s\n",
                    s / BB_TEAM_SLOTS, s % BB_TEAM_SLOTS, p->x, p->y,
                    engine_state_code(p),
                    (p->flags & BB_PF_HAS_BALL) ? " BALL" : "");
        }
        fprintf(stderr, "  ball %d,%d state=%d\n", R->m.ball.x, R->m.ball.y,
                R->m.ball.state);
    }
}

// --- main --------------------------------------------------------------------------

int main(int argc, char** argv) {
    runner R;
    memset(&R, 0, sizeof R);
    const char* path = 0;
    const char* dump_path = 0;
    const char* reseat_dump_path = 0;
    const char* states_path = 0;
    R.span_clean = 1;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-v") == 0) R.verbose = 1;
        else if (strcmp(argv[i], "--reseat") == 0) R.reseat = 1;
        else if (strcmp(argv[i], "--force-reseat") == 0) R.force_reseat = 1;
        else if (strcmp(argv[i], "--seat-audit") == 0) R.seat_audit = 1;
        else if (strcmp(argv[i], "--seat-mirror-resources") == 0) R.mirror_resources = 1;
        else if (strcmp(argv[i], "--dump-pairs-reseat") == 0 && i + 1 < argc) {
            reseat_dump_path = argv[++i];
        }
        else if (strcmp(argv[i], "--pad") == 0 && i + 1 < argc) {
            R.pad = (int)strtol(argv[++i], 0, 10);
        } else if (strcmp(argv[i], "--dump-pairs") == 0 && i + 1 < argc) {
            dump_path = argv[++i];
        } else if (strcmp(argv[i], "--dump-states") == 0 && i + 1 < argc) {
            states_path = argv[++i];
        } else path = argv[i];
    }
    if (!path) {
        fprintf(stderr,
                "usage: bb_lockstep [-v] [--pad N] [--dump-pairs <out.bbp>]\n"
                "           [--dump-states <out.bbs>] [--reseat] [--force-reseat]\n"
                "           [--seat-audit] [--dump-pairs-reseat <out.bbr>] <script.jsonl>\n"
                "  -v       stderr line per consumed die with the live proc stack\n"
                "  --pad N  append N filler dice (value 1) per op so the roll that\n"
                "           would underrun shows up as an EXTRA die in -v output;\n"
                "           reported divergences are unchanged\n"
                "  --dump-pairs <out.bbp>  write one BC (obs, mask, action) record\n"
                "           per successfully applied act/place op (format: see the\n"
                "           .bbp comment block in this file / validation/README.md)\n"
                "  --dump-states <out.bbs>  write one raw bb_match snapshot per\n"
                "           team-turn boundary reached in lockstep, for the env's\n"
                "           demo-state reset curriculum (format: see the .bbs\n"
                "           comment block in this file / validation/README.md)\n"
                "  --reseat  PROTOTYPE: after a divergence, resume at the next\n"
                "           team-turn boundary by writing the state the replay\n"
                "           records there into the engine (state surgery: see the\n"
                "           re-seat comment block). Nothing after a re-seat reaches\n"
                "           --dump-pairs or --dump-states\n"
                "  --dump-pairs-reseat <out.bbr>  records written after a re-seat\n"
                "           (BBP v4 record layout, magic BBR1, segment number in\n"
                "           the pad bytes); without it they are counted only\n"
                "  --seat-audit  at every boundary reached in lockstep, rebuild\n"
                "           the state from the seat and report each field that\n"
                "           differs from the engine's own state\n"
                "  --force-reseat  TEST: replace the state at EVERY seatable\n"
                "           boundary although nothing diverged\n"
                "  --seat-mirror-resources  EXPERIMENT: seat re-rolls and\n"
                "           apothecaries from the mapper's engine-semantics mirror\n"
                "           instead of the replay's own counts\n");
        return 2;
    }
    if (R.reseat && R.force_reseat) {
        fprintf(stderr, "--reseat and --force-reseat are separate experiments\n");
        return 2;
    }
    if (dump_path) pd_open(dump_path);
    if (reseat_dump_path) pd_open_reseat(reseat_dump_path);
    if (states_path) sd_open(states_path);
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
        R.cur_line = line;
        if (strcmp(op, "skip") == 0) {
            R.skips++;
            R.ops_applied++; // skips are accounted, not applied to the engine
            continue;
        }
        bool is_expect = strcmp(op, "expect") == 0;
        bool is_decision = strcmp(op, "place") == 0 ||
                           (strcmp(op, "act") == 0 && !jint(line, "nopair", 0));
        if (R.reseat && R.lost) {
            // Lost: nothing is applied until a boundary the replay can seat.
            if (is_decision) {
                R.lost_decisions++;
                R.span_lost++;
            }
            if (is_expect) on_expect(&R, line, cmd);
            continue;
        }
        if (R.diverged && !R.reseat) continue; // keep counting ops_total for % consumed
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
        } else if (is_expect) {
            rc = on_expect(&R, line, cmd);
        }
        if (rc == 1) { // dropped as redundant: neither applied nor a stop
            R.ops_applied++;
            ctx_push(&R, line);
            continue;
        }
        if (rc != 0) {
            SD.staged = 0; // never confirmed: a later op must not commit it
            pd_span_flush(PD_SPAN_OPEN);
            if (R.reseat && is_decision) {
                R.lost_decisions++;
                R.span_lost++;
            }
        }
        if (rc == 0) {
            R.ops_applied++;
            sd_on_op_applied(&R, cmd);
        }
        if (getenv("BB_LOCKSTEP_TRACE")) trace_state(&R, cmd, op);
        ctx_push(&R, line);
    }
    fclose(f);
    double pct = R.ops_total ? 100.0 * R.ops_applied / R.ops_total : 0.0;
    char pairs[32] = "";
    if (PD.f) {
        snprintf(pairs, sizeof pairs, ",\"pairs\":%ld", PD.pairs);
        fclose(PD.f);
    }
    pd_span_flush(PD_SPAN_OPEN); // the script ended inside a span
    if (PD.f_reseat) fclose(PD.f_reseat);
    char states[32] = "";
    if (SD.f) {
        // A boundary staged by the final op of a fully consumed script has no
        // following op to confirm it; commit it iff nothing diverged (and
        // nothing was re-seated: a forced re-seat diverges from nothing).
        if (!R.diverged && R.segment == 0) sd_commit();
        snprintf(states, sizeof states, ",\"states\":%ld", SD.states);
        fclose(SD.f);
    }
    char seat[512] = "";
    if (R.reseat || R.force_reseat || R.seat_audit) {
        snprintf(seat, sizeof seat,
                 ",\"reseats\":%d,\"syncs\":%d,\"pairs_reseat\":%ld,"
                 "\"pairs_by_span_status\":[%ld,%ld,%ld,%ld,%ld],\"divergences\":%d,"
                 "\"lost_decisions\":%ld,\"seat_refused\":%d,\"seat_failed\":%d,"
                 "\"spans\":%d,\"spans_aligned\":%d,\"spans_mirror\":%d,"
                 "\"spans_drift\":%d,"
                 "\"spans_soft_drift\":%d,\"end_turn_dropped\":%d,"
                 "\"ended_lost\":%s",
                 R.reseats, R.syncs, PD.pairs_reseat, PD.span_status[0],
                 PD.span_status[1], PD.span_status[2], PD.span_status[3],
                 PD.span_status[4],
                 R.divergences, R.lost_decisions, R.seat_refused, R.seat_failed,
                 R.spans, R.spans_aligned, R.spans_mirror, R.spans_drift,
                 R.spans_soft_drift, R.end_turn_dropped, R.lost ? "true" : "false");
    }
    printf("{\"summary\":true,\"replay\":\"%s\",\"ops_total\":%d,"
           "\"ops_applied\":%d,\"pct_consumed\":%.1f,\"skips\":%d,"
           "\"diverged\":%s,\"engine_score\":[%d,%d],\"engine_status\":\"%s\","
           "\"unmapped_skills\":%d%s%s%s}\n",
           R.replay, R.ops_total, R.ops_applied, pct, R.skips,
           R.diverged ? "true" : "false", R.m.score[0], R.m.score[1],
           status_name(R.m.status), R.unmapped_skills, pairs, states, seat);
    return 0;
}

#ifndef BBE_STATE_BANK_RUNTIME_H
#define BBE_STATE_BANK_RUNTIME_H

/*
 * Included by bloodbowl.h after the engine amalgamation.  bb_match,
 * bb_state_bank_boundary_valid(), bb_state_bank_resumable_valid(),
 * bb_legal_actions(), and bbe_state_fingerprint() are therefore available.
 */
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdatomic.h>
#include <stdint.h>
#include <sys/stat.h>
#include <unistd.h>

#include "state_bank_sha256.h"

#ifndef BBE_STATE_BANK_BUILD_HEADER
#define BBE_STATE_BANK_BUILD_HEADER "state_bank_build.h"
#endif
#include BBE_STATE_BANK_BUILD_HEADER

#define BBE_STATE_BANK_REC_META 12u
#define BBE_STATE_BANK_MAX_BBS_BYTES (UINT64_C(256) * 1024u * 1024u)
#define BBE_STATE_BANK_MAX_RECORDS UINT64_C(1000000)
#define BBE_STATE_BANK_MAX_MANIFEST_BYTES (UINT64_C(4) * 1024u * 1024u)
#define BBE_STATE_BANK_MAX_PATH 4096u

typedef enum {
    BBE_STATE_BANK_NONE = 0,
    BBE_STATE_BANK_STRICT_REPLAY = 1,
    BBE_STATE_BANK_AUTHORED_SCENARIO = 2,
} bbe_state_bank_kind;

typedef struct {
    uint32_t source_id;
    uint32_t command;
    uint8_t half;
    uint8_t turn;
} bbe_state_bank_meta;

typedef enum {
    BBE_SB_OK = 0,
    BBE_SB_REQUEST_KIND_NONE,
    BBE_SB_REQUEST_KIND_UNKNOWN,
    BBE_SB_REQUEST_AUTHORED_DISABLED,
    BBE_SB_REQUEST_INCOMPLETE,
    BBE_SB_REQUEST_PATH_TOO_LONG,
    BBE_SB_REQUEST_LIMIT,
    BBE_SB_CONTRACT_OPEN,
    BBE_SB_CONTRACT_NOT_REGULAR,
    BBE_SB_CONTRACT_SIZE,
    BBE_SB_CONTRACT_READ,
    BBE_SB_CONTRACT_HASH,
    BBE_SB_PRODUCER_OPEN,
    BBE_SB_PRODUCER_NOT_REGULAR,
    BBE_SB_PRODUCER_SIZE,
    BBE_SB_PRODUCER_READ,
    BBE_SB_PRODUCER_HASH,
    BBE_SB_BBS_OPEN,
    BBE_SB_BBS_NOT_REGULAR,
    BBE_SB_BBS_SIZE,
    BBE_SB_BBS_READ,
    BBE_SB_BBS_HASH,
    BBE_SB_BBS_HEADER,
    BBE_SB_BBS_COUNT,
    BBE_SB_ALLOC,
    BBE_SB_RECORD_METADATA,
    BBE_SB_RECORD_NAMESPACE,
    BBE_SB_RECORD_STRUCTURE,
    BBE_SB_RECORD_LEGAL_ACTIONS,
    BBE_SB_IDENTITY_CONFLICT,
    BBE_SB_CONFIG_RESET_PCT,
    BBE_SB_CONFIG_RESET_PCT_UNDERFLOW,
    BBE_SB_CONFIG_KIND,
    BBE_SB_CONFIG_SELECTOR,
    BBE_SB_CONFIG_MULTIPLE_SELECTORS,
    BBE_SB_CONFIG_INERT_SELECTOR,
    BBE_SB_CONFIG_INERT_KIND,
    BBE_SB_CONFIG_MISSING_KIND,
    BBE_SB_CONFIG_KIND_MISMATCH,
    BBE_SB_CONFIG_TEAM_SENTINEL,
    BBE_SB_CONFIG_SELECTOR_BRIDGE,
} bbe_state_bank_error;

static const char* bbe_state_bank_error_name(bbe_state_bank_error error) {
    static const char* const names[] = {
        "ok",
        "requested bank kind is none",
        "unknown state-bank kind",
        "authored publisher not implemented",
        "compiled state-bank contract is incomplete",
        "state-bank path exceeds 4095 bytes",
        "state-bank contract exceeds a hard resource limit",
        "training contract open failed",
        "training contract is not a regular file",
        "training contract size is invalid",
        "training contract read failed",
        "training contract sha256 mismatch",
        "producer manifest open failed",
        "producer manifest is not a regular file",
        "producer manifest size is invalid",
        "producer manifest read failed",
        "producer manifest sha256 mismatch",
        "state bank open failed",
        "state bank is not a regular file",
        "state bank size is invalid",
        "state bank read failed",
        "state bank sha256 mismatch",
        "state bank header mismatch",
        "state bank record count mismatch",
        "state bank allocation failed",
        "state bank record metadata is invalid",
        "state bank record namespace is invalid",
        "state bank record is not resumable at the required boundary",
        "state bank record has no bounded legal-action surface",
        "state-bank process identity conflict",
        "demo_reset_pct must be finite and in [0,1]",
        "positive demo_reset_pct underflows to zero as float",
        "state_bank_kind must be an exact supported integer",
        "state-bank selectors must be exact nonnegative integers",
        "at most one state-bank selector may be nonzero",
        "a state-bank selector is inert when demo_reset_pct is zero",
        "state_bank_kind is inert when demo_reset_pct is zero",
        "positive demo_reset_pct requires a nonzero state_bank_kind",
        "requested state_bank_kind differs from the compiled contract",
        "banked resets require exact -1 team sentinels",
        "pre-indexed state-bank strata required",
    };
    size_t count = sizeof names / sizeof names[0];
    return (unsigned)error < count ? names[error] : "unknown state-bank error";
}

typedef struct {
    const char* contract_schema;
    const char* producer_schema;
    const char* authorization_schema;
    int kind;
    const char* kind_name;
    const char* ruleset;
    const char* bbs_sha256;
    const char* producer_manifest_sha256;
    const char* training_contract_sha256;
    const char* producer_engine_source_sha256;
    const char* loader_engine_source_sha256;
    uint64_t bbs_bytes;
    uint64_t records;
    uint32_t bbs_version;
    uint32_t match_size;
    uint32_t engine_fingerprint;
    const char* contract_identity;
    const char* bbs_path;
    const char* producer_manifest_path;
    const char* training_contract_path;
    /*
     * Candidate-parser tests may inspect structural-proof bytes.  The
     * process-global require path rejects this flag and kind 2.
     */
    int test_only_allow_authored;
} bbe_state_bank_request;

typedef struct {
    bb_match* matches;
    bbe_state_bank_meta* metadata;
    size_t count;
    int kind;
} bbe_state_bank_candidate;

static void bbe_state_bank_candidate_close(bbe_state_bank_candidate* candidate) {
    if (candidate == NULL) return;
    free(candidate->matches);
    free(candidate->metadata);
    memset(candidate, 0, sizeof *candidate);
}

static uint32_t bbe_state_bank_le32(const uint8_t* b) {
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) |
           ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

static int bbe_state_bank_string_is(const char* got, const char* expected) {
    return got != NULL && strcmp(got, expected) == 0;
}

static size_t bbe_state_bank_bounded_strlen(const char* value,
                                            size_t maximum) {
    if (value == NULL) return maximum;
    size_t length = 0;
    while (length < maximum && value[length] != '\0') length++;
    return length;
}

static int bbe_state_bank_path_valid(const char* path) {
    return path != NULL && path[0] != '\0' &&
           bbe_state_bank_bounded_strlen(
               path, BBE_STATE_BANK_MAX_PATH) < BBE_STATE_BANK_MAX_PATH;
}

static int bbe_state_bank_small_string_valid(const char* value,
                                             size_t maximum) {
    return value != NULL && value[0] != '\0' &&
           bbe_state_bank_bounded_strlen(value, maximum) < maximum;
}

static bbe_state_bank_error bbe_state_bank_validate_request(
        const bbe_state_bank_request* request, int production) {
    if (request == NULL) return BBE_SB_REQUEST_INCOMPLETE;
    if (request->kind == BBE_STATE_BANK_NONE) return BBE_SB_REQUEST_KIND_NONE;
    if (request->kind == BBE_STATE_BANK_AUTHORED_SCENARIO) {
        if (production || !request->test_only_allow_authored) {
            return BBE_SB_REQUEST_AUTHORED_DISABLED;
        }
    } else if (request->kind != BBE_STATE_BANK_STRICT_REPLAY) {
        return BBE_SB_REQUEST_KIND_UNKNOWN;
    }
    if (production && request->test_only_allow_authored) {
        return BBE_SB_REQUEST_AUTHORED_DISABLED;
    }
    if (!bbe_state_bank_string_is(
            request->contract_schema,
            "bloodbowl-state-bank-training-contract-v1") ||
        !bbe_state_bank_string_is(
            request->producer_schema,
            "bloodbowl-state-bank-producer-v1") ||
        !bbe_state_bank_string_is(
            request->authorization_schema,
            "bloodbowl-state-bank-authorization-v1") ||
        !bbe_state_bank_string_is(request->ruleset, "BB2025") ||
        !bbe_state_bank_small_string_valid(request->kind_name, 64) ||
        !bbe_state_bank_small_string_valid(request->contract_identity, 256) ||
        !bbe_sha256_valid_hex(request->bbs_sha256) ||
        !bbe_sha256_valid_hex(request->producer_manifest_sha256) ||
        !bbe_sha256_valid_hex(request->training_contract_sha256) ||
        !bbe_sha256_valid_hex(request->producer_engine_source_sha256) ||
        !bbe_sha256_valid_hex(request->loader_engine_source_sha256)) {
        return BBE_SB_REQUEST_INCOMPLETE;
    }
    if ((request->kind == BBE_STATE_BANK_STRICT_REPLAY &&
         !bbe_state_bank_string_is(request->kind_name, "strict-replay")) ||
        (request->kind == BBE_STATE_BANK_AUTHORED_SCENARIO &&
         !bbe_state_bank_string_is(request->kind_name, "authored-scenario"))) {
        return BBE_SB_REQUEST_INCOMPLETE;
    }
    if (!bbe_state_bank_path_valid(request->bbs_path) ||
        !bbe_state_bank_path_valid(request->producer_manifest_path) ||
        !bbe_state_bank_path_valid(request->training_contract_path)) {
        return BBE_SB_REQUEST_PATH_TOO_LONG;
    }
    if (request->bbs_bytes == 0 ||
        request->bbs_bytes > BBE_STATE_BANK_MAX_BBS_BYTES ||
        request->bbs_bytes > SIZE_MAX ||
        request->records == 0 ||
        request->records > BBE_STATE_BANK_MAX_RECORDS ||
        request->records > INT_MAX ||
        request->records > SIZE_MAX / sizeof(bb_match) ||
        request->records > SIZE_MAX / sizeof(bbe_state_bank_meta) ||
        request->bbs_version != 1 ||
        request->match_size != sizeof(bb_match) ||
        request->engine_fingerprint != bbe_state_fingerprint()) {
        return BBE_SB_REQUEST_LIMIT;
    }
    uint64_t record_bytes =
        (uint64_t)BBE_STATE_BANK_REC_META + request->match_size;
    if (request->records > (UINT64_MAX - 16u) / record_bytes ||
        16u + request->records * record_bytes != request->bbs_bytes) {
        return BBE_SB_REQUEST_LIMIT;
    }
    return BBE_SB_OK;
}

static int bbe_state_bank_open_regular(const char* path, struct stat* st) {
    int flags = O_RDONLY;
#ifdef O_CLOEXEC
    flags |= O_CLOEXEC;
#endif
#ifdef O_NOFOLLOW
    flags |= O_NOFOLLOW;
#endif
    int fd = open(path, flags);
    if (fd < 0) return -1;
    if (fstat(fd, st) != 0 || !S_ISREG(st->st_mode)) {
        int saved = errno;
        close(fd);
        errno = saved;
        return -2;
    }
    return fd;
}

static int bbe_state_bank_read_exact(int fd, uint8_t* bytes, size_t size) {
    size_t offset = 0;
    while (offset < size) {
        ssize_t n = read(fd, bytes + offset, size - offset);
        if (n > 0) {
            offset += (size_t)n;
            continue;
        }
        if (n < 0 && errno == EINTR) continue;
        return -1;
    }
    uint8_t trailing;
    for (;;) {
        ssize_t n = read(fd, &trailing, 1);
        if (n == 0) return 0;
        if (n < 0 && errno == EINTR) continue;
        return -1;
    }
}

static bbe_state_bank_error bbe_state_bank_check_manifest(
        const char* path, const char* expected_sha,
        bbe_state_bank_error open_error,
        bbe_state_bank_error regular_error,
        bbe_state_bank_error size_error,
        bbe_state_bank_error read_error,
        bbe_state_bank_error hash_error) {
    struct stat st;
    int fd = bbe_state_bank_open_regular(path, &st);
    if (fd == -1) return open_error;
    if (fd == -2) return regular_error;
    if (st.st_size <= 0 ||
        (uint64_t)st.st_size > BBE_STATE_BANK_MAX_MANIFEST_BYTES ||
        (uint64_t)st.st_size > SIZE_MAX) {
        close(fd);
        return size_error;
    }
    size_t size = (size_t)st.st_size;
    uint8_t* bytes = (uint8_t*)malloc(size);
    if (bytes == NULL) {
        close(fd);
        return BBE_SB_ALLOC;
    }
    int read_result = bbe_state_bank_read_exact(fd, bytes, size);
    int close_result = close(fd);
    if (read_result != 0 || close_result != 0) {
        free(bytes);
        return read_error;
    }
    uint8_t digest[32];
    bbe_sha256_bytes(bytes, size, digest);
    free(bytes);
    return bbe_sha256_matches(digest, expected_sha) ? BBE_SB_OK : hash_error;
}

/*
 * Pure, nonfatal, reentrant candidate loader.  It does not touch process
 * globals; output remains empty unless every byte and every record validates.
 */
static bbe_state_bank_error bbe_state_bank_load_candidate(
        const bbe_state_bank_request* request,
        bbe_state_bank_candidate* output) {
    if (output == NULL) return BBE_SB_REQUEST_INCOMPLETE;
    memset(output, 0, sizeof *output);
    bbe_state_bank_error error =
        bbe_state_bank_validate_request(request, 0);
    if (error != BBE_SB_OK) return error;

    error = bbe_state_bank_check_manifest(
        request->training_contract_path, request->training_contract_sha256,
        BBE_SB_CONTRACT_OPEN, BBE_SB_CONTRACT_NOT_REGULAR,
        BBE_SB_CONTRACT_SIZE, BBE_SB_CONTRACT_READ, BBE_SB_CONTRACT_HASH);
    if (error != BBE_SB_OK) return error;
    error = bbe_state_bank_check_manifest(
        request->producer_manifest_path, request->producer_manifest_sha256,
        BBE_SB_PRODUCER_OPEN, BBE_SB_PRODUCER_NOT_REGULAR,
        BBE_SB_PRODUCER_SIZE, BBE_SB_PRODUCER_READ, BBE_SB_PRODUCER_HASH);
    if (error != BBE_SB_OK) return error;

    struct stat st;
    int fd = bbe_state_bank_open_regular(request->bbs_path, &st);
    if (fd == -1) return BBE_SB_BBS_OPEN;
    if (fd == -2) return BBE_SB_BBS_NOT_REGULAR;
    if (st.st_size < 0 || (uint64_t)st.st_size != request->bbs_bytes) {
        close(fd);
        return BBE_SB_BBS_SIZE;
    }
    size_t bbs_size = (size_t)request->bbs_bytes;
    uint8_t* bytes = (uint8_t*)malloc(bbs_size);
    if (bytes == NULL) {
        close(fd);
        return BBE_SB_ALLOC;
    }
    int read_result = bbe_state_bank_read_exact(fd, bytes, bbs_size);
    int close_result = close(fd);
    if (read_result != 0 || close_result != 0) {
        free(bytes);
        return BBE_SB_BBS_READ;
    }
    uint8_t digest[32];
    bbe_sha256_bytes(bytes, bbs_size, digest);
    if (!bbe_sha256_matches(digest, request->bbs_sha256)) {
        free(bytes);
        return BBE_SB_BBS_HASH;
    }
    if (memcmp(bytes, "BBS1", 4) != 0 ||
        bbe_state_bank_le32(bytes + 4) != request->bbs_version ||
        bbe_state_bank_le32(bytes + 8) != request->match_size ||
        bbe_state_bank_le32(bytes + 12) != request->engine_fingerprint) {
        free(bytes);
        return BBE_SB_BBS_HEADER;
    }
    size_t record_size = BBE_STATE_BANK_REC_META + request->match_size;
    if ((bbs_size - 16u) / record_size != request->records ||
        (bbs_size - 16u) % record_size != 0) {
        free(bytes);
        return BBE_SB_BBS_COUNT;
    }

    size_t count = (size_t)request->records;
    bb_match* matches = (bb_match*)malloc(count * sizeof *matches);
    bbe_state_bank_meta* metadata =
        (bbe_state_bank_meta*)calloc(count, sizeof *metadata);
    if (matches == NULL || metadata == NULL) {
        free(bytes);
        free(matches);
        free(metadata);
        return BBE_SB_ALLOC;
    }
    for (size_t i = 0; i < count; i++) {
        const uint8_t* record = bytes + 16u + i * record_size;
        bbe_state_bank_meta meta = {0};
        meta.source_id = bbe_state_bank_le32(record);
        meta.command = bbe_state_bank_le32(record + 4);
        meta.half = record[8];
        meta.turn = record[9];
        memcpy(&matches[i], record + BBE_STATE_BANK_REC_META,
               sizeof matches[i]);
        const bb_match* match = &matches[i];
        if (meta.source_id == 0 || record[10] != 0 || record[11] != 0 ||
            meta.half < 1 || meta.half > 3 ||
            meta.turn < 1 || meta.turn > 8 ||
            match->half != meta.half || match->active_team > BB_AWAY ||
            match->turn[match->active_team] != meta.turn) {
            error = BBE_SB_RECORD_METADATA;
            goto reject;
        }
        int authored_namespace =
            (meta.source_id & UINT32_C(0xf0000000)) ==
            UINT32_C(0xa0000000);
        if ((request->kind == BBE_STATE_BANK_STRICT_REPLAY &&
             authored_namespace) ||
            (request->kind == BBE_STATE_BANK_AUTHORED_SCENARIO &&
             !authored_namespace)) {
            error = BBE_SB_RECORD_NAMESPACE;
            goto reject;
        }
        int structurally_valid =
            request->kind == BBE_STATE_BANK_STRICT_REPLAY
                ? bb_state_bank_boundary_valid(match)
                : bb_state_bank_resumable_valid(match);
        if (!structurally_valid) {
            error = BBE_SB_RECORD_STRUCTURE;
            goto reject;
        }
        bb_action legal[BB_LEGAL_MAX];
        int n_legal = bb_legal_actions(match, legal);
        if (n_legal <= 0 || n_legal > BB_LEGAL_MAX) {
            error = BBE_SB_RECORD_LEGAL_ACTIONS;
            goto reject;
        }
        metadata[i] = meta;
    }
    free(bytes);
    output->matches = matches;
    output->metadata = metadata;
    output->count = count;
    output->kind = request->kind;
    return BBE_SB_OK;

reject:
    free(bytes);
    free(matches);
    free(metadata);
    return error;
}

typedef enum {
    BBE_SB_UNTRIED = 0,
    BBE_SB_READY,
    BBE_SB_FAILED,
} bbe_state_bank_process_status;

typedef struct {
    int valid;
    int kind;
    uint64_t bbs_bytes;
    uint64_t records;
    uint32_t bbs_version;
    uint32_t match_size;
    uint32_t engine_fingerprint;
    int test_only_allow_authored;
    char contract_schema[128];
    char producer_schema[128];
    char authorization_schema[128];
    char kind_name[64];
    char ruleset[64];
    char contract_identity[256];
    char bbs_sha256[65];
    char producer_manifest_sha256[65];
    char training_contract_sha256[65];
    char producer_engine_source_sha256[65];
    char loader_engine_source_sha256[65];
    char bbs_path[BBE_STATE_BANK_MAX_PATH];
    char producer_manifest_path[BBE_STATE_BANK_MAX_PATH];
    char training_contract_path[BBE_STATE_BANK_MAX_PATH];
} bbe_state_bank_identity;

static atomic_flag bbe_state_bank_lock = ATOMIC_FLAG_INIT;
static bbe_state_bank_process_status bbe_state_bank_status = BBE_SB_UNTRIED;
static bbe_state_bank_error bbe_state_bank_failure = BBE_SB_OK;
static bbe_state_bank_identity bbe_state_bank_loaded_identity;
static int bbe_state_bank_failure_identity_valid = 0;
static uint8_t bbe_state_bank_failure_identity[32];
static bb_match* bbe_state_bank = NULL;
static bbe_state_bank_meta* bbe_state_bank_metadata = NULL;
static int bbe_state_bank_n = 0;
static int bbe_state_bank_loaded_kind = BBE_STATE_BANK_NONE;
static unsigned bbe_state_bank_load_attempts = 0;
static unsigned bbe_state_bank_publications = 0;
static int bbe_state_bank_location_override_set = 0;
static char bbe_state_bank_bbs_path_override[BBE_STATE_BANK_MAX_PATH];
static char bbe_state_bank_producer_path_override[BBE_STATE_BANK_MAX_PATH];
static char bbe_state_bank_contract_path_override[BBE_STATE_BANK_MAX_PATH];

static void bbe_state_bank_lock_acquire(void) {
    while (atomic_flag_test_and_set_explicit(
               &bbe_state_bank_lock, memory_order_acquire)) {
    }
}

static void bbe_state_bank_lock_release(void) {
    atomic_flag_clear_explicit(&bbe_state_bank_lock, memory_order_release);
}

static void bbe_state_bank_fingerprint_u64(
        bbe_sha256* fingerprint, uint64_t value) {
    uint8_t bytes[8];
    for (int i = 0; i < 8; i++) {
        bytes[i] = (uint8_t)(value >> (8u * (unsigned)i));
    }
    bbe_sha256_update(fingerprint, bytes, sizeof bytes);
}

static void bbe_state_bank_fingerprint_string(
        bbe_sha256* fingerprint, uint8_t field, const char* value,
        size_t maximum) {
    uint8_t present = value != NULL;
    bbe_sha256_update(fingerprint, &field, sizeof field);
    bbe_sha256_update(fingerprint, &present, sizeof present);
    bbe_state_bank_fingerprint_u64(fingerprint, (uint64_t)maximum);
    if (!present) return;

    size_t length = bbe_state_bank_bounded_strlen(value, maximum);
    uint8_t terminated = length < maximum;
    bbe_sha256_update(fingerprint, &terminated, sizeof terminated);
    bbe_state_bank_fingerprint_u64(fingerprint, (uint64_t)length);
    bbe_sha256_update(fingerprint, value, length);
}

/*
 * Bounded identity for requests whose strings cannot be copied into the
 * ordinary exact identity (NULL, empty, or unterminated within a hard limit).
 * A field tag, presence bit, termination bit, bounded length, and bounded
 * bytes make every value inside the accepted read domain unambiguous.
 */
static void bbe_state_bank_request_fingerprint(
        const bbe_state_bank_request* request, uint8_t output[32]) {
    static const char domain[] =
        "bbe-state-bank-request-fingerprint-v1";
    bbe_sha256 fingerprint;
    bbe_sha256_init(&fingerprint);
    bbe_sha256_update(&fingerprint, domain, sizeof domain - 1u);
    uint8_t present = request != NULL;
    bbe_sha256_update(&fingerprint, &present, sizeof present);
    if (request != NULL) {
        bbe_state_bank_fingerprint_u64(
            &fingerprint, (uint64_t)(int64_t)request->kind);
        bbe_state_bank_fingerprint_u64(
            &fingerprint, request->bbs_bytes);
        bbe_state_bank_fingerprint_u64(
            &fingerprint, request->records);
        bbe_state_bank_fingerprint_u64(
            &fingerprint, request->bbs_version);
        bbe_state_bank_fingerprint_u64(
            &fingerprint, request->match_size);
        bbe_state_bank_fingerprint_u64(
            &fingerprint, request->engine_fingerprint);
        bbe_state_bank_fingerprint_u64(
            &fingerprint,
            (uint64_t)(int64_t)request->test_only_allow_authored);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 1, request->contract_schema, 128);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 2, request->producer_schema, 128);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 3, request->authorization_schema, 128);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 4, request->kind_name, 64);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 5, request->ruleset, 64);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 6, request->bbs_sha256, 65);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 7, request->producer_manifest_sha256, 65);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 8, request->training_contract_sha256, 65);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 9, request->producer_engine_source_sha256, 65);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 10, request->loader_engine_source_sha256, 65);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 11, request->contract_identity, 256);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 12, request->bbs_path,
            BBE_STATE_BANK_MAX_PATH);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 13, request->producer_manifest_path,
            BBE_STATE_BANK_MAX_PATH);
        bbe_state_bank_fingerprint_string(
            &fingerprint, 14, request->training_contract_path,
            BBE_STATE_BANK_MAX_PATH);
    }
    bbe_sha256_final(&fingerprint, output);
}

static int bbe_state_bank_failure_identity_matches(
        const bbe_state_bank_request* request) {
    uint8_t fingerprint[32];
    bbe_state_bank_request_fingerprint(request, fingerprint);
    return bbe_state_bank_failure_identity_valid &&
        memcmp(fingerprint, bbe_state_bank_failure_identity,
               sizeof fingerprint) == 0;
}

static int bbe_state_bank_identity_can_store(
        const bbe_state_bank_request* request) {
    return request != NULL &&
        bbe_state_bank_small_string_valid(request->contract_schema, 128) &&
        bbe_state_bank_small_string_valid(request->producer_schema, 128) &&
        bbe_state_bank_small_string_valid(
            request->authorization_schema, 128) &&
        bbe_state_bank_small_string_valid(request->kind_name, 64) &&
        bbe_state_bank_small_string_valid(request->ruleset, 64) &&
        bbe_state_bank_small_string_valid(request->contract_identity, 256) &&
        bbe_sha256_valid_hex(request->bbs_sha256) &&
        bbe_sha256_valid_hex(request->producer_manifest_sha256) &&
        bbe_sha256_valid_hex(request->training_contract_sha256) &&
        bbe_sha256_valid_hex(request->producer_engine_source_sha256) &&
        bbe_sha256_valid_hex(request->loader_engine_source_sha256) &&
        bbe_state_bank_path_valid(request->bbs_path) &&
        bbe_state_bank_path_valid(request->producer_manifest_path) &&
        bbe_state_bank_path_valid(request->training_contract_path);
}

static void bbe_state_bank_identity_store(
        bbe_state_bank_identity* identity,
        const bbe_state_bank_request* request) {
    memset(identity, 0, sizeof *identity);
    identity->kind = request->kind;
    identity->bbs_bytes = request->bbs_bytes;
    identity->records = request->records;
    identity->bbs_version = request->bbs_version;
    identity->match_size = request->match_size;
    identity->engine_fingerprint = request->engine_fingerprint;
    identity->test_only_allow_authored = request->test_only_allow_authored;
#define BBE_SB_COPY_IDENTITY(field)                                             \
    memcpy(identity->field, request->field, strlen(request->field) + 1)
    BBE_SB_COPY_IDENTITY(contract_schema);
    BBE_SB_COPY_IDENTITY(producer_schema);
    BBE_SB_COPY_IDENTITY(authorization_schema);
    BBE_SB_COPY_IDENTITY(kind_name);
    BBE_SB_COPY_IDENTITY(ruleset);
    BBE_SB_COPY_IDENTITY(contract_identity);
    BBE_SB_COPY_IDENTITY(bbs_sha256);
    BBE_SB_COPY_IDENTITY(producer_manifest_sha256);
    BBE_SB_COPY_IDENTITY(training_contract_sha256);
    BBE_SB_COPY_IDENTITY(producer_engine_source_sha256);
    BBE_SB_COPY_IDENTITY(loader_engine_source_sha256);
    BBE_SB_COPY_IDENTITY(bbs_path);
    BBE_SB_COPY_IDENTITY(producer_manifest_path);
    BBE_SB_COPY_IDENTITY(training_contract_path);
#undef BBE_SB_COPY_IDENTITY
    identity->valid = 1;
}

static int bbe_state_bank_identity_matches(
        const bbe_state_bank_identity* identity,
        const bbe_state_bank_request* request) {
    return identity->valid && request != NULL &&
        identity->kind == request->kind &&
        identity->bbs_bytes == request->bbs_bytes &&
        identity->records == request->records &&
        identity->bbs_version == request->bbs_version &&
        identity->match_size == request->match_size &&
        identity->engine_fingerprint == request->engine_fingerprint &&
        identity->test_only_allow_authored ==
            request->test_only_allow_authored &&
        bbe_state_bank_string_is(request->contract_schema,
                                 identity->contract_schema) &&
        bbe_state_bank_string_is(request->producer_schema,
                                 identity->producer_schema) &&
        bbe_state_bank_string_is(request->authorization_schema,
                                 identity->authorization_schema) &&
        bbe_state_bank_string_is(request->kind_name,
                                 identity->kind_name) &&
        bbe_state_bank_string_is(request->ruleset, identity->ruleset) &&
        bbe_state_bank_string_is(request->contract_identity,
                                 identity->contract_identity) &&
        bbe_state_bank_string_is(request->bbs_sha256,
                                 identity->bbs_sha256) &&
        bbe_state_bank_string_is(request->producer_manifest_sha256,
                                 identity->producer_manifest_sha256) &&
        bbe_state_bank_string_is(request->training_contract_sha256,
                                 identity->training_contract_sha256) &&
        bbe_state_bank_string_is(request->producer_engine_source_sha256,
                                 identity->producer_engine_source_sha256) &&
        bbe_state_bank_string_is(request->loader_engine_source_sha256,
                                 identity->loader_engine_source_sha256) &&
        bbe_state_bank_string_is(request->bbs_path, identity->bbs_path) &&
        bbe_state_bank_string_is(request->producer_manifest_path,
                                 identity->producer_manifest_path) &&
        bbe_state_bank_string_is(request->training_contract_path,
                                 identity->training_contract_path);
}

static bbe_state_bank_request bbe_state_bank_compiled_request(
        const char* bbs_path, const char* producer_path,
        const char* contract_path) {
    bbe_state_bank_request request = {
        PUFFER_STATE_BANK_CONTRACT_SCHEMA,
        PUFFER_STATE_BANK_PRODUCER_SCHEMA,
        PUFFER_STATE_BANK_AUTHORIZATION_SCHEMA,
        PUFFER_STATE_BANK_COMPILED_KIND,
        PUFFER_STATE_BANK_KIND_NAME,
        PUFFER_STATE_BANK_RULESET,
        PUFFER_STATE_BANK_BBS_SHA256,
        PUFFER_STATE_BANK_PRODUCER_MANIFEST_SHA256,
        PUFFER_STATE_BANK_TRAINING_CONTRACT_SHA256,
        PUFFER_STATE_BANK_PRODUCER_ENGINE_SOURCE_SHA256,
        PUFFER_STATE_BANK_LOADER_ENGINE_SOURCE_SHA256,
        PUFFER_STATE_BANK_BBS_BYTES,
        PUFFER_STATE_BANK_RECORDS,
        PUFFER_STATE_BANK_BBS_VERSION,
        PUFFER_STATE_BANK_MATCH_SIZE,
        PUFFER_STATE_BANK_ENGINE_FINGERPRINT,
        PUFFER_STATE_BANK_CONTRACT_IDENTITY,
        bbs_path != NULL ? bbs_path : PUFFER_STATE_BANK_BBS_PATH,
        producer_path != NULL ? producer_path
                              : PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH,
        contract_path != NULL ? contract_path
                              : PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH,
        0,
    };
    return request;
}

/*
 * Nonfatal stateful core used by tests and by the aborting production wrapper.
 * A failed exact request is never retried; a different later request conflicts.
 */
static bbe_state_bank_error bbe_state_bank_require_core(
        const bbe_state_bank_request* request) {
    bbe_state_bank_lock_acquire();
    if (bbe_state_bank_status != BBE_SB_UNTRIED) {
        bbe_state_bank_error result;
        int same_identity = bbe_state_bank_loaded_identity.valid
            ? bbe_state_bank_identity_matches(
                  &bbe_state_bank_loaded_identity, request)
            : bbe_state_bank_failure_identity_matches(request);
        if (!same_identity) {
            result = BBE_SB_IDENTITY_CONFLICT;
        } else {
            result = bbe_state_bank_status == BBE_SB_READY
                         ? BBE_SB_OK : bbe_state_bank_failure;
        }
        bbe_state_bank_lock_release();
        return result;
    }

    bbe_state_bank_error error =
        bbe_state_bank_validate_request(request, 1);
    if (!bbe_state_bank_identity_can_store(request)) {
        if (error == BBE_SB_OK) error = BBE_SB_REQUEST_INCOMPLETE;
        bbe_state_bank_request_fingerprint(
            request, bbe_state_bank_failure_identity);
        bbe_state_bank_failure_identity_valid = 1;
        bbe_state_bank_status = BBE_SB_FAILED;
        bbe_state_bank_failure = error;
        bbe_state_bank_lock_release();
        return error;
    }
    bbe_state_bank_identity_store(&bbe_state_bank_loaded_identity, request);
    bbe_state_bank_load_attempts++;
    if (error == BBE_SB_OK) {
        bbe_state_bank_candidate candidate;
        error = bbe_state_bank_load_candidate(request, &candidate);
        if (error == BBE_SB_OK) {
            bbe_state_bank = candidate.matches;
            bbe_state_bank_metadata = candidate.metadata;
            bbe_state_bank_n = (int)candidate.count;
            bbe_state_bank_loaded_kind = candidate.kind;
            bbe_state_bank_status = BBE_SB_READY;
            bbe_state_bank_failure = BBE_SB_OK;
            bbe_state_bank_publications++;
            fprintf(stderr,
                    "bloodbowl: loaded state bank kind=%s records=%d "
                    "bbs=%s producer=%s contract=%s\n",
                    request->kind_name, bbe_state_bank_n,
                    request->bbs_sha256,
                    request->producer_manifest_sha256,
                    request->training_contract_sha256);
            bbe_state_bank_lock_release();
            return BBE_SB_OK;
        }
    }
    bbe_state_bank_status = BBE_SB_FAILED;
    bbe_state_bank_failure = error;
    bbe_state_bank_lock_release();
    return error;
}

static void bbe_state_bank_require_paths_or_abort(
        int requested_kind, const char* bbs_path, const char* producer_path,
        const char* contract_path) {
    bbe_state_bank_request request = bbe_state_bank_compiled_request(
        bbs_path, producer_path, contract_path);
    if (requested_kind != request.kind) {
        fprintf(stderr,
                "bloodbowl: state-bank startup failed: %s "
                "(requested=%d compiled=%d)\n",
                bbe_state_bank_error_name(BBE_SB_CONFIG_KIND_MISMATCH),
                requested_kind, request.kind);
        abort();
    }
    bbe_state_bank_error error = bbe_state_bank_require_core(&request);
    if (error != BBE_SB_OK) {
        fprintf(stderr, "bloodbowl: state-bank startup failed: %s\n",
                bbe_state_bank_error_name(error));
        abort();
    }
}

static void bbe_state_bank_require_or_abort(int requested_kind) {
    char bbs_path[BBE_STATE_BANK_MAX_PATH];
    char producer_path[BBE_STATE_BANK_MAX_PATH];
    char contract_path[BBE_STATE_BANK_MAX_PATH];
    int have_override;

    bbe_state_bank_lock_acquire();
    have_override = bbe_state_bank_location_override_set;
    if (have_override) {
        memcpy(bbs_path, bbe_state_bank_bbs_path_override,
               sizeof bbs_path);
        memcpy(producer_path, bbe_state_bank_producer_path_override,
               sizeof producer_path);
        memcpy(contract_path, bbe_state_bank_contract_path_override,
               sizeof contract_path);
    }
    bbe_state_bank_lock_release();

    bbe_state_bank_require_paths_or_abort(
        requested_kind, have_override ? bbs_path : NULL,
        have_override ? producer_path : NULL,
        have_override ? contract_path : NULL);
}

static void bbe_state_bank_set_location_overrides(
        const char* bbs_path, const char* producer_path,
        const char* contract_path) {
    size_t bbs_length =
        bbe_state_bank_bounded_strlen(bbs_path, BBE_STATE_BANK_MAX_PATH);
    size_t producer_length =
        bbe_state_bank_bounded_strlen(producer_path,
                                      BBE_STATE_BANK_MAX_PATH);
    size_t contract_length =
        bbe_state_bank_bounded_strlen(contract_path,
                                      BBE_STATE_BANK_MAX_PATH);
    if (bbs_length == 0 || bbs_length >= BBE_STATE_BANK_MAX_PATH ||
        producer_length == 0 ||
        producer_length >= BBE_STATE_BANK_MAX_PATH ||
        contract_length == 0 ||
        contract_length >= BBE_STATE_BANK_MAX_PATH) {
        fprintf(stderr, "bloodbowl: state-bank location override: %s\n",
                bbe_state_bank_error_name(BBE_SB_REQUEST_PATH_TOO_LONG));
        abort();
    }

    bbe_state_bank_lock_acquire();
    if (bbe_state_bank_status != BBE_SB_UNTRIED &&
        (!bbe_state_bank_loaded_identity.valid ||
         strcmp(bbe_state_bank_loaded_identity.bbs_path, bbs_path) != 0 ||
         strcmp(bbe_state_bank_loaded_identity.producer_manifest_path,
                producer_path) != 0 ||
         strcmp(bbe_state_bank_loaded_identity.training_contract_path,
                contract_path) != 0)) {
        bbe_state_bank_lock_release();
        fprintf(stderr, "bloodbowl: state-bank location override: %s\n",
                bbe_state_bank_error_name(BBE_SB_IDENTITY_CONFLICT));
        abort();
    }
    memcpy(bbe_state_bank_bbs_path_override, bbs_path, bbs_length + 1u);
    memcpy(bbe_state_bank_producer_path_override, producer_path,
           producer_length + 1u);
    memcpy(bbe_state_bank_contract_path_override, contract_path,
           contract_length + 1u);
    bbe_state_bank_location_override_set = 1;
    bbe_state_bank_lock_release();
}

typedef struct {
    double reset_pct;
    double kind;
    double endzone_selector;
    double pickup_selector;
    double postkick_selector;
    double pass_selector;
    double exclude_team;
    double force_home_team;
    double force_away_team;
} bbe_state_bank_config_values;

static int bbe_state_bank_exact_int(double value, int minimum, int maximum) {
    return isfinite(value) && value >= minimum && value <= maximum &&
           value == (double)(int)value;
}

static bbe_state_bank_error bbe_state_bank_validate_config_values(
        const bbe_state_bank_config_values* values, int compiled_kind) {
    if (values == NULL || !isfinite(values->reset_pct) ||
        values->reset_pct < 0.0 || values->reset_pct > 1.0) {
        return BBE_SB_CONFIG_RESET_PCT;
    }
    if (values->reset_pct > 0.0 && (float)values->reset_pct == 0.0f) {
        return BBE_SB_CONFIG_RESET_PCT_UNDERFLOW;
    }
    if (!bbe_state_bank_exact_int(
            values->kind, BBE_STATE_BANK_NONE,
            BBE_STATE_BANK_AUTHORED_SCENARIO)) {
        return BBE_SB_CONFIG_KIND;
    }
    int kind = (int)values->kind;
    if (kind == BBE_STATE_BANK_AUTHORED_SCENARIO) {
        return BBE_SB_REQUEST_AUTHORED_DISABLED;
    }
    const double selectors[] = {
        values->endzone_selector,
        values->pickup_selector,
        values->postkick_selector,
        values->pass_selector,
    };
    int nonzero = 0;
    for (size_t i = 0; i < sizeof selectors / sizeof selectors[0]; i++) {
        if (!bbe_state_bank_exact_int(selectors[i], 0, INT_MAX)) {
            return BBE_SB_CONFIG_SELECTOR;
        }
        nonzero += selectors[i] != 0.0;
    }
    if (nonzero > 1) return BBE_SB_CONFIG_MULTIPLE_SELECTORS;
    if (values->reset_pct == 0.0) {
        if (nonzero != 0) return BBE_SB_CONFIG_INERT_SELECTOR;
        if (kind != BBE_STATE_BANK_NONE) return BBE_SB_CONFIG_INERT_KIND;
        return BBE_SB_OK;
    }
    if (kind == BBE_STATE_BANK_NONE) return BBE_SB_CONFIG_MISSING_KIND;
    if (kind != compiled_kind) return BBE_SB_CONFIG_KIND_MISMATCH;
    if (values->exclude_team != -1.0 ||
        values->force_home_team != -1.0 ||
        values->force_away_team != -1.0) {
        return BBE_SB_CONFIG_TEAM_SENTINEL;
    }
    if (nonzero != 0) return BBE_SB_CONFIG_SELECTOR_BRIDGE;
    return BBE_SB_OK;
}

static int bbe_state_bank_effective_compiled_kind(void);

static void bbe_state_bank_validate_config_or_abort(
        const bbe_state_bank_config_values* values) {
    bbe_state_bank_error error = bbe_state_bank_validate_config_values(
        values, bbe_state_bank_effective_compiled_kind());
    if (error != BBE_SB_OK) {
        fprintf(stderr, "bloodbowl: invalid state-bank configuration: %s\n",
                bbe_state_bank_error_name(error));
        abort();
    }
}

#ifdef BBE_STATE_BANK_TESTING
static int bbe_state_bank_test_publication = 0;

static int bbe_state_bank_effective_compiled_kind(void) {
    return bbe_state_bank_test_publication
               ? bbe_state_bank_loaded_kind
               : PUFFER_STATE_BANK_COMPILED_KIND;
}

static void bbe_state_bank_test_reset_process(void) {
    bbe_state_bank_lock_acquire();
    free(bbe_state_bank);
    free(bbe_state_bank_metadata);
    bbe_state_bank = NULL;
    bbe_state_bank_metadata = NULL;
    bbe_state_bank_n = 0;
    bbe_state_bank_loaded_kind = BBE_STATE_BANK_NONE;
    bbe_state_bank_status = BBE_SB_UNTRIED;
    bbe_state_bank_failure = BBE_SB_OK;
    memset(&bbe_state_bank_loaded_identity, 0,
           sizeof bbe_state_bank_loaded_identity);
    bbe_state_bank_failure_identity_valid = 0;
    memset(bbe_state_bank_failure_identity, 0,
           sizeof bbe_state_bank_failure_identity);
    bbe_state_bank_load_attempts = 0;
    bbe_state_bank_publications = 0;
    bbe_state_bank_location_override_set = 0;
    memset(bbe_state_bank_bbs_path_override, 0,
           sizeof bbe_state_bank_bbs_path_override);
    memset(bbe_state_bank_producer_path_override, 0,
           sizeof bbe_state_bank_producer_path_override);
    memset(bbe_state_bank_contract_path_override, 0,
           sizeof bbe_state_bank_contract_path_override);
    bbe_state_bank_test_publication = 0;
    bbe_state_bank_lock_release();
}

static void bbe_state_bank_test_publish_candidate(
        bbe_state_bank_candidate* candidate) {
    bbe_state_bank_test_reset_process();
    bbe_state_bank = candidate->matches;
    bbe_state_bank_metadata = candidate->metadata;
    bbe_state_bank_n = (int)candidate->count;
    bbe_state_bank_loaded_kind = candidate->kind;
    bbe_state_bank_status = BBE_SB_READY;
    bbe_state_bank_test_publication = 1;
    candidate->matches = NULL;
    candidate->metadata = NULL;
    candidate->count = 0;
}
#else
static int bbe_state_bank_effective_compiled_kind(void) {
    return PUFFER_STATE_BANK_COMPILED_KIND;
}
#endif

#endif

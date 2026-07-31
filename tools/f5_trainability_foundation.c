#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L

/*
 * Build the sealed F5 qualification fixture from the complete immutable
 * authored-proof bundle. This is a qualification artifact generator, not a
 * state-bank publisher: durable identity is obtained only from the existing
 * complete-bundle mapper, while the one-record BBS retains its proof-local A9
 * transport ID.
 */
#include "authored_drill.h"
#include "bb/gen_skills.h"
#include "bb/gen_teams.h"
#include "state_bank_sha256.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#ifdef O_NOFOLLOW
#define F5_O_NOFOLLOW O_NOFOLLOW
#else
#define F5_O_NOFOLLOW 0
#endif

#ifdef O_DIRECTORY
#define F5_O_DIRECTORY O_DIRECTORY
#else
#define F5_O_DIRECTORY 0
#endif

#define F5_TASK_SCHEMA "bloodbowl-trainability-task-v1"
#define F5_FIXTURE_SCHEMA "bloodbowl-f5-fixture-v1"
#define F5_GENERATOR_SCHEMA "bloodbowl-f5-foundation-generator-v1"
#define F5_REFERENCE_TRACE_SCHEMA "bloodbowl-f5-reference-trace-v1"
#define F5_ROLE "f5-fixed-state-v1"
#define F5_RULESET "BB2025"

#define F5_FULL_BBS_SIZE 58568u
#define F5_BBS_SIZE 2268u
#define F5_MATCH_SIZE 2240u
#define F5_FULL_RECORDS 26u
#define F5_PROOF_INDEX 25u
#define F5_PROOF_SOURCE_ID 0xA9000019u
#define F5_DURABLE_SOURCE_ID 0xAE00001Au
#define F5_TEMPLATE_ID 5u
#define F5_RECIPE_REVISION 1u
#define F5_CELL_ID 1u
#define F5_VARIANT_ID 1u
#define F5_VARIANT_SEED 410u
#define F5_CAPTURE_ACTIONS 51u
#define F5_CAPTURE_DICE 19u
#define F5_ENGINE_FINGERPRINT 0x64897cdeu
#define F5_TEAM_COUNT 30u
#define F5_SKILL_COUNT 108u
#define F5_ACTION_TYPE_COUNT 30u

#define F5_FULL_BBS_SHA256 \
    "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1"
#define F5_BBS_SHA256 \
    "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71"
#define F5_MATCH_SHA256 \
    "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2"
#define F5_REFERENCE_TRACE_SHA256 \
    "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300"

static const char F5_REFERENCE_TRACE[] =
    "{\"actions\":[[6,6,390],[7,0,390],[9,32,254],[9,32,229],"
    "[9,32,204],[9,32,179],[9,32,154],[9,32,129]],"
    "\"schema\":\"bloodbowl-f5-reference-trace-v1\"}\n";

enum {
    F5_PATH_CAP = 4096,
    F5_HEADER_CAP = 32768,
    F5_TASK_CAP = 8192,
    F5_ERROR_CAP = 512,
};

typedef struct {
    uint8_t* data;
    size_t size;
} byte_buffer;

typedef struct {
    byte_buffer full_bbs;
    byte_buffer f5_bbs;
    byte_buffer raw_match;
    byte_buffer reference_trace;
    byte_buffer generated_header;
    byte_buffer task;
} f5_artifacts;

typedef struct {
    const char* name;
    const byte_buffer* bytes;
} artifact_file;

static int fail(char error[F5_ERROR_CAP], const char* format, ...) {
    if (error != NULL) {
        va_list args;
        va_start(args, format);
        vsnprintf(error, F5_ERROR_CAP, format, args);
        va_end(args);
    }
    return -1;
}

static void free_buffer(byte_buffer* buffer) {
    if (buffer == NULL) return;
    free(buffer->data);
    buffer->data = NULL;
    buffer->size = 0;
}

static void free_artifacts(f5_artifacts* artifacts) {
    if (artifacts == NULL) return;
    free_buffer(&artifacts->full_bbs);
    free_buffer(&artifacts->f5_bbs);
    free_buffer(&artifacts->raw_match);
    free_buffer(&artifacts->reference_trace);
    free_buffer(&artifacts->generated_header);
    free_buffer(&artifacts->task);
}

static int copy_buffer(byte_buffer* output, const void* bytes, size_t size,
                       char error[F5_ERROR_CAP]) {
    if (output == NULL || bytes == NULL || size == 0) {
        return fail(error, "invalid byte-buffer input");
    }
    uint8_t* copy = malloc(size);
    if (copy == NULL) return fail(error, "byte-buffer allocation failed");
    memcpy(copy, bytes, size);
    output->data = copy;
    output->size = size;
    return 0;
}

static void sha256_hex(const void* bytes, size_t size, char output[65]) {
    uint8_t digest[32];
    bbe_sha256_bytes(bytes, size, digest);
    bbe_sha256_hex(digest, output);
}

static int require_hash(const char* label, const void* bytes, size_t size,
                        const char* expected, char error[F5_ERROR_CAP]) {
    uint8_t digest[32];
    char actual[65];
    bbe_sha256_bytes(bytes, size, digest);
    bbe_sha256_hex(digest, actual);
    if (!bbe_sha256_matches(digest, expected)) {
        return fail(error, "%s SHA-256 %s differs from %s",
                    label, actual, expected);
    }
    return 0;
}

static int stream_bbs(const ad_bbs_record* records, size_t count,
                      byte_buffer* output, char error[F5_ERROR_CAP]) {
    FILE* stream = tmpfile();
    if (stream == NULL) {
        return fail(error, "cannot create temporary BBS stream: %s",
                    strerror(errno));
    }
    char authored_error[AD_ERROR_CAP];
    if (ad_bbs_write(stream, records, count, authored_error) != 0) {
        fclose(stream);
        return fail(error, "authored BBS serialization failed: %s",
                    authored_error);
    }
    if (fseek(stream, 0, SEEK_END) != 0) {
        fclose(stream);
        return fail(error, "cannot seek temporary BBS stream");
    }
    long end = ftell(stream);
    if (end <= 0 || (uintmax_t)end > SIZE_MAX) {
        fclose(stream);
        return fail(error, "temporary BBS stream has invalid size");
    }
    if (fseek(stream, 0, SEEK_SET) != 0) {
        fclose(stream);
        return fail(error, "cannot rewind temporary BBS stream");
    }
    uint8_t* bytes = malloc((size_t)end);
    if (bytes == NULL) {
        fclose(stream);
        return fail(error, "cannot allocate BBS bytes");
    }
    if (fread(bytes, 1, (size_t)end, stream) != (size_t)end ||
        fgetc(stream) != EOF || ferror(stream)) {
        free(bytes);
        fclose(stream);
        return fail(error, "cannot read complete temporary BBS stream");
    }
    if (fclose(stream) != 0) {
        free(bytes);
        return fail(error, "cannot close temporary BBS stream");
    }
    output->data = bytes;
    output->size = (size_t)end;
    return 0;
}

static uint32_t read_le32(const uint8_t* bytes) {
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static int find_exact_legal(const bb_match* match, bb_action wanted,
                            char error[F5_ERROR_CAP]) {
    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(match, legal);
    if (count <= 0 || count > BB_LEGAL_MAX) {
        return fail(error, "reference decision has invalid legal count %d",
                    count);
    }
    int matches = 0;
    for (int i = 0; i < count; i++) {
        matches += bb_action_eq(legal[i], wanted);
    }
    if (matches != 1) {
        return fail(error,
                    "reference action 0x%08x occurs %d times in legal set",
                    bb_action_pack(wanted), matches);
    }
    return 0;
}

typedef struct {
    int count;
} die_counter;

static void count_die(void* user, int sides, int value) {
    (void)sides;
    (void)value;
    die_counter* counter = user;
    counter->count++;
}

static int validate_reference_route(const bb_match* source,
                                    char error[F5_ERROR_CAP]) {
    static const bb_action actions[8] = {
        {BB_A_ACTIVATE, 6, 0, 0},
        {BB_A_DECLARE, BB_ACT_MOVE, 0, 0},
        {BB_A_STEP, 0, 20, 9},
        {BB_A_STEP, 0, 21, 8},
        {BB_A_STEP, 0, 22, 7},
        {BB_A_STEP, 0, 23, 6},
        {BB_A_STEP, 0, 24, 5},
        {BB_A_STEP, 0, 25, 4},
    };
    static const uint16_t tuples[8][3] = {
        {6, 6, 390}, {7, 0, 390}, {9, 32, 254}, {9, 32, 229},
        {9, 32, 204}, {9, 32, 179}, {9, 32, 154}, {9, 32, 129},
    };

    uint8_t scripted[64];
    memset(scripted, 6, sizeof scripted);
    bb_rng rng;
    bb_rng_script(&rng, scripted, sizeof scripted);
    die_counter dice = {0};
    bb_rng_set_sink(&rng, count_die, &dice);
    bb_match match = *source;

    for (size_t i = 0; i < 8; i++) {
        const bb_action action = actions[i];
        uint16_t square = action.type == BB_A_STEP
            ? (uint16_t)(action.x + BB_PITCH_LEN * action.y)
            : (uint16_t)(BB_PITCH_LEN * BB_PITCH_WID);
        uint16_t arg = action.type == BB_A_STEP ? 32u : action.arg;
        if (match.status != BB_STATUS_DECISION ||
            match.decision_team != BB_HOME ||
            tuples[i][0] != action.type || tuples[i][1] != arg ||
            tuples[i][2] != square ||
            find_exact_legal(&match, action, error) != 0) {
            if (error != NULL && error[0] == '\0') {
                fail(error, "reference route diverged at decision %zu", i + 1);
            }
            return -1;
        }
        bb_status status = bb_apply(&match, action, &rng);
        if (status == BB_STATUS_ERROR || bb_rng_error(&rng) ||
            dice.count != 0 || rng.script_pos != 0) {
            return fail(error,
                        "reference decision %zu consumed dice or failed",
                        i + 1);
        }
        if (i < 7 && (match.score[BB_HOME] != 0 ||
                      match.score[BB_AWAY] != 0)) {
            return fail(error, "reference route scored before decision 8");
        }
    }
    if (match.score[BB_HOME] != 1 || match.score[BB_AWAY] != 0) {
        return fail(error, "reference route did not produce one Home score");
    }
    return 0;
}

static int appendf(char* output, size_t capacity, size_t* used,
                   char error[F5_ERROR_CAP], const char* format, ...) {
    if (*used >= capacity) return fail(error, "generated text overflow");
    va_list args;
    va_start(args, format);
    int written = vsnprintf(output + *used, capacity - *used, format, args);
    va_end(args);
    if (written < 0 || (size_t)written >= capacity - *used) {
        return fail(error, "generated text overflow");
    }
    *used += (size_t)written;
    return 0;
}

static int build_generated_header(const uint8_t* match, size_t match_size,
                                  byte_buffer* output,
                                  char error[F5_ERROR_CAP]) {
    char* text = calloc(F5_HEADER_CAP, 1);
    if (text == NULL) return fail(error, "header allocation failed");
    size_t used = 0;
#define HEADER(...)                                                           \
    do {                                                                      \
        if (appendf(text, F5_HEADER_CAP, &used, error, __VA_ARGS__) != 0) {   \
            free(text);                                                       \
            return -1;                                                        \
        }                                                                     \
    } while (0)
    HEADER("/* Generated by tools/f5_trainability_foundation.c. */\n");
    HEADER("#ifndef BBE_F5_TRAINABILITY_FIXTURE_GENERATED_H\n");
    HEADER("#define BBE_F5_TRAINABILITY_FIXTURE_GENERATED_H\n\n");
    HEADER("#include <stdint.h>\n\n");
    HEADER("#define BBE_F5_TRAINABILITY_TASK_SCHEMA \"%s\"\n", F5_TASK_SCHEMA);
    HEADER("#define BBE_F5_TRAINABILITY_FIXTURE_SCHEMA \"%s\"\n",
           F5_FIXTURE_SCHEMA);
    HEADER("#define BBE_F5_TRAINABILITY_GENERATOR_SCHEMA \"%s\"\n",
           F5_GENERATOR_SCHEMA);
    HEADER("#define BBE_F5_TRAINABILITY_REFERENCE_TRACE_SCHEMA \"%s\"\n",
           F5_REFERENCE_TRACE_SCHEMA);
    HEADER("#define BBE_F5_TRAINABILITY_ROLE \"%s\"\n", F5_ROLE);
    HEADER("#define BBE_F5_TRAINABILITY_RULESET \"%s\"\n", F5_RULESET);
    HEADER("#define BBE_F5_TRAINABILITY_FULL_BUNDLE_RECORDS %uu\n",
           F5_FULL_RECORDS);
    HEADER("#define BBE_F5_TRAINABILITY_FULL_BUNDLE_BYTES %uu\n",
           F5_FULL_BBS_SIZE);
    HEADER("#define BBE_F5_TRAINABILITY_FULL_BUNDLE_SHA256 \"%s\"\n",
           F5_FULL_BBS_SHA256);
    HEADER("#define BBE_F5_TRAINABILITY_F5_BBS_BYTES %uu\n", F5_BBS_SIZE);
    HEADER("#define BBE_F5_TRAINABILITY_F5_BBS_SHA256 \"%s\"\n",
           F5_BBS_SHA256);
    HEADER("#define BBE_F5_TRAINABILITY_MATCH_BYTES_SIZE %uu\n",
           F5_MATCH_SIZE);
    HEADER("#define BBE_F5_TRAINABILITY_RAW_MATCH_SHA256 \"%s\"\n",
           F5_MATCH_SHA256);
    HEADER("#define BBE_F5_TRAINABILITY_REFERENCE_TRACE_SHA256 \"%s\"\n",
           F5_REFERENCE_TRACE_SHA256);
    HEADER("#define BBE_F5_TRAINABILITY_PROOF_SOURCE_ID 0x%08Xu\n",
           F5_PROOF_SOURCE_ID);
    HEADER("#define BBE_F5_TRAINABILITY_DURABLE_SOURCE_ID 0x%08Xu\n",
           F5_DURABLE_SOURCE_ID);
    HEADER("#define BBE_F5_TRAINABILITY_TEMPLATE_ID %uu\n", F5_TEMPLATE_ID);
    HEADER("#define BBE_F5_TRAINABILITY_RECIPE_REVISION %uu\n",
           F5_RECIPE_REVISION);
    HEADER("#define BBE_F5_TRAINABILITY_CELL_ID %uu\n", F5_CELL_ID);
    HEADER("#define BBE_F5_TRAINABILITY_VARIANT_ID %uu\n", F5_VARIANT_ID);
    HEADER("#define BBE_F5_TRAINABILITY_VARIANT_SEED %uu\n", F5_VARIANT_SEED);
    HEADER("#define BBE_F5_TRAINABILITY_CAPTURE_ACTIONS %uu\n",
           F5_CAPTURE_ACTIONS);
    HEADER("#define BBE_F5_TRAINABILITY_CAPTURE_DICE %uu\n", F5_CAPTURE_DICE);
    HEADER("#define BBE_F5_TRAINABILITY_ENGINE_FINGERPRINT 0x%08Xu\n",
           F5_ENGINE_FINGERPRINT);
    HEADER("#define BBE_F5_TRAINABILITY_TEAM_COUNT %uu\n", F5_TEAM_COUNT);
    HEADER("#define BBE_F5_TRAINABILITY_SKILL_COUNT %uu\n", F5_SKILL_COUNT);
    HEADER("#define BBE_F5_TRAINABILITY_ACTION_TYPE_COUNT %uu\n",
           F5_ACTION_TYPE_COUNT);
    HEADER("#define BBE_F5_TRAINABILITY_MAX_DECISIONS 8u\n\n");
    HEADER("static const uint16_t "
           "BBE_F5_TRAINABILITY_REFERENCE_ACTIONS[8][3] = {\n");
    HEADER("    {6u, 6u, 390u}, {7u, 0u, 390u},\n");
    HEADER("    {9u, 32u, 254u}, {9u, 32u, 229u},\n");
    HEADER("    {9u, 32u, 204u}, {9u, 32u, 179u},\n");
    HEADER("    {9u, 32u, 154u}, {9u, 32u, 129u},\n");
    HEADER("};\n\n");
    HEADER("static const uint8_t "
           "BBE_F5_TRAINABILITY_MATCH_BYTES[%zu] = {\n", match_size);
    for (size_t i = 0; i < match_size; i++) {
        if (i % 12 == 0) HEADER("    ");
        HEADER("0x%02x", match[i]);
        if (i + 1 != match_size) HEADER(",");
        if (i % 12 == 11 || i + 1 == match_size) {
            HEADER("\n");
        } else {
            HEADER(" ");
        }
    }
    HEADER("};\n\n");
    HEADER("#endif /* BBE_F5_TRAINABILITY_FIXTURE_GENERATED_H */\n");
#undef HEADER
    output->data = (uint8_t*)text;
    output->size = used;
    return 0;
}

static int build_task(const f5_artifacts* artifacts, byte_buffer* output,
                      char error[F5_ERROR_CAP]) {
    char header_sha[65];
    sha256_hex(artifacts->generated_header.data,
               artifacts->generated_header.size, header_sha);
    char* text = calloc(F5_TASK_CAP, 1);
    if (text == NULL) return fail(error, "task descriptor allocation failed");
    int written = snprintf(
        text, F5_TASK_CAP,
        "{\n"
        "  \"action_type_count\": 30,\n"
        "  \"capture_action_count\": 51,\n"
        "  \"capture_dice_count\": 19,\n"
        "  \"cell_id\": 1,\n"
        "  \"durable_source_id\": \"0xAE00001A\",\n"
        "  \"engine_fingerprint\": \"0x64897cde\",\n"
        "  \"f5_bbs_bytes\": 2268,\n"
        "  \"f5_bbs_sha256\": \"%s\",\n"
        "  \"fixture_schema\": \"%s\",\n"
        "  \"full_bundle_bytes\": 58568,\n"
        "  \"full_bundle_records\": 26,\n"
        "  \"full_bundle_sha256\": \"%s\",\n"
        "  \"generated_header_bytes\": %zu,\n"
        "  \"generated_header_sha256\": \"%s\",\n"
        "  \"max_decisions\": 8,\n"
        "  \"proof_bundle_index\": 25,\n"
        "  \"proof_source_id\": \"0xA9000019\",\n"
        "  \"qualification_fixture_role\": \"%s\",\n"
        "  \"qualification_only\": true,\n"
        "  \"raw_match_bytes\": 2240,\n"
        "  \"raw_match_sha256\": \"%s\",\n"
        "  \"recipe_revision\": 1,\n"
        "  \"reference_trace_bytes\": %zu,\n"
        "  \"reference_trace_schema\": \"%s\",\n"
        "  \"reference_trace_sha256\": \"%s\",\n"
        "  \"ruleset\": \"%s\",\n"
        "  \"schema\": \"%s\",\n"
        "  \"skill_count\": 108,\n"
        "  \"team_count\": 30,\n"
        "  \"template_id\": 5,\n"
        "  \"template_key\": \"f5-score-or-wait\",\n"
        "  \"variant_id\": 1,\n"
        "  \"variant_seed\": 410\n"
        "}\n",
        F5_BBS_SHA256, F5_FIXTURE_SCHEMA, F5_FULL_BBS_SHA256,
        artifacts->generated_header.size, header_sha, F5_ROLE,
        F5_MATCH_SHA256, artifacts->reference_trace.size,
        F5_REFERENCE_TRACE_SCHEMA, F5_REFERENCE_TRACE_SHA256,
        F5_RULESET, F5_TASK_SCHEMA);
    if (written < 0 || (size_t)written >= F5_TASK_CAP) {
        free(text);
        return fail(error, "task descriptor overflow");
    }
    output->data = (uint8_t*)text;
    output->size = (size_t)written;
    return 0;
}

static int validate_abi(char error[F5_ERROR_CAP]) {
    if (AD_AUTHORED_PROOF_BUNDLE_COUNT != (int)F5_FULL_RECORDS ||
        sizeof(bb_match) != F5_MATCH_SIZE ||
        BB_TEAM_COUNT != (int)F5_TEAM_COUNT ||
        BB_SKILL_COUNT != (int)F5_SKILL_COUNT ||
        BB_A_TYPE_COUNT != (int)F5_ACTION_TYPE_COUNT ||
        ad_bbs_fingerprint() != F5_ENGINE_FINGERPRINT) {
        return fail(error,
                    "engine ABI differs: records=%d match=%zu fingerprint="
                    "0x%08x teams=%d skills=%d actions=%d",
                    AD_AUTHORED_PROOF_BUNDLE_COUNT, sizeof(bb_match),
                    ad_bbs_fingerprint(), BB_TEAM_COUNT, BB_SKILL_COUNT,
                    BB_A_TYPE_COUNT);
    }
    if (16u + F5_FULL_RECORDS * (12u + F5_MATCH_SIZE) != F5_FULL_BBS_SIZE ||
        16u + 12u + F5_MATCH_SIZE != F5_BBS_SIZE) {
        return fail(error, "watched BBS size arithmetic differs");
    }
    return 0;
}

static int build_artifacts(f5_artifacts* output,
                           char error[F5_ERROR_CAP]) {
    memset(output, 0, sizeof *output);
    if (validate_abi(error) != 0) return -1;

    ad_recipe* recipes = calloc(F5_FULL_RECORDS, sizeof(*recipes));
    ad_bbs_record* records = calloc(F5_FULL_RECORDS, sizeof(*records));
    ad_authored_identity* identities =
        calloc(F5_FULL_RECORDS, sizeof(*identities));
    if (recipes == NULL || records == NULL || identities == NULL) {
        free(recipes);
        free(records);
        free(identities);
        return fail(error, "authored bundle allocation failed");
    }

    char authored_error[AD_ERROR_CAP];
    if (ad_build_authored_proof_bundle(
            recipes, F5_FULL_RECORDS, records, F5_FULL_RECORDS,
            authored_error) != 0 ||
        ad_validate_authored_proof_bundle(
            recipes, F5_FULL_RECORDS, authored_error) != 0 ||
        ad_identify_authored_proof_bundle(
            recipes, F5_FULL_RECORDS, identities, F5_FULL_RECORDS,
            authored_error) != 0) {
        free(recipes);
        free(records);
        free(identities);
        return fail(error, "complete authored bundle failed: %s",
                    authored_error);
    }

    if (stream_bbs(records, F5_FULL_RECORDS, &output->full_bbs, error) != 0 ||
        output->full_bbs.size != F5_FULL_BBS_SIZE ||
        require_hash("complete authored BBS", output->full_bbs.data,
                     output->full_bbs.size, F5_FULL_BBS_SHA256, error) != 0) {
        if (error[0] == '\0') {
            fail(error, "complete authored BBS size differs");
        }
        free(recipes);
        free(records);
        free(identities);
        free_artifacts(output);
        return -1;
    }

    size_t found = SIZE_MAX;
    unsigned matches = 0;
    for (size_t i = 0; i < F5_FULL_RECORDS; i++) {
        const ad_recipe* recipe = &recipes[i];
        const ad_authored_identity* identity = &identities[i];
        if (records[i].source_id == F5_PROOF_SOURCE_ID ||
            identity->source_id == F5_DURABLE_SOURCE_ID ||
            recipe->kind == AD_RECIPE_F5_SCORE_OR_WAIT) {
            if (records[i].source_id != F5_PROOF_SOURCE_ID ||
                identity->source_id != F5_DURABLE_SOURCE_ID ||
                identity->identity_schema_version !=
                    AD_AUTHORED_IDENTITY_SCHEMA_VERSION ||
                identity->template_id != F5_TEMPLATE_ID ||
                identity->recipe_revision != F5_RECIPE_REVISION ||
                identity->cell_id != F5_CELL_ID ||
                identity->variant_id != F5_VARIANT_ID ||
                identity->variant_seed != F5_VARIANT_SEED ||
                recipe->kind != AD_RECIPE_F5_SCORE_OR_WAIT) {
                free(recipes);
                free(records);
                free(identities);
                free_artifacts(output);
                return fail(error, "split or mutated F5 identity at row %zu", i);
            }
            found = i;
            matches++;
        }
    }
    const char* template_key = ad_authored_template_key(F5_TEMPLATE_ID);
    if (matches != 1 || found != F5_PROOF_INDEX || template_key == NULL ||
        strcmp(template_key, "f5-score-or-wait") != 0) {
        free(recipes);
        free(records);
        free(identities);
        free_artifacts(output);
        return fail(error, "complete bundle did not yield the one exact F5");
    }

    const ad_recipe* f5 = &recipes[found];
    if (f5->controller_seed != F5_VARIANT_SEED ||
        f5->action_count != (int)F5_CAPTURE_ACTIONS ||
        f5->dice_count != (int)F5_CAPTURE_DICE ||
        records[found].decision_index != F5_CAPTURE_ACTIONS ||
        records[found].recipe != f5 ||
        !ad_f5_score_or_wait_valid(&f5->captured) ||
        f5->captured.half != 1 || f5->captured.turn[BB_HOME] != 2 ||
        f5->captured.turn[BB_AWAY] != 2 ||
        f5->captured.score[BB_HOME] != 0 ||
        f5->captured.score[BB_AWAY] != 0 ||
        f5->captured.active_team != BB_HOME ||
        f5->captured.decision_team != BB_HOME ||
        f5->captured.ball.carrier != 6 ||
        f5->captured.players[6].location != BB_LOC_ON_PITCH ||
        f5->captured.players[6].stance != BB_STANCE_STANDING ||
        f5->captured.players[6].x != 19 ||
        f5->captured.players[6].y != 10 ||
        f5->captured.players[6].ma != 6) {
        free(recipes);
        free(records);
        free(identities);
        free_artifacts(output);
        return fail(error, "F5 capture facts differ");
    }

    bb_match replayed;
    uint32_t continuation = 0;
    bb_status continuation_status = BB_STATUS_ERROR;
    int continuation_dice = -1;
    if (ad_replay_exact(f5, &replayed, authored_error) != 0 ||
        memcmp(&replayed, &f5->captured, sizeof replayed) != 0 ||
        ad_verify_one_action_continuation(
            &replayed, &continuation, &continuation_status,
            &continuation_dice, authored_error) != 0 ||
        continuation_status == BB_STATUS_ERROR ||
        continuation_dice < 0 ||
        validate_reference_route(&replayed, error) != 0) {
        if (error[0] == '\0') {
            fail(error, "F5 replay/continuation failed: %s", authored_error);
        }
        free(recipes);
        free(records);
        free(identities);
        free_artifacts(output);
        return -1;
    }

    ad_bbs_record one = records[found];
    if (stream_bbs(&one, 1, &output->f5_bbs, error) != 0 ||
        output->f5_bbs.size != F5_BBS_SIZE ||
        require_hash("one-record F5 BBS", output->f5_bbs.data,
                     output->f5_bbs.size, F5_BBS_SHA256, error) != 0 ||
        memcmp(output->f5_bbs.data, "BBS1", 4) != 0 ||
        read_le32(output->f5_bbs.data + 4) != 1u ||
        read_le32(output->f5_bbs.data + 8) != F5_MATCH_SIZE ||
        read_le32(output->f5_bbs.data + 12) != F5_ENGINE_FINGERPRINT ||
        read_le32(output->f5_bbs.data + 16) != F5_PROOF_SOURCE_ID ||
        read_le32(output->f5_bbs.data + 20) != F5_CAPTURE_ACTIONS ||
        memcmp(output->f5_bbs.data + 28, &replayed, sizeof replayed) != 0) {
        if (error[0] == '\0') fail(error, "one-record F5 BBS differs");
        free(recipes);
        free(records);
        free(identities);
        free_artifacts(output);
        return -1;
    }

    if (copy_buffer(&output->raw_match, &replayed, sizeof replayed, error) != 0 ||
        require_hash("raw F5 match", output->raw_match.data,
                     output->raw_match.size, F5_MATCH_SHA256, error) != 0 ||
        copy_buffer(&output->reference_trace, F5_REFERENCE_TRACE,
                    sizeof F5_REFERENCE_TRACE - 1u, error) != 0 ||
        require_hash("reference trace", output->reference_trace.data,
                     output->reference_trace.size,
                     F5_REFERENCE_TRACE_SHA256, error) != 0 ||
        build_generated_header(output->raw_match.data,
                               output->raw_match.size,
                               &output->generated_header, error) != 0 ||
        build_task(output, &output->task, error) != 0) {
        free(recipes);
        free(records);
        free(identities);
        free_artifacts(output);
        return -1;
    }

    free(recipes);
    free(records);
    free(identities);
    error[0] = '\0';
    return 0;
}

static int join_path(char output[F5_PATH_CAP], const char* directory,
                     const char* name, char error[F5_ERROR_CAP]) {
    size_t length = strlen(directory);
    int slash = length != 0 && directory[length - 1] != '/';
    int written = snprintf(output, F5_PATH_CAP, "%s%s%s", directory,
                           slash ? "/" : "", name);
    if (written < 0 || written >= F5_PATH_CAP) {
        return fail(error, "artifact path is too long");
    }
    return 0;
}

static int write_all(int fd, const uint8_t* bytes, size_t size) {
    while (size != 0) {
        ssize_t written = write(fd, bytes, size);
        if (written < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (written == 0) return -1;
        bytes += (size_t)written;
        size -= (size_t)written;
    }
    return 0;
}

static int write_file_exclusive(const char* directory, const char* name,
                                const byte_buffer* bytes,
                                char error[F5_ERROR_CAP]) {
    char path[F5_PATH_CAP];
    if (join_path(path, directory, name, error) != 0) return -1;
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | F5_O_NOFOLLOW, 0444);
    if (fd < 0) {
        return fail(error, "cannot create %s: %s", path, strerror(errno));
    }
    int failed = write_all(fd, bytes->data, bytes->size) != 0;
    if (!failed && fsync(fd) != 0) failed = 1;
    int saved = failed ? errno : 0;
    if (close(fd) != 0 && !failed) {
        failed = 1;
        saved = errno;
    }
    if (failed) {
        unlink(path);
        return fail(error, "cannot write %s: %s", path, strerror(saved));
    }
    return 0;
}

static size_t artifact_files(const f5_artifacts* artifacts,
                             artifact_file files[6]) {
    files[0] = (artifact_file){"authored-proof-bundle.bbs",
                               &artifacts->full_bbs};
    files[1] = (artifact_file){"f5.bbs", &artifacts->f5_bbs};
    files[2] = (artifact_file){"f5.match", &artifacts->raw_match};
    files[3] = (artifact_file){"f5_trainability_fixture.generated.h",
                               &artifacts->generated_header};
    files[4] = (artifact_file){"reference-trace.json",
                               &artifacts->reference_trace};
    files[5] = (artifact_file){"task.json", &artifacts->task};
    return 6;
}

static void cleanup_temp_dir(const char* directory,
                             const artifact_file* files, size_t count) {
    char path[F5_PATH_CAP];
    for (size_t i = 0; i < count; i++) {
        if (snprintf(path, sizeof path, "%s/%s",
                     directory, files[i].name) > 0) {
            unlink(path);
        }
    }
    rmdir(directory);
}

static int publish_artifacts(const char* output_path,
                             const f5_artifacts* artifacts,
                             char error[F5_ERROR_CAP]) {
    if (output_path == NULL || output_path[0] == '\0' ||
        strcmp(output_path, "/") == 0 ||
        output_path[strlen(output_path) - 1] == '/') {
        return fail(error, "output must name a new directory");
    }
    struct stat existing;
    if (lstat(output_path, &existing) == 0 || errno != ENOENT) {
        return fail(error, "output path already exists or is inaccessible");
    }
    char temporary[F5_PATH_CAP];
    int written = snprintf(temporary, sizeof temporary, "%s.tmp.XXXXXX",
                           output_path);
    if (written < 0 || written >= (int)sizeof temporary ||
        mkdtemp(temporary) == NULL) {
        return fail(error, "cannot create atomic output directory: %s",
                    strerror(errno));
    }

    artifact_file files[6];
    size_t count = artifact_files(artifacts, files);
    for (size_t i = 0; i < count; i++) {
        if (write_file_exclusive(
                temporary, files[i].name, files[i].bytes, error) != 0) {
            cleanup_temp_dir(temporary, files, count);
            return -1;
        }
    }
    int directory_fd =
        open(temporary, O_RDONLY | F5_O_DIRECTORY | F5_O_NOFOLLOW);
    int sync_failed = directory_fd < 0;
    int saved = sync_failed ? errno : 0;
    if (!sync_failed && fsync(directory_fd) != 0) {
        sync_failed = 1;
        saved = errno;
    }
    if (directory_fd >= 0 && close(directory_fd) != 0 && !sync_failed) {
        sync_failed = 1;
        saved = errno;
    }
    if (sync_failed) {
        cleanup_temp_dir(temporary, files, count);
        return fail(error, "cannot sync atomic output directory: %s",
                    strerror(saved));
    }
    if (rename(temporary, output_path) != 0) {
        int saved = errno;
        cleanup_temp_dir(temporary, files, count);
        return fail(error, "cannot publish output directory: %s",
                    strerror(saved));
    }
    return 0;
}

static int read_exact_file(const char* directory, const char* name,
                           const byte_buffer* expected,
                           char error[F5_ERROR_CAP]) {
    char path[F5_PATH_CAP];
    if (join_path(path, directory, name, error) != 0) return -1;
    struct stat status;
    if (lstat(path, &status) != 0 || !S_ISREG(status.st_mode) ||
        status.st_nlink != 1 || status.st_size < 0 ||
        (uintmax_t)status.st_size != expected->size) {
        return fail(error, "%s is absent, non-regular, linked, or wrong-sized",
                    path);
    }
    int fd = open(path, O_RDONLY | F5_O_NOFOLLOW);
    if (fd < 0) return fail(error, "cannot open %s", path);
    uint8_t* bytes = malloc(expected->size);
    if (bytes == NULL) {
        close(fd);
        return fail(error, "verification allocation failed");
    }
    size_t used = 0;
    while (used < expected->size) {
        ssize_t count = read(fd, bytes + used, expected->size - used);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        used += (size_t)count;
    }
    uint8_t trailing;
    ssize_t extra = read(fd, &trailing, 1);
    int close_result = close(fd);
    int equal = used == expected->size && extra == 0 && close_result == 0 &&
                memcmp(bytes, expected->data, expected->size) == 0;
    free(bytes);
    if (!equal) return fail(error, "%s bytes differ", path);
    return 0;
}

static int name_expected(const char* name, const artifact_file* files,
                         size_t count) {
    for (size_t i = 0; i < count; i++) {
        if (strcmp(name, files[i].name) == 0) return 1;
    }
    return 0;
}

static int verify_artifacts(const char* input_path,
                            const f5_artifacts* expected,
                            char error[F5_ERROR_CAP]) {
    struct stat status;
    if (input_path == NULL || input_path[0] == '\0' ||
        lstat(input_path, &status) != 0 || !S_ISDIR(status.st_mode)) {
        return fail(error, "input must be a real artifact directory");
    }
    artifact_file files[6];
    size_t count = artifact_files(expected, files);
    DIR* directory = opendir(input_path);
    if (directory == NULL) return fail(error, "cannot open artifact directory");
    size_t seen = 0;
    errno = 0;
    struct dirent* entry;
    while ((entry = readdir(directory)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 ||
            strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (!name_expected(entry->d_name, files, count)) {
            closedir(directory);
            return fail(error, "unexpected artifact %s", entry->d_name);
        }
        seen++;
    }
    int read_error = errno;
    if (closedir(directory) != 0 || read_error != 0 || seen != count) {
        return fail(error, "artifact directory membership differs");
    }
    for (size_t i = 0; i < count; i++) {
        if (read_exact_file(input_path, files[i].name,
                            files[i].bytes, error) != 0) {
            return -1;
        }
    }
    return 0;
}

static void usage(FILE* stream, const char* program) {
    fprintf(stream,
            "usage: %s generate --output DIR\n"
            "       %s verify --input DIR\n",
            program, program);
}

int main(int argc, char** argv) {
    if (argc != 4 ||
        (strcmp(argv[1], "generate") != 0 &&
         strcmp(argv[1], "verify") != 0) ||
        (strcmp(argv[1], "generate") == 0 &&
         strcmp(argv[2], "--output") != 0) ||
        (strcmp(argv[1], "verify") == 0 &&
         strcmp(argv[2], "--input") != 0) ||
        argv[3][0] == '\0') {
        usage(stderr, argv[0]);
        return 2;
    }

    char error[F5_ERROR_CAP] = {0};
    f5_artifacts artifacts;
    if (build_artifacts(&artifacts, error) != 0) {
        fprintf(stderr, "f5 foundation: %s\n", error);
        return 1;
    }
    int result = strcmp(argv[1], "generate") == 0
        ? publish_artifacts(argv[3], &artifacts, error)
        : verify_artifacts(argv[3], &artifacts, error);
    free_artifacts(&artifacts);
    if (result != 0) {
        fprintf(stderr, "f5 foundation: %s\n", error);
        return 1;
    }
    printf("f5 foundation %s passed: %s\n", argv[1], argv[3]);
    return 0;
}

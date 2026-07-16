#include "authored_sidecar.h"
#include "bb/bb_reachability.h"
#include "bb/gen_teams.h"

#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void ad_sidecar_sha256(const void*, size_t, unsigned char[32]);
int ad_sidecar_hash_actions(const uint32_t*, const uint8_t*, size_t,
                            unsigned char[32]);
int ad_sidecar_hash_dice(const uint8_t*, const uint8_t*, size_t,
                         unsigned char[32]);
int ad_sidecar_hash_legal(const uint32_t*, size_t, unsigned char[32]);
int ad_sidecar_f5_end_activation_legal(const bb_match*);
int ad_sidecar_alias_contract(
    const ad_bbs_record*, size_t, const ad_recipe*, size_t,
    char*, size_t, size_t*, char*, size_t, size_t*, char[AD_ERROR_CAP]);
int ad_sidecar_reconcile_bundle(
    const ad_bbs_record*, size_t, const ad_recipe*, size_t,
    const ad_bbs_record*, const ad_recipe*, ad_bbs_record*,
    char[AD_ERROR_CAP]);

static void require(int condition, const char* message);

#if defined(__linux__)
static int writer_calls;
static int writer_returned;
static int writer_mode;
static int serializer_active;
static int open_memstream_calls;
static int fflush_calls;
static int fclose_calls;
static char** stream_buffer_slot;
static void* stream_owned_buffer;
static int stream_buffer_free_calls;
static int force_open_memstream_failure;
static int force_fflush_failure;
static int force_fclose_failure;
static int allocation_test_active;
static size_t allocation_calls;
static size_t fail_allocation_at;
static int builder_calls;
static int identity_calls;
static int force_builder_failure;
static int force_identity_failure;
static int enforce_writer_arguments;
static const ad_bbs_record* expected_writer_records;
static const ad_recipe* expected_writer_recipes;
static const ad_recipe* expected_writer_supplied_recipes;
static const ad_recipe* expected_writer_recipe_pointers[
    AD_AUTHORED_PROOF_BUNDLE_COUNT];
static uintptr_t expected_writer_caller_starts[7];
static size_t expected_writer_caller_lengths[7];
static const ad_bbs_record* canonical_writer_records;
static const ad_recipe* canonical_writer_recipes;
static const bb_match* expected_post_writer_matches[
    AD_AUTHORED_PROOF_BUNDLE_COUNT];
static ad_recipe_kind expected_post_writer_kinds[
    AD_AUTHORED_PROOF_BUNDLE_COUNT];
static int expected_legal_match_calls[AD_AUTHORED_PROOF_BUNDLE_COUNT];
static int post_writer_f1_calls;
static int post_writer_f2_calls;
static int post_writer_f4_calls;
static int post_writer_score_calls;
static int post_writer_marked_calls;
static int post_writer_legal_calls;
static int force_f1_result;
static int force_f1_ordinal;
static int force_f2_result;
static int force_f2_ordinal;
static int force_f4_result;
static int force_score_result;
static int force_marked_result;
static int force_marked_ordinal;
static int force_legal_mode;
static int force_legal_row;
static int force_legal_call;
void* __real_malloc(size_t);
void* __wrap_malloc(size_t size) {
    if (allocation_test_active && ++allocation_calls == fail_allocation_at) {
        return NULL;
    }
    return __real_malloc(size);
}
void* __real_calloc(size_t, size_t);
void* __wrap_calloc(size_t count, size_t size) {
    if (allocation_test_active && ++allocation_calls == fail_allocation_at) {
        return NULL;
    }
    return __real_calloc(count, size);
}
void* __real_realloc(void*, size_t);
void* __wrap_realloc(void* allocation, size_t size) {
    if (allocation_test_active && ++allocation_calls == fail_allocation_at) {
        return NULL;
    }
    return __real_realloc(allocation, size);
}
void __real_free(void*);
void __wrap_free(void* allocation) {
    if (serializer_active && allocation != NULL &&
            allocation == stream_owned_buffer) {
        stream_buffer_free_calls++;
        stream_owned_buffer = NULL;
    }
    __real_free(allocation);
}
FILE* __real_open_memstream(char**, size_t*);
FILE* __wrap_open_memstream(char** buffer, size_t* length) {
    if (serializer_active) {
        open_memstream_calls++;
        if (force_open_memstream_failure) return NULL;
        stream_buffer_slot = buffer;
    }
    return __real_open_memstream(buffer, length);
}
int __real_fflush(FILE*);
int __wrap_fflush(FILE* file) {
    if (serializer_active) fflush_calls++;
    int result = __real_fflush(file);
    if (serializer_active && stream_buffer_slot != NULL &&
            *stream_buffer_slot != NULL) {
        stream_owned_buffer = *stream_buffer_slot;
    }
    return serializer_active && force_fflush_failure ? EOF : result;
}
int __real_fclose(FILE*);
int __wrap_fclose(FILE* file) {
    if (serializer_active) fclose_calls++;
    int result = __real_fclose(file);
    if (serializer_active && stream_buffer_slot != NULL &&
            *stream_buffer_slot != NULL) {
        stream_owned_buffer = *stream_buffer_slot;
    }
    return serializer_active && force_fclose_failure ? EOF : result;
}
int __real_ad_build_authored_proof_bundle(
    ad_recipe*, size_t, ad_bbs_record*, size_t, char[AD_ERROR_CAP]);
int __wrap_ad_build_authored_proof_bundle(
    ad_recipe* recipes, size_t recipe_capacity,
    ad_bbs_record* records, size_t record_capacity,
    char error[AD_ERROR_CAP]) {
    builder_calls++;
    if (force_builder_failure) return -1;
    return __real_ad_build_authored_proof_bundle(
        recipes, recipe_capacity, records, record_capacity, error);
}
int __real_ad_identify_authored_proof_bundle(
    const ad_recipe*, size_t, ad_authored_identity*, size_t,
    char[AD_ERROR_CAP]);
int __wrap_ad_identify_authored_proof_bundle(
    const ad_recipe* recipes, size_t recipe_count,
    ad_authored_identity* identities, size_t identity_capacity,
    char error[AD_ERROR_CAP]) {
    identity_calls++;
    if (force_identity_failure) return -1;
    return __real_ad_identify_authored_proof_bundle(
        recipes, recipe_count, identities, identity_capacity, error);
}
int __real_ad_bbs_write(FILE*, const ad_bbs_record*, size_t,
                        char[AD_ERROR_CAP]);
int __wrap_ad_bbs_write(FILE* file, const ad_bbs_record* records, size_t count,
                        char error[AD_ERROR_CAP]) {
    writer_calls++;
    if (count == AD_AUTHORED_PROOF_BUNDLE_COUNT) {
        for (size_t i = 0; i < count; i++) {
            require(records[i].recipe != NULL,
                    "writer received a null recipe pointer");
            expected_post_writer_matches[i] = &records[i].recipe->captured;
            expected_post_writer_kinds[i] = records[i].recipe->kind;
        }
    }
    if (enforce_writer_arguments) {
        require(count == AD_AUTHORED_PROOF_BUNDLE_COUNT,
                "writer received the wrong record count");
        uintptr_t supplied_start = (uintptr_t)expected_writer_supplied_recipes;
        const size_t supplied_bytes =
            AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe);
        const size_t writer_bytes = count * sizeof *records;
        uintptr_t writer_start = (uintptr_t)records;
        require(supplied_start <= UINTPTR_MAX - supplied_bytes &&
                    writer_start <= UINTPTR_MAX - writer_bytes,
                "writer provenance extent overflowed");
        uintptr_t writer_end = writer_start + writer_bytes;
        for (size_t role = 0; role < 7; role++) {
            uintptr_t caller_start = expected_writer_caller_starts[role];
            size_t caller_length = expected_writer_caller_lengths[role];
            require(caller_start <= UINTPTR_MAX - caller_length,
                    "caller storage extent overflowed in writer probe");
            uintptr_t caller_end = caller_start + caller_length;
            require(!(writer_start < caller_end && caller_start < writer_end),
                    "writer records were not staged in serializer-owned storage");
        }
        unsigned char seen[AD_AUTHORED_PROOF_BUNDLE_COUNT] = {0};
        for (size_t i = 0; i < count; i++) {
            uintptr_t recipe_pointer = (uintptr_t)records[i].recipe;
            uintptr_t delta = recipe_pointer - supplied_start;
            require(records[i].source_id == expected_writer_records[i].source_id &&
                        records[i].decision_index ==
                            expected_writer_records[i].decision_index &&
                        recipe_pointer >= supplied_start &&
                        delta < supplied_bytes &&
                        delta % sizeof(ad_recipe) == 0 &&
                        records[i].recipe ==
                            expected_writer_recipe_pointers[i] &&
                        memcmp(records[i].recipe, &expected_writer_recipes[i],
                               sizeof expected_writer_recipes[i]) == 0,
                    "writer did not receive the complete canonicalized caller bundle");
            size_t supplied_index = delta / sizeof(ad_recipe);
            require(!seen[supplied_index],
                    "writer received a duplicate caller recipe pointer");
            seen[supplied_index] = 1;
        }
    }
    if (writer_mode == 1) {
        writer_returned = 0;
        return -1;
    }
    int result;
    if (writer_mode == 2) {
        result = fputc('X', file) == EOF ? -1 : 0;
    } else {
        result = __real_ad_bbs_write(file, records, count, error);
        if (result == 0 && writer_mode == 3) {
            result = fputc('\0', file) == EOF ? -1 : 0;
        } else if (result == 0 && (writer_mode == 4 || writer_mode == 5)) {
            long offset = writer_mode == 4 ? 0 : 5;
            if (fseek(file, offset, SEEK_SET) != 0 ||
                    fputc(writer_mode == 4 ? 0xFF : 0x01, file) == EOF ||
                    fseek(file, 0, SEEK_END) != 0) {
                result = -1;
            }
        }
    }
    writer_returned = result == 0;
    return result;
}

static const bb_match* expected_family_match(
    ad_recipe_kind kind, int ordinal) {
    int seen = 0;
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        if (expected_post_writer_kinds[i] != kind) continue;
        if (seen++ == ordinal) return expected_post_writer_matches[i];
    }
    require(0, "post-writer family call ordinal is out of range");
    return NULL;
}

int __real_ad_f1_pass_opportunity_valid(const bb_match*);
int __wrap_ad_f1_pass_opportunity_valid(const bb_match* match) {
    int ordinal = post_writer_f1_calls;
    if (writer_returned) {
        require(match == expected_family_match(
                            AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE, ordinal),
                "F1 fact was derived from the wrong admitted row");
        post_writer_f1_calls++;
    }
    int result = __real_ad_f1_pass_opportunity_valid(match);
    return writer_returned && ordinal == force_f1_ordinal &&
            force_f1_result != INT_MIN
        ? force_f1_result : result;
}
int __real_ad_f2_handoff_target_count(const bb_match*);
int __wrap_ad_f2_handoff_target_count(const bb_match* match) {
    int ordinal = post_writer_f2_calls;
    if (writer_returned) {
        require(match == expected_family_match(
                            AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT, ordinal),
                "F2 fact was derived from the wrong admitted row");
        post_writer_f2_calls++;
    }
    int result = __real_ad_f2_handoff_target_count(match);
    return writer_returned && ordinal == force_f2_ordinal &&
            force_f2_result != INT_MIN
        ? force_f2_result : result;
}
int __real_ad_f4_pending_dodge_reroll_valid(const bb_match*);
int __wrap_ad_f4_pending_dodge_reroll_valid(const bb_match* match) {
    if (writer_returned) {
        require(match == expected_family_match(
                            AD_RECIPE_F4_PENDING_DODGE_REROLL, 0),
                "F4 fact was derived from the wrong admitted row");
        post_writer_f4_calls++;
    }
    int result = __real_ad_f4_pending_dodge_reroll_valid(match);
    return writer_returned && force_f4_result != INT_MIN
        ? force_f4_result : result;
}
bool __real_bb_can_score_without_dice(const bb_match*, int);
bool __wrap_bb_can_score_without_dice(const bb_match* match, int carrier) {
    if (writer_returned) {
        const bb_match* expected = expected_family_match(
            AD_RECIPE_F5_SCORE_OR_WAIT, 0);
        require(match == expected && carrier == expected->ball.carrier,
                "F5 score fact was derived from the wrong admitted row");
        post_writer_score_calls++;
    }
    bool result = __real_bb_can_score_without_dice(match, carrier);
    return writer_returned && force_score_result != INT_MIN
        ? force_score_result != 0 : result;
}
bool __real_bb_is_marked(const bb_match*, int);
bool __wrap_bb_is_marked(const bb_match* match, int slot) {
    int ordinal = post_writer_marked_calls;
    bool result = __real_bb_is_marked(match, slot);
    if (writer_returned) {
        const bb_match* expected = expected_family_match(
            AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE, ordinal);
        require(match == expected && slot == expected->ball.carrier,
                "F1 pressure fact was derived from the wrong admitted row");
        post_writer_marked_calls++;
    }
    return writer_returned && ordinal == force_marked_ordinal &&
            force_marked_result != INT_MIN
        ? force_marked_result != 0 : result;
}
int __real_bb_legal_actions(const bb_match*, bb_action*);
int __wrap_bb_legal_actions(const bb_match* match, bb_action* actions) {
    int matched_row = -1;
    int matched_call = -1;
    if (writer_returned) {
        post_writer_legal_calls++;
        for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
            if (match == expected_post_writer_matches[i]) {
                expected_legal_match_calls[i]++;
                matched_row = (int)i;
                matched_call = expected_legal_match_calls[i];
            }
        }
    }
    int result = __real_bb_legal_actions(match, actions);
    int force_this_call = force_legal_row < 0 ||
        (matched_row == force_legal_row && matched_call == force_legal_call);
    if (writer_returned && force_this_call && result > 0 &&
            force_legal_mode == 1) {
        return result - 1;
    }
    if (writer_returned && force_this_call && result > 0 &&
            force_legal_mode == 2) {
        actions[0].type ^= 1u;
    }
    if (writer_returned && force_this_call && result > 1 &&
            force_legal_mode == 3) {
        actions[1] = actions[0];
    }
    return result;
}
#endif

static void require(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "sidecar serializer probe: %s\n", message);
        exit(1);
    }
}

#if defined(__linux__)
static void reset_interposition(void) {
    writer_calls = 0;
    writer_returned = 0;
    writer_mode = 0;
    open_memstream_calls = 0;
    fflush_calls = 0;
    fclose_calls = 0;
    stream_buffer_slot = NULL;
    stream_owned_buffer = NULL;
    stream_buffer_free_calls = 0;
    force_open_memstream_failure = 0;
    force_fflush_failure = 0;
    force_fclose_failure = 0;
    builder_calls = 0;
    identity_calls = 0;
    force_builder_failure = 0;
    force_identity_failure = 0;
    enforce_writer_arguments = 0;
    expected_writer_records = NULL;
    expected_writer_recipes = NULL;
    expected_writer_supplied_recipes = NULL;
    memset(expected_writer_caller_starts, 0,
           sizeof expected_writer_caller_starts);
    memset(expected_writer_caller_lengths, 0,
           sizeof expected_writer_caller_lengths);
    memset(expected_writer_recipe_pointers, 0,
           sizeof expected_writer_recipe_pointers);
    memset(expected_post_writer_matches, 0,
           sizeof expected_post_writer_matches);
    memset(expected_post_writer_kinds, 0,
           sizeof expected_post_writer_kinds);
    memset(expected_legal_match_calls, 0,
           sizeof expected_legal_match_calls);
    post_writer_f1_calls = 0;
    post_writer_f2_calls = 0;
    post_writer_f4_calls = 0;
    post_writer_score_calls = 0;
    post_writer_marked_calls = 0;
    post_writer_legal_calls = 0;
    force_f1_result = INT_MIN;
    force_f1_ordinal = -1;
    force_f2_result = INT_MIN;
    force_f2_ordinal = -1;
    force_f4_result = INT_MIN;
    force_score_result = INT_MIN;
    force_marked_result = INT_MIN;
    force_marked_ordinal = -1;
    force_legal_mode = 0;
    force_legal_row = -1;
    force_legal_call = -1;
}

static void set_expected_writer_caller_storage(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    size_t* records_length, unsigned char* recipes_output,
    size_t recipes_capacity, size_t* recipes_length, char* error) {
    const void* pointers[7] = {
        records, recipes, records_output, records_length,
        recipes_output, recipes_length, error,
    };
    const size_t lengths[7] = {
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records,
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes,
        records_capacity, sizeof *records_length,
        recipes_capacity, sizeof *recipes_length, AD_ERROR_CAP,
    };
    for (size_t role = 0; role < 7; role++) {
        expected_writer_caller_starts[role] = (uintptr_t)pointers[role];
        expected_writer_caller_lengths[role] = lengths[role];
    }
    for (size_t canonical = 0;
         canonical < AD_AUTHORED_PROOF_BUNDLE_COUNT; canonical++) {
        const ad_recipe* found = NULL;
        for (size_t supplied = 0;
             supplied < AD_AUTHORED_PROOF_BUNDLE_COUNT; supplied++) {
            if (memcmp(&recipes[supplied], &canonical_writer_recipes[canonical],
                       sizeof recipes[supplied]) != 0) {
                continue;
            }
            require(found == NULL,
                    "caller recipe bytes do not map one-to-one to canonical rows");
            found = &recipes[supplied];
        }
        require(found != NULL,
                "caller recipe is absent from the canonical proof bundle");
        expected_writer_recipe_pointers[canonical] = found;
    }
}
#endif

static unsigned char hex_nibble(char value) {
    if (value >= '0' && value <= '9') return (unsigned char)(value - '0');
    if (value >= 'a' && value <= 'f') {
        return (unsigned char)(value - 'a' + 10);
    }
    require(0, "invalid trusted digest hex");
    return 0;
}

static void require_digest(const unsigned char actual[32], const char* expected,
                           const char* message) {
    unsigned char bytes[32];
    require(strlen(expected) == 64, "trusted digest length differs");
    for (size_t i = 0; i < sizeof bytes; i++) {
        bytes[i] = (unsigned char)((hex_nibble(expected[i * 2]) << 4) |
                                   hex_nibble(expected[i * 2 + 1]));
    }
    require(memcmp(actual, bytes, sizeof bytes) == 0, message);
}

static void expect_candidate_hash_vectors(void) {
    unsigned char digest[32];
    ad_sidecar_sha256(NULL, 0, digest);
    require_digest(digest,
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "candidate SHA-256 empty vector differs");
    ad_sidecar_sha256("abc", 3, digest);
    require_digest(digest,
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        "candidate SHA-256 abc vector differs");
    unsigned char* million = malloc(1000000);
    require(million != NULL, "million-byte SHA vector allocation failed");
    memset(million, 'a', 1000000);
    ad_sidecar_sha256(million, 1000000, digest);
    free(million);
    require_digest(digest,
        "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
        "candidate SHA-256 million-a vector differs");

    const uint32_t empty_action = 0;
    const uint8_t empty_byte = 0;
    require(ad_sidecar_hash_actions(&empty_action, &empty_byte, 0, digest) == 0,
            "candidate empty action hash failed");
    require_digest(digest,
        "0701073366e61d05f8a567522a1e9fda6a7aca2dd79f142c74b6c632056646a2",
        "candidate empty action framing differs");
    const uint32_t action_one[] = {0x01020304u};
    const uint8_t team_one[] = {1u};
    require(ad_sidecar_hash_actions(action_one, team_one, 1, digest) == 0,
            "candidate single action hash failed");
    require_digest(digest,
        "ac763e91f6894e86fd936ce81f9887bde2f7854fe6ef58d3389babe089af2f62",
        "candidate single action framing differs");
    const uint32_t action_many[] = {0u, 0xFFFFFFFFu, 0x78563412u};
    const uint8_t team_many[] = {0u, 1u, 0u};
    require(ad_sidecar_hash_actions(action_many, team_many, 3, digest) == 0,
            "candidate multi-action hash failed");
    require_digest(digest,
        "c531efce2610800d2c10a9f6e2f8439d81458c38abb4264b7daa12ad09cf2319",
        "candidate multi-action framing differs");

    require(ad_sidecar_hash_dice(&empty_byte, &empty_byte, 0, digest) == 0,
            "candidate empty dice hash failed");
    require_digest(digest,
        "ae5c9f679d0a744934bc6648e0e72c8a528c8637410b37599897437b32c64703",
        "candidate empty dice framing differs");
    const uint8_t sides_one[] = {6u};
    const uint8_t values_one[] = {4u};
    require(ad_sidecar_hash_dice(sides_one, values_one, 1, digest) == 0,
            "candidate single dice hash failed");
    require_digest(digest,
        "b8ffc012864b1e0734a1e39864d4292d4cb02c59c9cfd0048a56396397ad86ee",
        "candidate single dice framing differs");
    const uint8_t sides_many[] = {2u, 6u, 8u};
    const uint8_t values_many[] = {1u, 6u, 3u};
    require(ad_sidecar_hash_dice(sides_many, values_many, 3, digest) == 0,
            "candidate multi-dice hash failed");
    require_digest(digest,
        "24c81de066665df5435255f058b42226b20445ef9d4c8a2a41d2dfab9b2d46bc",
        "candidate multi-dice framing differs");

    require(ad_sidecar_hash_legal(&empty_action, 0, digest) == 0,
            "candidate empty legal hash failed");
    require_digest(digest,
        "d7a977accf7d0fbb44e3c4c235b4f8cfdca2443915ee09fb6b80ccb82dca18fe",
        "candidate empty legal framing differs");
    require(ad_sidecar_hash_legal(action_one, 1, digest) == 0,
            "candidate single legal hash failed");
    require_digest(digest,
        "31c0d5189875da6f0e69108f7d245168eca4a4f73abc87259cf4c1db7c5be4a9",
        "candidate single legal framing differs");
    const uint32_t legal_many[] = {0u, 0x78563412u, 0xFFFFFFFFu};
    require(ad_sidecar_hash_legal(legal_many, 3, digest) == 0,
            "candidate multi-legal hash failed");
    require_digest(digest,
        "d015a25d403fe44cf23edb867e191290d22ab7cf43ad7da6d9f923da94aeda88",
        "candidate multi-legal framing differs");
}

static unsigned char* read_file(const char* path, size_t* length) {
    FILE* file = fopen(path, "rb");
    require(file != NULL, "cannot open expected output");
    require(fseek(file, 0, SEEK_END) == 0, "expected seek failed");
    long end = ftell(file);
    require(end >= 0, "expected length failed");
    require(fseek(file, 0, SEEK_SET) == 0, "expected rewind failed");
    *length = (size_t)end;
    unsigned char* bytes = malloc(*length == 0 ? 1 : *length);
    require(bytes != NULL, "expected allocation failed");
    require(fread(bytes, 1, *length, file) == *length,
            "expected read failed");
    require(fclose(file) == 0, "expected close failed");
    return bytes;
}

static void reset_output(unsigned char* output, size_t capacity,
                         size_t* length, size_t sentinel) {
    memset(output, 0xA5, capacity + 1);
    *length = sentinel;
}

static void require_unchanged(const unsigned char* output, size_t capacity,
                              size_t length, size_t sentinel,
                              const char* message) {
    require(length == sentinel, message);
    for (size_t i = 0; i <= capacity; i++) require(output[i] == 0xA5, message);
}

static void reset_guarded_output(unsigned char* output, size_t allocated,
                                 size_t* length, size_t sentinel) {
    memset(output, 0xA5, allocated);
    *length = sentinel;
}

static void require_guarded_output_unchanged(
    const unsigned char* output, size_t allocated, size_t length,
    size_t sentinel, const char* message) {
    require(length == sentinel, message);
    for (size_t i = 0; i < allocated; i++) require(output[i] == 0xA5, message);
}

static void expect_success(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    size_t records_allocated,
    unsigned char* recipes_output, size_t recipes_capacity,
    size_t recipes_allocated,
    const unsigned char* expected_records, const unsigned char* expected_recipes) {
    require(records_allocated > records_capacity &&
                recipes_allocated > recipes_capacity,
            "success output guard is absent");
    size_t records_length = SIZE_MAX - 1;
    size_t recipes_length = SIZE_MAX - 2;
    char error[AD_ERROR_CAP];
    memset(error, 0x5A, sizeof error);
    reset_guarded_output(records_output, records_allocated, &records_length,
                         SIZE_MAX - 1);
    reset_guarded_output(recipes_output, recipes_allocated, &recipes_length,
                         SIZE_MAX - 2);
#if defined(__linux__)
    reset_interposition();
    enforce_writer_arguments = 1;
    expected_writer_records = canonical_writer_records;
    expected_writer_recipes = canonical_writer_recipes;
    expected_writer_supplied_recipes = recipes;
    set_expected_writer_caller_storage(
        records, recipes, records_output, records_capacity, &records_length,
        recipes_output, recipes_capacity, &recipes_length, error);
#endif
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) == 0,
            "canonical serialization failed");
#if defined(__linux__)
    require(writer_calls == 1, "serializer did not call public writer once");
    require(builder_calls == 1,
            "serializer did not rebuild the canonical proof bundle once");
    require(identity_calls >= 1,
            "serializer did not map the supplied proof identities");
    require(post_writer_f1_calls == 4,
            "serializer did not derive four post-writer F1 facts");
    require(post_writer_f2_calls == 4,
            "serializer did not derive four post-writer F2 facts");
    require(post_writer_f4_calls == 1,
            "serializer did not derive the post-writer F4 fact");
    require(post_writer_score_calls == 1,
            "serializer did not derive the post-writer F5 score fact");
    require(post_writer_marked_calls == 4,
            "serializer did not derive each post-writer F1 marking fact once");
    require(post_writer_legal_calls >= AD_AUTHORED_PROOF_BUNDLE_COUNT,
            "serializer did not enumerate every post-writer legal set");
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        int expected_calls = expected_post_writer_kinds[i] ==
                AD_RECIPE_F3_EXACT_SECOND_HALF_TURN ? 1 : 2;
        require(expected_legal_match_calls[i] == expected_calls,
                "serializer legal-action derivation count differs by row");
    }
    require(open_memstream_calls == 1 && fflush_calls == 1 && fclose_calls == 1,
            "serializer memory-stream adapter call counts differ");
    require(stream_buffer_free_calls == 1 && stream_owned_buffer == NULL,
            "serializer did not release the memory-stream buffer once");
#endif
    require(records_length == records_capacity &&
                recipes_length == recipes_capacity,
            "returned output length differs");
    require(memcmp(records_output, expected_records, records_length) == 0 &&
                memcmp(recipes_output, expected_recipes, recipes_length) == 0,
            "canonical output bytes differ");
    for (size_t i = records_length; i < records_allocated; i++) {
        require(records_output[i] == 0xA5,
                "serializer changed the record output guard");
    }
    for (size_t i = recipes_length; i < recipes_allocated; i++) {
        require(recipes_output[i] == 0xA5,
                "serializer changed the recipe output guard");
    }
    require(error[0] == '\0', "success diagnostic differs");
}

static void expect_transformed_f5_rejection_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    size_t records_allocated,
    unsigned char* recipes_output, size_t recipes_capacity,
    size_t recipes_allocated) {
    require(records_allocated > records_capacity &&
                recipes_allocated > recipes_capacity,
            "transformed-F5 output guard is absent");
    const size_t record_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    const size_t recipe_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "transformed-F5 snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    memset(error, 0x5A, sizeof error);
    reset_guarded_output(records_output, records_allocated, &records_length,
                         0x11223344u);
    reset_guarded_output(recipes_output, recipes_allocated, &recipes_length,
                         0x55667788u);
#if defined(__linux__)
    reset_interposition();
#endif
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "false mandatory F5 fact was accepted");
#if defined(__linux__)
    require(builder_calls == 1 && identity_calls >= 1,
            "transformed-F5 rejection bypassed required stages");
    require(writer_calls == 1 && writer_returned == 1,
            "transformed-F5 rejection bypassed the writer lifecycle");
    require(open_memstream_calls == 1 && fflush_calls == 1 && fclose_calls == 1,
            "transformed-F5 stream lifecycle differs");
    require(stream_buffer_free_calls == 1 && stream_owned_buffer == NULL,
            "transformed-F5 rejection leaked the memory-stream buffer");
#endif
    require_guarded_output_unchanged(
        records_output, records_allocated, records_length, 0x11223344u,
        "record output or guard changed on transformed-F5 rejection");
    require_guarded_output_unchanged(
        recipes_output, recipes_allocated, recipes_length, 0x55667788u,
        "recipe output or guard changed on transformed-F5 rejection");
    require(memcmp(records, records_before, record_bytes) == 0 &&
                memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "transformed-F5 rejection changed caller input");
    free(recipes_before);
    free(records_before);
}

static void expect_larger_capacities_preserved(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t expected_records_length,
    unsigned char* recipes_output, size_t expected_recipes_length,
    const unsigned char* expected_records, const unsigned char* expected_recipes) {
    size_t records_capacity = expected_records_length + 64;
    size_t recipes_capacity = expected_recipes_length + 64;
    size_t records_length = SIZE_MAX - 1;
    size_t recipes_length = SIZE_MAX - 2;
    char error[AD_ERROR_CAP];
    reset_output(records_output, records_capacity, &records_length,
                 SIZE_MAX - 1);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 SIZE_MAX - 2);
#if defined(__linux__)
    reset_interposition();
    enforce_writer_arguments = 1;
    expected_writer_records = canonical_writer_records;
    expected_writer_recipes = canonical_writer_recipes;
    expected_writer_supplied_recipes = recipes;
    set_expected_writer_caller_storage(
        records, recipes, records_output, records_capacity, &records_length,
        recipes_output, recipes_capacity, &recipes_length, error);
#endif
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) == 0,
            "larger output capacities were rejected");
#if defined(__linux__)
    require(writer_calls == 1,
            "larger-capacity success writer count differs");
    require(stream_buffer_free_calls == 1 && stream_owned_buffer == NULL,
            "larger-capacity success leaked the memory-stream buffer");
#endif
    require(records_length == expected_records_length &&
                recipes_length == expected_recipes_length,
            "larger capacities changed returned lengths");
    require(memcmp(records_output, expected_records, records_length) == 0 &&
                memcmp(recipes_output, expected_recipes, recipes_length) == 0,
            "larger capacities changed output bytes");
    for (size_t i = records_length; i <= records_capacity; i++) {
        require(records_output[i] == 0xA5,
                "larger record-capacity suffix changed");
    }
    for (size_t i = recipes_length; i <= recipes_capacity; i++) {
        require(recipes_output[i] == 0xA5,
                "larger recipe-capacity suffix changed");
    }
}

static void expect_all_alias_pairs_rejected(
    const ad_bbs_record* canonical_records,
    const ad_recipe* canonical_recipes,
    size_t records_output_length, size_t recipes_output_length) {
    enum { ROLE_COUNT = 7 };
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe);
    size_t slot_size = recipe_bytes;
    if (slot_size < recipes_output_length + 1) {
        slot_size = recipes_output_length + 1;
    }
    unsigned char* slots[ROLE_COUNT];
    unsigned char* before[ROLE_COUNT];
    for (size_t role = 0; role < ROLE_COUNT; role++) {
        slots[role] = malloc(slot_size);
        before[role] = malloc(slot_size);
        require(slots[role] != NULL && before[role] != NULL,
                "alias matrix allocation failed");
        memset(slots[role], (int)(0x40 + role), slot_size);
    }
    memcpy(slots[0], canonical_records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_bbs_record));
    memcpy(slots[1], canonical_recipes, recipe_bytes);
    ad_bbs_record* stored_records = (ad_bbs_record*)slots[0];
    ad_recipe* stored_recipes = (ad_recipe*)slots[1];
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        stored_records[i].recipe = &stored_recipes[i];
    }
    memset(slots[2], 0xA5, records_output_length + 1);
    *(size_t*)slots[3] = 0x11223344u;
    memset(slots[4], 0xA5, recipes_output_length + 1);
    *(size_t*)slots[5] = 0x55667788u;
    memset(slots[6], 0x5A, AD_ERROR_CAP);

    for (size_t left = 0; left < ROLE_COUNT; left++) {
        for (size_t right = left + 1; right < ROLE_COUNT; right++) {
            for (size_t role = 0; role < ROLE_COUNT; role++) {
                memcpy(before[role], slots[role], slot_size);
            }
            unsigned char* role_pointer[ROLE_COUNT];
            for (size_t role = 0; role < ROLE_COUNT; role++) {
                role_pointer[role] = slots[role];
            }
            role_pointer[right] = role_pointer[left];
#if defined(__linux__)
            reset_interposition();
#endif
            int result = ad_serialize_authored_sidecars(
                (const ad_bbs_record*)role_pointer[0],
                AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (const ad_recipe*)role_pointer[1],
                AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)role_pointer[2], records_output_length,
                (size_t*)role_pointer[3],
                (char*)role_pointer[4], recipes_output_length,
                (size_t*)role_pointer[5], (char*)role_pointer[6]);
            require(result != 0, "pairwise storage alias accepted");
#if defined(__linux__)
            require(writer_calls == 0,
                    "pairwise alias reached the public writer");
#endif
            for (size_t role = 0; role < ROLE_COUNT; role++) {
                require(memcmp(slots[role], before[role], slot_size) == 0,
                        "pairwise alias changed caller storage");
            }
        }
    }
    for (size_t role = 0; role < ROLE_COUNT; role++) {
        free(before[role]);
        free(slots[role]);
    }
}

enum { STORAGE_ROLE_COUNT = 7 };

static size_t storage_role_length(size_t role, size_t records_output_length,
                                  size_t recipes_output_length) {
    const size_t lengths[STORAGE_ROLE_COUNT] = {
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_bbs_record),
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe),
        records_output_length,
        sizeof(size_t),
        recipes_output_length,
        sizeof(size_t),
        AD_ERROR_CAP,
    };
    require(role < STORAGE_ROLE_COUNT, "invalid storage role");
    return lengths[role];
}

static size_t storage_role_alignment(size_t role) {
    const size_t alignments[STORAGE_ROLE_COUNT] = {
        _Alignof(ad_bbs_record), _Alignof(ad_recipe), 1,
        _Alignof(size_t), 1, _Alignof(size_t), 1,
    };
    require(role < STORAGE_ROLE_COUNT, "invalid storage role alignment");
    return alignments[role];
}

static int call_alias_contract(unsigned char* const role_pointer[STORAGE_ROLE_COUNT],
                               size_t records_output_length,
                               size_t recipes_output_length) {
    return ad_sidecar_alias_contract(
        (const ad_bbs_record*)role_pointer[0],
        AD_AUTHORED_PROOF_BUNDLE_COUNT,
        (const ad_recipe*)role_pointer[1],
        AD_AUTHORED_PROOF_BUNDLE_COUNT,
        (char*)role_pointer[2], records_output_length,
        (size_t*)role_pointer[3],
        (char*)role_pointer[4], recipes_output_length,
        (size_t*)role_pointer[5], (char*)role_pointer[6]);
}

static int call_alias_contract_dynamic(
    unsigned char* const role_pointer[STORAGE_ROLE_COUNT],
    size_t record_count, size_t recipe_count,
    size_t records_capacity, size_t recipes_capacity) {
    return ad_sidecar_alias_contract(
        (const ad_bbs_record*)role_pointer[0], record_count,
        (const ad_recipe*)role_pointer[1], recipe_count,
        (char*)role_pointer[2], records_capacity,
        (size_t*)role_pointer[3],
        (char*)role_pointer[4], recipes_capacity,
        (size_t*)role_pointer[5], (char*)role_pointer[6]);
}

static int call_public_roles_dynamic(
    unsigned char* const role_pointer[STORAGE_ROLE_COUNT],
    size_t record_count, size_t recipe_count,
    size_t records_capacity, size_t recipes_capacity) {
    return ad_serialize_authored_sidecars(
        (const ad_bbs_record*)role_pointer[0], record_count,
        (const ad_recipe*)role_pointer[1], recipe_count,
        (char*)role_pointer[2], records_capacity,
        (size_t*)role_pointer[3],
        (char*)role_pointer[4], recipes_capacity,
        (size_t*)role_pointer[5], (char*)role_pointer[6]);
}

static int call_public_roles(unsigned char* const role_pointer[STORAGE_ROLE_COUNT],
                             size_t records_output_length,
                             size_t recipes_output_length) {
    return ad_serialize_authored_sidecars(
        (const ad_bbs_record*)role_pointer[0],
        AD_AUTHORED_PROOF_BUNDLE_COUNT,
        (const ad_recipe*)role_pointer[1],
        AD_AUTHORED_PROOF_BUNDLE_COUNT,
        (char*)role_pointer[2], records_output_length,
        (size_t*)role_pointer[3],
        (char*)role_pointer[4], recipes_output_length,
        (size_t*)role_pointer[5], (char*)role_pointer[6]);
}

static unsigned char* aligned_pointer(unsigned char* allocation,
                                      size_t alignment) {
    uintptr_t value = (uintptr_t)allocation;
    uintptr_t aligned = (value + alignment - 1u) & ~(uintptr_t)(alignment - 1u);
    return (unsigned char*)aligned;
}

static void require_allocations_unchanged(
    unsigned char* const allocation[STORAGE_ROLE_COUNT],
    unsigned char* const before[STORAGE_ROLE_COUNT],
    const size_t allocation_size[STORAGE_ROLE_COUNT], const char* message) {
    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
        require(memcmp(allocation[role], before[role],
                       allocation_size[role]) == 0, message);
    }
}

static void expect_dynamic_input_extent_aliases_rejected(
    size_t records_output_length, size_t recipes_output_length) {
    const size_t invalid_counts[] = {
        0, AD_AUTHORED_PROOF_BUNDLE_COUNT - 1,
        AD_AUTHORED_PROOF_BUNDLE_COUNT + 1,
    };
    size_t max_role_length = 0;
    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
        size_t length = storage_role_length(
            role, records_output_length, recipes_output_length);
        if (length > max_role_length) max_role_length = length;
    }
    for (size_t input_role = 0; input_role < 2; input_role++) {
        size_t element_size = input_role == 0
            ? sizeof(ad_bbs_record) : sizeof(ad_recipe);
        for (size_t count_index = 0;
             count_index < sizeof invalid_counts / sizeof invalid_counts[0];
             count_index++) {
            size_t supplied_count = invalid_counts[count_index];
            size_t protected_count =
                supplied_count > AD_AUTHORED_PROOF_BUNDLE_COUNT
                    ? supplied_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;
            size_t protected_bytes = protected_count * element_size;
            for (size_t target_role = 0;
                 target_role < STORAGE_ROLE_COUNT; target_role++) {
                if (target_role == input_role) continue;
                for (int boundary = 0; boundary < 2; boundary++) {
                    unsigned char* allocation[STORAGE_ROLE_COUNT];
                    unsigned char* before[STORAGE_ROLE_COUNT];
                    unsigned char* role_pointer[STORAGE_ROLE_COUNT];
                    size_t allocation_size[STORAGE_ROLE_COUNT];
                    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                        size_t length = storage_role_length(
                            role, records_output_length, recipes_output_length);
                        allocation_size[role] =
                            length + 64u + 4u * _Alignof(max_align_t);
                        if (role == input_role) {
                            allocation_size[role] +=
                                protected_bytes + max_role_length;
                        }
                        allocation[role] = malloc(allocation_size[role]);
                        before[role] = malloc(allocation_size[role]);
                        require(allocation[role] != NULL && before[role] != NULL,
                                "dynamic-input alias allocation failed");
                        memset(allocation[role], (int)(0x30 + role),
                               allocation_size[role]);
                        role_pointer[role] = aligned_pointer(
                            allocation[role], storage_role_alignment(role));
                    }
                    unsigned char* input_start = role_pointer[input_role];
                    size_t target_alignment =
                        storage_role_alignment(target_role);
                    if (boundary == 0) {
                        role_pointer[target_role] = input_start +
                            (protected_count - 1) * element_size;
                        role_pointer[target_role] = aligned_pointer(
                            role_pointer[target_role], target_alignment);
                    } else {
                        uintptr_t final =
                            (uintptr_t)(input_start + protected_bytes - 1u);
                        final &= ~(uintptr_t)(target_alignment - 1u);
                        role_pointer[target_role] = (unsigned char*)final;
                    }
                    require(role_pointer[target_role] >= input_start &&
                                role_pointer[target_role] <
                                    input_start + protected_bytes,
                            "dynamic-input target missed protected extent");
                    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                        memcpy(before[role], allocation[role],
                               allocation_size[role]);
                    }
                    size_t record_count = input_role == 0
                        ? supplied_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;
                    size_t recipe_count = input_role == 1
                        ? supplied_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;
                    for (size_t capacity_mode = 0; capacity_mode < 2;
                         capacity_mode++) {
                        size_t records_capacity = records_output_length +
                            (capacity_mode == 0 ? 0u : 64u);
                        size_t recipes_capacity = recipes_output_length +
                            (capacity_mode == 0 ? 0u : 64u);
                        for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                            memcpy(allocation[role], before[role],
                                   allocation_size[role]);
                        }
                        require(call_alias_contract_dynamic(
                                    role_pointer, record_count, recipe_count,
                                    records_capacity, recipes_capacity) != 0,
                                "dynamic count/capacity alias was accepted");
#if defined(__linux__)
                        reset_interposition();
#endif
                        require(call_public_roles_dynamic(
                                    role_pointer, record_count, recipe_count,
                                    records_capacity, recipes_capacity) != 0,
                                "public entry accepted a dynamic count/capacity alias");
#if defined(__linux__)
                        require(builder_calls == 0 && writer_calls == 0,
                                "dynamic count/capacity alias reached staging");
#endif
                        require_allocations_unchanged(
                            allocation, before, allocation_size,
                            "dynamic count/capacity alias changed caller storage");
                    }
                    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                        free(before[role]);
                        free(allocation[role]);
                    }
                }
            }
        }
    }
}

static void expect_output_capacity_suffix_aliases_rejected(
    const ad_bbs_record* canonical_records,
    const ad_recipe* canonical_recipes,
    size_t records_output_length, size_t recipes_output_length) {
    const size_t capacities[2] = {
        records_output_length + 64, recipes_output_length + 64,
    };
    const size_t output_roles[2] = {2, 4};
    for (size_t output_side = 0; output_side < 2; output_side++) {
        size_t output_role = output_roles[output_side];
        size_t returned_length = output_side == 0
            ? records_output_length : recipes_output_length;
        size_t output_capacity = capacities[output_side];
        for (size_t target_role = 0;
             target_role < STORAGE_ROLE_COUNT; target_role++) {
            if (target_role == output_role) continue;
            for (int boundary = 0; boundary < 2; boundary++) {
                unsigned char* allocation[STORAGE_ROLE_COUNT];
                unsigned char* before[STORAGE_ROLE_COUNT];
                unsigned char* role_pointer[STORAGE_ROLE_COUNT];
                size_t allocation_size[STORAGE_ROLE_COUNT];
                size_t target_length = storage_role_length(
                    target_role, records_output_length, recipes_output_length);
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    size_t length = storage_role_length(
                        role, records_output_length, recipes_output_length);
                    if (role == 2) length = capacities[0];
                    if (role == 4) length = capacities[1];
                    allocation_size[role] =
                        length + 4u * _Alignof(max_align_t);
                    if (role == output_role) {
                        allocation_size[role] += target_length + 64u;
                    }
                    allocation[role] = malloc(allocation_size[role]);
                    before[role] = malloc(allocation_size[role]);
                    require(allocation[role] != NULL && before[role] != NULL,
                            "output-suffix alias allocation failed");
                    memset(allocation[role], (int)(0x40 + role),
                           allocation_size[role]);
                    role_pointer[role] = aligned_pointer(
                        allocation[role], storage_role_alignment(role));
                }
                unsigned char* output_start = role_pointer[output_role];
                size_t target_alignment = storage_role_alignment(target_role);
                if (boundary == 0) {
                    role_pointer[target_role] = aligned_pointer(
                        output_start + returned_length, target_alignment);
                } else {
                    uintptr_t final =
                        (uintptr_t)(output_start + output_capacity - 1u);
                    final &= ~(uintptr_t)(target_alignment - 1u);
                    role_pointer[target_role] = (unsigned char*)final;
                }
                require(role_pointer[target_role] >=
                            output_start + returned_length &&
                            role_pointer[target_role] <
                                output_start + output_capacity,
                        "output-suffix target missed capacity-only extent");

                memcpy(role_pointer[1], canonical_recipes,
                       AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe));
                memcpy(role_pointer[0], canonical_records,
                       AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_bbs_record));
                ad_bbs_record* records = (ad_bbs_record*)role_pointer[0];
                ad_recipe* recipes = (ad_recipe*)role_pointer[1];
                for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
                    records[i].recipe = &recipes[i];
                }
                *(size_t*)role_pointer[3] = 0x11223344u;
                *(size_t*)role_pointer[5] = 0x55667788u;
                memset(role_pointer[6], 0x5A, AD_ERROR_CAP);
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    memcpy(before[role], allocation[role],
                           allocation_size[role]);
                }
                require(call_alias_contract_dynamic(
                            role_pointer, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            AD_AUTHORED_PROOF_BUNDLE_COUNT, capacities[0],
                            capacities[1]) != 0,
                        "output capacity-suffix alias was accepted");
#if defined(__linux__)
                reset_interposition();
#endif
                require(call_public_roles_dynamic(
                            role_pointer, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            AD_AUTHORED_PROOF_BUNDLE_COUNT, capacities[0],
                            capacities[1]) != 0,
                        "public entry accepted an output capacity-suffix alias");
#if defined(__linux__)
                require(builder_calls == 0 && writer_calls == 0,
                        "output capacity-suffix alias reached staging");
#endif
                require_allocations_unchanged(
                    allocation, before, allocation_size,
                    "output capacity-suffix alias changed caller storage");
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    free(before[role]);
                    free(allocation[role]);
                }
            }
        }
    }
}

static void expect_joint_dynamic_count_capacity_aliases_rejected(
    size_t records_output_length, size_t recipes_output_length) {
    const size_t long_count = AD_AUTHORED_PROOF_BUNDLE_COUNT + 1u;
    const size_t record_bytes = long_count * sizeof(ad_bbs_record);
    const size_t recipe_bytes = long_count * sizeof(ad_recipe);
    for (size_t input_role = 0; input_role < 2; input_role++) {
        unsigned char* allocation[STORAGE_ROLE_COUNT];
        unsigned char* before[STORAGE_ROLE_COUNT];
        unsigned char* role_pointer[STORAGE_ROLE_COUNT];
        size_t allocation_size[STORAGE_ROLE_COUNT] = {
            record_bytes + AD_ERROR_CAP,
            recipe_bytes + AD_ERROR_CAP,
            records_output_length + 65u + AD_ERROR_CAP,
            sizeof(size_t) + AD_ERROR_CAP,
            recipes_output_length + 65u + AD_ERROR_CAP,
            sizeof(size_t) + AD_ERROR_CAP,
            AD_ERROR_CAP,
        };
        for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
            allocation_size[role] += 2u * _Alignof(max_align_t);
            allocation[role] = malloc(allocation_size[role]);
            before[role] = malloc(allocation_size[role]);
            require(allocation[role] != NULL && before[role] != NULL,
                    "joint dynamic alias allocation failed");
            memset(allocation[role], (int)(0x20 + role),
                   allocation_size[role]);
            role_pointer[role] = aligned_pointer(
                allocation[role], storage_role_alignment(role));
        }
        size_t input_element_size = input_role == 0
            ? sizeof(ad_bbs_record) : sizeof(ad_recipe);
        role_pointer[6] = role_pointer[input_role] +
            (long_count - 1u) * input_element_size;
        for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
            memcpy(before[role], allocation[role], allocation_size[role]);
        }
        require(call_alias_contract_dynamic(
                    role_pointer, long_count, long_count,
                    records_output_length + 64u,
                    recipes_output_length + 64u) != 0,
                "joint dynamic count/capacity alias was accepted");
#if defined(__linux__)
        reset_interposition();
#endif
        require(call_public_roles_dynamic(
                    role_pointer, long_count, long_count,
                    records_output_length + 64u,
                    recipes_output_length + 64u) != 0,
                "public entry accepted a joint dynamic count/capacity alias");
#if defined(__linux__)
        require(builder_calls == 0 && writer_calls == 0,
                "joint dynamic count/capacity alias reached staging");
#endif
        require_allocations_unchanged(
            allocation, before, allocation_size,
            "joint dynamic count/capacity alias changed caller storage");
        for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
            free(before[role]);
            free(allocation[role]);
        }
    }
}

static void expect_short_capacity_aliases_precede_diagnostics(
    size_t records_output_length, size_t recipes_output_length) {
    const size_t host_roles[5] = {0, 1, 2, 3, 5};
    for (size_t short_side = 0; short_side < 2; short_side++) {
        for (size_t short_mode = 0; short_mode < 2; short_mode++) {
            size_t records_capacity = records_output_length;
            size_t recipes_capacity = recipes_output_length;
            if (short_side == 0) {
                records_capacity = short_mode == 0
                    ? 0u : records_output_length - 1u;
            } else {
                recipes_capacity = short_mode == 0
                    ? 0u : recipes_output_length - 1u;
            }
            for (size_t host_index = 0;
                 host_index < sizeof host_roles / sizeof host_roles[0];
                 host_index++) {
                size_t host_role = host_roles[host_index];
                if ((short_side == 0 && host_role == 2) ||
                        (short_side == 1 && host_role == 4)) {
                    host_role = short_side == 0 ? 4 : 2;
                }
                unsigned char* allocation[STORAGE_ROLE_COUNT];
                unsigned char* before[STORAGE_ROLE_COUNT];
                unsigned char* role_pointer[STORAGE_ROLE_COUNT];
                size_t allocation_size[STORAGE_ROLE_COUNT];
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    size_t length = storage_role_length(
                        role, records_output_length, recipes_output_length);
                    allocation_size[role] = length + AD_ERROR_CAP +
                        2u * _Alignof(max_align_t);
                    allocation[role] = malloc(allocation_size[role]);
                    before[role] = malloc(allocation_size[role]);
                    require(allocation[role] != NULL && before[role] != NULL,
                            "short-capacity alias allocation failed");
                    memset(allocation[role], (int)(0x60 + role),
                           allocation_size[role]);
                    role_pointer[role] = aligned_pointer(
                        allocation[role], storage_role_alignment(role));
                }
                role_pointer[6] = role_pointer[host_role];
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    memcpy(before[role], allocation[role],
                           allocation_size[role]);
                }
#if defined(__linux__)
                reset_interposition();
#endif
                require(call_public_roles_dynamic(
                            role_pointer, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            records_capacity, recipes_capacity) != 0,
                        "short capacity plus alias was accepted");
#if defined(__linux__)
                require(builder_calls == 0 && writer_calls == 0,
                        "short capacity plus alias reached staging");
#endif
                require_allocations_unchanged(
                    allocation, before, allocation_size,
                    "short-capacity diagnostic changed aliased caller storage");
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    free(before[role]);
                    free(allocation[role]);
                }
            }
        }
    }
}

static void expect_partial_alias_pairs_rejected(
    size_t records_output_length, size_t recipes_output_length) {
    size_t slot_size = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe);
    if (slot_size < recipes_output_length) slot_size = recipes_output_length;
    size_t allocation_size = slot_size * 3u + _Alignof(max_align_t);
    unsigned char* allocation[STORAGE_ROLE_COUNT];
    unsigned char* before[STORAGE_ROLE_COUNT];
    unsigned char* base[STORAGE_ROLE_COUNT];
    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
        allocation[role] = malloc(allocation_size);
        before[role] = malloc(allocation_size);
        require(allocation[role] != NULL && before[role] != NULL,
                "partial-alias arena allocation failed");
        base[role] = aligned_pointer(allocation[role] + slot_size,
                                     _Alignof(max_align_t));
    }
    for (size_t left = 0; left < STORAGE_ROLE_COUNT; left++) {
        for (size_t right = left + 1; right < STORAGE_ROLE_COUNT; right++) {
            for (int variant = 0; variant < 4; variant++) {
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    memset(allocation[role], (int)(0x30 + role), allocation_size);
                }
                unsigned char* role_pointer[STORAGE_ROLE_COUNT];
                memcpy(role_pointer, base, sizeof role_pointer);
                size_t left_length = storage_role_length(
                    left, records_output_length, recipes_output_length);
                size_t right_length = storage_role_length(
                    right, records_output_length, recipes_output_length);
                if (variant == 0) {
                    role_pointer[right] = role_pointer[left] + 1;
                } else if (variant == 1) {
                    role_pointer[right] = role_pointer[left] + left_length - 1;
                } else if (variant == 2) {
                    role_pointer[left] = role_pointer[right] + 1;
                } else {
                    role_pointer[left] = role_pointer[right] + right_length - 1;
                }
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    memcpy(before[role], allocation[role], allocation_size);
                }
#if defined(__linux__)
                reset_interposition();
#endif
                require(call_public_roles(role_pointer, records_output_length,
                                          recipes_output_length) != 0,
                        "partial storage overlap was accepted");
#if defined(__linux__)
                require(writer_calls == 0,
                        "partial storage overlap reached the public writer");
#endif
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    require(memcmp(allocation[role], before[role],
                                   allocation_size) == 0,
                            "partial storage overlap changed caller bytes");
                }
            }
        }
    }
    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
        free(before[role]);
        free(allocation[role]);
    }
}

static void expect_every_endpoint_adjacency_allowed(
    const ad_bbs_record* canonical_records,
    const ad_recipe* canonical_recipes,
    const unsigned char* expected_records,
    const unsigned char* expected_recipes,
    size_t records_output_length, size_t recipes_output_length) {
    for (size_t capacity_mode = 0; capacity_mode < 2; capacity_mode++) {
        size_t records_capacity = records_output_length +
            (capacity_mode == 0 ? 0u : 64u);
        size_t recipes_capacity = recipes_output_length +
            (capacity_mode == 0 ? 0u : 64u);
        size_t protected_length[STORAGE_ROLE_COUNT];
        for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
            protected_length[role] = storage_role_length(
                role, records_output_length, recipes_output_length);
        }
        protected_length[2] = records_capacity;
        protected_length[4] = recipes_capacity;
        for (size_t first = 0; first < STORAGE_ROLE_COUNT; first++) {
            for (size_t second = 0; second < STORAGE_ROLE_COUNT; second++) {
                if (first == second || protected_length[first] %
                        storage_role_alignment(second) != 0) {
                    continue;
                }
                size_t pair_size = protected_length[first] +
                    protected_length[second] + _Alignof(max_align_t);
                unsigned char* pair_allocation = malloc(pair_size);
                require(pair_allocation != NULL,
                        "endpoint-adjacency pair allocation failed");
                unsigned char* role_pointer[STORAGE_ROLE_COUNT];
                unsigned char* separate[STORAGE_ROLE_COUNT] = {0};
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    separate[role] = malloc(
                        protected_length[role] + _Alignof(max_align_t));
                    require(separate[role] != NULL,
                            "endpoint-adjacency role allocation failed");
                    role_pointer[role] = aligned_pointer(
                        separate[role], storage_role_alignment(role));
                }
                role_pointer[first] = aligned_pointer(
                    pair_allocation, storage_role_alignment(first));
                role_pointer[second] =
                    role_pointer[first] + protected_length[first];
                require((uintptr_t)role_pointer[second] %
                            storage_role_alignment(second) == 0,
                        "endpoint adjacency is misaligned");
                require(call_alias_contract_dynamic(
                            role_pointer, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            records_capacity, recipes_capacity) == 0,
                        "ordered half-open endpoint adjacency was rejected");

                memcpy(role_pointer[1], canonical_recipes,
                       AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe));
                memcpy(role_pointer[0], canonical_records,
                       AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_bbs_record));
                ad_bbs_record* records = (ad_bbs_record*)role_pointer[0];
                ad_recipe* recipes = (ad_recipe*)role_pointer[1];
                for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
                    records[i].recipe = &recipes[i];
                }
                memset(role_pointer[2], 0xA5, records_capacity);
                memset(role_pointer[4], 0xA5, recipes_capacity);
                *(size_t*)role_pointer[3] = 0x11223344u;
                *(size_t*)role_pointer[5] = 0x55667788u;
                memset(role_pointer[6], 0x5A, AD_ERROR_CAP);
                const size_t record_bytes =
                    AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_bbs_record);
                const size_t recipe_bytes =
                    AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe);
                ad_bbs_record* records_before = malloc(record_bytes);
                ad_recipe* recipes_before = malloc(recipe_bytes);
                require(records_before != NULL && recipes_before != NULL,
                        "endpoint-adjacency snapshot allocation failed");
                memcpy(records_before, records, record_bytes);
                memcpy(recipes_before, recipes, recipe_bytes);
#if defined(__linux__)
                reset_interposition();
#endif
                require(call_public_roles_dynamic(
                            role_pointer, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            AD_AUTHORED_PROOF_BUNDLE_COUNT,
                            records_capacity, recipes_capacity) == 0,
                        "public entry rejected ordered endpoint adjacency");
#if defined(__linux__)
                require(writer_calls == 1,
                        "endpoint-adjacency success bypassed the public writer");
#endif
                require(*(size_t*)role_pointer[3] == records_output_length &&
                            *(size_t*)role_pointer[5] == recipes_output_length &&
                            role_pointer[6][0] == '\0',
                        "endpoint-adjacency success metadata differs");
                require(memcmp(role_pointer[2], expected_records,
                               records_output_length) == 0 &&
                            memcmp(role_pointer[4], expected_recipes,
                                   recipes_output_length) == 0,
                        "endpoint-adjacency success output differs");
                for (size_t i = records_output_length;
                     i < records_capacity; i++) {
                    require(role_pointer[2][i] == 0xA5,
                            "endpoint-adjacency record suffix changed");
                }
                for (size_t i = recipes_output_length;
                     i < recipes_capacity; i++) {
                    require(role_pointer[4][i] == 0xA5,
                            "endpoint-adjacency recipe suffix changed");
                }
                require(memcmp(records, records_before, record_bytes) == 0 &&
                            memcmp(recipes, recipes_before, recipe_bytes) == 0,
                        "endpoint-adjacency success changed caller input");
                free(recipes_before);
                free(records_before);
                for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
                    free(separate[role]);
                }
                free(pair_allocation);
            }
        }
    }
}

static void expect_every_extent_overflow_rejected(
    size_t records_output_length, size_t recipes_output_length) {
    unsigned char* role_pointer[STORAGE_ROLE_COUNT];
    unsigned char* allocations[STORAGE_ROLE_COUNT];
    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
        size_t length = storage_role_length(
            role, records_output_length, recipes_output_length);
        allocations[role] = malloc(length + _Alignof(max_align_t));
        require(allocations[role] != NULL, "extent-overflow allocation failed");
        role_pointer[role] = aligned_pointer(
            allocations[role], storage_role_alignment(role));
    }
    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
        unsigned char* saved = role_pointer[role];
        size_t length = storage_role_length(
            role, records_output_length, recipes_output_length);
        role_pointer[role] = (unsigned char*)(UINTPTR_MAX - length + 2u);
        require(call_alias_contract(role_pointer, records_output_length,
                                    recipes_output_length) != 0,
                "pointer-end overflow was accepted");
        role_pointer[role] = saved;
    }
    for (size_t role = 0; role < STORAGE_ROLE_COUNT; role++) {
        free(allocations[role]);
    }
}

static void expect_failure_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity,
    int expected_writer_calls) {
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "failure snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    reset_output(records_output, records_capacity, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 0x55667788u);
#if defined(__linux__)
    reset_interposition();
#else
    (void)expected_writer_calls;
#endif
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "malformed proof input was accepted");
#if defined(__linux__)
    require(writer_calls == expected_writer_calls,
            "malformed input reached the wrong writer phase");
#endif
    require_unchanged(records_output, records_capacity, records_length,
                      0x11223344u, "record output changed on input failure");
    require_unchanged(recipes_output, recipes_capacity, recipes_length,
                      0x55667788u, "recipe output changed on input failure");
    require(memcmp(records, records_before, record_bytes) == 0 &&
                memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "malformed input changed on failure");
    free(recipes_before);
    free(records_before);
}

static void expect_preflight_rejected_unchanged(
    const ad_bbs_record* records, size_t record_count,
    const ad_recipe* recipes, size_t recipe_count,
    unsigned char* records_output, size_t records_capacity,
    size_t records_allocated,
    unsigned char* recipes_output, size_t recipes_capacity,
    size_t recipes_allocated,
    char* error, int require_error_unchanged) {
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    reset_output(records_output, records_allocated, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_allocated, &recipes_length,
                 0x55667788u);
    if (error != NULL) memset(error, 0x5A, AD_ERROR_CAP);
#if defined(__linux__)
    reset_interposition();
#endif
    require(ad_serialize_authored_sidecars(
                records, record_count, recipes, recipe_count,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "invalid preflight input was accepted");
#if defined(__linux__)
    require(writer_calls == 0, "invalid preflight reached public writer");
#endif
    require_unchanged(records_output, records_allocated, records_length,
                      0x11223344u, "record output changed in preflight");
    require_unchanged(recipes_output, recipes_allocated, recipes_length,
                      0x55667788u, "recipe output changed in preflight");
    if (require_error_unchanged) {
        require(error != NULL, "missing error storage for preservation check");
        for (size_t i = 0; i < AD_ERROR_CAP; i++) {
            require((unsigned char)error[i] == 0x5A,
                    "error storage changed before safe alias proof");
        }
    }
}

static void expect_each_null_role_rejected(
    const ad_bbs_record* records, const ad_recipe* recipes,
    size_t records_output_length, size_t recipes_output_length) {
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    for (size_t missing = 0; missing < STORAGE_ROLE_COUNT; missing++) {
        unsigned char* records_output = malloc(records_output_length + 1);
        unsigned char* recipes_output = malloc(recipes_output_length + 1);
        ad_bbs_record* records_before = malloc(record_bytes);
        ad_recipe* recipes_before = malloc(recipe_bytes);
        require(records_output != NULL && recipes_output != NULL &&
                    records_before != NULL && recipes_before != NULL,
                "null-role snapshot allocation failed");
        memcpy(records_before, records, record_bytes);
        memcpy(recipes_before, recipes, recipe_bytes);
        size_t records_length = 0x11223344u;
        size_t recipes_length = 0x55667788u;
        char error[AD_ERROR_CAP];
        reset_output(records_output, records_output_length, &records_length,
                     0x11223344u);
        reset_output(recipes_output, recipes_output_length, &recipes_length,
                     0x55667788u);
        memset(error, 0x5A, sizeof error);
        unsigned char* role_pointer[STORAGE_ROLE_COUNT] = {
            (unsigned char*)records, (unsigned char*)recipes,
            records_output, (unsigned char*)&records_length,
            recipes_output, (unsigned char*)&recipes_length,
            (unsigned char*)error,
        };
        role_pointer[missing] = NULL;
#if defined(__linux__)
        reset_interposition();
#endif
        require(call_public_roles(role_pointer, records_output_length,
                                  recipes_output_length) != 0,
                "null storage role was accepted");
#if defined(__linux__)
        require(builder_calls == 0 && writer_calls == 0,
                "null storage role reached staging");
#endif
        require_unchanged(records_output, records_output_length,
                          records_length, 0x11223344u,
                          "record output changed on null-role failure");
        require_unchanged(recipes_output, recipes_output_length,
                          recipes_length, 0x55667788u,
                          "recipe output changed on null-role failure");
        require(memcmp(records, records_before, record_bytes) == 0 &&
                    memcmp(recipes, recipes_before, recipe_bytes) == 0,
                "null-role failure changed caller input");
        if (missing != 6) {
            for (size_t i = 0; i < sizeof error; i++) {
                require((unsigned char)error[i] == 0x5A,
                        "null-role failure wrote a diagnostic before extent proof");
            }
        }
        free(recipes_before);
        free(records_before);
        free(recipes_output);
        free(records_output);
    }
}

static void expect_symmetric_count_capacity_rejections(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_output_length,
    unsigned char* recipes_output, size_t recipes_output_length, char* error) {
    const size_t invalid_counts[] = {
        0, AD_AUTHORED_PROOF_BUNDLE_COUNT - 1,
        AD_AUTHORED_PROOF_BUNDLE_COUNT + 1, SIZE_MAX,
    };
    ad_recipe* over_recipes = malloc(
        (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_recipes);
    ad_bbs_record* over_records = malloc(
        (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_records);
    ad_recipe* recipes_before = malloc(
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes_before);
    ad_bbs_record* records_before = malloc(
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records_before);
    ad_recipe* over_recipes_before = malloc(
        (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_recipes_before);
    ad_bbs_record* over_records_before = malloc(
        (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_records_before);
    require(over_recipes != NULL && over_records != NULL &&
                recipes_before != NULL && records_before != NULL &&
                over_recipes_before != NULL && over_records_before != NULL,
            "long-count backing allocation failed");
    memcpy(recipes_before, recipes,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes_before);
    memcpy(records_before, records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records_before);
    memcpy(over_recipes, recipes,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *over_recipes);
    memcpy(over_records, records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *over_records);
    memset(&over_recipes[AD_AUTHORED_PROOF_BUNDLE_COUNT], 0x5A,
           sizeof over_recipes[AD_AUTHORED_PROOF_BUNDLE_COUNT]);
    memset(&over_records[AD_AUTHORED_PROOF_BUNDLE_COUNT], 0x5A,
           sizeof over_records[AD_AUTHORED_PROOF_BUNDLE_COUNT]);
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        over_records[i].recipe = &over_recipes[i];
    }
    memcpy(over_recipes_before, over_recipes,
           (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_recipes_before);
    memcpy(over_records_before, over_records,
           (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) * sizeof *over_records_before);
    for (size_t side = 0; side < 2; side++) {
        for (size_t i = 0; i < sizeof invalid_counts / sizeof invalid_counts[0];
             i++) {
            size_t count = invalid_counts[i];
            const ad_bbs_record* record_pointer =
                count == AD_AUTHORED_PROOF_BUNDLE_COUNT + 1
                    ? over_records : records;
            const ad_recipe* recipe_pointer =
                count == AD_AUTHORED_PROOF_BUNDLE_COUNT + 1
                    ? over_recipes : recipes;
            expect_preflight_rejected_unchanged(
                side == 0 ? record_pointer : records,
                side == 0 ? count : AD_AUTHORED_PROOF_BUNDLE_COUNT,
                side == 1 ? recipe_pointer : recipes,
                side == 1 ? count : AD_AUTHORED_PROOF_BUNDLE_COUNT,
                records_output, records_output_length, records_output_length,
                recipes_output, recipes_output_length, recipes_output_length,
                error, count == SIZE_MAX);
            require(memcmp(records, records_before,
                           AD_AUTHORED_PROOF_BUNDLE_COUNT *
                               sizeof *records_before) == 0 &&
                        memcmp(recipes, recipes_before,
                               AD_AUTHORED_PROOF_BUNDLE_COUNT *
                                   sizeof *recipes_before) == 0 &&
                        memcmp(over_records, over_records_before,
                               (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) *
                                   sizeof *over_records_before) == 0 &&
                        memcmp(over_recipes, over_recipes_before,
                               (AD_AUTHORED_PROOF_BUNDLE_COUNT + 1) *
                                   sizeof *over_recipes_before) == 0,
                    "invalid count changed caller input");
        }
    }
    const size_t invalid_record_capacities[] = {
        0, records_output_length - 1, SIZE_MAX,
    };
    for (size_t i = 0;
         i < sizeof invalid_record_capacities /
                 sizeof invalid_record_capacities[0]; i++) {
        expect_preflight_rejected_unchanged(
            records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            records_output, invalid_record_capacities[i],
            records_output_length,
            recipes_output, recipes_output_length, recipes_output_length,
            error, invalid_record_capacities[i] == SIZE_MAX);
        require(memcmp(records, records_before,
                       AD_AUTHORED_PROOF_BUNDLE_COUNT *
                           sizeof *records_before) == 0 &&
                    memcmp(recipes, recipes_before,
                           AD_AUTHORED_PROOF_BUNDLE_COUNT *
                               sizeof *recipes_before) == 0,
                "invalid record capacity changed caller input");
    }
    const size_t invalid_recipe_capacities[] = {
        0, recipes_output_length - 1, SIZE_MAX,
    };
    for (size_t i = 0;
         i < sizeof invalid_recipe_capacities /
                 sizeof invalid_recipe_capacities[0]; i++) {
        expect_preflight_rejected_unchanged(
            records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            records_output, records_output_length, records_output_length,
            recipes_output, invalid_recipe_capacities[i],
            recipes_output_length,
            error, invalid_recipe_capacities[i] == SIZE_MAX);
        require(memcmp(records, records_before,
                       AD_AUTHORED_PROOF_BUNDLE_COUNT *
                           sizeof *records_before) == 0 &&
                    memcmp(recipes, recipes_before,
                           AD_AUTHORED_PROOF_BUNDLE_COUNT *
                               sizeof *recipes_before) == 0,
                "invalid recipe capacity changed caller input");
    }
    free(over_records_before);
    free(over_recipes_before);
    free(records_before);
    free(recipes_before);
    free(over_records);
    free(over_recipes);
}

static void require_reconcile_failure_preserves_callers(
    const ad_bbs_record* supplied_records, const ad_recipe* supplied_recipes,
    const ad_bbs_record* canonical_records, const ad_recipe* canonical_recipes) {
    const size_t record_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *supplied_records;
    const size_t recipe_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *supplied_recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    ad_bbs_record* canonical_records_before = malloc(record_bytes);
    ad_recipe* canonical_recipes_before = malloc(recipe_bytes);
    ad_bbs_record ordered[AD_AUTHORED_PROOF_BUNDLE_COUNT + 1];
    unsigned char ordered_before[sizeof ordered];
    char error[AD_ERROR_CAP];
    require(records_before != NULL && recipes_before != NULL &&
                canonical_records_before != NULL &&
                canonical_recipes_before != NULL,
            "reconciliation snapshot allocation failed");
    memcpy(records_before, supplied_records, record_bytes);
    memcpy(recipes_before, supplied_recipes, recipe_bytes);
    memcpy(canonical_records_before, canonical_records, record_bytes);
    memcpy(canonical_recipes_before, canonical_recipes, recipe_bytes);
    memset(ordered, 0xA5, sizeof ordered);
    memcpy(ordered_before, ordered, sizeof ordered);
    memset(error, 0x5A, sizeof error);
    require(ad_sidecar_reconcile_bundle(
                supplied_records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                supplied_recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                canonical_records, canonical_recipes, ordered, error) != 0,
            "malformed caller bundle reconciled successfully");
    require(memcmp(ordered, ordered_before, sizeof ordered) == 0,
            "failed reconciliation changed staged records");
    require(memcmp(supplied_records, records_before, record_bytes) == 0 &&
                memcmp(supplied_recipes, recipes_before, recipe_bytes) == 0 &&
                memcmp(canonical_records, canonical_records_before,
                       record_bytes) == 0 &&
                memcmp(canonical_recipes, canonical_recipes_before,
                       recipe_bytes) == 0,
            "failed reconciliation changed an input bundle");
    free(canonical_recipes_before);
    free(canonical_records_before);
    free(recipes_before);
    free(records_before);
}

static void mutate_recipe_projection(ad_recipe* recipe, int projection) {
    switch (projection) {
        case 0: recipe->procgen_seed ^= 1u; break;
        case 1: recipe->procgen_stream ^= 1u; break;
        case 2: recipe->game_seed ^= 1u; break;
        case 3: recipe->game_stream ^= 1u; break;
        case 4: recipe->controller_seed ^= 1u; break;
        case 5: recipe->controller_stream ^= 1u; break;
        case 6:
            recipe->kind = (ad_recipe_kind)((recipe->kind + 1) %
                                             AD_RECIPE_KIND_COUNT);
            break;
        case 7: recipe->capture_turn ^= 1; break;
        case 8: recipe->capture_active_team ^= 1; break;
        case 9:
            recipe->capture_handoff_target_bucket =
                (ad_f2_target_count_bucket)(
                    (recipe->capture_handoff_target_bucket + 1) % 3);
            break;
        case 10:
            recipe->capture_pass_carrier_pressure =
                (ad_f1_carrier_pressure_bucket)(
                    (recipe->capture_pass_carrier_pressure + 1) % 3);
            break;
        case 11: recipe->home_team = (recipe->home_team + 1) % BB_TEAM_COUNT; break;
        case 12: recipe->away_team = (recipe->away_team + 1) % BB_TEAM_COUNT; break;
        case 13: recipe->exclude_team = recipe->exclude_team == -1 ? 0 : -1; break;
        case 14: recipe->procgen.skillup_max_players ^= 1; break;
        case 15: recipe->procgen.skillup_max_each ^= 1; break;
        case 16:
            ((unsigned char*)&recipe->procgen.skillup_secondary_pct)[0] ^= 1u;
            break;
        case 17: ((unsigned char*)&recipe->initialized)[0] ^= 1u; break;
        case 18: ((unsigned char*)&recipe->captured)[0] ^= 1u; break;
        case 19: recipe->actions[0] ^= 1u; break;
        case 20: recipe->actions[recipe->action_count - 1] ^= 1u; break;
        case 21: recipe->decision_teams[0] ^= 1u; break;
        case 22: recipe->decision_teams[recipe->action_count - 1] ^= 1u; break;
        case 23: recipe->dice_sides[0] ^= 1u; break;
        case 24: recipe->dice_sides[recipe->dice_count - 1] ^= 1u; break;
        case 25: recipe->dice_values[0] ^= 1u; break;
        case 26: recipe->dice_values[recipe->dice_count - 1] ^= 1u; break;
        case 27: recipe->action_count--; break;
        case 28: recipe->dice_count--; break;
        default: require(0, "unknown recipe mutation projection");
    }
}

static void expect_complete_reconciliation_matrix(
    const ad_bbs_record* canonical_records, const ad_recipe* canonical_recipes) {
    const size_t record_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *canonical_records;
    const size_t recipe_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *canonical_recipes;
    ad_bbs_record ordered[AD_AUTHORED_PROOF_BUNDLE_COUNT + 1];
    char error[AD_ERROR_CAP];
    memset(ordered, 0xA5, sizeof ordered);
    require(ad_sidecar_reconcile_bundle(
                canonical_records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                canonical_recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                canonical_records, canonical_recipes, ordered, error) == 0,
            "canonical bundle reconciliation failed");
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        require(ordered[i].source_id == canonical_records[i].source_id &&
                    ordered[i].decision_index ==
                        canonical_records[i].decision_index &&
                    ordered[i].recipe == &canonical_recipes[i],
                "canonical reconciliation result differs");
    }
    for (size_t i = 0; i < sizeof ordered[AD_AUTHORED_PROOF_BUNDLE_COUNT]; i++) {
        require(((unsigned char*)&ordered[AD_AUTHORED_PROOF_BUNDLE_COUNT])[i] ==
                    0xA5,
                "canonical reconciliation wrote past its fixed output");
    }
    require(error[0] == '\0', "canonical reconciliation diagnostic differs");

    ad_bbs_record* bad_records = malloc(record_bytes);
    ad_recipe* bad_recipes = malloc(recipe_bytes);
    ad_recipe* external_recipe = malloc(sizeof *external_recipe);
    require(bad_records != NULL && bad_recipes != NULL &&
                external_recipe != NULL,
            "reconciliation mutation allocation failed");
    for (size_t index = 0; index < AD_AUTHORED_PROOF_BUNDLE_COUNT; index++) {
        for (int record_case = 0; record_case < 5; record_case++) {
            memcpy(bad_records, canonical_records, record_bytes);
            if (record_case == 0) {
                bad_records[index].recipe =
                    canonical_recipes + AD_AUTHORED_PROOF_BUNDLE_COUNT;
            } else if (record_case == 1) {
                bad_records[index].recipe =
                    &canonical_recipes[(index + 1) %
                                       AD_AUTHORED_PROOF_BUNDLE_COUNT];
            } else if (record_case == 2) {
                bad_records[index].source_id ^= 1u;
            } else if (record_case == 3) {
                bad_records[index].decision_index++;
            } else {
                *external_recipe = canonical_recipes[index];
                bad_records[index].recipe = external_recipe;
            }
            require_reconcile_failure_preserves_callers(
                bad_records, canonical_recipes,
                canonical_records, canonical_recipes);
        }
        for (int projection = 0; projection < 29; projection++) {
            memcpy(bad_recipes, canonical_recipes, recipe_bytes);
            memcpy(bad_records, canonical_records, record_bytes);
            for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
                bad_records[i].recipe = &bad_recipes[i];
            }
            mutate_recipe_projection(&bad_recipes[index], projection);
            require_reconcile_failure_preserves_callers(
                bad_records, bad_recipes,
                canonical_records, canonical_recipes);
        }
        memcpy(bad_recipes, canonical_recipes, recipe_bytes);
        memcpy(bad_records, canonical_records, record_bytes);
        size_t duplicate = (index + 1) % AD_AUTHORED_PROOF_BUNDLE_COUNT;
        bad_recipes[index] = bad_recipes[duplicate];
        for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
            bad_records[i].recipe = &bad_recipes[i];
        }
        require_reconcile_failure_preserves_callers(
            bad_records, bad_recipes, canonical_records, canonical_recipes);
    }
    free(external_recipe);
    free(bad_recipes);
    free(bad_records);
}

static void expect_f5_end_activation_helper(
    const ad_recipe* canonical_recipes) {
    const bb_match* match = NULL;
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        if (canonical_recipes[i].kind == AD_RECIPE_F5_SCORE_OR_WAIT) {
            require(match == NULL, "proof bundle contains duplicate F5 recipes");
            match = &canonical_recipes[i].captured;
        }
    }
    require(match != NULL, "proof bundle contains no F5 recipe");
    bb_match before = *match;
    require(ad_sidecar_f5_end_activation_legal(match) == 1,
            "candidate F5 end-activation helper rejected the proof row");
    require(memcmp(match, &before, sizeof before) == 0,
            "candidate F5 helper changed its valid input");

    bb_match altered = *match;
    altered.ball.state = BB_BALL_ON_GROUND;
    altered.ball.carrier = BB_NO_PLAYER;
    before = altered;
    require(ad_sidecar_f5_end_activation_legal(&altered) == 0,
            "candidate F5 end-activation helper accepted a ground ball");
    require(memcmp(&altered, &before, sizeof before) == 0,
            "candidate F5 helper changed its ground-ball input");

    altered = *match;
    require(altered.ball.carrier < BB_NUM_PLAYERS,
            "proof F5 carrier is invalid");
    altered.players[altered.ball.carrier].flags |= BB_PF_USED;
    before = altered;
    require(ad_sidecar_f5_end_activation_legal(&altered) == 0,
            "candidate F5 end-activation helper ignored activation legality");
    require(memcmp(&altered, &before, sizeof before) == 0,
            "candidate F5 helper changed its used-carrier input");

    altered = *match;
    altered.ball.carrier = (uint8_t)(
        altered.ball.carrier < BB_TEAM_SLOTS
            ? altered.ball.carrier + BB_TEAM_SLOTS
            : altered.ball.carrier - BB_TEAM_SLOTS);
    before = altered;
    require(ad_sidecar_f5_end_activation_legal(&altered) == 0,
            "candidate F5 end-activation helper accepted an opposing carrier");
    require(memcmp(&altered, &before, sizeof before) == 0,
            "candidate F5 helper changed its opposing-carrier input");
}

#if defined(__linux__)
static const ad_recipe* family_recipe_by_ordinal(
    const ad_recipe* recipes, ad_recipe_kind kind, int ordinal) {
    int seen = 0;
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        if (recipes[i].kind != kind) continue;
        if (seen++ == ordinal) return &recipes[i];
    }
    require(0, "canonical family ordinal is out of range");
    return NULL;
}
#endif

static void expect_permuted_reconciliation(
    const ad_bbs_record* permuted_records, const ad_recipe* permuted_recipes,
    const ad_bbs_record* canonical_records, const ad_recipe* canonical_recipes) {
    ad_bbs_record ordered[AD_AUTHORED_PROOF_BUNDLE_COUNT + 1];
    char error[AD_ERROR_CAP];
    memset(ordered, 0xA5, sizeof ordered);
    require(ad_sidecar_reconcile_bundle(
                permuted_records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                permuted_recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                canonical_records, canonical_recipes, ordered, error) == 0,
            "valid caller permutation did not reconcile");
    uintptr_t supplied_start = (uintptr_t)permuted_recipes;
    const size_t supplied_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof(ad_recipe);
    unsigned char seen[AD_AUTHORED_PROOF_BUNDLE_COUNT] = {0};
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        uintptr_t recipe_pointer = (uintptr_t)ordered[i].recipe;
        uintptr_t delta = recipe_pointer - supplied_start;
        require(ordered[i].source_id == canonical_records[i].source_id &&
                    ordered[i].decision_index ==
                        canonical_records[i].decision_index &&
                    recipe_pointer >= supplied_start &&
                    delta < supplied_bytes &&
                    delta % sizeof(ad_recipe) == 0 &&
                    memcmp(ordered[i].recipe, &canonical_recipes[i],
                           sizeof canonical_recipes[i]) == 0,
                "permuted reconciliation result differs");
        size_t supplied_index = delta / sizeof(ad_recipe);
        require(!seen[supplied_index],
                "permuted reconciliation duplicated a caller recipe");
        seen[supplied_index] = 1;
    }
    for (size_t i = 0; i < sizeof ordered[AD_AUTHORED_PROOF_BUNDLE_COUNT]; i++) {
        require(((unsigned char*)&ordered[AD_AUTHORED_PROOF_BUNDLE_COUNT])[i] ==
                    0xA5,
                "permuted reconciliation wrote past its fixed output");
    }
}

#if defined(__linux__)
static void expect_writer_failure_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity) {
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    reset_output(records_output, records_capacity, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 0x55667788u);
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "writer-failure input snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    reset_interposition();
    writer_mode = 1;
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "injected writer failure was accepted");
    require(writer_calls == 1, "injected writer failure call count differs");
    require(open_memstream_calls == 1 && fflush_calls == 0 && fclose_calls == 1,
            "writer-failure stream cleanup differs");
    require(stream_buffer_free_calls == 1 && stream_owned_buffer == NULL,
            "writer failure leaked the memory-stream buffer");
    require_unchanged(records_output, records_capacity, records_length,
                      0x11223344u, "record output changed on writer failure");
    require_unchanged(recipes_output, recipes_capacity, recipes_length,
                      0x55667788u, "recipe output changed on writer failure");
    require(memcmp(records, records_before, record_bytes) == 0 &&
                memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "writer failure changed caller input");
    free(recipes_before);
    free(records_before);
}

static void expect_successful_writer_corruption_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity, int mode) {
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "writer-corruption input snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    reset_output(records_output, records_capacity, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 0x55667788u);
    reset_interposition();
    writer_mode = mode;
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "successful corrupt writer output was accepted");
    require(writer_calls == 1 && writer_returned == 1,
            "successful corrupt writer call contract differs");
    require(open_memstream_calls == 1 && fflush_calls == 1 && fclose_calls == 1,
            "corrupt-writer stream lifecycle differs");
    require(stream_buffer_free_calls == 1 && stream_owned_buffer == NULL,
            "corrupt writer output leaked the memory-stream buffer");
    require(post_writer_f1_calls == 0 && post_writer_f2_calls == 0 &&
                post_writer_f4_calls == 0 && post_writer_score_calls == 0 &&
                post_writer_marked_calls == 0 && post_writer_legal_calls == 0,
            "row derivation ran after corrupt BBS success");
    require_unchanged(records_output, records_capacity, records_length,
                      0x11223344u,
                      "record output changed on corrupt writer success");
    require_unchanged(recipes_output, recipes_capacity, recipes_length,
                      0x55667788u,
                      "recipe output changed on corrupt writer success");
    require(memcmp(records, records_before, record_bytes) == 0 &&
                memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "corrupt writer success changed caller input");
    free(recipes_before);
    free(records_before);
}

static void expect_required_stage_failure_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity, int stage) {
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "required-stage input snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    reset_output(records_output, records_capacity, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 0x55667788u);
    reset_interposition();
    force_builder_failure = stage == 0;
    force_identity_failure = stage == 1;
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "required stage failure was ignored");
    require(builder_calls == 1 && identity_calls == (stage == 0 ? 0 : 1) &&
                writer_calls == 0 && open_memstream_calls == 0,
            "required stage failure reached a later stage");
    require_unchanged(records_output, records_capacity, records_length,
                      0x11223344u,
                      "record output changed on required stage failure");
    require_unchanged(recipes_output, recipes_capacity, recipes_length,
                      0x55667788u,
                      "recipe output changed on required stage failure");
    require(memcmp(records, records_before, record_bytes) == 0 &&
                memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "required stage failure changed caller input");
    free(recipes_before);
    free(records_before);
}

static void expect_forced_family_failure_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity,
    int mode, int ordinal, int forced_value) {
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "family-failure input snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    reset_output(records_output, records_capacity, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 0x55667788u);
    reset_interposition();
    if (mode == 0) {
        force_f1_ordinal = ordinal;
        force_f1_result = forced_value;
    }
    if (mode == 1) {
        force_marked_ordinal = ordinal;
        force_marked_result = forced_value;
    }
    if (mode == 2) {
        force_f2_ordinal = ordinal;
        force_f2_result = forced_value;
    }
    if (mode == 3) force_f4_result = 0;
    if (mode == 4) force_score_result = 0;
    if (mode >= 5) force_legal_mode = mode - 4;
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "forced family contradiction was accepted");
    require(writer_calls == 1 && writer_returned == 1 &&
                stream_buffer_free_calls == 1 && stream_owned_buffer == NULL,
            "forced family contradiction bypassed writer lifecycle");
    int target_calls = 0;
    if (mode == 0) target_calls = post_writer_f1_calls;
    if (mode == 1) target_calls = post_writer_marked_calls;
    if (mode == 2) target_calls = post_writer_f2_calls;
    if (mode == 3) target_calls = post_writer_f4_calls;
    if (mode == 4) target_calls = post_writer_score_calls;
    if (mode >= 5) target_calls = post_writer_legal_calls;
    require(target_calls > 0, "forced family seam was not exercised");
    require_unchanged(records_output, records_capacity, records_length,
                      0x11223344u,
                      "record output changed on family contradiction");
    require_unchanged(recipes_output, recipes_capacity, recipes_length,
                      0x55667788u,
                      "recipe output changed on family contradiction");
    require(memcmp(records, records_before, record_bytes) == 0 &&
                memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "family contradiction changed caller input");
    free(recipes_before);
    free(records_before);
}

static void expect_each_row_legal_hash_failure_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity) {
    const size_t record_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    const size_t recipe_bytes =
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "per-row legal-hash snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    for (int row = 0; row < AD_AUTHORED_PROOF_BUNDLE_COUNT; row++) {
        size_t records_length = 0x11223344u;
        size_t recipes_length = 0x55667788u;
        char error[AD_ERROR_CAP];
        reset_output(records_output, records_capacity, &records_length,
                     0x11223344u);
        reset_output(recipes_output, recipes_capacity, &recipes_length,
                     0x55667788u);
        reset_interposition();
        force_legal_mode = 1;
        force_legal_row = row;
        force_legal_call = recipes[row].kind ==
                AD_RECIPE_F3_EXACT_SECOND_HALF_TURN ? 1 : 2;
        require(ad_serialize_authored_sidecars(
                    records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                    recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                    (char*)records_output, records_capacity, &records_length,
                    (char*)recipes_output, recipes_capacity, &recipes_length,
                    error) != 0,
                "per-row legal-hash contradiction was accepted");
        require(expected_legal_match_calls[row] == force_legal_call,
                "targeted legal-hash seam was not exercised");
        require(writer_calls == 1 && writer_returned == 1,
                "per-row legal-hash contradiction bypassed writer lifecycle");
        require_unchanged(records_output, records_capacity, records_length,
                          0x11223344u,
                          "record output changed on legal-hash contradiction");
        require_unchanged(recipes_output, recipes_capacity, recipes_length,
                          0x55667788u,
                          "recipe output changed on legal-hash contradiction");
        require(memcmp(records, records_before, record_bytes) == 0 &&
                    memcmp(recipes, recipes_before, recipe_bytes) == 0,
                "legal-hash contradiction changed caller input");
    }
    free(recipes_before);
    free(records_before);
}

static void expect_adapter_failure_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity,
    int stage) {
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    reset_output(records_output, records_capacity, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 0x55667788u);
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "adapter-failure input snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    reset_interposition();
    force_open_memstream_failure = stage == 0;
    force_fflush_failure = stage == 1;
    force_fclose_failure = stage == 2;
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, records_capacity, &records_length,
                (char*)recipes_output, recipes_capacity, &recipes_length,
                error) != 0,
            "injected memory-stream failure was accepted");
    force_open_memstream_failure = 0;
    force_fflush_failure = 0;
    force_fclose_failure = 0;
    require(open_memstream_calls == 1,
            "memory-stream open failure call count differs");
    require(writer_calls == (stage == 0 ? 0 : 1),
            "memory-stream failure writer count differs");
    require(fflush_calls == (stage == 0 ? 0 : 1),
            "memory-stream failure flush count differs");
    require(fclose_calls == (stage == 0 ? 0 : 1),
            "memory-stream failure close count differs");
    require_unchanged(records_output, records_capacity, records_length,
                      0x11223344u, "record output changed on adapter failure");
    require_unchanged(recipes_output, recipes_capacity, recipes_length,
                      0x55667788u, "recipe output changed on adapter failure");
    require(memcmp(records, records_before, record_bytes) == 0 &&
                memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "adapter failure changed caller input");
    if (stage != 0) {
        require(stream_buffer_free_calls == 1 && stream_owned_buffer == NULL,
                "adapter failure leaked the memory-stream buffer");
    }
    free(recipes_before);
    free(records_before);
}

static void expect_every_allocation_failure_is_atomic(
    const ad_bbs_record* records, const ad_recipe* recipes,
    unsigned char* records_output, size_t records_capacity,
    unsigned char* recipes_output, size_t recipes_capacity) {
    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    char error[AD_ERROR_CAP];
    size_t record_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *records;
    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_bbs_record* records_before = malloc(record_bytes);
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(records_before != NULL && recipes_before != NULL,
            "allocation-failure input snapshot allocation failed");
    memcpy(records_before, records, record_bytes);
    memcpy(recipes_before, recipes, recipe_bytes);
    reset_output(records_output, records_capacity, &records_length,
                 0x11223344u);
    reset_output(recipes_output, recipes_capacity, &recipes_length,
                 0x55667788u);
    reset_interposition();
    allocation_calls = 0;
    fail_allocation_at = 0;
    allocation_test_active = 1;
    int result = ad_serialize_authored_sidecars(
        records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
        recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
        (char*)records_output, records_capacity, &records_length,
        (char*)recipes_output, recipes_capacity, &recipes_length, error);
    allocation_test_active = 0;
    require(result == 0, "allocation-count baseline failed");
    size_t allocation_count = allocation_calls;
    require(allocation_count > 0 && allocation_count <= 64,
            "serializer allocation count exceeds authority bound");

    for (size_t failure = 1; failure <= allocation_count; failure++) {
        reset_output(records_output, records_capacity, &records_length,
                     0x11223344u);
        reset_output(recipes_output, recipes_capacity, &recipes_length,
                     0x55667788u);
        reset_interposition();
        allocation_calls = 0;
        fail_allocation_at = failure;
        allocation_test_active = 1;
        result = ad_serialize_authored_sidecars(
            records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            (char*)records_output, records_capacity, &records_length,
            (char*)recipes_output, recipes_capacity, &recipes_length, error);
        allocation_test_active = 0;
        require(result != 0, "injected allocation failure was accepted");
        require(allocation_calls >= failure,
                "injected allocation failure site was not reached");
        require_unchanged(
            records_output, records_capacity, records_length, 0x11223344u,
            "record output changed on allocation failure");
        require_unchanged(
            recipes_output, recipes_capacity, recipes_length, 0x55667788u,
            "recipe output changed on allocation failure");
        require(memcmp(records, records_before, record_bytes) == 0 &&
                    memcmp(recipes, recipes_before, recipe_bytes) == 0,
                "allocation failure changed caller input");
    }
    fail_allocation_at = 0;
    free(recipes_before);
    free(records_before);
}
#endif

int main(int argc, char** argv) {
    require(argc == 3 || (argc == 4 &&
                (strcmp(argv[3], "public-only") == 0 ||
                 strcmp(argv[3], "f5-reject") == 0)),
            "usage: serializer-probe RECORDS RECIPES [public-only|f5-reject]");
    size_t expected_records_length = 0;
    size_t expected_recipes_length = 0;
    unsigned char* expected_records = read_file(argv[1],
                                                 &expected_records_length);
    unsigned char* expected_recipes = read_file(argv[2],
                                                 &expected_recipes_length);
    require(expected_records_length > 0 && expected_recipes_length > 0,
            "empty expected output");
    unsigned char* records_output = malloc(expected_records_length + 65);
    unsigned char* recipes_output = malloc(expected_recipes_length + 65);
    ad_recipe* recipes = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                sizeof *recipes);
    ad_bbs_record* records = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                    sizeof *records);
    require(records_output != NULL && recipes_output != NULL &&
                recipes != NULL && records != NULL,
            "probe allocation failed");
    char error[AD_ERROR_CAP];
    require(ad_build_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) == 0,
            "proof builder failed");

#if defined(__linux__)
    canonical_writer_records = records;
    canonical_writer_recipes = recipes;
    serializer_active = 1;
#endif

    if (argc == 4) {
        if (strcmp(argv[3], "f5-reject") == 0) {
            expect_transformed_f5_rejection_is_atomic(
                records, recipes, records_output, expected_records_length,
                expected_records_length + 65, recipes_output,
                expected_recipes_length, expected_recipes_length + 65);
        } else {
            expect_success(records, recipes, records_output,
                           expected_records_length,
                           expected_records_length + 65, recipes_output,
                           expected_recipes_length,
                           expected_recipes_length + 65,
                           expected_records, expected_recipes);
        }
#if defined(__linux__)
        serializer_active = 0;
#endif
        free(records);
        free(recipes);
        free(recipes_output);
        free(records_output);
        free(expected_recipes);
        free(expected_records);
        return 0;
    }

    expect_candidate_hash_vectors();
    expect_complete_reconciliation_matrix(records, recipes);
    expect_f5_end_activation_helper(recipes);

    expect_success(records, recipes, records_output, expected_records_length,
                   expected_records_length + 65, recipes_output,
                   expected_recipes_length, expected_recipes_length + 65,
                   expected_records, expected_recipes);
    expect_larger_capacities_preserved(
        records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length,
        expected_records, expected_recipes);
    expect_symmetric_count_capacity_rejections(
        records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, error);
    expect_each_null_role_rejected(
        records, recipes, expected_records_length, expected_recipes_length);
    expect_preflight_rejected_unchanged(
        records, SIZE_MAX, recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
        records_output, expected_records_length, expected_records_length,
        recipes_output, expected_recipes_length, expected_recipes_length,
        error, 1);
    expect_preflight_rejected_unchanged(
        records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
        recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
        records_output, SIZE_MAX, expected_records_length,
        recipes_output, expected_recipes_length, expected_recipes_length,
        error, 1);
    expect_preflight_rejected_unchanged(
        records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
        recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
        records_output, expected_records_length, expected_records_length,
        recipes_output, expected_recipes_length, expected_recipes_length,
        NULL, 0);
    expect_all_alias_pairs_rejected(
        records, recipes, expected_records_length, expected_recipes_length);
    expect_partial_alias_pairs_rejected(
        expected_records_length, expected_recipes_length);
    expect_dynamic_input_extent_aliases_rejected(
        expected_records_length, expected_recipes_length);
    expect_output_capacity_suffix_aliases_rejected(
        records, recipes, expected_records_length, expected_recipes_length);
    expect_joint_dynamic_count_capacity_aliases_rejected(
        expected_records_length, expected_recipes_length);
    expect_short_capacity_aliases_precede_diagnostics(
        expected_records_length, expected_recipes_length);
    expect_every_endpoint_adjacency_allowed(
        records, recipes, expected_records, expected_recipes,
        expected_records_length, expected_recipes_length);
    expect_every_extent_overflow_rejected(
        expected_records_length, expected_recipes_length);
#if defined(__linux__)
    expect_writer_failure_is_atomic(
        records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length);
    for (int mode = 2; mode <= 5; mode++) {
        expect_successful_writer_corruption_is_atomic(
            records, recipes, records_output, expected_records_length,
            recipes_output, expected_recipes_length, mode);
    }
    for (int stage = 0; stage < 2; stage++) {
        expect_required_stage_failure_is_atomic(
            records, recipes, records_output, expected_records_length,
            recipes_output, expected_recipes_length, stage);
    }
    for (int stage = 0; stage < 3; stage++) {
        expect_adapter_failure_is_atomic(
            records, recipes, records_output, expected_records_length,
            recipes_output, expected_recipes_length, stage);
    }
    for (int ordinal = 0; ordinal < 4; ordinal++) {
        expect_forced_family_failure_is_atomic(
            records, recipes, records_output, expected_records_length,
            recipes_output, expected_recipes_length, 0, ordinal, 0);
    }
    for (int ordinal = 0; ordinal < 4; ordinal++) {
        const ad_recipe* recipe = family_recipe_by_ordinal(
            recipes, AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE, ordinal);
        int expected_marked = recipe->capture_pass_carrier_pressure ==
            AD_F1_CARRIER_PRESSURE_MARKED;
        expect_forced_family_failure_is_atomic(
            records, recipes, records_output, expected_records_length,
            recipes_output, expected_recipes_length, 1, ordinal,
            !expected_marked);
    }
    for (int ordinal = 0; ordinal < 4; ordinal++) {
        const ad_recipe* recipe = family_recipe_by_ordinal(
            recipes, AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT, ordinal);
        int forced_count = recipe->capture_handoff_target_bucket ==
            AD_F2_TARGET_COUNT_EXACTLY_ONE ? 2 : 1;
        expect_forced_family_failure_is_atomic(
            records, recipes, records_output, expected_records_length,
            recipes_output, expected_recipes_length, 2, ordinal,
            forced_count);
    }
    for (int mode = 3; mode < 8; mode++) {
        expect_forced_family_failure_is_atomic(
            records, recipes, records_output, expected_records_length,
            recipes_output, expected_recipes_length, mode, -1, 0);
    }
    expect_each_row_legal_hash_failure_is_atomic(
        records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length);
    expect_every_allocation_failure_is_atomic(
        records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length);
#endif

    ad_bbs_record* bad_records = malloc(
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_records);
    ad_recipe* bad_recipes = malloc(
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_recipes);
    require(bad_records != NULL && bad_recipes != NULL,
            "negative input allocation failed");
    memcpy(bad_records, records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_records);
    bad_records[0].recipe = recipes + AD_AUTHORED_PROOF_BUNDLE_COUNT;
    expect_failure_is_atomic(
        bad_records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, 0);
    memcpy(bad_records, records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_records);
    bad_recipes[0] = recipes[0];
    bad_records[0].recipe = &bad_recipes[0];
    expect_failure_is_atomic(
        bad_records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, 0);
    memcpy(bad_records, records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_records);
    bad_records[0].source_id ^= 1u;
    expect_failure_is_atomic(
        bad_records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, 0);
    memcpy(bad_records, records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_records);
    bad_records[0].decision_index++;
    expect_failure_is_atomic(
        bad_records, recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, 0);

    memcpy(bad_recipes, recipes,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_recipes);
    memcpy(bad_records, records,
           AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *bad_records);
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        bad_records[i].recipe = &bad_recipes[i];
    }
    bad_recipes[0].controller_seed ^= 1u;
    expect_failure_is_atomic(
        bad_records, bad_recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, 0);
    bad_recipes[0] = recipes[0];
    bad_recipes[0].actions[0] ^= 1u;
    expect_failure_is_atomic(
        bad_records, bad_recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, 1);
    bad_recipes[0] = recipes[0];
    ((unsigned char*)&bad_recipes[0].captured)[0] ^= 1u;
    expect_failure_is_atomic(
        bad_records, bad_recipes, records_output, expected_records_length,
        recipes_output, expected_recipes_length, 1);
    free(bad_recipes);
    free(bad_records);

    ad_recipe* permuted_recipes = malloc(
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *permuted_recipes);
    ad_bbs_record* permuted_records = malloc(
        AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *permuted_records);
    require(permuted_recipes != NULL && permuted_records != NULL,
            "permutation allocation failed");
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        size_t recipe_index = AD_AUTHORED_PROOF_BUNDLE_COUNT - 1 - i;
        size_t record_index = (i * 7) % AD_AUTHORED_PROOF_BUNDLE_COUNT;
        permuted_recipes[recipe_index] = recipes[i];
        permuted_records[record_index] = records[i];
        permuted_records[record_index].recipe = &permuted_recipes[recipe_index];
    }
    expect_success(permuted_records, permuted_recipes,
                   records_output, expected_records_length,
                   expected_records_length + 65, recipes_output,
                   expected_recipes_length, expected_recipes_length + 65,
                   expected_records, expected_recipes);
    expect_permuted_reconciliation(
        permuted_records, permuted_recipes, records, recipes);

    size_t records_length = 0x11223344u;
    size_t recipes_length = 0x55667788u;
    reset_output(records_output, expected_records_length, &records_length,
                 0x11223344u);
    reset_output(recipes_output, expected_recipes_length, &recipes_length,
                 0x55667788u);
#if defined(__linux__)
    writer_calls = 0;
#endif
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT - 1,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, expected_records_length, &records_length,
                (char*)recipes_output, expected_recipes_length, &recipes_length,
                error) != 0,
            "short record count accepted");
#if defined(__linux__)
    require(writer_calls == 0, "invalid count reached public writer");
#endif
    require_unchanged(records_output, expected_records_length, records_length,
                      0x11223344u, "record output changed on count failure");
    require_unchanged(recipes_output, expected_recipes_length, recipes_length,
                      0x55667788u, "recipe output changed on count failure");

    reset_output(records_output, expected_records_length, &records_length,
                 0x11223344u);
    reset_output(recipes_output, expected_recipes_length, &recipes_length,
                 0x55667788u);
#if defined(__linux__)
    writer_calls = 0;
#endif
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)records_output, expected_records_length - 1,
                &records_length,
                (char*)recipes_output, expected_recipes_length,
                &recipes_length, error) != 0,
            "short output capacity accepted");
#if defined(__linux__)
    require(writer_calls == 0, "short capacity reached public writer");
#endif
    require_unchanged(records_output, expected_records_length, records_length,
                      0x11223344u, "record output changed on capacity failure");
    require_unchanged(recipes_output, expected_recipes_length, recipes_length,
                      0x55667788u, "recipe output changed on capacity failure");

    size_t recipe_bytes = AD_AUTHORED_PROOF_BUNDLE_COUNT * sizeof *recipes;
    ad_recipe* recipes_before = malloc(recipe_bytes);
    require(recipes_before != NULL, "alias snapshot allocation failed");
    memcpy(recipes_before, recipes, recipe_bytes);
#if defined(__linux__)
    writer_calls = 0;
#endif
    require(ad_serialize_authored_sidecars(
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                (char*)recipes, expected_records_length, &records_length,
                (char*)recipes_output, expected_recipes_length,
                &recipes_length, error) != 0,
            "input/output alias accepted");
#if defined(__linux__)
    require(writer_calls == 0, "alias failure reached public writer");
#endif
    require(memcmp(recipes, recipes_before, recipe_bytes) == 0,
            "input changed on alias failure");

    free(recipes_before);
    free(permuted_records);
    free(permuted_recipes);
    free(records);
    free(recipes);
    free(recipes_output);
    free(records_output);
    free(expected_recipes);
    free(expected_records);
#if defined(__linux__)
    serializer_active = 0;
#endif
    return 0;
}

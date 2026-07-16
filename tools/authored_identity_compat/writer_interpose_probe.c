#include "authored_drill.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int __real_ad_authored_fresh_admission_gate(const bb_match* match);
int __real_ad_authored_resumable_admission_gate(const bb_match* match);
int __real_ad_authored_continuation_gate(const bb_match* match,
                                         char error[AD_ERROR_CAP]);

enum {
    EVENT_FRESH = 1,
    EVENT_RESUMABLE = 2,
    EVENT_CONTINUATION = 3,
    MAX_EVENTS = AD_AUTHORED_PROOF_BUNDLE_COUNT * 2,
};

static unsigned char events[MAX_EVENTS];
static size_t event_count;
static size_t force_admission_event;
static size_t force_continuation_event;
static size_t write_count;
static size_t first_write_event_count;

size_t __real_fwrite(const void* ptr, size_t size, size_t count, FILE* stream);

size_t __wrap_fwrite(const void* ptr, size_t size, size_t count, FILE* stream) {
    if (write_count == 0) first_write_event_count = event_count;
    write_count++;
    return __real_fwrite(ptr, size, count, stream);
}

static void event(unsigned char value) {
    if (event_count >= MAX_EVENTS) {
        fputs("writer emitted excess gate calls\n", stderr);
        exit(1);
    }
    events[event_count++] = value;
}

int __wrap_ad_authored_fresh_admission_gate(const bb_match* match) {
    event(EVENT_FRESH);
    if (event_count == force_admission_event) return 0;
    return __real_ad_authored_fresh_admission_gate(match);
}

int __wrap_ad_authored_resumable_admission_gate(const bb_match* match) {
    event(EVENT_RESUMABLE);
    if (event_count == force_admission_event) return 0;
    return __real_ad_authored_resumable_admission_gate(match);
}

int __wrap_ad_authored_continuation_gate(const bb_match* match,
                                         char error[AD_ERROR_CAP]) {
    event(EVENT_CONTINUATION);
    if (event_count == force_continuation_event) {
        snprintf(error, AD_ERROR_CAP, "forced continuation failure");
        return -1;
    }
    return __real_ad_authored_continuation_gate(match, error);
}

static void require(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "%s\n", message);
        exit(1);
    }
}

static void reset_events(void) {
    memset(events, 0, sizeof events);
    event_count = 0;
    force_admission_event = SIZE_MAX;
    force_continuation_event = SIZE_MAX;
    write_count = 0;
    first_write_event_count = SIZE_MAX;
}

static void require_empty(FILE* file) {
    require(fseek(file, 0, SEEK_END) == 0, "failed to seek writer output");
    require(ftell(file) == 0, "failed writer emitted a byte");
}

int main(void) {
    ad_recipe* recipes = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                sizeof *recipes);
    ad_bbs_record* records = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                    sizeof *records);
    require(recipes != NULL && records != NULL, "allocation failed");
    char error[AD_ERROR_CAP];
    require(ad_build_authored_proof_bundle(
                recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                records, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) == 0,
            error);

    reset_events();
    FILE* file = tmpfile();
    require(file != NULL, "tmpfile failed");
    require(ad_bbs_write(file, records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                         error) == 0,
            error);
    require(event_count == MAX_EVENTS, "writer gate call count differs");
    require(write_count > 0, "successful writer made no write calls");
    require(first_write_event_count == MAX_EVENTS,
            "writer emitted bytes before complete batch preflight");
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        unsigned char admission =
            i == AD_AUTHORED_PROOF_BUNDLE_COUNT - 2
                ? EVENT_RESUMABLE : EVENT_FRESH;
        require(events[i * 2] == admission,
                "writer admission kind/order differs");
        require(events[i * 2 + 1] == EVENT_CONTINUATION,
                "writer continuation order differs");
    }
    require(fclose(file) == 0, "fclose failed");

    // The writer accepts arbitrary positive batch counts. Exercise every
    // canonical record at count one so no family/index-selective branch can
    // reserve the real gates for only the fixed 26-record integration batch.
    for (size_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        int nested = i == AD_AUTHORED_PROOF_BUNDLE_COUNT - 2;
        reset_events();
        file = tmpfile();
        require(file != NULL, "tmpfile failed");
        require(ad_bbs_write(file, &records[i], 1, error) == 0,
                "single-record writer unexpectedly failed");
        require(event_count == 2,
                "single-record writer gate call count differs");
        require(events[0] == (nested ? EVENT_RESUMABLE : EVENT_FRESH),
                "single-record writer used wrong admission gate");
        require(events[1] == EVENT_CONTINUATION,
                "single-record writer omitted continuation");
        require(write_count > 0 && first_write_event_count == 2,
                "single-record writer emitted before complete preflight");
        require(fclose(file) == 0, "fclose failed");

        reset_events();
        force_admission_event = 1;
        file = tmpfile();
        require(file != NULL, "tmpfile failed");
        require(ad_bbs_write(file, &records[i], 1, error) != 0,
                "single-record admission failure unexpectedly succeeded");
        require_empty(file);
        require(write_count == 0 && event_count == 1,
                "single-record admission failure reached later work");
        require(events[0] == (nested ? EVENT_RESUMABLE : EVENT_FRESH),
                "single-record admission failure used wrong gate");
        require(fclose(file) == 0, "fclose failed");

        reset_events();
        force_continuation_event = 2;
        file = tmpfile();
        require(file != NULL, "tmpfile failed");
        require(ad_bbs_write(file, &records[i], 1, error) != 0,
                "single-record continuation failure unexpectedly succeeded");
        require_empty(file);
        require(write_count == 0 && event_count == 2,
                "single-record continuation failure reached a write");
        require(events[0] == (nested ? EVENT_RESUMABLE : EVENT_FRESH) &&
                    events[1] == EVENT_CONTINUATION,
                "single-record continuation order differs");
        require(fclose(file) == 0, "fclose failed");
    }

    // These complete-batch positions bind the stronger transaction property:
    // a late gate failure cannot leave even a header or write callback.
    static const size_t failure_indices[] = {0, 12, 24, 25};
    for (size_t failure = 0;
         failure < sizeof failure_indices / sizeof failure_indices[0];
         failure++) {
        size_t i = failure_indices[failure];
        int nested = i == AD_AUTHORED_PROOF_BUNDLE_COUNT - 2;
        reset_events();
        force_admission_event = i * 2 + 1;
        file = tmpfile();
        require(file != NULL, "tmpfile failed");
        require(ad_bbs_write(file, records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                             error) != 0,
                "forced admission unexpectedly succeeded");
        require_empty(file);
        require(write_count == 0,
                "admission failure reached a write callback");
        require(event_count == force_admission_event,
                "admission failure gate count differs");
        require(events[i * 2] == (nested ? EVENT_RESUMABLE : EVENT_FRESH),
                "wrong admission gate called");
        require(fclose(file) == 0, "fclose failed");

        reset_events();
        force_continuation_event = i * 2 + 2;
        file = tmpfile();
        require(file != NULL, "tmpfile failed");
        require(ad_bbs_write(file, records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                             error) != 0,
                "forced continuation unexpectedly succeeded");
        require_empty(file);
        require(write_count == 0,
                "continuation failure reached a write callback");
        require(event_count == force_continuation_event,
                "continuation failure gate call count differs");
        require(events[i * 2] == (nested ? EVENT_RESUMABLE : EVENT_FRESH),
                "wrong admission gate called before continuation");
        require(events[i * 2 + 1] == EVENT_CONTINUATION,
                "continuation gate missing or reordered");
        require(fclose(file) == 0, "fclose failed");
    }

    free(records);
    free(recipes);
    puts("writer gateway interposition verified");
    return 0;
}

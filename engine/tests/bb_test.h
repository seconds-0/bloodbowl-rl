// bb_test.h — minimal single-header test harness for the engine.
//
// Usage:
//   #include "bb_test.h"
//   BB_TEST(rng_is_deterministic) { ... BB_CHECK(x == y); ... }
//   ...
//   int main(void) { return bb_test_run_all(); }
//
// Tests self-register via constructor attributes (clang/gcc).
#ifndef BB_TEST_H
#define BB_TEST_H

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

typedef void (*bb_test_fn)(void);

typedef struct {
    const char* name;
    bb_test_fn fn;
} bb_test_case;

#define BB_TEST_MAX 4096
extern bb_test_case bb_tests[BB_TEST_MAX];
extern int bb_test_count;
extern int bb_test_failures;
extern const char* bb_test_current;

#define BB_TEST(id)                                                       \
    static void bb_test_##id(void);                                       \
    __attribute__((constructor)) static void bb_test_reg_##id(void) {     \
        if (bb_test_count >= BB_TEST_MAX) { /* no silent OOB write */     \
            fprintf(stderr, "bb_test: too many tests (max %d) at %s\n",   \
                    BB_TEST_MAX, #id);                                    \
            abort();                                                      \
        }                                                                 \
        bb_tests[bb_test_count] = (bb_test_case){#id, bb_test_##id};      \
        bb_test_count++;                                                  \
    }                                                                     \
    static void bb_test_##id(void)

#define BB_CHECK(cond)                                                          \
    do {                                                                        \
        if (!(cond)) {                                                          \
            printf("FAIL %s (%s:%d): %s\n", bb_test_current, __FILE__, __LINE__, #cond); \
            bb_test_failures++;                                                 \
        }                                                                       \
    } while (0)

#define BB_CHECK_EQ(a, b)                                                       \
    do {                                                                        \
        long long _a = (long long)(a), _b = (long long)(b);                     \
        if (_a != _b) {                                                         \
            printf("FAIL %s (%s:%d): %s == %s (%lld != %lld)\n", bb_test_current, \
                   __FILE__, __LINE__, #a, #b, _a, _b);                         \
            bb_test_failures++;                                                 \
        }                                                                       \
    } while (0)

#ifdef BB_TEST_MAIN
bb_test_case bb_tests[BB_TEST_MAX];
int bb_test_count = 0;
int bb_test_failures = 0;
const char* bb_test_current = "";

static int bb_test_run_all(const char* filter) {
    int ran = 0;
    for (int i = 0; i < bb_test_count; i++) {
        if (filter && !strstr(bb_tests[i].name, filter)) continue;
        bb_test_current = bb_tests[i].name;
        int before = bb_test_failures;
        bb_tests[i].fn();
        ran++;
        if (bb_test_failures == before) printf("ok   %s\n", bb_tests[i].name);
    }
    printf("%d tests, %d failures\n", ran, bb_test_failures);
    return bb_test_failures ? 1 : 0;
}

int main(int argc, char** argv) {
    return bb_test_run_all(argc > 1 ? argv[1] : 0);
}
#endif // BB_TEST_MAIN

#endif // BB_TEST_H

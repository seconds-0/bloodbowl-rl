# bloodbowl-rl engine build
#
# Targets:
#   make            -> build libbb.a + test runner, run tests
#   make test       -> run unit tests (optionally TEST=<filter>)
#   make asan       -> rebuild + run tests under ASan/UBSan
#   make fuzz       -> build libFuzzer harnesses (clang only)
#   make clean
CC      ?= clang
BUILD   ?= build
CFLAGS  ?= -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include
LDFLAGS ?=

SAN_FLAGS = -fsanitize=address,undefined -fno-omit-frame-pointer -O1

SRC      := $(wildcard engine/src/*.c)
OBJ      := $(SRC:engine/src/%.c=$(BUILD)/obj/%.o)
TEST_SRC := $(wildcard engine/tests/test_*.c)
LIB      := $(BUILD)/libbb.a
TESTBIN  := $(BUILD)/bb_tests
PUFFER_TESTBIN := $(BUILD)/puffer_reward_tests

.PHONY: all test asan fuzz coverage coverage-run lockstep blockev-mc clean

all: test

$(BUILD)/obj/%.o: engine/src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -MMD -MP -c $< -o $@

-include $(OBJ:.o=.d)

# libbb.a is built from ONE relocatable object (ld -r) so constructor-based
# skill registrations are never dropped by archive member selection — plain
# `-lbb` consumers get the full engine (Codex finding).
$(LIB): $(OBJ)
	@mkdir -p $(BUILD)
	ld -r $(OBJ) -o $(BUILD)/bb_all.o
	ar rcs $@ $(BUILD)/bb_all.o

# NOTE: tests link the object files directly (not libbb.a) — skill hook
# registrations live in constructor-only objects that a static archive would
# drop. External consumers of libbb.a must use -force_load / --whole-archive.
$(TESTBIN): $(TEST_SRC) engine/tests/bb_test.h engine/tests/bb_fixtures.h engine/tests/bb_test_main.c $(OBJ)
	$(CC) $(CFLAGS) -Iengine/tests engine/tests/bb_test_main.c $(TEST_SRC) $(OBJ) -o $@ $(LDFLAGS)

$(PUFFER_TESTBIN): puffer/bloodbowl/test_reward_send_off.c puffer/bloodbowl/bloodbowl.h engine/tests/bb_test.h engine/tests/bb_fixtures.h
	$(CC) $(CFLAGS) -Iengine/tests -Ipuffer/bloodbowl -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

test: $(TESTBIN) $(PUFFER_TESTBIN)
	./$(TESTBIN) $(TEST)
	./$(PUFFER_TESTBIN) $(TEST)

blockev-mc: $(OBJ)
	$(CC) $(CFLAGS) -Iengine/tests tools/blockev_mc.c $(OBJ) -o $(BUILD)/blockev_mc -lm
	./$(BUILD)/blockev_mc

asan:
	$(MAKE) BUILD=build/asan CFLAGS="-std=c11 $(SAN_FLAGS) -Wall -Wextra -Werror -Iengine/include" test

# libFuzzer harness. Apple clang has no libFuzzer: use Homebrew LLVM
# (brew install llvm) on macOS, or any stock clang on Linux (CI nightly).
FUZZ_CC ?= $(shell test -x /opt/homebrew/opt/llvm/bin/clang && echo /opt/homebrew/opt/llvm/bin/clang || echo clang)
fuzz:
	@mkdir -p build/fuzz engine/tests/corpus
	$(FUZZ_CC) -std=c11 -O1 -g -fsanitize=fuzzer,address,undefined -Iengine/include \
		engine/tests/fuzz_match.c $(SRC) -o build/fuzz/bb_fuzz
	@echo "run: ./build/fuzz/bb_fuzz -max_total_time=300 engine/tests/corpus/"

# FUMBBL lockstep differential runner (validation layer 7).
# Single-TU build through the PufferLib env amalgamation (bloodbowl.h includes
# every engine .c) so the runner carries the EXACT training encoders for
# --dump-pairs. -Wno-unused-function: the env header defines the full binding
# surface (c_step, c_render, ...); the runner only uses the encoders.
lockstep:
	$(CC) $(CFLAGS) -Ipuffer/bloodbowl -Wno-unused-function \
		tools/bb_lockstep.c -o $(BUILD)/bb_lockstep
	@echo "run: ./$(BUILD)/bb_lockstep validation/lockstep/<id>.jsonl"

# Regenerate golden traces (explicit; goldens change when rules change).
# Links objects directly (constructor-registered skill hooks would be dropped
# from a static archive).
goldens: $(OBJ)
	$(CC) $(CFLAGS) tools/gen_goldens.c $(OBJ) -o $(BUILD)/gen_goldens
	./$(BUILD)/gen_goldens engine/tests/golden

# Coverage counters are compiled in ONLY here (-DBB_COVERAGE): the OpenMP
# training build must not share-write the process-global counters (review P3).
coverage:
	$(MAKE) BUILD=build/coverage \
		CFLAGS="-std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -DBB_COVERAGE" \
		coverage-run

coverage-run: $(OBJ)
	$(CC) $(CFLAGS) tools/coverage_report.c $(OBJ) -o $(BUILD)/coverage_report
	./$(BUILD)/coverage_report

clean:
	rm -rf $(BUILD)

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
ENGINE_HDR := $(wildcard engine/include/bb/*.h)
OBJ      := $(SRC:engine/src/%.c=$(BUILD)/obj/%.o)
TEST_SRC := $(wildcard engine/tests/test_*.c)
SCENARIO_SRC := tools/bank_scenario_predicates.c
SCENARIO_TEST_SRC := $(SCENARIO_SRC) tools/bank_scenario_scan.c
AUTHORED_DRILL_SRC := tools/authored_drill.c
AUTHORED_IDENTITY_SRC := tools/authored_identity.c tools/authored_writer_gates.c
LIB      := $(BUILD)/libbb.a
TESTBIN  := $(BUILD)/bb_tests
PUFFER_REWARD_TESTBIN := $(BUILD)/puffer_reward_tests
PUFFER_CONTACT_TESTBIN := $(BUILD)/puffer_contact_bot_tests
PUFFER_STATE_BANK_TESTBIN := $(BUILD)/puffer_state_bank_tests
PUFFER_STATE_BANK_FIXTURE_WRITER := $(BUILD)/state_bank_fixture_writer
PUFFER_STATE_BANK_CONTRACT_DIR := $(BUILD)/test_state_bank_contract
PUFFER_STATE_BANK_CONTRACT_STAMP := $(PUFFER_STATE_BANK_CONTRACT_DIR)/.generated
PUFFER_STATE_BANK_CONTRACT_TESTBIN := $(BUILD)/puffer_state_bank_contract_tests
PUFFER_STANDALONE_TESTBIN := $(BUILD)/bloodbowl_standalone_test
PUFFER_STATE_BANK_TOOL_TESTBIN := $(BUILD)/bloodbowl_state_bank_tool_test
STATE_BANK_VALIDATE_BIN := $(BUILD)/state_bank_validate
STATE_BANK_VALIDATE_ENV_HASH = $(shell python3 tools/state_bank_contract.py environment-source-sha256 --root puffer/bloodbowl --plain)
PUFFER_OBSERVATION_TESTBIN := $(BUILD)/puffer_observation_tests
BBP_V6_WRITER_TESTBIN := $(BUILD)/bbp_v6_writer_tests
PUFFER_TESTBINS := $(PUFFER_REWARD_TESTBIN) $(PUFFER_CONTACT_TESTBIN) $(PUFFER_STATE_BANK_TESTBIN) $(PUFFER_STATE_BANK_CONTRACT_TESTBIN) $(PUFFER_STANDALONE_TESTBIN) $(PUFFER_STATE_BANK_TOOL_TESTBIN) $(PUFFER_OBSERVATION_TESTBIN) $(BBP_V6_WRITER_TESTBIN)

.PHONY: all test asan fuzz coverage coverage-run lockstep ballstats blockstats human-ball-advancement blockev-mc scenario-scan state-bank-validate clean

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
$(TESTBIN): $(TEST_SRC) $(SCENARIO_TEST_SRC) $(AUTHORED_DRILL_SRC) $(AUTHORED_IDENTITY_SRC) tools/bank_scenario_scan.h tools/authored_drill.h tools/authored_identity_internal.h tools/authored_identity_ledger.def tools/authored_identity_legacy_proof.def engine/tests/bb_test.h engine/tests/bb_fixtures.h engine/tests/bb_test_main.c $(OBJ)
	$(CC) $(CFLAGS) -DBBS_SCANNER_LIBRARY -Iengine/tests -Itools engine/tests/bb_test_main.c $(TEST_SRC) $(SCENARIO_TEST_SRC) $(AUTHORED_DRILL_SRC) $(AUTHORED_IDENTITY_SRC) $(OBJ) -o $@ $(LDFLAGS)

$(PUFFER_REWARD_TESTBIN): puffer/bloodbowl/test_reward_send_off.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/contact_bot.h engine/tests/bb_test.h engine/tests/bb_fixtures.h $(SRC) $(ENGINE_HDR)
	$(CC) $(CFLAGS) -Iengine/tests -Ipuffer/bloodbowl -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

$(PUFFER_CONTACT_TESTBIN): puffer/bloodbowl/test_contact_bot.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/contact_bot.h engine/tests/bb_test.h $(SRC) $(ENGINE_HDR)
	$(CC) $(CFLAGS) -Iengine/tests -Ipuffer/bloodbowl -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

$(PUFFER_STATE_BANK_TESTBIN): puffer/bloodbowl/test_state_bank.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/state_bank_runtime.h puffer/bloodbowl/state_bank_sha256.h puffer/bloodbowl/state_bank_build.h $(AUTHORED_DRILL_SRC) $(AUTHORED_IDENTITY_SRC) tools/authored_drill.h tools/authored_identity_internal.h engine/tests/bb_test.h engine/tests/bb_fixtures.h $(SRC) $(ENGINE_HDR)
	$(CC) $(CFLAGS) -DBBE_STATE_BANK_TESTING -Iengine/tests -Ipuffer/bloodbowl -Itools -Wno-unused-function $< $(AUTHORED_DRILL_SRC) $(AUTHORED_IDENTITY_SRC) -o $@ -lm $(LDFLAGS)

$(PUFFER_STATE_BANK_FIXTURE_WRITER): puffer/bloodbowl/state_bank_fixture_writer.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/state_bank_runtime.h puffer/bloodbowl/state_bank_sha256.h puffer/bloodbowl/state_bank_build.h engine/tests/bb_fixtures.h $(SRC) $(ENGINE_HDR)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -Iengine/tests -Ipuffer/bloodbowl -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

$(PUFFER_STATE_BANK_CONTRACT_STAMP): $(PUFFER_STATE_BANK_FIXTURE_WRITER) tools/generate_state_bank_contract_fixture.py tools/state_bank_contract.py
	@mkdir -p $(PUFFER_STATE_BANK_CONTRACT_DIR)/immutable
	$(PUFFER_STATE_BANK_FIXTURE_WRITER) \
		$(PUFFER_STATE_BANK_CONTRACT_DIR)/immutable/state_bank.bbs \
		$(PUFFER_STATE_BANK_CONTRACT_DIR)/immutable/state_bank.expected.json
	python3 tools/generate_state_bank_contract_fixture.py \
		--bbs $(PUFFER_STATE_BANK_CONTRACT_DIR)/immutable/state_bank.bbs \
		--expectations $(PUFFER_STATE_BANK_CONTRACT_DIR)/immutable/state_bank.expected.json \
		--out-dir $(PUFFER_STATE_BANK_CONTRACT_DIR)
	@touch $@

$(PUFFER_STATE_BANK_CONTRACT_TESTBIN): puffer/bloodbowl/test_state_bank_contract_integration.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/state_bank_runtime.h puffer/bloodbowl/state_bank_sha256.h $(PUFFER_STATE_BANK_CONTRACT_STAMP) $(SRC) $(ENGINE_HDR)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -DBBE_STATE_BANK_TESTING \
		-DBBE_STATE_BANK_BUILD_HEADER='"state_bank_build.generated.h"' \
		-I$(PUFFER_STATE_BANK_CONTRACT_DIR) -Ipuffer/bloodbowl \
		-Wno-unused-function $< -o $@ -lm -pthread $(LDFLAGS)

$(PUFFER_STANDALONE_TESTBIN): puffer/bloodbowl/bloodbowl.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/state_bank_runtime.h puffer/bloodbowl/state_bank_sha256.h puffer/bloodbowl/state_bank_build.h $(SRC) $(ENGINE_HDR)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -Ipuffer/bloodbowl -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

$(PUFFER_STATE_BANK_TOOL_TESTBIN): puffer/bloodbowl/bloodbowl.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/state_bank_runtime.h puffer/bloodbowl/state_bank_sha256.h $(PUFFER_STATE_BANK_CONTRACT_STAMP) $(SRC) $(ENGINE_HDR)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) \
		-DBBE_STATE_BANK_BUILD_HEADER='"state_bank_build.generated.h"' \
		-I$(PUFFER_STATE_BANK_CONTRACT_DIR) -Ipuffer/bloodbowl \
		-Wno-unused-function $< -o $@ -lm $(LDFLAGS)

$(STATE_BANK_VALIDATE_BIN): puffer/bloodbowl/state_bank_validate.c puffer/bloodbowl/bloodbowl.h puffer/bloodbowl/state_bank_runtime.h puffer/bloodbowl/state_bank_sha256.h puffer/bloodbowl/state_bank_build.h tools/state_bank_contract.py $(SRC) $(ENGINE_HDR)
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) \
		-DPUFFER_ENV_SOURCE_HASH='"$(STATE_BANK_VALIDATE_ENV_HASH)"' \
		-Ipuffer/bloodbowl -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

state-bank-validate: $(STATE_BANK_VALIDATE_BIN)
	@echo "$(STATE_BANK_VALIDATE_BIN)"

$(PUFFER_OBSERVATION_TESTBIN): puffer/bloodbowl/test_observation.c puffer/bloodbowl/bloodbowl.h engine/tests/bb_test.h $(SRC) $(ENGINE_HDR)
	$(CC) $(CFLAGS) -Iengine/tests -Ipuffer/bloodbowl -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

$(BBP_V6_WRITER_TESTBIN): tools/test_bbp_v6_writer.c tools/bb_lockstep.c puffer/bloodbowl/bloodbowl.h $(SRC) $(ENGINE_HDR)
	$(CC) $(CFLAGS) -Ipuffer/bloodbowl -Itools -Wno-unused-function $< -o $@ -lm $(LDFLAGS)

test: $(TESTBIN) $(PUFFER_TESTBINS)
	$(TESTBIN) $(TEST)
	$(PUFFER_REWARD_TESTBIN) $(TEST)
	$(PUFFER_CONTACT_TESTBIN) $(TEST)
	$(PUFFER_STATE_BANK_TESTBIN) $(TEST)
	$(PUFFER_STATE_BANK_CONTRACT_TESTBIN)
	$(PUFFER_STANDALONE_TESTBIN) --state-bank-contract
	! $(PUFFER_STANDALONE_TESTBIN) --demo --bank-kind >/dev/null 2>&1
	! $(PUFFER_STANDALONE_TESTBIN) --demo --bank >/dev/null 2>&1
	! $(PUFFER_STANDALONE_TESTBIN) --demo --bank-producer-manifest >/dev/null 2>&1
	! $(PUFFER_STANDALONE_TESTBIN) --demo --bank-contract >/dev/null 2>&1
	python3 tools/test_state_bank_standalone.py \
		--binary $(PUFFER_STATE_BANK_TOOL_TESTBIN) \
		--fixture-dir $(PUFFER_STATE_BANK_CONTRACT_DIR)
	$(PUFFER_OBSERVATION_TESTBIN) $(TEST)
	$(BBP_V6_WRITER_TESTBIN)

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

# FUMBBL human ball-advancement baseline. Replays lockstep JSONL through the
# engine and aggregates the same possession-path metric as the env, but in
# docs/human-baseline.json units (per-game and per-team-turn).
ballstats: $(OBJ)
	$(CC) $(CFLAGS) tools/bb_ballstats.c $(OBJ) -o $(BUILD)/bb_ballstats -lm $(LDFLAGS)
	@echo "run: ./$(BUILD)/bb_ballstats validation/lockstep/<id>.jsonl"

blockstats: $(OBJ)
	$(CC) $(CFLAGS) tools/bb_blockstats.c $(OBJ) -o $(BUILD)/bb_blockstats -lm $(LDFLAGS)
	@echo "run: ./$(BUILD)/bb_blockstats validation/normalized/*.jsonl"

backplay-coverage: tools/bank_backplay_coverage.c
	$(CC) $(CFLAGS) tools/bank_backplay_coverage.c \
		-o $(BUILD)/bank_backplay_coverage $(LDFLAGS) -lm
	@echo "run: ./$(BUILD)/bank_backplay_coverage validation/states/bank.bbs"

scenario-scan: $(OBJ) tools/bank_scenario_scan.c tools/bank_scenario_scan.h $(SCENARIO_SRC) tools/bank_scenario_predicates.h
	$(CC) $(CFLAGS) tools/bank_scenario_scan.c $(SCENARIO_SRC) $(OBJ) \
		-o $(BUILD)/bank_scenario_scan $(LDFLAGS)
	@echo "run: ./$(BUILD)/bank_scenario_scan validation/states/bb2025-strict/bank.bbs"

human-ball-advancement: ballstats
	python3 tools/human_ball_advancement.py --runner ./$(BUILD)/bb_ballstats \
		--input validation/lockstep --output docs/human-ball-advancement.json

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

offense_test: ## rigorous behavioral validation of the scripted offense bot
	cc -std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include -Ipuffer/bloodbowl -Wno-unused-function tools/bb_offense_test.c -o build/bb_offense_test -lm
	./build/bb_offense_test

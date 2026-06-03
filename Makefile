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

.PHONY: all test asan fuzz clean

all: test

$(BUILD)/obj/%.o: engine/src/%.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -MMD -MP -c $< -o $@

-include $(OBJ:.o=.d)

$(LIB): $(OBJ)
	@mkdir -p $(BUILD)
	ar rcs $@ $^

$(TESTBIN): $(TEST_SRC) engine/tests/bb_test.h engine/tests/bb_test_main.c $(LIB)
	$(CC) $(CFLAGS) -Iengine/tests engine/tests/bb_test_main.c $(TEST_SRC) $(LIB) -o $@ $(LDFLAGS)

test: $(TESTBIN)
	./$(TESTBIN) $(TEST)

asan:
	$(MAKE) BUILD=build/asan CFLAGS="-std=c11 $(SAN_FLAGS) -Wall -Wextra -Werror -Iengine/include" test

clean:
	rm -rf $(BUILD)

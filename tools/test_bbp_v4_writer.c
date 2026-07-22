#define _POSIX_C_SOURCE 200809L

#define main bb_lockstep_cli_main
#include "bb_lockstep.c"
#undef main

#include <assert.h>
#include <unistd.h>

static uint32_t read_u32(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int main(void) {
    runner context_runner = {0};
    char long_context[1024];
    memset(long_context, 'x', sizeof long_context - 1);
    long_context[sizeof long_context - 1] = '\0';
    ctx_push(&context_runner, long_context);
    assert(context_runner.ctx_n == 1);
    assert(strlen(context_runner.ctx[0]) == sizeof context_runner.ctx[0] - 1);

    char path[] = "/tmp/bbp-v4-writer-XXXXXX";
    int fd = mkstemp(path);
    assert(fd >= 0);
    close(fd);

    memset(&PD, 0, sizeof PD);
    pd_open(path);
    PD.replay_id = 123;
    PD.env.match.status = BB_STATUS_DECISION;
    PD.env.match.decision_team = BB_HOME;
    PD.env.n_legal = 3;
    PD.env.legal[0] = (bb_action){BB_A_SPECIAL_TARGET, 0, 2, 4};
    PD.env.legal[1] = (bb_action){BB_A_SPECIAL_TARGET, 1, 9, 11};
    PD.env.legal[2] = (bb_action){BB_A_END_TURN, 0, 0, 0};
    bbe_fill_mask(&PD.env, BB_HOME);

    pd_stage_prepared(&PD.env, BB_HOME, PD.env.legal[0], 7);
    pd_commit();
    pd_stage_prepared(&PD.env, BB_HOME, PD.env.legal[2], 8);
    pd_commit();
    assert(fclose(PD.f) == 0);
    PD.f = NULL;

    FILE* f = fopen(path, "rb");
    assert(f != NULL);
    const size_t rec_size = 12 + BBE_OBS_SIZE + BBE_MASK_SIZE + 4;
    const size_t file_size = 16 + 2 * rec_size;
    uint8_t* bytes = malloc(file_size);
    assert(bytes != NULL);
    assert(fread(bytes, 1, file_size, f) == file_size);
    assert(fgetc(f) == EOF);
    fclose(f);
    unlink(path);

    assert(memcmp(bytes, "BBP1", 4) == 0);
    assert(read_u32(bytes + 4) == 4);
    assert(read_u32(bytes + 8) == BBE_OBS_SIZE);
    assert(read_u32(bytes + 12) == BBE_MASK_SIZE);

    const size_t mask_off = 16 + 12 + BBE_OBS_SIZE;
    const uint8_t* first_mask = bytes + mask_off;
    const uint8_t* first_target = first_mask + BBE_MASK_SIZE;
    assert(first_target[0] == BB_A_SPECIAL_TARGET);
    assert(first_target[1] == 0);
    assert(read_u32((uint8_t[]){first_target[2], first_target[3], 0, 0}) ==
           4 * BB_PITCH_LEN + 2);
    assert(first_mask[BB_A_SPECIAL_TARGET] == 1);
    assert(first_mask[BB_A_END_TURN] == 1);
    assert(first_mask[BBE_HEAD_TYPE + 0] == 1);
    assert(first_mask[BBE_HEAD_TYPE + 1] == 1);
    assert(first_mask[BBE_HEAD_TYPE + 32] == 0);
    assert(first_mask[BBE_HEAD_TYPE + BBE_HEAD_ARG +
                      4 * BB_PITCH_LEN + 2] == 1);
    assert(first_mask[BBE_HEAD_TYPE + BBE_HEAD_ARG +
                      11 * BB_PITCH_LEN + 9] == 0);

    const uint8_t* second = bytes + 16 + rec_size;
    const uint8_t* second_mask = second + 12 + BBE_OBS_SIZE;
    const uint8_t* second_target = second_mask + BBE_MASK_SIZE;
    assert(second_target[0] == BB_A_END_TURN);
    assert(second_target[1] == 32);
    assert((uint16_t)(second_target[2] | (second_target[3] << 8)) == 390);
    int arg_bits = 0, square_bits = 0;
    for (int i = 0; i < BBE_HEAD_ARG; i++)
        arg_bits += second_mask[BBE_HEAD_TYPE + i] != 0;
    for (int i = 0; i < BBE_HEAD_SQ; i++)
        square_bits += second_mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + i] != 0;
    assert(arg_bits == 1 && second_mask[BBE_HEAD_TYPE + 32] == 1);
    assert(square_bits == 1 &&
           second_mask[BBE_HEAD_TYPE + BBE_HEAD_ARG + 390] == 1);

    free(bytes);
    puts("bbp v4 writer: conditional masks and inactive targets verified");
    return 0;
}

// cpu5_logits.c -- PufferLib 5.0 CPU network forward on a recorded obs trace.
//
// Uses src/puffercpu.c from the pinned 5.0 tree as a library (no
// PUFFERCPU_EVAL_MAIN): load_weights, make_puffernet, mingru_zero_term,
// linear, mingru. Weight order is the 5.0 reg_params order (encoder, decoder
// with the value row last, MinGRU layers), which is also the 4.0 order
// (training/convert_checkpoint.py cuda_layout).
//
// Usage: cpu5_logits CHECKPOINT.bin TRACE.bin OUT.bin
//
// Output format (little-endian):
//   char magic[8] = "BBLOG5v1"
//   uint32 steps, uint32 agents, uint32 cols (= 454 logits + 1 value)
//   per step: float32 out[agents * cols]
#include "puffercpu.c"

#define OBS_SIZE 2782
#define HIDDEN 512
#define LAYERS 3
#define AGENTS 2

static int align8(int n) {
    return (n + 7) & ~7;
}

int main(int argc, char** argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s CHECKPOINT.bin TRACE.bin OUT.bin\n", argv[0]);
        return 2;
    }
    int act_sizes[] = {30, 33, 391};
    int num_actions = 3;
    int atn_sum = 30 + 33 + 391;
    int cols = atn_sum + 1;

    Weights* weights = load_weights(argv[1]);
    if (!weights) {
        perror(argv[1]);
        return 1;
    }
    int file_floats = weights->size - 7;
    int need = 0;
    need = align8(need + HIDDEN * OBS_SIZE);
    need = align8(need + cols * HIDDEN);
    for (int l = 0; l < LAYERS; l++) need = align8(need + 3 * HIDDEN * HIDDEN);
    if (!(need - file_floats <= 7 && file_floats <= need)) {
        fprintf(stderr, "weight count mismatch: file=%d need=%d\n", file_floats, need);
        return 1;
    }

    PufferNet* net = make_puffernet(weights, AGENTS, OBS_SIZE, HIDDEN, LAYERS,
                                    act_sizes, num_actions);
    if (weights->idx != need) {
        fprintf(stderr, "net consumed %d floats, expected %d\n", weights->idx, need);
        return 1;
    }

    FILE* in = fopen(argv[2], "rb");
    if (!in) {
        perror(argv[2]);
        return 1;
    }
    char magic[8];
    uint32_t header[4];
    if (fread(magic, 1, 8, in) != 8 || memcmp(magic, "BBOBSTR1", 8) != 0 ||
        fread(header, sizeof(uint32_t), 4, in) != 4) {
        fprintf(stderr, "bad trace header\n");
        return 1;
    }
    uint32_t steps = header[0];
    if (header[1] != OBS_SIZE || header[2] != AGENTS) {
        fprintf(stderr, "trace obs_size=%u agents=%u, expected %d/%d\n",
                header[1], header[2], OBS_SIZE, AGENTS);
        return 1;
    }

    FILE* out = fopen(argv[3], "wb");
    if (!out) {
        perror(argv[3]);
        return 1;
    }
    uint32_t out_header[3] = {steps, AGENTS, (uint32_t)cols};
    fwrite("BBLOG5v1", 1, 8, out);
    fwrite(out_header, sizeof(uint32_t), 3, out);

    static uint8_t obs_u8[AGENTS * OBS_SIZE];
    static float obs_f[AGENTS * OBS_SIZE];
    float terms[AGENTS];
    for (uint32_t t = 0; t < steps; t++) {
        if (fread(obs_u8, 1, sizeof obs_u8, in) != sizeof obs_u8 ||
            fread(terms, sizeof(float), AGENTS, in) != AGENTS) {
            fprintf(stderr, "truncated trace at step %u\n", t);
            return 1;
        }
        for (int i = 0; i < AGENTS * OBS_SIZE; i++) obs_f[i] = (float)obs_u8[i];
        // Same order as forward_puffernet, minus the sampling tail.
        mingru_zero_term(net->mingru, terms);
        linear(net->encoder, obs_f);
        mingru(net->mingru, net->encoder->output);
        linear(net->decoder, net->mingru->output);
        fwrite(net->decoder->output, sizeof(float), (size_t)AGENTS * cols, out);
    }
    fclose(in);
    fclose(out);
    printf("cpu5_logits steps=%u file_floats=%d need=%d\n", steps, file_floats, need);
    free_puffernet(net);
    free(weights);
    return 0;
}

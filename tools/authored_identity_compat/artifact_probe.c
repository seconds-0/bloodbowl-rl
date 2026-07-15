#include "authored_drill.h"
#include "bb/gen_skills.h"
#include "bb/gen_teams.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void die(const char* message) {
    perror(message);
    exit(1);
}

static void put_bytes(FILE* out, const void* data, size_t size) {
    if (fwrite(data, 1, size, out) != size) die("fwrite");
}

static void put_u32(FILE* out, uint32_t value) {
    uint8_t data[4] = {
        (uint8_t)value,
        (uint8_t)(value >> 8),
        (uint8_t)(value >> 16),
        (uint8_t)(value >> 24),
    };
    put_bytes(out, data, sizeof data);
}

static FILE* open_output(const char* directory, const char* filename) {
    char path[4096];
    int length = snprintf(path, sizeof path, "%s/%s", directory, filename);
    if (length < 0 || (size_t)length >= sizeof path) {
        fputs("artifact output path is too long\n", stderr);
        exit(1);
    }
    FILE* out = fopen(path, "wb");
    if (out == NULL) die(path);
    return out;
}

static void close_output(FILE* out) {
    if (fclose(out) != 0) die("fclose");
}

int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s OUTPUT_DIRECTORY\n", argv[0]);
        return 2;
    }
    ad_recipe* recipes = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                sizeof *recipes);
    ad_bbs_record* records = calloc(AD_AUTHORED_PROOF_BUNDLE_COUNT,
                                    sizeof *records);
    if (recipes == NULL || records == NULL) die("calloc");
    char error[AD_ERROR_CAP];
    if (ad_build_authored_proof_bundle(
            recipes, AD_AUTHORED_PROOF_BUNDLE_COUNT,
            records, AD_AUTHORED_PROOF_BUNDLE_COUNT, error) != 0) {
        fprintf(stderr, "builder failed: %s\n", error);
        return 1;
    }

    FILE* independent = open_output(argv[1], "independent.bbs");
    put_bytes(independent, "BBS1", 4);
    put_u32(independent, 1);
    put_u32(independent, (uint32_t)sizeof(bb_match));
    put_u32(independent,
            (uint32_t)sizeof(bb_match) * UINT32_C(2654435761) ^
                ((uint32_t)BB_TEAM_COUNT << 20) ^
                ((uint32_t)BB_SKILL_COUNT << 10) ^
                (uint32_t)BB_A_TYPE_COUNT);
    FILE* raw = open_output(argv[1], "raw.bin");
    for (uint32_t i = 0; i < AD_AUTHORED_PROOF_BUNDLE_COUNT; i++) {
        const bb_match* match = &recipes[i].captured;
        put_u32(independent, UINT32_C(0xA9000000) + i);
        put_u32(independent, (uint32_t)recipes[i].action_count);
        uint8_t metadata[4] = {
            match->half,
            match->turn[match->active_team],
            0,
            0,
        };
        put_bytes(independent, metadata, sizeof metadata);
        put_bytes(independent, match, sizeof *match);
        put_bytes(raw, match, sizeof *match);
    }
    close_output(independent);
    close_output(raw);

    FILE* writer = open_output(argv[1], "writer.bbs");
    if (ad_bbs_write(writer, records, AD_AUTHORED_PROOF_BUNDLE_COUNT,
                     error) != 0) {
        fprintf(stderr, "writer failed: %s\n", error);
        return 1;
    }
    close_output(writer);
    free(records);
    free(recipes);
    return 0;
}

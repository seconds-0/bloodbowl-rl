// Shared trace writer for the 4.0 <-> 5.0 env parity drivers.
//
// Both drivers step the same env configuration with the same deterministic
// action choice (a hash of seed, step and row indexing into the packed exact
// joint support) and write:
//   header: "BBPT", u32 version, u32 agents, u32 steps, u32 obs_size
//   per step (state BEFORE the step's actions):
//     u32 step, obs bytes (agents*obs_size), f32 rewards[agents],
//     f32 terminals[agents], i32 counts[agents], then for each row its
//     u32 packed support tuples
//   footer: u32 log_floats, f32 summed Log over all envs
// plus one FNV-1a line per step on stdout.
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint64_t pt_fnv_bytes(uint64_t h, const void* p, size_t n) {
    const unsigned char* b = (const unsigned char*)p;
    for (size_t i = 0; i < n; i++) {
        h ^= b[i];
        h *= 1099511628211ULL;
    }
    return h;
}

static uint64_t pt_mix(uint64_t x) {
    x += 0x9E3779B97F4A7C15ULL;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

static void pt_write(FILE* fp, const void* p, size_t n) {
    if (fwrite(p, 1, n, fp) != n) {
        perror("trace write");
        exit(2);
    }
}

static void pt_header(FILE* fp, uint32_t agents, uint32_t steps, uint32_t obs_size) {
    uint32_t v[4] = {1, agents, steps, obs_size};
    pt_write(fp, "BBPT", 4);
    pt_write(fp, v, sizeof v);
}

// Records one step and fills actions from the support. Returns the step FNV.
static uint64_t pt_step(FILE* fp, uint32_t step, uint64_t seed, int agents,
        int obs_size, const uint8_t* obs, const float* rewards,
        const float* terminals, const uint32_t* joint, const int* offsets,
        const int* counts, float* actions) {
    uint64_t h = 1469598103934665603ULL;
    pt_write(fp, &step, sizeof step);
    pt_write(fp, obs, (size_t)agents * (size_t)obs_size);
    pt_write(fp, rewards, (size_t)agents * sizeof(float));
    pt_write(fp, terminals, (size_t)agents * sizeof(float));
    pt_write(fp, counts, (size_t)agents * sizeof(int));
    h = pt_fnv_bytes(h, obs, (size_t)agents * (size_t)obs_size);
    h = pt_fnv_bytes(h, rewards, (size_t)agents * sizeof(float));
    h = pt_fnv_bytes(h, terminals, (size_t)agents * sizeof(float));
    for (int row = 0; row < agents; row++) {
        const uint32_t* support = joint + offsets[row];
        pt_write(fp, support, (size_t)counts[row] * sizeof(uint32_t));
        h = pt_fnv_bytes(h, &counts[row], sizeof(int));
        h = pt_fnv_bytes(h, support, (size_t)counts[row] * sizeof(uint32_t));
        if (counts[row] <= 0) {
            fprintf(stderr, "row %d has empty support at step %u\n", row, step);
            exit(3);
        }
        uint64_t k = pt_mix(seed ^ pt_mix(((uint64_t)step << 20) | (uint64_t)row))
            % (uint64_t)counts[row];
        uint32_t packed = support[k];
        for (int hd = 0; hd < 3; hd++) {
            actions[row * 3 + hd] = (float)((packed >> (10 * hd)) & 1023u);
        }
    }
    return h;
}

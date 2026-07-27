#ifndef BBE_STATE_BANK_SHA256_H
#define BBE_STATE_BANK_SHA256_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct {
    uint32_t h[8];
    uint64_t bytes;
    uint8_t block[64];
    size_t used;
} bbe_sha256;

static uint32_t bbe_sha256_rotr(uint32_t value, unsigned shift) {
    return (value >> shift) | (value << (32u - shift));
}

static uint32_t bbe_sha256_be32(const uint8_t* p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static void bbe_sha256_compress(bbe_sha256* ctx, const uint8_t block[64]) {
    static const uint32_t k[64] = {
        0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u,
        0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
        0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u,
        0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
        0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
        0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
        0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
        0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
        0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u,
        0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
        0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u,
        0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
        0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u,
        0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
        0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
        0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u,
    };
    uint32_t w[64];
    for (int i = 0; i < 16; i++) w[i] = bbe_sha256_be32(block + 4 * i);
    for (int i = 16; i < 64; i++) {
        uint32_t x = w[i - 15];
        uint32_t y = w[i - 2];
        uint32_t s0 = bbe_sha256_rotr(x, 7) ^ bbe_sha256_rotr(x, 18) ^
                      (x >> 3);
        uint32_t s1 = bbe_sha256_rotr(y, 17) ^ bbe_sha256_rotr(y, 19) ^
                      (y >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }

    uint32_t a = ctx->h[0], b = ctx->h[1], c = ctx->h[2], d = ctx->h[3];
    uint32_t e = ctx->h[4], f = ctx->h[5], g = ctx->h[6], h = ctx->h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t s1 = bbe_sha256_rotr(e, 6) ^ bbe_sha256_rotr(e, 11) ^
                      bbe_sha256_rotr(e, 25);
        uint32_t choose = (e & f) ^ (~e & g);
        uint32_t t1 = h + s1 + choose + k[i] + w[i];
        uint32_t s0 = bbe_sha256_rotr(a, 2) ^ bbe_sha256_rotr(a, 13) ^
                      bbe_sha256_rotr(a, 22);
        uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = s0 + majority;
        h = g;
        g = f;
        f = e;
        e = d + t1;
        d = c;
        c = b;
        b = a;
        a = t1 + t2;
    }
    ctx->h[0] += a;
    ctx->h[1] += b;
    ctx->h[2] += c;
    ctx->h[3] += d;
    ctx->h[4] += e;
    ctx->h[5] += f;
    ctx->h[6] += g;
    ctx->h[7] += h;
}

static void bbe_sha256_init(bbe_sha256* ctx) {
    static const uint32_t initial[8] = {
        0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
        0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u,
    };
    memcpy(ctx->h, initial, sizeof initial);
    ctx->bytes = 0;
    ctx->used = 0;
}

static void bbe_sha256_update(bbe_sha256* ctx, const void* data, size_t len) {
    const uint8_t* p = (const uint8_t*)data;
    ctx->bytes += (uint64_t)len;
    while (len != 0) {
        size_t room = sizeof ctx->block - ctx->used;
        size_t take = len < room ? len : room;
        memcpy(ctx->block + ctx->used, p, take);
        ctx->used += take;
        p += take;
        len -= take;
        if (ctx->used == sizeof ctx->block) {
            bbe_sha256_compress(ctx, ctx->block);
            ctx->used = 0;
        }
    }
}

static void bbe_sha256_final(bbe_sha256* ctx, uint8_t out[32]) {
    uint64_t bit_length = ctx->bytes * 8u;
    ctx->block[ctx->used++] = 0x80;
    if (ctx->used > 56) {
        memset(ctx->block + ctx->used, 0, 64 - ctx->used);
        bbe_sha256_compress(ctx, ctx->block);
        ctx->used = 0;
    }
    memset(ctx->block + ctx->used, 0, 56 - ctx->used);
    for (int i = 0; i < 8; i++) {
        ctx->block[63 - i] = (uint8_t)(bit_length >> (8 * i));
    }
    bbe_sha256_compress(ctx, ctx->block);
    for (int i = 0; i < 8; i++) {
        out[4 * i] = (uint8_t)(ctx->h[i] >> 24);
        out[4 * i + 1] = (uint8_t)(ctx->h[i] >> 16);
        out[4 * i + 2] = (uint8_t)(ctx->h[i] >> 8);
        out[4 * i + 3] = (uint8_t)ctx->h[i];
    }
    memset(ctx, 0, sizeof *ctx);
}

static void bbe_sha256_bytes(const void* data, size_t len, uint8_t out[32]) {
    bbe_sha256 ctx;
    bbe_sha256_init(&ctx);
    bbe_sha256_update(&ctx, data, len);
    bbe_sha256_final(&ctx, out);
}

static void bbe_sha256_hex(const uint8_t digest[32], char out[65]) {
    static const char alphabet[] = "0123456789abcdef";
    for (int i = 0; i < 32; i++) {
        out[2 * i] = alphabet[digest[i] >> 4];
        out[2 * i + 1] = alphabet[digest[i] & 15u];
    }
    out[64] = '\0';
}

static int bbe_sha256_valid_hex(const char* text) {
    if (text == NULL) return 0;
    for (int i = 0; i < 64; i++) {
        char c = text[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return 0;
    }
    return text[64] == '\0';
}

static int bbe_sha256_matches(const uint8_t digest[32], const char* expected) {
    char actual[65];
    if (!bbe_sha256_valid_hex(expected)) return 0;
    bbe_sha256_hex(digest, actual);
    return memcmp(actual, expected, sizeof actual) == 0;
}

#endif

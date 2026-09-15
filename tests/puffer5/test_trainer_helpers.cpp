// Host unit tests for the PufferLib 5.0 port's trainer helpers:
//   src/exact_joint.h    (patch 0002, exact sequential joint masks)
//   src/train_rows.h     (patch 0003, learner-row gather excludes frozen rows)
//   src/scripted_bank.h  (patch 0006, scripted bank forward skip keying)
//   src/masked_softmax.h (patch 0009, disabled categories excluded)
//   algo.cu NaN guard predicates are exercised through puf_ppo_* in
//   src/ppo_guard.h      (patch 0005)
//
// Build: clang++ -std=c++17 -O1 -I<puffer5 tree>/src test_trainer_helpers.cpp -o t && ./t
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <set>
#include <vector>

#define __host__
#define __device__
typedef float precision_t;
#define from_float(x) (x)
#define to_float(x) (x)
#include "exact_joint.h"
#include "masked_softmax.h"
#include "ppo_guard.h"
#include "scripted_bank.h"
#include "train_rows.h"

static int failures = 0;
#define CHECK(cond, ...) do { if (!(cond)) { failures++; \
    fprintf(stderr, "FAIL %s:%d: ", __FILE__, __LINE__); \
    fprintf(stderr, __VA_ARGS__); fprintf(stderr, "\n"); } } while (0)

static uint32_t pack(int t, int a, int s) {
    return (uint32_t)t | ((uint32_t)a << 10) | ((uint32_t)s << 20);
}

// Reference: the torch sample_joint_logits prefix filter, written independently.
static std::set<int> ref_support(const std::vector<uint32_t>& sup, int h, const int* sel) {
    std::set<int> out;
    for (uint32_t p : sup) {
        bool ok = true;
        for (int q = 0; q < h; ++q) {
            ok = ok && (int)((p >> (10 * q)) & 1023) == sel[q];
        }
        if (ok) out.insert((int)((p >> (10 * h)) & 1023));
    }
    return out;
}

static void test_exact_joint() {
    const int sizes[3] = {30, 33, 391};
    std::vector<uint32_t> sup = {
        pack(3, 0, 17), pack(3, 0, 18), pack(3, 5, 17), pack(4, 32, 390),
        pack(7, 1, 100), pack(7, 2, 100), pack(7, 2, 101), pack(29, 32, 0),
    };
    // Every tuple in support, sequentially: masks must equal the reference.
    for (uint32_t chosen : sup) {
        float sel[3] = {0, 0, 0};
        for (int h = 0; h < 3; ++h) {
            std::vector<float> mask(sizes[h], -1.0f);
            int enabled = puf_joint_fill_head_mask(sup.data(), (int)sup.size(), h,
                sel, sizes[h], mask.data());
            int isel[3] = {(int)sel[0], (int)sel[1], (int)sel[2]};
            std::set<int> ref = ref_support(sup, h, isel);
            CHECK(enabled == (int)ref.size(), "head %d enabled %d ref %zu", h, enabled, ref.size());
            for (int a = 0; a < sizes[h]; ++a) {
                CHECK((mask[a] != 0.0f) == (ref.count(a) == 1), "head %d value %d", h, a);
            }
            int v = (int)((chosen >> (10 * h)) & 1023);
            CHECK(mask[v] == 1.0f, "chosen value %d not enabled at head %d", v, h);
            sel[h] = (float)v;
        }
    }
    // Waiting-coach sentinel: singleton support gives singleton masks.
    std::vector<uint32_t> none = {pack(0, 32, 390)};
    float sel[3] = {0, 32, 390};
    for (int h = 0; h < 3; ++h) {
        std::vector<float> mask(sizes[h], 0.0f);
        CHECK(puf_joint_fill_head_mask(none.data(), 1, h, sel, sizes[h], mask.data()) == 1,
            "sentinel head %d not singleton", h);
    }
    // Duplicate head values count once; an earlier mismatch hides later heads.
    std::vector<uint32_t> dup = {pack(1, 2, 3), pack(1, 2, 4), pack(2, 2, 5)};
    float s1[3] = {1, 2, 0};
    std::vector<float> m1(33, 0.0f);
    CHECK(puf_joint_fill_head_mask(dup.data(), 3, 1, s1, 33, m1.data()) == 1, "duplicate arg");
    std::vector<float> m2(391, 0.0f);
    CHECK(puf_joint_fill_head_mask(dup.data(), 3, 2, s1, 391, m2.data()) == 2, "square | type,arg");
    CHECK(m2[5] == 0.0f, "square from other type leaked");
    // Stale mask contents are cleared.
    std::vector<float> stale(30, 1.0f);
    float s0[3] = {0, 0, 0};
    puf_joint_fill_head_mask(dup.data(), 3, 0, s0, 30, stale.data());
    CHECK(stale[0] == 0.0f && stale[1] == 1.0f && stale[2] == 1.0f && stale[3] == 0.0f,
        "stale mask not cleared");
}

static void test_train_rows() {
    // Chain 30 layout: 2 buffers x 1024 rows, 536 learner rows per buffer.
    const int apb = 1024, buffers = 2, primary = 536, mb_segs = 256;
    const int total_agents = apb * buffers;
    const int eligible = buffers * primary;
    CHECK(puf_train_pad_rows(eligible, mb_segs, 8) == 208, "rr 1.0 pad %d",
        puf_train_pad_rows(eligible, mb_segs, 8));
    CHECK(puf_train_pad_rows(eligible, mb_segs, 2) == 0, "rr 0.25 pad");
    // Review case: 1920 eligible rows at 8 steps x 256 rows reach offset 1792,
    // so 128 pad rows suffice and 2048 rows fit (the old whole-minibatch pad refused it).
    CHECK(puf_train_pad_rows(1920, 256, 8) == 128, "1920-row pad %d",
        puf_train_pad_rows(1920, 256, 8));
    for (double rr : {1.0, 0.25}) {
        int total_mb = (int)(rr * total_agents * 64 / (mb_segs * 64));
        int rows = eligible + puf_train_pad_rows(eligible, mb_segs, total_mb);
        CHECK(rows <= total_agents, "rows %d exceed capacity", rows);
        std::vector<int> visits(total_agents, 0);
        const int epochs = 12;
        for (long epoch = 0; epoch < epochs; ++epoch) {
            std::vector<int> map(rows);
            long start = puf_train_epoch_start(epoch, total_mb, mb_segs, eligible);
            puf_fill_train_row_map(map.data(), rows, eligible, primary, apb, start);
            for (int r = 0; r < rows; ++r) {
                int phys = map[r];
                CHECK(phys >= 0 && phys < total_agents, "row out of range");
                CHECK(phys % apb < primary, "frozen row %d gathered", phys);
            }
            for (int mb = 0; mb < total_mb; ++mb) {
                int off = (mb * mb_segs) % eligible;
                CHECK(off + mb_segs <= rows, "slice [%d,%d) escapes %d rows", off, off + mb_segs, rows);
                for (int i = 0; i < mb_segs; ++i) visits[map[off + i]]++;
            }
        }
        long seen = 0, frozen_seen = 0, min_v = 1 << 30, max_v = 0;
        for (int phys = 0; phys < total_agents; ++phys) {
            if (phys % apb < primary) {
                seen += visits[phys] > 0;
                min_v = visits[phys] < min_v ? visits[phys] : min_v;
                max_v = visits[phys] > max_v ? visits[phys] : max_v;
            } else {
                frozen_seen += visits[phys];
            }
        }
        CHECK(frozen_seen == 0, "rr %.2f: frozen rows trained %ld times", rr, frozen_seen);
        CHECK(seen == eligible, "rr %.2f: only %ld of %d learner rows visited", rr, seen, eligible);
        printf("train_rows rr=%.2f epochs=%d steps/epoch=%d learner visits min=%ld max=%ld\n",
            rr, epochs, total_mb, min_v, max_v);
    }
    // No frozen policies: identity rows, no pad.
    CHECK(puf_train_pad_rows(2048, 256, 8) == 0, "no pad expected");
    std::vector<int> id(2048);
    puf_fill_train_row_map(id.data(), 2048, 2048, 1024, 1024, 0);
    for (int r = 0; r < 2048; ++r) CHECK(id[r] == r, "identity map broken at %d", r);
}

static void test_scripted_bank() {
    CHECK(puf_scripted_skip_policy(1, 1, 4, 5) == 4, "chain 30 bank");
    CHECK(puf_scripted_skip_policy(0, 1, 4, 5) == 0, "no scripted opponent");
    CHECK(puf_scripted_skip_policy(1, 0, 4, 5) == 0, "HOME bot seat is not a bank seat");
    CHECK(puf_scripted_skip_policy(1, 1, 0, 5) == 0, "global scripted mode");
    CHECK(puf_scripted_skip_policy(1, 1, 5, 5) == 0, "tag beyond banks");
    CHECK(puf_scripted_skip_policy(1, 1, 1, 2) == 1, "single bank");
}

static void test_ppo_guard() {
    CHECK(puf_ppo_ratio_logratio(0.5f) == 0.5f, "in-range logratio");
    CHECK(puf_ppo_ratio_logratio(50.0f) == 10.0f, "clamp high");
    CHECK(puf_ppo_ratio_logratio(-50.0f) == -10.0f, "clamp low");
    CHECK(std::isfinite(std::exp(puf_ppo_ratio_logratio(1e30f))), "exp overflow");
    CHECK(puf_ppo_element_finite(0.1f, -0.2f, 1.0f, 0.3f, 0.4f, 0.5f), "finite element");
    CHECK(!puf_ppo_element_finite(NAN, -0.2f, 1.0f, 0.3f, 0.4f, 0.5f), "nan new logp");
    CHECK(!puf_ppo_element_finite(0.1f, -INFINITY, 1.0f, 0.3f, 0.4f, 0.5f), "inf old logp");
    CHECK(!puf_ppo_element_finite(0.1f, 0.2f, NAN, 0.3f, 0.4f, 0.5f), "nan advantage");
    CHECK(!puf_ppo_element_finite(0.1f, 0.2f, 0.3f, INFINITY, 0.4f, 0.5f), "inf value");
    CHECK(puf_muon_norm_ok(4.0f), "finite norm");
    CHECK(!puf_muon_norm_ok(NAN), "nan norm");
    CHECK(!puf_muon_norm_ok(INFINITY), "inf norm");
    CHECK(!puf_muon_norm_ok(-1.0f), "negative norm");
}

static void test_masked_softmax() {
    // Review counterexample: singleton support whose legal logit is -1e4.
    // With a -1e4 substitute every disabled category took probability 1/30.
    const int A = 30;
    std::vector<float> logits(A, -10000.0f), mask(A, 0.0f), cache(A);
    mask[7] = 1.0f;
    float lse = puf_masked_logsumexp(logits.data(), 0, 0, A, mask.data(), 0, cache.data());
    CHECK(std::fabs((cache[7] - lse) - 0.0f) < 1e-6f, "legal logp %g", cache[7] - lse);
    std::vector<float> g(A);
    for (int j = 0; j < A; ++j) g[j] = cache[j] - lse;
    float ent = puf_masked_head_entropy(g.data(), mask.data(), A);
    CHECK(ent == 0.0f && std::isfinite(ent), "singleton entropy %g", ent);
    puf_masked_head_grad(g.data(), mask.data(), A, 7, 0.5f, -0.01f, ent);
    for (int j = 0; j < A; ++j) {
        CHECK(std::isfinite(g[j]), "grad %d not finite", j);
        if (j != 7) CHECK(g[j] == 0.0f, "disabled grad %d = %g", j, g[j]);
    }
    // Random logits against a float64 log-softmax over the enabled subset.
    srand(7);
    for (int trial = 0; trial < 200; ++trial) {
        int n = 391;
        std::vector<float> lg(n), mk(n), ch(n);
        int enabled = 0;
        for (int j = 0; j < n; ++j) {
            lg[j] = (float)((rand() % 20000) - 10000) * 0.3f;
            mk[j] = (rand() % 7 == 0) ? 1.0f : 0.0f;
            enabled += mk[j] != 0.0f;
        }
        if (!enabled) { mk[0] = 1.0f; enabled = 1; }
        float l = puf_masked_logsumexp(lg.data(), 0, 0, n, mk.data(), 0, ch.data());
        double mx = -1e300;
        for (int j = 0; j < n; ++j) if (mk[j] != 0.0f && lg[j] > mx) mx = lg[j];
        double sum = 0.0;
        for (int j = 0; j < n; ++j) if (mk[j] != 0.0f) sum += std::exp((double)lg[j] - mx);
        double ref = mx + std::log(sum);
        CHECK(std::fabs(l - ref) <= 1e-3 * std::max(1.0, std::fabs(ref)), "lse %g ref %g", l, ref);
        for (int j = 0; j < n; ++j) {
            if (mk[j] == 0.0f) CHECK(ch[j] == -INFINITY, "disabled cache %d", j);
        }
    }
}

int main() {
    test_masked_softmax();
    test_exact_joint();
    test_train_rows();
    test_scripted_bank();
    test_ppo_guard();
    if (failures) {
        fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    printf("trainer helper tests: OK\n");
    return 0;
}

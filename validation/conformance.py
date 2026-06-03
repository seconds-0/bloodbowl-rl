#!/usr/bin/env python3
"""conformance.py — layer-2 statistical dice conformance (chi-square).

Runs tools/dist_dump (compiling it against the engine objects if needed),
then chi-squares every empirical frequency table against EXACT probabilities
derived analytically from the BB2025 rules:

  block dice          d6 faces uniform 1/6 (1d pool and 2d joint pairs)
  armour              P(break) = P(2d6 >= AV), AV 7..11, no modifiers
  injury (normal)     2-7 stunned / 8-9 KO / 10-12 casualty
  injury (stunty)     2-6 stunned / 7-8 KO / 9 badly hurt / 10-12 casualty
  casualty            D16: 1-8 BH / 9-10 SH / 11-12 SI / 13-14 LI / 15-16 DEAD
  dodge AG3+, 0/1 TZ  d6 >= 3 (resp. 4); natural 1 fails, natural 6 passes
  rush                d6 >= 2, same natural-roll rules
  full-match d6 pool  every d6 across whole random games, uniform

Failure threshold p < 0.001 per cell battery (deliberately strict to avoid
CI flakes; the bb-validation skill's re-run-to-confirm protocol applies to
persistent near-misses). Uses scipy when available, otherwise a built-in
regularized incomplete-gamma chi-square survival function.

ORACLE CROSS-CHECK — vendor/BloodBowlActionCalculator (Season3 = BB2025,
281 InlineData rows). Five rows covering plain block/dodge/armour/injury
sequences are parsed from ActionCalculatorTests.cs and asserted against both
our analytic model and the empirical dist_dump output. Notation mapping
(grammar from the vendor CLAUDE.md; block faces: 1=skull 2=both-down
3/4=push 5=stumble 6=pow):

  row "2"          p0=0.83333  d6 test needing 2+        <-> rush_2plus
  row "2,3,4,5,6"  p0=0.01543  chained 2+..6+ tests      <-> analytic ladder
                               (factors 3+ and 4+ measured by dodge_ag3_tz0/1)
  row "1D5"        p0=0.83333  1-die block, any of 5 faces <-> block_1d
                               P(not skull)
  row "2D5"        p0=0.97222  2-die block               <-> block_2d
                               P(not both skulls)
  row "2D3,K8"     p0=0.31250  2-die block needing one of 3 faces (vs a
                               skill-less defender: both-down/stumble/pow =
                               faces {2,5,6}) * armour 8+ <-> block_2d x av8
  row "2D3,K8,J8"  p0=0.13021  ... * injury 8+ (= KO-or-worse band)
                               <-> block_2d x av8 x injury_normal

NOT yet validated here (honest gaps): pass/catch/interception paths, kickoff
scatter geometry, reroll-modified compound paths (team/skill rerolls, Loner),
skill-modified armour/injury stacks (Mighty Blow/Claws/Dirty Player) — those
need dedicated micro-scenarios in dist_dump.c.

Usage:
  python3 validation/conformance.py [--trials 60000] [--seed 1234] [--quick]
Exit code 0 = all green; 1 = any failure.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DUMP_SRC = os.path.join(REPO, "tools", "dist_dump.c")
FIXTURES_HDR = os.path.join(REPO, "engine", "tests", "bb_fixtures.h")  # included by dist_dump.c
DIST_DUMP_BIN = os.path.join(REPO, "build", "dist_dump")
CALC_TESTS = os.path.join(REPO, "vendor", "BloodBowlActionCalculator",
                          "ActionCalculator.Tests", "ActionCalculatorTests.cs")
ALPHA = 0.001

# --- chi-square survival function ---------------------------------------------
try:
    from scipy.stats import chi2 as _scipy_chi2

    def chi2_sf(x, df):
        return float(_scipy_chi2.sf(x, df))
    CHI2_IMPL = "scipy"
except ImportError:  # manual fallback: regularized upper incomplete gamma
    def _gammq(a, x):
        if x < 0 or a <= 0:
            raise ValueError("bad gammq args")
        if x == 0:
            return 1.0
        if x < a + 1.0:  # series for P(a,x), return 1-P
            ap, summ = a, 1.0 / a
            delt = summ
            for _ in range(1000):
                ap += 1.0
                delt *= x / ap
                summ += delt
                if abs(delt) < abs(summ) * 1e-15:
                    break
            return 1.0 - summ * math.exp(-x + a * math.log(x) - math.lgamma(a))
        tiny = 1e-300  # continued fraction for Q(a,x)
        b = x + 1.0 - a
        c = 1.0 / tiny
        d = 1.0 / b
        h = d
        for i in range(1, 1000):
            an = -i * (i - a)
            b += 2.0
            d = an * d + b
            if abs(d) < tiny:
                d = tiny
            c = b + an / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            de = d * c
            h *= de
            if abs(de - 1.0) < 1e-15:
                break
        return h * math.exp(-x + a * math.log(x) - math.lgamma(a))

    def chi2_sf(x, df):
        return _gammq(df / 2.0, x / 2.0)
    CHI2_IMPL = "builtin"


# --- exact probabilities --------------------------------------------------------

def p_2d6_ge(t):
    return sum(1 for a in range(1, 7) for b in range(1, 7) if a + b >= t) / 36.0


def p_d6_test(target):
    """Natural 1 always fails, natural 6 always passes, else die >= target."""
    return sum(1 for d in range(2, 7) if d == 6 or d >= target) / 6.0


P_INJURY_NORMAL = {"stun": 21 / 36, "ko": 9 / 36, "cas": 6 / 36}           # 2-7/8-9/10-12
P_INJURY_STUNTY = {"stun": 15 / 36, "ko": 11 / 36, "bh": 4 / 36, "cas": 6 / 36}  # 2-6/7-8/9/10-12
P_CASUALTY = {"badly_hurt": 8 / 16, "seriously_hurt": 2 / 16,
              "serious_injury": 2 / 16, "lasting_injury": 2 / 16, "dead": 2 / 16}
P_2D6_SUM = {s: sum(1 for a in range(1, 7) for b in range(1, 7) if a + b == s) / 36.0
             for s in range(2, 13)}


# --- harness --------------------------------------------------------------------

class Report:
    def __init__(self):
        self.rows = []
        self.failures = 0

    def check(self, name, ok, detail):
        self.rows.append((name, ok, detail))
        if not ok:
            self.failures += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    def chi_square(self, name, observed, probs):
        n = sum(observed)
        if n == 0:
            self.check(name, False, "no observations")
            return
        chi = 0.0
        for o, p in zip(observed, probs):
            e = n * p
            if e <= 0:
                self.check(name, False, f"zero expectation cell (p={p})")
                return
            chi += (o - e) ** 2 / e
        df = len(observed) - 1
        p_val = chi2_sf(chi, df)
        self.check(name, p_val >= ALPHA,
                   f"n={n} chi2={chi:.2f} df={df} p={p_val:.4g}")

    def binomial(self, name, k, n, p):
        self.chi_square(name, [k, n - k], [p, 1.0 - p])

    def clean_counters(self, name, scen):
        ok = scen.get("errors", 0) == 0 and scen.get("xcheck_mismatch", 0) == 0
        self.check(f"{name} internal counters", ok,
                   f"errors={scen.get('errors')} xcheck={scen.get('xcheck_mismatch')}")


def build_dist_dump():
    # Of the candidate object dirs, pick the one whose NEWEST object is most
    # recent. First-hit-wins preferred a stale out-of-band build/main over the
    # `make`-default build/obj, silently validating an old engine (review T2).
    best = None
    for cand in ("build/main/obj", "build/obj"):
        d = os.path.join(REPO, cand)
        if not os.path.isdir(d):
            continue
        mtimes = [os.path.getmtime(os.path.join(d, f))
                  for f in os.listdir(d) if f.endswith(".o")]
        if mtimes and (best is None or max(mtimes) > best[0]):
            best = (max(mtimes), d)
    if best is None:
        print("ERROR: no engine objects found (run `make` first)", file=sys.stderr)
        sys.exit(2)
    objs_dir = best[1]
    objs = sorted(os.path.join(objs_dir, f) for f in os.listdir(objs_dir)
                  if f.endswith(".o"))
    newest_dep = max([os.path.getmtime(DIST_DUMP_SRC),
                      os.path.getmtime(FIXTURES_HDR)] +
                     [os.path.getmtime(o) for o in objs])
    need = (not os.path.exists(DIST_DUMP_BIN) or
            os.path.getmtime(DIST_DUMP_BIN) < newest_dep)
    if need:
        cmd = ["cc", "-std=c11", "-O2", "-Iengine/include", DIST_DUMP_SRC,
               *objs, "-o", DIST_DUMP_BIN]
        print(f"building dist_dump against {objs_dir} ...")
        subprocess.run(cmd, cwd=REPO, check=True)
    return DIST_DUMP_BIN


def run_dist_dump(trials, seed, matches):
    binary = build_dist_dump()
    print(f"running dist_dump trials={trials} seed={seed} matches={matches} ...")
    out = subprocess.run([binary, str(trials), str(seed), str(matches)],
                         cwd=REPO, check=True, capture_output=True, text=True)
    return json.loads(out.stdout)


# --- ActionCalculator oracle ----------------------------------------------------

def load_calculator_rows(notations):
    """Parse p0 (0-reroll probability) for given notations from the vendor
    test file. Returns {notation: p0}."""
    rows = {}
    pat = re.compile(r'\[InlineData\("((?:[^"\\]|\\.)*)", (\d+)((?:, [\d.]+)+)\)\]')
    with open(CALC_TESTS, encoding="utf-8") as f:
        for line in f:
            mm = pat.search(line)
            if not mm:
                continue
            notation = mm.group(1).replace('\\"', '"')
            probs = [float(x) for x in mm.group(3).lstrip(", ").split(", ")]
            if notation in notations and notation not in rows:
                rows[notation] = probs[0]
    return rows


def oracle_checks(rep, data):
    notations = ["2", "2,3,4,5,6", "1D5", "2D5", "2D3,K8", "2D3,K8,J8"]
    rows = load_calculator_rows(set(notations))
    missing = [nt for nt in notations if nt not in rows]
    rep.check("oracle rows parsed", not missing,
              f"{len(rows)}/{len(notations)} rows from ActionCalculatorTests.cs"
              + (f" (missing {missing})" if missing else ""))
    if missing:
        return

    b1 = data["block_1d"]
    b2 = data["block_2d"]
    n1, n2 = b1["trials"], b2["trials"]
    faces = b1["faces"]                       # index 0..5 = face 1..6
    pairs = b2["pairs"]                       # row-major 6x6, face1..6 x face1..6

    def pair_p(face_set):
        """Empirical P(at least one die in face_set) over the 2d pool."""
        hit = sum(pairs[(i - 1) * 6 + (j - 1)]
                  for i in range(1, 7) for j in range(1, 7)
                  if i in face_set or j in face_set)
        return hit / n2

    inj = data["injury_normal"]
    n_inj = inj["trials"]
    av8 = data["armour"]["av8"]
    p_av8 = av8["broken"] / av8["trials"]
    p_j8 = (inj["ko"] + inj["cas"]) / n_inj   # injury 8+ = KO-or-worse
    rush = data["rush_2plus"]
    p_rush = rush["pass"] / rush["trials"]

    def se(p, n):
        return math.sqrt(max(p * (1 - p), 1e-12) / n)

    cases = [
        # (name, oracle notation, analytic value, empirical value, empirical SE)
        ("rush 2+ vs row '2'", "2", p_d6_test(2), p_rush,
         se(5 / 6, rush["trials"])),
        ("d6 ladder vs row '2,3,4,5,6'", "2,3,4,5,6",
         math.prod(p_d6_test(t) for t in range(2, 7)), None, None),
        ("1d block any-of-5-faces vs row '1D5'", "1D5", 5 / 6,
         1.0 - faces[0] / n1, se(5 / 6, n1)),
        ("2d block not-double-skull vs row '2D5'", "2D5", 1 - (1 / 6) ** 2,
         1.0 - pairs[0] / n2, se(35 / 36, n2)),
        ("2d block 3-faces x armour8 vs row '2D3,K8'", "2D3,K8",
         (1 - (3 / 6) ** 2) * p_2d6_ge(8),
         pair_p({2, 5, 6}) * p_av8, None),
        ("... x injury8 vs row '2D3,K8,J8'", "2D3,K8,J8",
         (1 - (3 / 6) ** 2) * p_2d6_ge(8) * p_2d6_ge(8),
         pair_p({2, 5, 6}) * p_av8 * p_j8, None),
    ]
    for name, notation, analytic, empirical, e_se in cases:
        oracle = rows[notation]
        ok = abs(analytic - oracle) < 1e-4   # rows are rounded to 5 decimals
        rep.check(f"analytic {name}", ok,
                  f"analytic={analytic:.5f} oracle={oracle:.5f}")
        if empirical is None:
            continue
        if e_se is None:
            # product of independent empirical factors: combine relative SEs
            ps = [(pair_p({2, 5, 6}), n2), (p_av8, av8["trials"])]
            if "J8" in notation:
                ps.append((p_j8, n_inj))
            rel = math.sqrt(sum((se(p, n) / max(p, 1e-9)) ** 2 for p, n in ps))
            e_se = empirical * rel
        tol = max(4.5 * e_se, 1e-3)
        ok = abs(empirical - oracle) < tol
        rep.check(f"empirical {name}", ok,
                  f"empirical={empirical:.5f} oracle={oracle:.5f} tol={tol:.5f}")


# --- main -----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--trials", type=int, default=60000,
                    help="base trials per micro-scenario (see dist_dump.c)")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--matches", type=int, default=20,
                    help="full random matches for the whole-engine d6 stream")
    ap.add_argument("--quick", action="store_true",
                    help="5k trials / 4 matches (smoke run, weaker power)")
    args = ap.parse_args()
    trials = 5000 if args.quick else args.trials
    matches = 4 if args.quick else args.matches

    data = run_dist_dump(trials, args.seed, matches)
    rep = Report()
    print(f"\n=== layer-2 dice conformance (alpha={ALPHA}, chi2 impl: {CHI2_IMPL}) ===")

    print("\n-- engine micro-scenario internal counters --")
    for name in ("block_1d", "block_2d", "injury_normal", "injury_stunty",
                 "casualty", "dodge_ag3_tz0", "dodge_ag3_tz1", "rush_2plus"):
        rep.clean_counters(name, data[name])
    for av, scen in data["armour"].items():
        rep.clean_counters(f"armour {av}", scen)

    print("\n-- block dice --")
    rep.chi_square("block_1d faces uniform", data["block_1d"]["faces"], [1 / 6] * 6)
    rep.chi_square("block_2d joint pairs uniform", data["block_2d"]["pairs"],
                   [1 / 36] * 36)

    print("\n-- armour (2d6 >= AV) --")
    for av in range(7, 12):
        scen = data["armour"][f"av{av}"]
        rep.binomial(f"armour av{av} break rate", scen["broken"], scen["trials"],
                     p_2d6_ge(av))

    print("\n-- injury bands --")
    inj = data["injury_normal"]
    rep.chi_square("injury normal stun/ko/cas",
                   [inj["stun"], inj["ko"], inj["cas"]],
                   [P_INJURY_NORMAL["stun"], P_INJURY_NORMAL["ko"],
                    P_INJURY_NORMAL["cas"]])
    rep.check("injury normal has no BH band", inj["bh"] == 0, f"bh={inj['bh']}")
    rep.chi_square("injury normal 2d6 sum", inj["sum_2d6"],
                   [P_2D6_SUM[s] for s in range(2, 13)])
    stn = data["injury_stunty"]
    rep.chi_square("injury stunty stun/ko/bh/cas",
                   [stn["stun"], stn["ko"], stn["bh"], stn["cas"]],
                   [P_INJURY_STUNTY["stun"], P_INJURY_STUNTY["ko"],
                    P_INJURY_STUNTY["bh"], P_INJURY_STUNTY["cas"]])
    rep.chi_square("injury stunty 2d6 sum", stn["sum_2d6"],
                   [P_2D6_SUM[s] for s in range(2, 13)])

    print("\n-- casualty (D16) --")
    cas = data["casualty"]
    rep.chi_square("casualty bands",
                   [cas[k] for k in ("badly_hurt", "seriously_hurt",
                                     "serious_injury", "lasting_injury", "dead")],
                   [P_CASUALTY[k] for k in ("badly_hurt", "seriously_hurt",
                                            "serious_injury", "lasting_injury",
                                            "dead")])
    rep.chi_square("casualty raw d16 uniform", cas["d16"], [1 / 16] * 16)

    print("\n-- agility tests (nat 1 fails / nat 6 passes) --")
    for tz, target in ((0, 3), (1, 4)):
        scen = data[f"dodge_ag3_tz{tz}"]
        rep.binomial(f"dodge AG3+ {tz} TZ (needs {target}+)", scen["pass"],
                     scen["trials"], p_d6_test(target))
    rep.binomial("rush (needs 2+)", data["rush_2plus"]["pass"],
                 data["rush_2plus"]["trials"], p_d6_test(2))

    print("\n-- whole-engine d6 stream (random matches) --")
    rm = data["random_matches"]
    rep.check("random matches completed", rm["completed"] == rm["games"],
              f"{rm['completed']}/{rm['games']} (decisions={rm['decisions']})")
    rep.chi_square("full-match d6 faces uniform", rm["d6_faces"], [1 / 6] * 6)

    print("\n-- BloodBowlActionCalculator oracle (Season3 = BB2025) --")
    oracle_checks(rep, data)

    total = len(rep.rows)
    print(f"\n=== {total - rep.failures}/{total} checks passed ===")
    if rep.failures:
        print(f"{rep.failures} FAILURES — see above. Re-run with a fresh --seed "
              f"before concluding bias (re-run-to-confirm protocol).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

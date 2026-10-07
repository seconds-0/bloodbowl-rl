"""Descriptive splits of the D425 records, not part of the registered reading.

Raw counts with no intervals. Run from anywhere; reads the eight shard
directories the report was made from.
"""
import collections
import json
import math

R = "/Users/alexanderhuth/Code/bb-harness-search/.play-artifacts/search-ab"
DIRS = [R + "/ab-d425/s1"] + [R + f"/ab-d425r/s{i}" for i in range(2, 9)]


def elo(w, l):
    return float("nan") if w == 0 or l == 0 else 400 * math.log10(w / l)


def summ(rs):
    if not rs:
        return "none"
    c = collections.Counter(r["result_a"] for r in rs)
    w, d, l = c["W"], c["D"], c["L"]
    n = len(rs)
    return (f"n={n} W/D/L {w}/{d}/{l} win score {(w + 0.5 * d) / n:.3f} "
            f"decisive share {w / max(1, w + l):.3f} decisive-Elo {elo(w, l):+.0f} "
            f"TD for {sum(r['a_td'] for r in rs) / n:.3f} "
            f"against {sum(r['b_td'] for r in rs) / n:.3f}")


def host(r):
    return "relaunch" if "d425r" in r["runtime"]["hostname"] else "first launch"


def main():
    recs = [json.loads(line) for d in DIRS for line in open(d + "/games.jsonl")]
    print("records", len(recs), dict(collections.Counter(r["arm"] for r in recs)))
    print("every game natural:", all(r["natural"] for r in recs),
          "| any decision cap:", any(r["decision_cap"] for r in recs),
          "| any invalid:", any(r["invalid"] for r in recs),
          "| error rollouts:", sum(r["error_rollouts"] for r in recs),
          "| integrity checks per record:",
          dict(collections.Counter(len(r["integrity_checks"]) for r in recs)))
    print("records by arm and droplet:",
          sorted(collections.Counter((r["arm"], host(r)) for r in recs).items()))
    for arm in ("plain", "s10"):
        rs = [r for r in recs if r["arm"] == arm]
        print(f"\n{arm}: {summ(rs)}")
        for leg in ("A_home", "B_home"):
            print(f"  {leg}: {summ([r for r in rs if r['leg'] == leg])}")
        for s in ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"):
            print(f"  {s}: {summ([r for r in rs if r['shard'] == s])}")
        for h in ("first launch", "relaunch"):
            print(f"  played on the {h} droplet: {summ([r for r in rs if host(r) == h])}")
        sec = sorted(r["seconds"] for r in rs)
        print(f"  engine steps per game {sum(r['c_steps'] for r in rs) / len(rs):.0f}; "
              f"seconds per game mean {sum(sec) / len(sec):.1f}, median "
              f"{sec[len(sec) // 2]:.1f}, max {sec[-1]:.1f}")
    s10 = [r for r in recs if r["arm"] == "s10"]
    dev = sorted(sum(r["deviations"].values()) for r in s10)
    searched = sum(sum(r["searched"].values()) for r in s10)
    print(f"\ns10 deviations per game: mean {sum(dev) / len(dev):.2f}, median "
          f"{dev[len(dev) // 2]}, max {dev[-1]}, games with none {dev.count(0)}")
    print(f"s10 searched decisions {searched}, deviations {sum(dev)} "
          f"({100 * sum(dev) / searched:.2f}%)")
    pg = sorted(g for r in s10 for g in r["predicted_gains"])
    print(f"s10 predicted gain at deviations: n {len(pg)}, mean {sum(pg) / len(pg):.3f}, "
          f"median {pg[len(pg) // 2]:.3f}, 90th percentile {pg[int(len(pg) * 0.9)]:.3f}, "
          f"max {pg[-1]:.3f}")
    print(f"s10 rollouts {sum(r['rollouts'] for r in s10)}, ended by the 200-step cutoff "
          f"{sum(r['cutoff_rollouts'] for r in s10)}")
    plain = {(r["engine_seed"], r["leg"]): r for r in recs if r["arm"] == "plain"}
    srch = {(r["engine_seed"], r["leg"]): r for r in s10}
    moves = collections.Counter((plain[k]["result_a"], srch[k]["result_a"]) for k in plain)
    print("result of the same seed and orientation, plain then s10:", sorted(moves.items()))
    print("\ns10 by deviations in the game (not causal: the count depends on how the game went)")
    by = collections.defaultdict(list)
    for r in s10:
        by[min(sum(r["deviations"].values()), 5)].append(r)
    for n in sorted(by):
        print(f"  {n}{'+' if n == 5 else ''} deviations: {summ(by[n])}")


if __name__ == "__main__":
    main()

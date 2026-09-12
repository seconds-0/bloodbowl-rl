#!/usr/bin/env python3
"""Compare two complete frozen-policy exams using exactly matched game keys.

This is a development comparison, not a training-seed confidence interval.
The same engine seed does not imply the same dice are consumed after policies
diverge. Results remain paired by the prospectively assigned game seed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def key(row):
    return tuple(row[name] for name in
                 ("style", "learner_side", "base_seed", "episode"))


def load_exam(directory):
    directory = Path(directory)
    manifest_path = directory / "MANIFEST.json"
    games_path = directory / "GAMES.jsonl"
    complete_path = directory / "COMPLETE.json"
    manifest = json.loads(manifest_path.read_text())
    complete = json.loads(complete_path.read_text())
    for name, path in (("manifest_sha256", manifest_path),
                       ("games_sha256", games_path)):
        if complete.get(name) != digest(path):
            raise ValueError(f"{directory}: {name} mismatch")
    rows = [json.loads(line) for line in games_path.read_text().splitlines()]
    expected = {(cell["style"], cell["learner_side"], cell["seed"], episode)
                for cell in manifest["cells"]
                for episode in range(1, manifest["games_per_cell"] + 1)}
    indexed = {key(row): row for row in rows}
    if (len(indexed) != len(rows) or set(indexed) != expected
            or complete["expected_games"] != len(expected)):
        raise ValueError(f"{directory}: duplicate, missing, or extra games")
    for row in rows:
        points = row["match_points"]
        td = row["td_diff"]
        if not math.isfinite(points) or not math.isfinite(td):
            raise ValueError("non-finite game metric")
        expected_points = 1.0 if td > 0 else 0.5 if td == 0 else 0.0
        if points != expected_points:
            raise ValueError("match points disagree with TD difference")
        if row["checkpoint_sha256"] != manifest["checkpoint_sha256"]:
            raise ValueError("game checkpoint identity mismatch")
        if row["runtime_identity_sha256"] != manifest["runtime_identity_sha256"]:
            raise ValueError("game runtime identity mismatch")
    return manifest, indexed, digest(complete_path)


def paired_summary(pairs):
    n = len(pairs)
    delta = [b["match_points"] - a["match_points"] for a, b in pairs]
    return {
        "paired_games": n,
        "reference_match_score": sum(a["match_points"] for a, _ in pairs) / n,
        "candidate_match_score": sum(b["match_points"] for _, b in pairs) / n,
        "match_score_delta": sum(delta) / n,
        "td_diff_delta": sum(b["td_diff"] - a["td_diff"] for a, b in pairs) / n,
        "candidate_better_games": sum(d > 0 for d in delta),
        "candidate_worse_games": sum(d < 0 for d in delta),
        "equal_games": sum(d == 0 for d in delta),
    }


def compare(reference, candidate):
    am, ar, ah = load_exam(reference)
    bm, br, bh = load_exam(candidate)
    if set(ar) != set(br):
        raise ValueError("exam game populations differ")
    if am["runtime_identity_sha256"] != bm["runtime_identity_sha256"]:
        raise ValueError("runtime identities differ; comparison requires one runtime")
    # Runtime config files are hashed by the evaluator; explicit effective
    # overrides must also match once that field is available.
    if am.get("effective_configs") != bm.get("effective_configs"):
        raise ValueError("effective evaluation configurations differ")
    pairs = [(ar[k], br[k]) for k in sorted(ar)]
    cells = []
    for style, side, seed in sorted({k[:3] for k in ar}):
        subset = [(ar[k], br[k]) for k in sorted(ar)
                  if k[:3] == (style, side, seed)]
        cells.append({"style": style, "learner_side": side, "seed": seed,
                      **paired_summary(subset)})
    return {
        "schema_version": 1,
        "reference_complete_sha256": ah,
        "candidate_complete_sha256": bh,
        "reference_checkpoint_sha256": am["checkpoint_sha256"],
        "candidate_checkpoint_sha256": bm["checkpoint_sha256"],
        "runtime_identity_sha256": am["runtime_identity_sha256"],
        "aggregate": paired_summary(pairs),
        "macro_match_score_delta": sum(c["match_score_delta"] for c in cells) / len(cells),
        "per_cell": cells,
        "interpretation": "Descriptive paired development exam. Game repetitions are not independent training seeds. No promotion or training-seed confidence claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.reference, args.candidate)
    with args.output.open("x") as out:
        json.dump(result, out, indent=2, sort_keys=True, allow_nan=False)
        out.write("\n")
    print(json.dumps(result["aggregate"], sort_keys=True))


if __name__ == "__main__":
    main()

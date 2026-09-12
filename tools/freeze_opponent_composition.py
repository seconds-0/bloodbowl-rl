#!/usr/bin/env python3
"""Freeze the two eight-seat pools for the fixed-exposure composition screen."""
import argparse, hashlib, json, os, shutil, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_league import DEFAULT_EXPECT_BYTES, build_league, parse_seed_args


class FreezeError(RuntimeError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(out, shared, candidates, expect_bytes=DEFAULT_EXPECT_BYTES,
           builder=build_league):
    if len(shared) != 3 or len(candidates) != 3:
        raise FreezeError("exactly three --shared and three --candidate entries are required")
    all_names = [n for n, _ in shared + candidates]
    if len(set(all_names)) != 6:
        raise FreezeError("shared and candidate labels must be unique")
    identities = []
    for label, path in shared + candidates:
        if not os.path.isfile(path) or not os.path.isfile(path + ".lineage.json"):
            raise FreezeError(f"{label}: checkpoint and lineage sidecar must both exist: {path}")
        identities.append((label, path, sha(path)))
    if len({digest for _, _, digest in identities}) != 6:
        raise FreezeError("the six learned-policy inputs must have distinct checkpoint hashes")

    out = Path(out).resolve()
    if out.exists():
        raise FreezeError(f"output already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.tmp.", dir=out.parent))
    try:
        placeholder = shared[0][1]
        control = [("script-placeholder-a", placeholder),
                   ("script-placeholder-b", placeholder)]
        for name, path in shared:
            control += [(f"{name}-copy-a", path), (f"{name}-copy-b", path)]
        candidate = [("script-placeholder-a", placeholder),
                     ("script-placeholder-b", placeholder)] + shared + candidates
        cm = builder(stage / "control", control, expect_bytes=expect_bytes)
        xm = builder(stage / "candidate", candidate, expect_bytes=expect_bytes)
        contract = {
            "schema_version": 1,
            "factor": "learned_opponent_composition_at_fixed_exposure",
            "exploratory_selection": True,
            "num_frozen_banks": 8,
            "frozen_bank_pct": 0.06,
            "rows_per_buffer": 1024,
            "rows_per_bank": 61,
            "scripted_bank_mask": 3,
            "scripted_rows": 122,
            "learned_history_rows": 366,
            "learner_rows": 536,
            "learner_mirror_rows": 48,
            "seeds": [42, 44],
            "run_order": ["seed42-control", "seed42-candidate",
                          "seed44-candidate", "seed44-control"],
            "initial_screen_steps": 100_000_000,
            "shared": [{"label": n, "source": os.path.abspath(p), "sha256": d}
                       for n, p, d in identities[:3]],
            "candidate_only": [{"label": n, "source": os.path.abspath(p), "sha256": d}
                               for n, p, d in identities[3:]],
            "control_pool_manifest_sha256": sha(stage / "control/pool/league_seeds.json"),
            "candidate_pool_manifest_sha256": sha(stage / "candidate/pool/league_seeds.json"),
            "control_seats": [e["name"] for e in cm["seeds"]],
            "candidate_seats": [e["name"] for e in xm["seeds"]],
        }
        (stage / "OPPONENT_COMPOSITION_PLAN.json").write_text(
            json.dumps(contract, indent=2, sort_keys=True) + "\n")
        os.replace(stage, out)
        return contract
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--shared", action="append", default=[])
    ap.add_argument("--candidate", action="append", default=[])
    ap.add_argument("--expect-bytes", type=int, default=DEFAULT_EXPECT_BYTES)
    a = ap.parse_args()
    try:
        contract = freeze(a.out, parse_seed_args(a.shared),
                          parse_seed_args(a.candidate), a.expect_bytes)
    except Exception as exc:
        raise SystemExit(f"error: {exc}")
    print(json.dumps(contract, sort_keys=True))


if __name__ == "__main__":
    main()

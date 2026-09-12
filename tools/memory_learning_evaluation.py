#!/usr/bin/env python3
"""Run and compare held-out scripted exams for the paired memory-learning screen."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

try:
    from compare_frozen_eval import load_exam, paired_summary
except ModuleNotFoundError:
    from tools.compare_frozen_eval import load_exam, paired_summary


SHA = re.compile(r"^[0-9a-f]{64}$")
CONTRACTS = {"old": "tail-bootstrap-v1", "new": "terminal-aware-tbptt-v1"}
MODULES = {
    "old": "553c70a9bc3ad33da20c34a52bbc7c2dd58c1f286f4e3dcff51c375ca8ba690b",
    "new": "651ffc40e43e669912803e2f5bb3d3e641c34c0d8b431ab0f38f8393bbc700a3",
}
EVAL_SEEDS = (2026090511, 2026090512, 2026090513, 2026090514)
GAMES_PER_SEED_CELL = 8


class EvaluationFailure(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True,
                                    allow_nan=False) + "\n")
    os.replace(temporary, path)


def validate_plan(plan: Mapping[str, Any], *, require_checkpoints: bool) -> None:
    if plan.get("schema_version") != 1 or plan.get("mode") != "memory-learning-heldout-v1":
        raise EvaluationFailure("unsupported memory-learning evaluation plan")
    if tuple(plan.get("evaluation_seeds", ())) != EVAL_SEEDS:
        raise EvaluationFailure("evaluation seeds differ from the prospective four-seed set")
    if plan.get("games_per_seed_style_side") != GAMES_PER_SEED_CELL:
        raise EvaluationFailure("evaluation requires eight games per seed/style/side")
    if plan.get("games_per_model") != 128:
        raise EvaluationFailure("evaluation requires exactly 128 games per model")
    if plan.get("training_seeds") != [42, 43]:
        raise EvaluationFailure("paired screen requires training seeds 42 and 43")
    if plan.get("qualification_only") is not True or plan.get("promotion_eligible") is not False:
        raise EvaluationFailure("post-training screen must remain qualification-only")
    models = plan.get("models")
    if not isinstance(models, list) or len(models) != 4:
        raise EvaluationFailure("plan must contain old/new models for both training seeds")
    expected = {(arm, seed) for arm in CONTRACTS for seed in (42, 43)}
    observed = set()
    for model in models:
        arm, seed = model.get("arm"), model.get("training_seed")
        observed.add((arm, seed))
        if model.get("contract") != CONTRACTS.get(arm) or model.get("module_sha256") != MODULES.get(arm):
            raise EvaluationFailure("model runtime identity is not the frozen old/new pair")
        for key in ("runtime", "python", "cudart", "source_snapshot_root"):
            if not Path(str(model.get(key, ""))).is_absolute():
                raise EvaluationFailure(f"model {key} must be absolute")
        if not SHA.fullmatch(str(model.get("source_closure_sha256", ""))):
            raise EvaluationFailure("source closure SHA-256 is not frozen")
        checkpoint = Path(str(model.get("checkpoint", "")))
        checkpoint_sha = str(model.get("checkpoint_sha256", ""))
        if not checkpoint.is_absolute() or not SHA.fullmatch(checkpoint_sha):
            raise EvaluationFailure("checkpoint path and SHA-256 must be frozen")
        if require_checkpoints and (not checkpoint.is_file() or sha256(checkpoint) != checkpoint_sha):
            raise EvaluationFailure("checkpoint bytes differ from the evaluation plan")
    if observed != expected:
        raise EvaluationFailure("model arm/training-seed matrix is incomplete or duplicated")


def command(model: Mapping[str, Any], plan: Mapping[str, Any], output: Path) -> list[str]:
    evaluator = Path(__file__).resolve().with_name("frozen_scripted_eval.py")
    argv = [str(model["python"]), str(evaluator),
            "--checkpoint", str(model["checkpoint"]), "--output", str(output),
            "--games-per-cell", str(GAMES_PER_SEED_CELL), "--allow-qualification",
            "--runtime-root", str(model["runtime"]),
            "--rollout-transition-contract", str(model["contract"]),
            "--source-snapshot-root", str(model["source_snapshot_root"]),
            "--source-closure-sha256", str(model["source_closure_sha256"])]
    if model["arm"] == "old":
        argv.extend(("--runtime-bridge-reason",
                     "historical control evaluated in its producing frozen runtime"))
    for seed in plan["evaluation_seeds"]:
        argv.extend(("--seed", str(seed)))
    return argv


def environment(model: Mapping[str, Any]) -> dict[str, str]:
    runtime = Path(model["runtime"])
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": os.pathsep.join((str(runtime / "vendor/PufferLib"), str(runtime / "tools"))),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "CUDA_VISIBLE_DEVICES": "0", "LD_PRELOAD": str(model["cudart"]),
        "OMP_NUM_THREADS": "16", "OPENBLAS_NUM_THREADS": "16",
    })
    env["PATH"] = str(Path(model["python"]).parent) + os.pathsep + env["PATH"]
    return env


def run(plan_path: Path, output: Path) -> None:
    plan = json.loads(plan_path.read_text())
    validate_plan(plan, require_checkpoints=True)
    if output.exists():
        raise EvaluationFailure("refusing to overwrite evaluation output")
    output.mkdir(parents=True)
    completions = {}
    for model in plan["models"]:
        name = f'{model["arm"]}-s{model["training_seed"]}'
        destination = output / name
        subprocess.run(command(model, plan, destination), cwd=model["runtime"],
                       env=environment(model), check=True)
        manifest = json.loads((destination / "MANIFEST.json").read_text())
        complete = json.loads((destination / "COMPLETE.json").read_text())
        if (manifest["runtime_identity"]["compiled_module_sha256"] != model["module_sha256"]
                or manifest["runtime_identity"]["rollout_transition_contract"] != model["contract"]
                or manifest["checkpoint_sha256"] != model["checkpoint_sha256"]
                or complete.get("expected_games") != 128):
            raise EvaluationFailure(f"{name} completed under the wrong identity or game count")
        completions[name] = sha256(destination / "COMPLETE.json")
    result = compare(plan, output)
    result["plan_sha256"] = sha256(plan_path)
    result["exam_complete_sha256"] = completions
    atomic_json(output / "MEMORY_LEARNING_EVALUATION.json", result)


def _configs_without_runtime(manifest: Mapping[str, Any]) -> Any:
    # frozen_scripted_eval effective configs contain only model/env arguments;
    # require literal equality rather than maintaining an omission allowlist.
    return manifest.get("effective_configs")


def validate_exam_identity(manifest: Mapping[str, Any], model: Mapping[str, Any]) -> None:
    identity = manifest.get("runtime_identity", {})
    if (manifest.get("checkpoint_sha256") != model["checkpoint_sha256"]
            or identity.get("compiled_module_sha256") != model["module_sha256"]
            or identity.get("rollout_transition_contract") != model["contract"]):
        raise EvaluationFailure("exam checkpoint/module/recurrent identity differs from plan")
    if manifest.get("checkpoint_qualification_only") is not True:
        raise EvaluationFailure("exam checkpoint is not explicitly qualification-only")
    cells = manifest.get("cells", [])
    population = {(cell.get("style"), cell.get("learner_side"), cell.get("seed"))
                  for cell in cells}
    expected = {(style, side, seed) for style in ("contact", "cage")
                for side in ("home", "away") for seed in EVAL_SEEDS}
    if population != expected or len(cells) != len(expected):
        raise EvaluationFailure("exam style/side/evaluation-seed matrix differs from plan")


def compare(plan: Mapping[str, Any], output: Path) -> dict[str, Any]:
    validate_plan(plan, require_checkpoints=False)
    by_arm_seed = {}
    for model in plan["models"]:
        name = f'{model["arm"]}-s{model["training_seed"]}'
        manifest, rows, complete_sha = load_exam(output / name)
        validate_exam_identity(manifest, model)
        if len(rows) != 128:
            raise EvaluationFailure(f"{name} does not contain exactly 128 complete games")
        by_arm_seed[(model["arm"], model["training_seed"])] = (
            manifest, rows, complete_sha)
    pairs_by_seed = []
    for seed in plan["training_seeds"]:
        old_manifest, old_rows, old_complete = by_arm_seed[("old", seed)]
        new_manifest, new_rows, new_complete = by_arm_seed[("new", seed)]
        if set(old_rows) != set(new_rows):
            raise EvaluationFailure(f"training seed {seed} has unmatched game keys")
        if _configs_without_runtime(old_manifest) != _configs_without_runtime(new_manifest):
            raise EvaluationFailure(f"training seed {seed} effective evaluation configs differ")
        pairs = [(old_rows[key], new_rows[key]) for key in sorted(old_rows)]
        cells = []
        for style, side in sorted({key[:2] for key in old_rows}):
            subset = [(old_rows[key], new_rows[key]) for key in sorted(old_rows)
                      if key[:2] == (style, side)]
            cells.append({"style": style, "learner_side": side,
                          **paired_summary(subset)})
        pairs_by_seed.append({"training_seed": seed,
                              "old_complete_sha256": old_complete,
                              "new_complete_sha256": new_complete,
                              "aggregate": paired_summary(pairs), "cells": cells})
    macro_delta = sum(row["aggregate"]["match_score_delta"] for row in pairs_by_seed) / 2
    return {
        "schema_version": 1, "accepted": True, "games_per_model": 128,
        "paired_games_total": 256, "training_seed_pairs": pairs_by_seed,
        "macro_training_seed_match_score_delta": macro_delta,
        "interpretation": "Two-seed scripted held-out screen; descriptive, qualification-only, and not promotion evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command_name", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", required=True, type=Path)
    execute.add_argument("--output", required=True, type=Path)
    analyze = sub.add_parser("compare")
    analyze.add_argument("--plan", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if args.command_name == "run":
        run(args.plan, args.output)
    else:
        atomic_json(args.output / "MEMORY_LEARNING_EVALUATION.json",
                    compare(plan, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

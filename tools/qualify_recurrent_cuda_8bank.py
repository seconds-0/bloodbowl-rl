#!/usr/bin/env python3
"""CUDA qualification for the eight-bank opponent-training profile.

This is deliberately separate from qualify_recurrent_cuda.py: that gate proves
the generic one-bank contract, while this profile proves the exact row layout
and recurrent groups used by the eight-bank opponent experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_recurrent_cuda as q
import checkpoint_lineage

PROFILE = "opponent-eight-bank-recurrent-v1"
TOTAL_AGENTS = 2048
NUM_BUFFERS = 2
AGENTS_PER_BUFFER = 1024
FROZEN_BANKS = 8
FROZEN_BANK_PCT = 0.06
ROWS_PER_FROZEN_BANK = 61
FROZEN_ROWS_PER_BUFFER = 488
PRIMARY_ROWS_PER_BUFFER = 536
SCRIPTED_BANK_MASK = 3
EXPECTED_LAYOUT = [0, 536, 597, 658, 719, 780, 841, 902, 963, 1024]
EXPECTED_GROUPS = (FROZEN_BANKS + 1) * NUM_BUFFERS
MIN_GRAPH_TRAIN_CALLS = q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS + 1
SNAPSHOT_CAP_BYTES = 64 << 20
ACTION_MASK_WIDTH = 454
PARTIAL_ARTIFACT_NAME = "EIGHT_BANK_RECURRENT.partial.npz"


def validate_screen_manifest(
    manifest_path: Path, expected_sha256: str, identity: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind qualification lineage to a measured reward-screen runtime."""
    manifest_path = Path(manifest_path).resolve()
    expected_sha256 = q._require_sha256(
        expected_sha256, "screen manifest digest")
    if not manifest_path.is_file() or q.sha256(manifest_path) != expected_sha256:
        raise q.QualificationError("screen manifest digest differs")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise q.QualificationError(f"cannot read screen manifest: {exc}") from exc
    contract = manifest.get("contract") if isinstance(manifest, Mapping) else None
    implementation = (
        contract.get("implementation") if isinstance(contract, Mapping) else None)
    semantic = (
        implementation.get("compiled_semantic_contract")
        if isinstance(implementation, Mapping) else None)
    if not isinstance(implementation, Mapping) or not isinstance(semantic, Mapping):
        raise q.QualificationError("screen manifest implementation is malformed")

    expected = {
        "source_sha256": identity["environment_sha256"],
        "compiled_module_sha256": identity["module_sha256"],
        "compiled_backend_sources_sha256": identity["backend_sources_sha256"],
        "vendor_source_sha256": identity["backend_sources_sha256"],
    }
    for key, value in expected.items():
        if implementation.get(key) != value:
            raise q.QualificationError(
                f"screen manifest {key} differs from imported runtime")
    semantic_expected = {
        "env_name": identity["compiled_env"],
        "environment_source_sha256": identity["environment_sha256"],
        "exact_action_source_sha256": identity["compiled_backend_sha256"],
        "observation_abi": identity["observation_abi"],
        "observation_version": identity["observation_version"],
        "action_abi": identity["action_abi"],
        "rollout_transition_contract": identity["rollout_transition_contract"],
        "entropy_schedule_contract": identity["entropy_schedule_contract"],
        "precision_bytes": identity["precision_bytes"],
    }
    for key, value in semantic_expected.items():
        if semantic.get(key) != value:
            raise q.QualificationError(
                f"screen manifest compiled contract {key} differs")
    patch_bundle_sha256 = q._require_sha256(
        implementation.get("puffer_patch_bundle_sha256"),
        "screen manifest Puffer patch bundle digest")
    return {
        "path": str(manifest_path),
        "sha256": expected_sha256,
        "puffer_patch_bundle_sha256": patch_bundle_sha256,
    }


def summarize_ratio_call(
    selected: np.ndarray, ratios: np.ndarray, *, atol: float
) -> dict[str, Any]:
    flat = ratios.astype(np.float64, copy=False).reshape(-1)
    delta = flat - 1.0
    absolute = np.abs(delta)
    finite = np.isfinite(flat)
    finite_flat = flat[finite]
    finite_delta = delta[finite]
    finite_absolute = absolute[finite]
    return {
        "ratio_elements": int(flat.size),
        "selected_elements": int(selected.size),
        "selected_unique_rows": int(np.unique(selected).size),
        "selected_row_min": int(selected.min()) if selected.size else None,
        "selected_row_max": int(selected.max()) if selected.size else None,
        "finite_elements": int(finite.sum()),
        "nonfinite_elements": int((~finite).sum()),
        "ratio_min": float(np.min(finite_flat)) if finite_flat.size else None,
        "ratio_max": float(np.max(finite_flat)) if finite_flat.size else None,
        "ratio_mean": float(np.mean(finite_flat)) if finite_flat.size else None,
        "signed_delta_mean": float(np.mean(finite_delta)) if finite_delta.size else None,
        "max_abs_ratio_minus_one": (
            float(np.max(finite_absolute)) if finite_absolute.size else None
        ),
        "abs_delta_p50": (
            float(np.percentile(finite_absolute, 50)) if finite_absolute.size else None
        ),
        "abs_delta_p90": (
            float(np.percentile(finite_absolute, 90)) if finite_absolute.size else None
        ),
        "abs_delta_p99": (
            float(np.percentile(finite_absolute, 99)) if finite_absolute.size else None
        ),
        "elements_over_atol": int(np.count_nonzero(finite_absolute > atol)),
        "atol": float(atol),
    }


def terminal_snapshot_shapes(config: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    agents = q._int(config["vec"]["total_agents"], "snapshot agents", minimum=1)
    buffers = q._int(config["vec"]["num_buffers"], "snapshot buffers", minimum=1)
    horizon = q._int(config["train"]["horizon"], "snapshot horizon", minimum=1)
    minibatch = q._int(
        config["train"]["minibatch_size"], "snapshot minibatch", minimum=1
    )
    hidden = q._int(config["policy"]["hidden_size"], "snapshot hidden", minimum=1)
    layers = q._int(config["policy"]["num_layers"], "snapshot layers", minimum=1)
    if minibatch % horizon:
        raise q.QualificationError("snapshot minibatch is not horizon-divisible")
    segments = minibatch // horizon
    return {
        "mb_ratio": (segments, horizon),
        "selected_rows": (segments,),
        "segment_initial_states": (layers, agents, hidden),
        "mb_initial_states": (layers, segments, hidden),
        "mb_observation_terminals": (segments, horizon),
        "segment_initial_valid": (buffers,),
        "tail_valid": (buffers,),
        "tail_values": (agents,),
        "tail_terminals": (agents,),
    }


def snapshot_byte_budget(config: Mapping[str, Any]) -> dict[str, Any]:
    """Bound the exact terminal-aware compact snapshot."""
    agents = q._int(config["vec"]["total_agents"], "snapshot agents", minimum=1)
    horizon = q._int(config["train"]["horizon"], "snapshot horizon", minimum=1)
    shapes = terminal_snapshot_shapes(config)
    tensor_bytes = {
        name: int(np.prod(shape, dtype=np.int64)) * 4
        for name, shape in shapes.items()
    }
    # Decoder snapshots contain every active physical row exactly once across
    # the nine banks and two buffers, with 454 logits plus one value column.
    decoder_bytes = agents * (ACTION_MASK_WIDTH + 1) * 4
    exact = sum(tensor_bytes.values()) + decoder_bytes
    if exact > SNAPSHOT_CAP_BYTES:
        raise q.QualificationError(
            f"declared snapshot bytes {exact} exceeds "
            f"bounded cap {SNAPSHOT_CAP_BYTES}"
        )
    return {
        "cap_bytes": SNAPSHOT_CAP_BYTES,
        "declared_exact_bytes": exact,
        "declared_upper_bound_bytes": exact,
        "decoder_bytes": decoder_bytes,
        "tensor_bytes": tensor_bytes,
        "tensor_shapes": shapes,
    }


def take_snapshot(
    backend: Any, pufferl: Any, budget: Mapping[str, Any]
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    if getattr(backend, "rollout_transition_contract", None) != \
            "terminal-aware-tbptt-v1":
        raise q.QualificationError(
            "compact snapshot requires terminal-aware-tbptt-v1")
    raw = backend.qualification_snapshot(
        pufferl, int(budget["cap_bytes"]), False
    )
    used = q._int(raw.get("used_bytes"), "qualification snapshot used_bytes", minimum=1)
    returned_cap = q._int(raw.get("max_bytes"), "qualification snapshot max_bytes", minimum=1)
    expected_shapes = dict(budget["tensor_shapes"])
    if (raw.get("include_rollout") is not False
            or set(raw.get("tensors", {})) != set(expected_shapes)):
        raise q.QualificationError("native compact snapshot schema differs")
    if (returned_cap != budget["cap_bytes"] or used != budget["declared_exact_bytes"]
            or used > returned_cap):
        raise q.QualificationError("native snapshot byte-bound evidence differs")
    decoded = q.decode_snapshot(raw)
    expected_dtypes = {
        "selected_rows": np.dtype(np.int32),
        "segment_initial_valid": np.dtype(np.int32),
        "tail_valid": np.dtype(np.int32),
    }
    for name, shape in expected_shapes.items():
        value = decoded.get(name)
        dtype = expected_dtypes.get(name, np.dtype(np.float32))
        if not isinstance(value, np.ndarray) or value.shape != shape or value.dtype != dtype:
            raise q.QualificationError(
                f"native compact tensor {name} shape/dtype differs")
    expected_decoders = {
        f"decoder_bank_{bank}_buffer_{buffer}": (
            PRIMARY_ROWS_PER_BUFFER if bank == 0 else ROWS_PER_FROZEN_BANK,
            ACTION_MASK_WIDTH + 1,
        )
        for bank in range(FROZEN_BANKS + 1)
        for buffer in range(NUM_BUFFERS)
    }
    observed_decoders = {
        name: value for name, value in decoded.items()
        if name.startswith("decoder_bank_")
    }
    if set(observed_decoders) != set(expected_decoders):
        raise q.QualificationError("native compact decoder schema differs")
    for name, shape in expected_decoders.items():
        value = observed_decoders[name]
        if value.shape != shape or value.dtype != np.dtype(np.float32):
            raise q.QualificationError(
                f"native compact decoder {name} shape/dtype differs")
    return decoded, {"max_bytes": returned_cap, "used_bytes": used}


def array_set_sha256(arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for key in sorted(arrays):
        value = arrays[key]
        digest.update(key.encode("utf-8") + b"\0")
        digest.update(str(value.dtype).encode("ascii") + b"\0")
        digest.update(repr(value.shape).encode("ascii") + b"\0")
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def validate_graph_cycle(
    before: Mapping[str, Any], after: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    roles = ("rollout", "tail", "train")
    expected = {
        "rollout": int(config["train"]["horizon"]) * int(config["vec"]["num_buffers"]),
        "tail": int(config["vec"]["num_buffers"]),
        "train": (
            int(config["vec"]["total_agents"]) * int(config["train"]["horizon"])
            // int(config["train"]["minibatch_size"])
            * int(config["train"]["replay_ratio"])
        ),
    }
    if before.get("cudagraphs") != q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS or after.get(
        "cudagraphs"
    ) != q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS:
        raise q.QualificationError("graph execution accessor reports wrong graph mode")
    graph_delta, eager_delta = {}, {}
    for role in roles:
        if before.get("captured", {}).get(role) is not True or after.get(
            "captured", {}
        ).get(role) is not True:
            raise q.QualificationError(f"{role} CUDA graph was not captured")
        if before.get("handles_ready", {}).get(role) is not True or after.get(
            "handles_ready", {}
        ).get(role) is not True:
            raise q.QualificationError(f"{role} CUDA graph handle is not ready")
        graph_delta[role] = int(after["graph_launch_counts"][role]) - int(
            before["graph_launch_counts"][role]
        )
        eager_delta[role] = int(after["eager_execution_counts"][role]) - int(
            before["eager_execution_counts"][role]
        )
        if graph_delta[role] != expected[role] or eager_delta[role] != 0:
            raise q.QualificationError(
                f"{role} execution delta graph={graph_delta[role]} "
                f"eager={eager_delta[role]} expected graph={expected[role]} eager=0"
            )
    return {"expected_graph_delta": expected, "graph_delta": graph_delta,
            "eager_delta": eager_delta}


def profile_config(seed: int, ratio_call_limit: int = 64) -> dict[str, Any]:
    ratio_call_limit = q._int(ratio_call_limit, "ratio call limit", minimum=MIN_GRAPH_TRAIN_CALLS)
    config = q.qualification_args(
        cudagraphs=q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS,
        seed=seed,
        total_agents=TOTAL_AGENTS,
        num_buffers=NUM_BUFFERS,
        num_threads=16,
        horizon=64,
        max_decisions=64,
        hidden_size=512,
        num_layers=3,
        frozen_banks=FROZEN_BANKS,
        frozen_bank_pct=FROZEN_BANK_PCT,
        learning_rate=0.0,
        minibatch_size=16384,
    )
    config["env"].update(
        scripted_opponent=1,
        scripted_opponent_type=0,
        scripted_opponent_team=1,
        scripted_bank_mask=SCRIPTED_BANK_MASK,
    )
    # Native epochs advance once per full rollout, not per minibatch. Reserve
    # the complete declared coverage budget before constructing the backend.
    config["train"]["total_timesteps"] = (
        TOTAL_AGENTS * config["train"]["horizon"] * ratio_call_limit
    )
    return config


def validate_profile_layout(report: Mapping[str, Any]) -> dict[str, Any]:
    """Require every primary/frozen bank and buffer at its exact row count."""
    entries = q._state_entries(report, FROZEN_BANKS + 1, NUM_BUFFERS)
    if report.get("agents_per_buffer") != AGENTS_PER_BUFFER:
        raise q.QualificationError("eight-bank agents_per_buffer is not 1024")
    if report.get("bank_layout") != EXPECTED_LAYOUT:
        raise q.QualificationError(
            f"eight-bank row layout differs: {report.get('bank_layout')}"
        )
    observed: list[dict[str, Any]] = []
    for entry in entries:
        bank, buffer = int(entry["bank"]), int(entry["buffer"])
        expected = PRIMARY_ROWS_PER_BUFFER if bank == 0 else ROWS_PER_FROZEN_BANK
        actual = int(entry["active_rows"])
        if actual != expected:
            raise q.QualificationError(
                f"recurrent group bank={bank} buffer={buffer} has {actual} rows; "
                f"expected {expected}"
            )
        observed.append({
            "group": "primary" if bank == 0 else f"frozen_bank_{bank - 1}",
            "bank": bank, "buffer": buffer,
            "expected_rows": expected, "observed_rows": actual,
        })
    if len(observed) != EXPECTED_GROUPS:
        raise q.QualificationError("eight-bank recurrent group coverage is incomplete")
    primary, frozen = q.derive_row_partition(report, total_agents=TOTAL_AGENTS)
    if len(primary) != PRIMARY_ROWS_PER_BUFFER * NUM_BUFFERS:
        raise q.QualificationError("primary learner row total differs from 1072")
    if len(frozen) != FROZEN_ROWS_PER_BUFFER * NUM_BUFFERS:
        raise q.QualificationError("frozen row total differs from 976")
    if SCRIPTED_BANK_MASK.bit_count() != 2 or SCRIPTED_BANK_MASK >> FROZEN_BANKS:
        raise q.QualificationError("scripted bank mask does not select exactly two banks")
    return {
        "groups": observed,
        "group_count": len(observed),
        "primary_rows": sorted(primary),
        "frozen_rows": sorted(frozen),
        "scripted_bank_mask": SCRIPTED_BANK_MASK,
        "scripted_frozen_banks": [0, 1],
    }


def load_real_frozen_banks(
    backend: Any, pufferl: Any, manifest_path: Path, *,
    expected_implementation: Mapping[str, str], allow_qualification: bool,
) -> dict[str, Any]:
    """Load and hash the eight concrete pool blobs used by the experiment."""
    manifest_path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise q.QualificationError(f"cannot read frozen pool manifest: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise q.QualificationError("frozen pool manifest must be an object")
    seeds = manifest.get("seeds")
    if manifest.get("lineage_required") is not True:
        raise q.QualificationError(
            "frozen pool manifest must require current checkpoint lineage")
    manifest_qualification_only = manifest.get("qualification_only")
    if not isinstance(manifest_qualification_only, bool):
        raise q.QualificationError(
            "frozen pool manifest must declare qualification_only as a boolean")
    if manifest_qualification_only and not allow_qualification:
        raise q.QualificationError(
            "qualification-only frozen pool requires --allow-qualification")
    if not isinstance(seeds, list) or len(seeds) != FROZEN_BANKS:
        raise q.QualificationError("frozen pool manifest must contain exactly eight seeds")
    expected_bytes = q._int(
        manifest.get("expected_bytes"), "frozen pool expected_bytes", minimum=1
    )
    loaded: list[dict[str, Any]] = []
    for bank, entry in enumerate(seeds):
        if not isinstance(entry, Mapping) or entry.get("bank") != bank:
            raise q.QualificationError("frozen pool bank order is not canonical")
        relative = entry.get("file")
        if not isinstance(relative, str) or Path(relative).name != relative:
            raise q.QualificationError("frozen pool seed file is not a local basename")
        path = manifest_path.parent / relative
        if not path.is_file() or path.stat().st_size != expected_bytes:
            raise q.QualificationError(f"frozen bank {bank} blob size differs")
        digest = q.sha256(path)
        if digest != q._require_sha256(entry.get("sha256"), f"frozen bank {bank} digest"):
            raise q.QualificationError(f"frozen bank {bank} blob digest differs")
        lineage_relative = entry.get("lineage_file")
        if (not isinstance(lineage_relative, str) or
                Path(lineage_relative).name != lineage_relative):
            raise q.QualificationError(
                f"frozen bank {bank} lineage file is not a local basename")
        lineage_path = manifest_path.parent / lineage_relative
        if not lineage_path.is_file():
            raise q.QualificationError(f"frozen bank {bank} lineage is missing")
        lineage_sha = q.sha256(lineage_path)
        if lineage_sha != q._require_sha256(
                entry.get("lineage_sha256"), f"frozen bank {bank} lineage digest"):
            raise q.QualificationError(f"frozen bank {bank} lineage digest differs")
        try:
            lineage = checkpoint_lineage.validate_lineage(
                path, lineage_path, expected=dict(expected_implementation),
                require_eligible=not allow_qualification,
            )
            lineage_id = checkpoint_lineage.lineage_digest(lineage)
        except checkpoint_lineage.LineageError as exc:
            raise q.QualificationError(
                f"frozen bank {bank} lineage rejected: {exc}") from exc
        lineage_qualification_only = bool(
            lineage.get("ancestry", {}).get("qualification_only"))
        if lineage_qualification_only is not manifest_qualification_only:
            raise q.QualificationError(
                f"frozen bank {bank} qualification status differs from manifest")
        backend.load_frozen_bank(pufferl, bank, str(path))
        loaded.append({
            "bank": bank, "name": str(entry.get("name", "")),
            "file": relative, "bytes": expected_bytes, "sha256": digest,
            "lineage_file": lineage_relative, "lineage_sha256": lineage_sha,
            "lineage_digest": lineage_id,
            "qualification_only": lineage_qualification_only,
        })
    return {
        "manifest": str(manifest_path), "manifest_sha256": q.sha256(manifest_path),
        "loaded_bank_indices": list(range(8)), "seeds": loaded,
    }


def exercise_profile(
    backend: Any, pufferl: Any, config: Mapping[str, Any], directory: Path,
    *, ratio_call_limit: int,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Exercise strict rollout ownership and prove every learner row at LR zero."""
    q.require_zero_learning_rate(config, PROFILE)
    initial = backend.qualification_recurrent_state(pufferl, False)
    coverage = validate_profile_layout(initial)
    q.validate_zero_state(initial, expected_banks=9, expected_buffers=2)
    primary, frozen = set(coverage["primary_rows"]), set(coverage["frozen_rows"])
    snapshot_budget = snapshot_byte_budget(config)
    arrays: dict[str, np.ndarray] = {}
    calls: list[dict[str, np.ndarray]] = []
    before_path = directory / f"eight-bank-before-{os.getpid()}.bin"
    after_path = directory / f"eight-bank-after-{os.getpid()}.bin"
    backend.save_weights(pufferl, str(before_path))
    before = q.sha256(before_path)
    covered: set[int] = set()
    first_snapshot = False
    first_snapshot_evidence = None
    reset = None
    per_call_weights: list[str] = []
    ratio_summaries: list[dict[str, Any]] = []
    graph_cycles: list[dict[str, Any]] = []
    if not hasattr(backend, "qualification_graph_execution"):
        raise q.QualificationError("compiled graph-execution accessor is missing")
    try:
        while ((covered != primary or len(calls) < MIN_GRAPH_TRAIN_CALLS)
               and len(calls) < ratio_call_limit):
            graph_before = backend.qualification_graph_execution(pufferl)
            backend.rollouts(pufferl)
            fresh, snapshot_evidence = take_snapshot(backend, pufferl, snapshot_budget)
            if not first_snapshot:
                first_snapshot_evidence = {
                    **snapshot_evidence,
                    "decoded_sha256": array_set_sha256(fresh),
                    "decoded_fields": sorted(fresh),
                    "decoder_group_count": len([
                        key for key in fresh if key.startswith("decoder_bank_")
                    ]),
                }
                if first_snapshot_evidence["decoder_group_count"] != EXPECTED_GROUPS:
                    raise q.QualificationError("first snapshot lacks all recurrent groups")
                active = backend.qualification_recurrent_state(pufferl, False)
                validate_profile_layout(active)
                q.validate_nonzero_state(active, expected_banks=9, expected_buffers=2)
                first_snapshot = True
            # Keep only bounded hashes/field names from the full fresh batch;
            # releasing its large observations before train avoids overlapping
            # two qualification snapshots in host memory.
            del fresh
            backend.train(pufferl)  # exactly one owner consumes this fresh tail
            graph_after = backend.qualification_graph_execution(pufferl)
            graph_cycles.append(validate_graph_cycle(graph_before, graph_after, config))
            snap, _ = take_snapshot(backend, pufferl, snapshot_budget)
            selected = snap["selected_rows"].astype(np.int32, copy=False)
            ratios = snap["mb_ratio"].astype(np.float32, copy=False)
            index = len(calls)
            arrays[f"selected_{index}"] = selected
            arrays[f"ratio_{index}"] = ratios
            del snap
            calls.append({"selected_rows": selected, "ratios": ratios})
            ratio_summaries.append(summarize_ratio_call(
                selected, ratios,
                atol=q.RATIO_ATOL_BY_PRECISION[int(backend.precision_bytes)],
            ))
            rows = {int(v) for v in selected.reshape(-1).tolist()}
            if rows & frozen or not rows <= primary:
                raise q.QualificationError("PPO minibatch violated learner ownership")
            covered.update(rows)
            backend.save_weights(pufferl, str(after_path))
            digest = q.sha256(after_path)
            q.validate_weight_identity(before, digest)
            per_call_weights.append(digest)
            partial = directory / PARTIAL_ARTIFACT_NAME
            q.write_npz_atomic(partial, arrays)
            q.write_json_atomic(directory / "PROGRESS.json", {
                "completed_updates": len(calls),
                "ratio_call_limit": ratio_call_limit,
                "covered_primary_rows": len(covered),
                "required_primary_rows": len(primary),
                "weights_sha256": digest,
                "total_timesteps": config["train"]["total_timesteps"],
                "partial_artifact": str(partial),
                "partial_artifact_sha256": q.sha256(partial),
                "ratio_calls": ratio_summaries,
                "graph_execution_cycles": graph_cycles,
            })
            if reset is None:
                reset = backend.qualification_recurrent_state(pufferl, True)
                validate_profile_layout(reset)
                q.validate_zero_state(reset, expected_banks=9, expected_buffers=2)
        backend.save_weights(pufferl, str(after_path))
        after = q.sha256(after_path)
    finally:
        before_path.unlink(missing_ok=True)
        after_path.unlink(missing_ok=True)
    q.validate_weight_identity(before, after)
    ratio = q.validate_ratio_calls(
        calls, primary_rows=primary, frozen_rows=frozen,
        atol=q.RATIO_ATOL_BY_PRECISION[int(backend.precision_bytes)],
    )
    if len(calls) < MIN_GRAPH_TRAIN_CALLS:
        raise q.QualificationError("CUDA graph warmup/capture boundary was not crossed")
    return {
        "profile": PROFILE,
        "config": dict(config),
        "initialization_zero": True,
        "post_rollout_all_groups_nonzero": True,
        "explicit_reset_zero": True,
        "group_coverage": coverage,
        "rollout_calls": len(calls), "train_calls": len(calls),
        "tail_ownership": "one_fresh_rollout_per_train",
        "graph_warmup_epochs": q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS,
        "graph_capture_exercised": True,
        "graph_execution_cycles": graph_cycles,
        "snapshot_budget": snapshot_budget,
        "first_fresh_snapshot": first_snapshot_evidence,
        "weights_before_sha256": before, "weights_after_sha256": after,
        "per_call_weight_sha256": per_call_weights,
        "ratio_call_summaries": ratio_summaries,
        "ratio": ratio,
    }, arrays


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    backend, module, cuda = q._load_backend(Path(args.puffer_root))
    identity = q._module_identity(backend, module, Path(args.puffer_root))
    q.validate_module_identity(identity)
    screen_manifest = validate_screen_manifest(
        args.screen_manifest, args.screen_manifest_sha256, identity)
    patch_bundle_sha256 = screen_manifest["puffer_patch_bundle_sha256"]
    config = profile_config(args.seed, args.ratio_call_limit)
    pufferl = None
    result: dict[str, Any] = {
        "schema_version": 1, "qualification_only": True, "accepted": False,
        "profile": PROFILE, "identity": identity, "cuda_runtime_preflight": cuda,
        "config": config, "ratio_call_limit": args.ratio_call_limit,
        "screen_manifest": screen_manifest,
        "host": socket.gethostname(), "platform": platform.platform(),
    }
    try:
        pufferl = backend.create_pufferl(config)
        result["frozen_loading"] = load_real_frozen_banks(
            backend, pufferl, Path(args.league_manifest),
            expected_implementation={
                "source_sha256": identity["environment_sha256"],
                "compiled_module_sha256": identity["module_sha256"],
                "puffer_patch_bundle_sha256": patch_bundle_sha256,
            },
            allow_qualification=args.allow_qualification,
        )
        evidence, arrays = exercise_profile(
            backend, pufferl, config, output, ratio_call_limit=args.ratio_call_limit
        )
        result.update(evidence)
        q.bind_transition_integrity(backend, pufferl, result)
        artifact = output / "EIGHT_BANK_RECURRENT.npz"
        q.write_npz_atomic(artifact, arrays)
        result["artifact"] = str(artifact)
        result["artifact_sha256"] = q.sha256(artifact)
        result["accepted"] = True
        q.write_json_atomic(output / "EIGHT_BANK_RECURRENT.json", result)
        print(f"eight-bank recurrent qualification accepted -> {output}")
        return 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        progress_path = output / "PROGRESS.json"
        partial_path = output / PARTIAL_ARTIFACT_NAME
        if progress_path.is_file():
            result["progress"] = q._read_json(progress_path)
        if partial_path.is_file():
            result["failure_artifact"] = str(partial_path)
            result["failure_artifact_sha256"] = q.sha256(partial_path)
        q.write_json_atomic(output / "EIGHT_BANK_RECURRENT.json", result)
        raise
    finally:
        if pufferl is not None:
            backend.close(pufferl)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puffer-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--league-manifest", required=True, type=Path,
        help="eight-entry pool/league_seeds.json to load into the real banks",
    )
    parser.add_argument("--seed", type=int, default=271828)
    parser.add_argument("--ratio-call-limit", type=int, default=64)
    parser.add_argument("--screen-manifest", required=True, type=Path)
    parser.add_argument("--screen-manifest-sha256", required=True)
    parser.add_argument("--allow-qualification", action="store_true")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except q.QualificationError as exc:
        print(f"eight-bank qualification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

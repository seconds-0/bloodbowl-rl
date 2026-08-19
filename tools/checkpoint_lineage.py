#!/usr/bin/env python3
"""Content-addressed policy lineage for current Blood Bowl checkpoints.

Flat Puffer checkpoints carry no header, and obs-v4/obs-v5/obs-v6 plus
marginal/exact action policies have identical tensor shapes -- 2782 bytes of
observation and 16,066,560 bytes of weights for all three observation
revisions. This module is the single launch authority for proving that a blob
belongs to the current semantic lineage, and the observation version is the
ONLY thing that separates v4 from v5 from v6.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path


SCHEMA_VERSION = 1
OBSERVATION_ABI = "obs-v6"
OBSERVATION_VERSION = 6
ACTION_ABI = "exact-joint-v1"
POLICY_HIDDEN_SIZE = 512
POLICY_NUM_LAYERS = 3
POLICY_EXPANSION_FACTOR = 1
EXPECTED_CHECKPOINT_BYTES = 16_066_560
ALLOWED_INITIALIZATIONS = frozenset(("fresh", "lineage-v6"))
SHA256_KEYS = (
    "source_sha256",
    "compiled_module_sha256",
    "puffer_patch_bundle_sha256",
)
# A GRAFT is a reviewed lineage bridge across a source/patch-bundle change: at
# least one of the warm checkpoint / pool banks was produced on an OLD build
# and the new run publishes on the NEW build's digests. The run manifest
# declares the old identity plus a reason under these keys (all five or none)
# and the sidecar records them as `ancestry.grafted_from`, so the bridge is
# auditable rather than invisible. The warm itself may already be new-build
# (a rung after the graft, whose pool still holds old-build banks); the bridge
# is then the pool's, and warm_lineage_sha256 still names the warm it started
# from.
GRAFT_MANIFEST_KEYS = (
    "graft_from_source_sha256",
    "graft_from_module_sha256",
    "graft_from_patch_bundle_sha256",
    "graft_from_warm_lineage_sha256",
    "graft_reason",
)
GRAFTED_FROM_KEYS = (
    "warm_lineage_sha256",
    "source_sha256",
    "compiled_module_sha256",
    "puffer_patch_bundle_sha256",
    "reason",
)
GRAFT_REASON_MAX_CHARS = 200


class LineageError(RuntimeError):
    pass


def sha256_file(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(payload):
    return (json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) + "\n").encode("utf-8")


def sidecar_path(checkpoint):
    return Path(str(Path(checkpoint)) + ".lineage.json")


def _need_sha(value, label, allow_empty=False):
    if allow_empty and value == "":
        return value
    if (not isinstance(value, str) or len(value) != 64 or
            any(ch not in "0123456789abcdef" for ch in value)):
        raise LineageError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _need_int(value, label):
    if isinstance(value, bool):
        raise LineageError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LineageError(f"{label} must be an integer") from exc
    if str(parsed) != str(value):
        raise LineageError(f"{label} must be a canonical integer")
    return parsed


def _need_reason(value, label):
    if not isinstance(value, str) or not value.strip():
        raise LineageError(f"{label} must be a non-empty string")
    if len(value) > GRAFT_REASON_MAX_CHARS:
        raise LineageError(
            f"{label} must be at most {GRAFT_REASON_MAX_CHARS} characters")
    return value


def _need_bool_string(value, label):
    if str(value) not in ("0", "1"):
        raise LineageError(f"{label} must be 0 or 1")
    return str(value) == "1"


def _load_object(path, label):
    path = Path(path)
    if not path.is_file():
        raise LineageError(f"missing {label}: {path}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LineageError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LineageError(f"{label} must be a JSON object: {path}")
    return payload, raw


def lineage_from_run_manifest(checkpoint, run_manifest, *,
                              allow_eligible_publication=False):
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file():
        raise LineageError(f"missing checkpoint: {checkpoint}")
    manifest, manifest_raw = _load_object(run_manifest, "run manifest")
    if manifest.get("schema_version") != 1:
        raise LineageError(
            f"unsupported run manifest schema: {manifest.get('schema_version')!r}")

    observation_abi = manifest.get("observation_abi")
    observation_version = _need_int(
        manifest.get("observation_version"), "observation_version")
    action_abi = manifest.get("action_abi")
    if observation_abi != OBSERVATION_ABI:
        raise LineageError(
            f"observation_abi must be {OBSERVATION_ABI}, got {observation_abi!r}")
    if observation_version != OBSERVATION_VERSION:
        raise LineageError(
            f"observation_version must be {OBSERVATION_VERSION}, "
            f"got {observation_version}")
    if action_abi != ACTION_ABI:
        raise LineageError(
            f"action_abi must be {ACTION_ABI}, got {action_abi!r}")

    initialization = manifest.get("initialization")
    if initialization not in ALLOWED_INITIALIZATIONS:
        raise LineageError(
            f"initialization must be one of {sorted(ALLOWED_INITIALIZATIONS)}, "
            f"got {initialization!r}")
    qualification_only = _need_bool_string(
        manifest.get("qualification_only"), "qualification_only")
    if qualification_only and initialization != "fresh":
        raise LineageError("qualification-only output must use fresh initialization")
    # A fresh run may publish eligible lineage in exactly one case: it declared
    # itself the GENESIS of the lineage. Without that exception the rules form a
    # closed loop with no entry point -- eligible output requires non-fresh
    # initialization, non-fresh requires an eligible warm checkpoint and pool,
    # and eligible may only be published by an accepted screen -- so obs-v6
    # could never train at all. Measured on the training host: zero
    # .lineage.json files existed anywhere, i.e. no ancestor and no way to mint
    # one. The exception is narrow on purpose: the mode string must SAY genesis,
    # so an ordinary fresh canary still cannot become ancestry by accident, and
    # the caller must still be accepted-screen materialization (checked below).
    mode = manifest.get("mode")
    if initialization == "fresh" and not qualification_only \
            and mode != "native_fresh_v6_genesis":
        raise LineageError(
            "fresh initialization may only publish eligible lineage as declared "
            "genesis (mode native_fresh_v6_genesis)")
    if mode == "native_fresh_v6_genesis":
        if qualification_only:
            raise LineageError(
                "genesis output is eligible ancestry, not qualification-only")
        if initialization != "fresh":
            raise LineageError("genesis output must use fresh initialization")
    expected_mode = (
        "native_fresh_v6_qualification" if qualification_only
        else "native_fresh_v6_genesis" if mode == "native_fresh_v6_genesis"
        else "native_static_pool_reward_ablation")
    if manifest.get("mode") != expected_mode:
        raise LineageError(
            f"run manifest mode must be {expected_mode}, got "
            f"{manifest.get('mode')!r}")
    if not qualification_only and not allow_eligible_publication:
        raise LineageError(
            "eligible lineage may only be published by accepted screen "
            "result materialization")

    policy = {
        "hidden_size": _need_int(
            manifest.get("policy_hidden_size"), "policy_hidden_size"),
        "num_layers": _need_int(
            manifest.get("policy_num_layers"), "policy_num_layers"),
        "expansion_factor": _need_int(
            manifest.get("policy_expansion_factor"),
            "policy_expansion_factor"),
    }
    expected_policy = {
        "hidden_size": POLICY_HIDDEN_SIZE,
        "num_layers": POLICY_NUM_LAYERS,
        "expansion_factor": POLICY_EXPANSION_FACTOR,
    }
    if policy != expected_policy:
        raise LineageError(
            f"policy shape mismatch: {policy!r} != {expected_policy!r}")

    checkpoint_bytes = checkpoint.stat().st_size
    expected_bytes = _need_int(
        manifest.get("expected_checkpoint_bytes"),
        "expected_checkpoint_bytes")
    if expected_bytes != EXPECTED_CHECKPOINT_BYTES:
        raise LineageError(
            "expected_checkpoint_bytes must be "
            f"{EXPECTED_CHECKPOINT_BYTES}, got {expected_bytes}")
    if checkpoint_bytes != expected_bytes:
        raise LineageError(
            f"checkpoint is {checkpoint_bytes} bytes; run manifest expects "
            f"{expected_bytes}")

    implementation = {}
    for key in SHA256_KEYS:
        implementation[key] = _need_sha(manifest.get(key), key)

    warm_lineage = _need_sha(
        manifest.get("warm_lineage_sha256", ""),
        "warm_lineage_sha256", allow_empty=True)
    pool_lineage = _need_sha(
        manifest.get("pool_lineage_bundle_sha256", ""),
        "pool_lineage_bundle_sha256", allow_empty=True)
    if initialization == "fresh" and (warm_lineage or pool_lineage):
        raise LineageError("fresh initialization cannot declare warm/pool ancestry")
    if initialization == "lineage-v6" and not (warm_lineage and pool_lineage):
        raise LineageError("lineage-v6 requires warm and pool lineage digests")

    screen_sha = _need_sha(
        manifest.get("screen_manifest_sha256"), "screen_manifest_sha256")
    seed = _need_int(manifest.get("seed"), "seed")

    grafted_from = None
    present = [key for key in GRAFT_MANIFEST_KEYS if key in manifest]
    if present:
        if len(present) != len(GRAFT_MANIFEST_KEYS):
            missing = sorted(set(GRAFT_MANIFEST_KEYS) - set(present))
            raise LineageError(
                "graft_from_* keys are all-or-none; run manifest lacks "
                f"{missing}")
        if initialization != "lineage-v6":
            raise LineageError("a graft requires lineage-v6 initialization")
        grafted_from = {
            "warm_lineage_sha256": _need_sha(
                manifest.get("graft_from_warm_lineage_sha256"),
                "graft_from_warm_lineage_sha256"),
            "source_sha256": _need_sha(
                manifest.get("graft_from_source_sha256"),
                "graft_from_source_sha256"),
            "compiled_module_sha256": _need_sha(
                manifest.get("graft_from_module_sha256"),
                "graft_from_module_sha256"),
            "puffer_patch_bundle_sha256": _need_sha(
                manifest.get("graft_from_patch_bundle_sha256"),
                "graft_from_patch_bundle_sha256"),
            "reason": _need_reason(manifest.get("graft_reason"), "graft_reason"),
        }
        # The graft names the warm it started from; the manifest's
        # warm_lineage_sha256 is that sidecar's digest, so both must agree.
        if grafted_from["warm_lineage_sha256"] != warm_lineage:
            raise LineageError(
                "graft_from_warm_lineage_sha256 differs from warm_lineage_sha256")
        if (grafted_from["source_sha256"] == implementation["source_sha256"] and
                grafted_from["puffer_patch_bundle_sha256"]
                == implementation["puffer_patch_bundle_sha256"]):
            raise LineageError(
                "graft is a no-op: the declared old source/patch bundle equal "
                "the new build's, so there is nothing to graft; a module-only "
                "difference is a `rehost`, otherwise run an ordinary lineage-v6 "
                "arm")

    ancestry = {
        "initialization": initialization,
        # The producer's mode is bound here, not merely checked at create
        # time, because it is what distinguishes declared genesis from an
        # ordinary fresh canary. validate_lineage needs it to re-derive that
        # distinction, and binding it means the eligibility flag cannot be
        # edited into a lie without also editing a hashed field.
        "mode": mode,
        "qualification_only": qualification_only,
        "eligible": not qualification_only,
        "warm_lineage_sha256": warm_lineage,
        "pool_lineage_bundle_sha256": pool_lineage,
    }
    if grafted_from is not None:
        ancestry["grafted_from"] = grafted_from
    return {
        "schema_version": SCHEMA_VERSION,
        "checkpoint": {
            "bytes": checkpoint_bytes,
            "sha256": sha256_file(checkpoint),
        },
        "compatibility": {
            "observation_abi": observation_abi,
            "observation_version": observation_version,
            "action_abi": action_abi,
            "policy_hidden_size": policy["hidden_size"],
            "policy_num_layers": policy["num_layers"],
            "policy_expansion_factor": policy["expansion_factor"],
        },
        "implementation": implementation,
        "producer": {
            "run_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "screen_manifest_sha256": screen_sha,
            "seed": seed,
        },
        "ancestry": ancestry,
    }


def write_lineage(path, payload, replace=False):
    path = Path(path)
    body = canonical_bytes(payload)
    if path.exists():
        if path.read_bytes() == body:
            return path
        if not replace:
            raise LineageError(f"refusing to replace different lineage: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        temporary.write_bytes(body)
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def rehost_lineage(checkpoint, *, target_module, target_source_sha256,
                   target_patch_bundle_sha256, sidecar=None):
    """Re-bind an ELIGIBLE sidecar to a different compiled module.

    A checkpoint moved between hosts is validated against that host's build,
    and every eligibility check binds `compiled_module_sha256`. Two builds of
    the SAME environment source under the SAME Puffer patch stack differ only
    in compiler output, so a rehost is legitimate exactly when
    `source_sha256` and `puffer_patch_bundle_sha256` are byte-identical to
    the target's; the module digest is the one field that may change. The
    original sidecar's digest is recorded as `ancestry.rehosted_from` so the
    provenance chain stays auditable, and the checkpoint bytes are re-hashed
    so a substituted blob cannot ride the rehost.
    """
    checkpoint = Path(checkpoint)
    payload = validate_lineage(checkpoint, sidecar, require_eligible=True)
    target_module = Path(target_module)
    if not target_module.is_file():
        raise LineageError(f"missing target module: {target_module}")
    _need_sha(target_source_sha256, "target_source_sha256")
    _need_sha(target_patch_bundle_sha256, "target_patch_bundle_sha256")
    implementation = payload["implementation"]
    if implementation["source_sha256"] != target_source_sha256:
        raise LineageError(
            "rehost refused: environment source differs from the target build "
            f"({implementation['source_sha256'][:12]} != "
            f"{target_source_sha256[:12]}); that is a new lineage, not a rehost")
    if implementation["puffer_patch_bundle_sha256"] != target_patch_bundle_sha256:
        raise LineageError(
            "rehost refused: Puffer patch bundle differs from the target build "
            f"({implementation['puffer_patch_bundle_sha256'][:12]} != "
            f"{target_patch_bundle_sha256[:12]}); that is a new lineage, not a rehost")
    target_module_sha = sha256_file(target_module)
    if target_module_sha == implementation["compiled_module_sha256"]:
        raise LineageError("rehost is a no-op: the target module is already bound")
    rehosted = json.loads(json.dumps(payload))
    rehosted["implementation"]["compiled_module_sha256"] = target_module_sha
    rehosted["ancestry"]["rehosted_from"] = lineage_digest(payload)
    rehosted["checkpoint"]["sha256"] = sha256_file(checkpoint)
    rehosted["checkpoint"]["bytes"] = checkpoint.stat().st_size
    return rehosted


def graft_bridge(sidecars, *, current, old_source_sha256,
                 old_patch_bundle_sha256):
    """Classify validated warm/pool sidecars for a graft; return the old module.

    ``sidecars`` is a sequence of ``(label, payload)`` where each payload has
    already passed ``validate_lineage`` (eligible, hash-bound, obs-v6) with no
    implementation overrides. ``current`` is this build's three implementation
    digests. Every sidecar must bind EITHER this build exactly (source, module
    and patch bundle -- what lineage-v6 would demand) OR the declared old
    build's source and patch bundle with any module; anything else is refused.
    At least one sidecar must be old-build (else there is nothing to graft), and
    every old-build sidecar must record the same module, which is returned so
    the run manifest can carry it as graft_from_module_sha256.

    This is the single definition both the per-arm launcher and the screen plan
    writer use, so a graft the screen plans is a graft the launcher accepts. It
    is what lets a lineage keep chaining after a graft: the next rung's warm is
    new-build while its pool still holds old-build banks, and lineage-v6 alone
    would refuse that pool forever.
    """
    for key in SHA256_KEYS:
        _need_sha(current.get(key), f"current.{key}")
    _need_sha(old_source_sha256, "old_source_sha256")
    _need_sha(old_patch_bundle_sha256, "old_patch_bundle_sha256")
    if (old_source_sha256 == current["source_sha256"] and
            old_patch_bundle_sha256 == current["puffer_patch_bundle_sha256"]):
        raise LineageError(
            "graft refused: the declared old source/patch bundle ARE this "
            "build's, so there is nothing to graft; a module-only difference "
            "is a `rehost`, otherwise use lineage-v6")
    old_modules = {}
    for label, payload in sidecars:
        implementation = payload["implementation"]
        if all(implementation.get(key) == current[key] for key in SHA256_KEYS):
            continue
        if (implementation.get("source_sha256") == old_source_sha256 and
                implementation.get("puffer_patch_bundle_sha256")
                == old_patch_bundle_sha256):
            old_modules[label] = implementation["compiled_module_sha256"]
            continue
        raise LineageError(
            f"graft refused: {label} binds neither this build nor the declared "
            "old build (source "
            f"{implementation.get('source_sha256', '?')[:12]}, patch "
            f"{implementation.get('puffer_patch_bundle_sha256', '?')[:12]}, "
            f"module {implementation.get('compiled_module_sha256', '?')[:12]}); "
            "a same-source/same-patch module difference is a `rehost`")
    if not old_modules:
        raise LineageError(
            "graft refused as a no-op: every sidecar already binds this build, "
            "so there is nothing to graft; use lineage-v6 (or `rehost` for a "
            "module-only difference)")
    modules = sorted(set(old_modules.values()))
    if len(modules) != 1:
        raise LineageError(
            "graft refused: old-build sidecars record different compiled "
            "modules: " + ", ".join(
                f"{label}={module[:12]}" for label, module in sorted(
                    old_modules.items())))
    return modules[0]


def validate_lineage(checkpoint, sidecar=None, *, expected=None,
                     require_eligible=True):
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file():
        raise LineageError(f"missing checkpoint: {checkpoint}")
    sidecar = Path(sidecar) if sidecar is not None else sidecar_path(checkpoint)
    payload, raw = _load_object(sidecar, "checkpoint lineage")
    try:
        canonical = canonical_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise LineageError(f"checkpoint lineage is not canonical JSON: {sidecar}") from exc
    if raw != canonical:
        raise LineageError(f"checkpoint lineage is not canonical: {sidecar}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LineageError(
            f"unsupported checkpoint lineage schema: {payload.get('schema_version')!r}")

    checkpoint_record = payload.get("checkpoint")
    compatibility = payload.get("compatibility")
    implementation = payload.get("implementation")
    producer = payload.get("producer")
    ancestry = payload.get("ancestry")
    for name, value in (
        ("checkpoint", checkpoint_record),
        ("compatibility", compatibility),
        ("implementation", implementation),
        ("producer", producer),
        ("ancestry", ancestry),
    ):
        if not isinstance(value, dict):
            raise LineageError(f"checkpoint lineage {name} must be an object")

    # The observation revision is checked FIRST, explicitly, and with a message
    # that names the failure. obs-v4, obs-v5 and obs-v6 are all 2782-byte
    # observations producing 16,066,560-byte checkpoints, so the byte checks
    # below cannot see the difference and every other field can agree while the
    # semantics silently do not. A v4/v5 mixup of exactly this shape already
    # cost a 12B-step run; warm-starting an obs-v6 module from an obs-v5
    # sidecar would repeat it with no symptom other than a bad learning curve.
    sidecar_abi = compatibility.get("observation_abi")
    sidecar_version = compatibility.get("observation_version")
    if sidecar_abi != OBSERVATION_ABI or sidecar_version != OBSERVATION_VERSION:
        raise LineageError(
            "observation_abi/observation_version lineage mismatch: "
            "sidecar declares "
            f"{sidecar_abi!r}/{sidecar_version!r} but this module is "
            f"{OBSERVATION_ABI!r}/{OBSERVATION_VERSION!r}. Every observation "
            "revision has the same blob size, so this cannot be detected by "
            "checkpoint bytes -- there is no warm start, replay mix or curve "
            "comparison across the boundary without a reviewed bridge")

    actual_bytes = checkpoint.stat().st_size
    actual_sha = sha256_file(checkpoint)
    if actual_bytes != EXPECTED_CHECKPOINT_BYTES:
        raise LineageError(
            f"checkpoint is {actual_bytes} bytes; current ABI requires "
            f"{EXPECTED_CHECKPOINT_BYTES}")
    if checkpoint_record.get("bytes") != actual_bytes:
        raise LineageError("checkpoint byte count differs from lineage")
    if checkpoint_record.get("sha256") != actual_sha:
        raise LineageError("checkpoint SHA-256 differs from lineage")
    _need_sha(checkpoint_record.get("sha256"), "checkpoint.sha256")

    frozen_expected = {
        "observation_abi": OBSERVATION_ABI,
        "observation_version": OBSERVATION_VERSION,
        "action_abi": ACTION_ABI,
        "policy_hidden_size": POLICY_HIDDEN_SIZE,
        "policy_num_layers": POLICY_NUM_LAYERS,
        "policy_expansion_factor": POLICY_EXPANSION_FACTOR,
    }
    if expected:
        unsupported = sorted(set(expected) - set(SHA256_KEYS))
        if unsupported:
            raise LineageError(
                "expected overrides are limited to implementation digests; "
                f"unsupported keys: {unsupported}")
        for key, value in expected.items():
            _need_sha(value, key)
        frozen_expected.update(expected)
    for key, wanted in frozen_expected.items():
        section = implementation if key in SHA256_KEYS else compatibility
        actual = section.get(key)
        if actual != wanted:
            raise LineageError(
                f"{key} lineage mismatch: {actual!r} != {wanted!r}")
    for key in SHA256_KEYS:
        _need_sha(implementation.get(key), key)
    _need_sha(producer.get("run_manifest_sha256"),
              "producer.run_manifest_sha256")
    _need_sha(producer.get("screen_manifest_sha256"),
              "producer.screen_manifest_sha256")
    _need_int(producer.get("seed"), "producer.seed")

    qualification_only = ancestry.get("qualification_only")
    eligible = ancestry.get("eligible")
    if not isinstance(qualification_only, bool) or not isinstance(eligible, bool):
        raise LineageError("lineage eligibility fields must be booleans")
    if eligible == qualification_only:
        raise LineageError("lineage eligibility contradicts qualification status")
    initialization = ancestry.get("initialization")
    if initialization not in ALLOWED_INITIALIZATIONS:
        raise LineageError(f"invalid lineage initialization: {initialization!r}")
    warm_lineage = _need_sha(ancestry.get("warm_lineage_sha256", ""),
                             "warm_lineage_sha256", allow_empty=True)
    pool_lineage = _need_sha(
        ancestry.get("pool_lineage_bundle_sha256", ""),
        "pool_lineage_bundle_sha256", allow_empty=True)
    if initialization == "fresh":
        # Fresh output is ancestry-free by construction: it has no warm
        # checkpoint and no pool, so those two digests must stay empty either
        # way. Eligibility is the one axis where genesis differs -- it is the
        # root of the lineage, so it is eligible while every ordinary fresh
        # canary is not. The mode string carries that declaration and is itself
        # bound into the sidecar, so this cannot be loosened by editing the
        # eligibility flag alone.
        genesis = ancestry.get("mode") == "native_fresh_v6_genesis"
        if warm_lineage or pool_lineage:
            raise LineageError("fresh lineage must be ancestry-free")
        if genesis:
            if qualification_only or not eligible:
                raise LineageError(
                    "genesis lineage must be eligible and not qualification-only")
        elif not qualification_only or eligible:
            raise LineageError(
                "fresh lineage must be qualification-only and ineligible unless "
                "it is declared genesis")
    elif qualification_only or not eligible or not warm_lineage or not pool_lineage:
        raise LineageError(
            "lineage-v6 must be eligible and bind warm/pool ancestry")
    if "rehosted_from" in ancestry:
        _need_sha(ancestry.get("rehosted_from"), "ancestry.rehosted_from")
        if initialization == "fresh" and ancestry.get("mode") != "native_fresh_v6_genesis":
            raise LineageError("only eligible lineage may be rehosted")
    if "grafted_from" in ancestry:
        # Optional, and otherwise unchanged: a graft records the OLD build the
        # warm/pool came from. Its shape is exact -- the four digests, nothing
        # else -- and it is only meaningful on a warm-started lineage.
        grafted_from = ancestry.get("grafted_from")
        if not isinstance(grafted_from, dict):
            raise LineageError("ancestry.grafted_from must be an object")
        if sorted(grafted_from) != sorted(GRAFTED_FROM_KEYS):
            raise LineageError(
                "ancestry.grafted_from must contain exactly "
                f"{sorted(GRAFTED_FROM_KEYS)}, got {sorted(grafted_from)}")
        for key in GRAFTED_FROM_KEYS:
            if key == "reason":
                _need_reason(grafted_from.get(key), "ancestry.grafted_from.reason")
            else:
                _need_sha(grafted_from.get(key), f"ancestry.grafted_from.{key}")
        if initialization != "lineage-v6":
            raise LineageError("only lineage-v6 lineage may be grafted")
        if grafted_from["warm_lineage_sha256"] != warm_lineage:
            raise LineageError(
                "ancestry.grafted_from.warm_lineage_sha256 differs from "
                "ancestry.warm_lineage_sha256")
    if require_eligible and not eligible:
        raise LineageError("qualification-only checkpoint is not eligible ancestry")
    return payload


def lineage_digest(payload_or_path):
    if isinstance(payload_or_path, dict):
        body = canonical_bytes(payload_or_path)
    else:
        body = Path(payload_or_path).read_bytes()
    return hashlib.sha256(body).hexdigest()


def _parse_expected(items):
    result = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator or not key:
            raise LineageError(f"invalid --expect {item!r}; use key=value")
        if key not in SHA256_KEYS:
            raise LineageError(
                "--expect is limited to implementation digests; "
                f"unsupported key: {key}")
        result[key] = _need_sha(value, key)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--checkpoint", required=True)
    create.add_argument("--run-manifest", required=True)
    create.add_argument("--out")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--checkpoint", required=True)
    validate.add_argument("--lineage")
    validate.add_argument("--expect", action="append", default=[])
    validate.add_argument("--allow-qualification", action="store_true")
    rehost = subparsers.add_parser(
        "rehost", help="re-bind an eligible sidecar to another build of the "
        "same source + patch bundle (writes <out>, default in place)")
    rehost.add_argument("--checkpoint", required=True)
    rehost.add_argument("--lineage")
    rehost.add_argument("--target-module", required=True)
    rehost.add_argument("--target-source-sha256", required=True)
    rehost.add_argument("--target-patch-bundle-sha256", required=True)
    rehost.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        if args.command == "rehost":
            payload = rehost_lineage(
                args.checkpoint, sidecar=args.lineage,
                target_module=args.target_module,
                target_source_sha256=args.target_source_sha256,
                target_patch_bundle_sha256=args.target_patch_bundle_sha256)
            output = Path(args.out) if args.out else sidecar_path(args.checkpoint)
            write_lineage(output, payload, replace=True)
            print(lineage_digest(payload), output)
        elif args.command == "create":
            payload = lineage_from_run_manifest(
                args.checkpoint, args.run_manifest)
            output = Path(args.out) if args.out else sidecar_path(args.checkpoint)
            write_lineage(output, payload)
            print(lineage_digest(payload), output)
        else:
            expected = _parse_expected(args.expect)
            payload = validate_lineage(
                args.checkpoint, args.lineage, expected=expected,
                require_eligible=not args.allow_qualification)
            print(lineage_digest(payload),
                  Path(args.lineage) if args.lineage else sidecar_path(args.checkpoint))
    except LineageError as exc:
        parser.exit(1, f"checkpoint_lineage: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

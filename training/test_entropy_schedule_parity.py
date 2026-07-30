"""Red source, installer, and authorization contracts for entropy parity.

The executable schedule and raw-artifact oracle lives in
``verify_entropy_schedule_parity.py``.  This suite watches the Puffer patch
boundary that cannot execute on a non-NVIDIA development host: stable device
state, graph ordering, raw pre-narrowing validation, compiled markers, patch
stack ownership, and the deliberately retained production guards.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "training"
PATCH = TRAINING / "puffer_entropy_schedule_parity.patch"
QUALIFICATION_PATCH = TRAINING / "puffer_recurrent_cuda_qualification.patch"
INSTALLER = ROOT / "tools/install_puffer_env.sh"
SCREEN = ROOT / "tools/run_reward_screen.sh"
ARM = ROOT / "tools/run_reward_ablation.sh"
COMPILED_LEDGER = TRAINING / "puffer_compiled_backend_sources.txt"

CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"


def _added_text(patch: Path) -> str:
    if not patch.is_file():
        raise AssertionError(
            "watched fail: training/puffer_entropy_schedule_parity.patch "
            "does not exist"
        )
    additions = []
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions.append(line[1:])
    return "\n".join(additions)


def _patch_names(source: str) -> list[str]:
    return re.findall(r'training/([^"/]+\.patch)', source)


def _selected_puffer_source(relative: str) -> str | None:
    root = os.environ.get("PUFFER_ENTROPY_TEST_ROOT")
    if not root:
        return None
    path = Path(root).resolve() / relative
    if not path.is_file():
        raise AssertionError(f"selected Puffer source is missing: {path}")
    return path.read_text(encoding="utf-8")


def _source_or_additions(relative: str) -> str:
    selected = _selected_puffer_source(relative)
    if selected is not None:
        return selected
    return _added_text(PATCH)


class EntropySchedulePatchStackTests(unittest.TestCase):
    def test_patch_is_owned_once_in_every_causal_stack(self) -> None:
        self.assertTrue(
            PATCH.is_file(),
            "watched fail: create the reviewed entropy schedule patch",
        )
        installer = INSTALLER.read_text(encoding="utf-8")
        screen = SCREEN.read_text(encoding="utf-8")
        arm = ARM.read_text(encoding="utf-8")

        self.assertIn(
            'ENTROPY_SCHEDULE_PATCH="$ROOT/training/'
            'puffer_entropy_schedule_parity.patch"',
            installer,
        )
        for marker in (
            '"$ENTROPY_SCHEDULE_PATCH"',
            "entropy_schedule_sources_valid",
            "entropy_schedule_contract",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, installer)

        installer_order = (
            installer.index("# Frozen PPO rows"),
            installer.index("# Entropy-schedule objective parity"),
            installer.index("# Bounded CUDA qualification surfaces"),
        )
        self.assertEqual(installer_order, tuple(sorted(installer_order)))

        for source in (screen, arm):
            names = _patch_names(source)
            self.assertEqual(
                names.count("puffer_entropy_schedule_parity.patch"),
                1,
            )
            self.assertLess(
                names.index("puffer_frozen_prio_mask.patch"),
                names.index("puffer_entropy_schedule_parity.patch"),
            )
            self.assertLess(
                names.index("puffer_entropy_schedule_parity.patch"),
                names.index("puffer_recurrent_cuda_qualification.patch"),
            )

        final_reverse = installer.split(
            "for overlapping_patch in", 1
        )[1].split("; do", 1)[0]
        self.assertIn('"$ENTROPY_SCHEDULE_PATCH"', final_reverse)

    def test_compiled_source_registry_already_closes_over_changed_sources(
        self,
    ) -> None:
        entries = [
            line.strip()
            for line in COMPILED_LEDGER.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(len(entries), 14)
        for expected in (
            "pufferlib/pufferl.py",
            "pufferlib/torch_pufferl.py",
            "src/bindings.cu",
            "src/bindings_cpu.cpp",
            "src/pufferlib.cu",
        ):
            self.assertIn(expected, entries)

    def test_qualification_guard_is_recut_but_shell_guards_remain(self) -> None:
        qualification_patch = QUALIFICATION_PATCH.read_text(encoding="utf-8")
        self.assertNotIn(
            "CUDA graph training with entropy annealing is disabled until",
            qualification_patch,
            "the constructor guard must be removed by recutting the "
            "qualification patch, not deleted by a later patch",
        )

        arm = ARM.read_text(encoding="utf-8")
        screen = SCREEN.read_text(encoding="utf-8")
        arm_guard = (
            'if [ "$DRY_RUN" != "1" ] && '
            '[ "$CUDAGRAPHS" -ge 0 ] && '
            '[ "$ANNEAL_ENT_COEF" = "1" ]; then'
        )
        screen_guard = (
            'if [ "$PLAN_ONLY" != "1" ] && '
            '[ "$CUDAGRAPHS" -ge 0 ] && '
            '[ "$ANNEAL_ENT_COEF" = "1" ]; then'
        )
        self.assertIn(arm_guard, arm)
        self.assertIn(screen_guard, screen)
        self.assertLess(arm.index(arm_guard), arm.index('META_ARGS=('))
        self.assertLess(
            screen.index(screen_guard),
            screen.index('mkdir -p "$OUT_DIR"'),
        )
        for source in (arm, screen):
            self.assertIn("BLOCKED_UNQUALIFIED_ENTROPY_SCHEDULE", source)
            self.assertIn("implemented_pending_nvidia", source)


class NativeEntropyObjectiveSourceTests(unittest.TestCase):
    def test_device_scalar_is_stable_fp32_and_kernel_owned(self) -> None:
        source = _source_or_additions("src/pufferlib.cu")
        for marker in (
            "const float* ent_coef",
            "FloatTensor ent_coef",
            ".ent_coef = {.shape = {1}}",
            "alloc_register(alloc, &bufs.ent_coef)",
            "float ent_coef = *a.ent_coef",
            "LOSS_ENT_COEF",
            "LOSS_ENT_TERM",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

        self.assertIn("-ent_coef * total_entropy", source)
        self.assertIn("dL * (-ent_coef)", source)
        self.assertNotIn(
            "dL * (-a.ent_coef)",
            source,
            "gradient must use the one kernel-local device value",
        )
        self.assertNotIn(
            "- a.ent_coef * total_entropy",
            source,
            "forward loss must use the one kernel-local device value",
        )

    def test_checked_same_stream_copy_and_successful_epoch_commit(self) -> None:
        source = _selected_puffer_source("src/pufferlib.cu")
        if source is None:
            additions = _added_text(PATCH)
            for marker in (
                "cudaMemcpyAsync",
                "cudaMemcpyHostToDevice",
                "train_stream",
                "entropy coefficient copy failed",
                "training CUDA execution failed",
            ):
                self.assertIn(marker, additions)
            return

        copy_at = source.index("cudaMemcpyAsync(\n        pufferl.ppo_bufs_puf.ent_coef.data")
        replay_at = source.index(
            "cudaGraphLaunch(\n                    pufferl.train_cudagraph",
            copy_at,
        )
        capture_at = source.index("cudaStreamBeginCapture", copy_at)
        self.assertLess(copy_at, replay_at)
        self.assertLess(copy_at, capture_at)
        copy_end = source.index(";", copy_at)
        self.assertIn("train_stream", source[copy_at:copy_end])

        synchronize = source.index(
            "cudaStreamSynchronize(train_stream)", replay_at
        )
        epoch_commit = source.index("pufferl.epoch =", synchronize)
        self.assertLess(synchronize, epoch_commit)

    def test_warmup_restores_scalar_and_all_schedule_evidence(self) -> None:
        source = _source_or_additions("src/pufferlib.cu")
        for marker in (
            "entropy_schedule_update_count",
            "entropy_loss_minibatch_count",
            "entropy_first_update",
            "entropy_last_update",
            "entropy_first_coefficient",
            "entropy_last_coefficient",
            "entropy_schedule_valid",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        self.assertGreaterEqual(
            source.count("ppo_bufs_puf.ent_coef.data"),
            3,
            "allocate/use/reset must all name the stable scalar",
        )

    def test_profile_fixture_uses_mutable_device_coefficient(self) -> None:
        source = _source_or_additions("tests/profile_kernels.cu")
        for marker in (
            "ent_coef_t",
            "alloc_register(&p->alloc, &p->ent_coef_t)",
            ".ent_coef = p->ent_coef_t.data",
            "LOSS_ENT_COEF",
            "LOSS_ENT_TERM",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)


class EntropyValidationAndTelemetrySourceTests(unittest.TestCase):
    def test_torch_helper_uses_applied_fp32_value_and_success_commit(self) -> None:
        source = _source_or_additions("pufferlib/torch_pufferl.py")
        for marker in (
            f'ENTROPY_SCHEDULE_CONTRACT = "{CONTRACT}"',
            "def entropy_schedule_point(",
            '"c_real"',
            '"c_applied"',
            "current_ent_coef",
            "entropy_term",
            "total_loss",
            "entropy_schedule_contract",
            "entropy_applied_update_index",
            "entropy_loss_minibatch_count",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        self.assertNotIn(
            "- config['ent_coef']*entropy_loss",
            source,
            "Torch may not retain the fixed-base objective",
        )
        self.assertNotIn(
            "self.total_epochs = max(1,",
            source,
            "zero-update configurations must fail rather than coerce",
        )

    def test_raw_validation_precedes_native_narrowing_and_cuda_discovery(
        self,
    ) -> None:
        source = _source_or_additions("src/bindings.cu")
        for marker in (
            "anneal_ent_coef must be an exact boolean or 0/1",
            "ent_coef must be finite, nonnegative, and representable as float32",
            "min_ent_coef_ratio must be finite and in [0, 1]",
            "training has zero complete updates",
            "training has zero minibatches per update",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

        selected = _selected_puffer_source("src/bindings.cu")
        if selected is not None:
            validate_at = selected.index(
                "anneal_ent_coef must be an exact boolean or 0/1"
            )
            narrow_at = selected.index("hypers.anneal_ent_coef =", validate_at)
            cuda_at = selected.index("cudaGetDeviceCount", validate_at)
            self.assertLess(validate_at, narrow_at)
            self.assertLess(validate_at, cuda_at)

    def test_shared_python_validation_is_explicit_and_repeated_per_rank(
        self,
    ) -> None:
        source = _source_or_additions("pufferlib/pufferl.py")
        for marker in (
            "validate_entropy_schedule_config",
            "training has zero complete updates",
            "training has zero minibatches per update",
            "validate_config(args)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)
        selected = _selected_puffer_source("pufferlib/pufferl.py")
        if selected is not None:
            validator = selected[
                selected.index("def validate_entropy_schedule_config"):
                selected.index("def guard_scripted_training")
            ]
            self.assertNotIn("assert ", validator)
            train = selected[selected.index("def train("):]
            self.assertGreaterEqual(
                train.count("validate_config(args)"),
                2,
                "effective per-rank configuration must be revalidated",
            )

    def test_compiled_markers_and_closed_interval_telemetry_exist(self) -> None:
        for relative in ("src/bindings.cu", "src/bindings_cpu.cpp"):
            source = _source_or_additions(relative)
            self.assertIn(
                f'm.attr("entropy_schedule_contract") = "{CONTRACT}";',
                source,
            )

        native = _source_or_additions("src/bindings.cu")
        for marker in (
            '"schedule_update_count"',
            '"loss_minibatch_count"',
            '"first_update_index"',
            '"last_update_index"',
            '"first_effective_coefficient"',
            '"last_effective_coefficient"',
            '"interval_role"',
            '"entropy_term"',
            '"entropy_coefficient"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, native)


if __name__ == "__main__":
    unittest.main()

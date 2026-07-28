#!/usr/bin/env python3

from __future__ import annotations

import math
from pathlib import Path
import re
import tempfile
import unittest

from tools import ci_strict_environment_config as strict_ci


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_CONFIG_HEADER = ROOT / "puffer/bloodbowl/environment_config.h"


def _native_ledger_key_domains() -> dict[str, str]:
    source = ENVIRONMENT_CONFIG_HEADER.read_text(encoding="utf-8")
    match = re.search(
        r"#define\s+BBE_ENVIRONMENT_CONFIG_LEDGER\(X\)\s*\\\n" r"(?P<body>.*?)\n\n",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError("missing BBE_ENVIRONMENT_CONFIG_LEDGER")
    joined = re.sub(r"\\\n\s*", " ", match.group("body"))
    entries = re.findall(
        r"\bX\(\s*([a-z0-9_]+)\s*,\s*[^,]+?\s*,\s*"
        r"[^,]+?\s*,\s*([A-Z0-9_]+)\s*,\s*[^)]+?\)",
        joined,
    )
    if len(entries) != strict_ci.ENVIRONMENT_CONFIG_KEY_COUNT:
        raise AssertionError(
            f"parsed {len(entries)} environment ledger rows; expected "
            f"{strict_ci.ENVIRONMENT_CONFIG_KEY_COUNT}"
        )
    return dict(entries)


class StrictEnvironmentConfigCITests(unittest.TestCase):
    def test_checked_in_dependency_and_raylib_pins_are_exact(self):
        self.assertEqual(
            strict_ci._read_requirement_pins(ROOT),
            strict_ci.EXPECTED_REQUIREMENTS,
        )
        self.assertEqual(
            strict_ci._read_raylib_digest(ROOT),
            strict_ci.RAYLIB_SHA256,
        )

    def test_invalid_subprocess_matrix_covers_every_boundary_class(self):
        transport_and_structure = {
            "nonstring-key",
            "bytes-key",
            "string-subclass-key",
            "empty-key",
            "embedded-nul-key",
            "nonascii-key",
            "lone-surrogate-key",
            "overlong-key",
            "nonnumeric-value",
            "numeric-subclass",
            "integer-subclass",
            "custom-float-protocol",
            "integer-transport-overflow",
            "integer-exact-double-overflow",
            "unknown-numeric-key",
            "environment-cardinality",
            "environment-huge-cardinality",
        }
        additional_domain_extremes = {
            "seed-nan",
            "reward-nan",
            "gamma-nan",
            "gamma-float32-underflow",
        }
        ordering_cases = {"invalid-env-before-vec-geometry"}
        required = (
            transport_and_structure
            | set(strict_ci.NATIVE_LEDGER_DOMAIN_CASES.values())
            | additional_domain_extremes
            | ordering_cases
            | set(strict_ci.CROSS_FIELD_CASES)
        )
        self.assertEqual(set(strict_ci.INVALID_CASES), required)
        for name, (factory, diagnostic) in strict_ci.INVALID_CASES.items():
            with self.subTest(name=name):
                config = factory(30)
                self.assertIsInstance(config, dict)
                self.assertTrue(config)
                self.assertIsInstance(diagnostic, str)
                self.assertTrue(diagnostic)
        ledger_key_domains = _native_ledger_key_domains()
        ledger_domains = set(ledger_key_domains.values())
        self.assertEqual(len(ledger_domains), 19)
        self.assertEqual(
            set(strict_ci.NATIVE_LEDGER_DOMAIN_CASES),
            ledger_domains,
        )
        domain_cases = tuple(strict_ci.NATIVE_LEDGER_DOMAIN_CASES.values())
        self.assertEqual(len(domain_cases), len(set(domain_cases)))
        self.assertEqual(len(domain_cases), len(ledger_domains))
        self.assertLessEqual(set(domain_cases), set(strict_ci.INVALID_CASES))
        for domain, case_name in strict_ci.NATIVE_LEDGER_DOMAIN_CASES.items():
            with self.subTest(domain=domain, case=case_name):
                factory, _diagnostic = strict_ci.INVALID_CASES[case_name]
                config = factory(30)
                self.assertEqual(len(config), 1)
                key = next(iter(config))
                self.assertEqual(ledger_key_domains.get(key), domain)
        self.assertEqual(
            strict_ci.CROSS_FIELD_CASES,
            (
                "reward-cross-field-conflict",
                "bank-inert-selector-cross-field",
                "bank-multiple-selectors-cross-field",
            ),
        )
        self.assertEqual(
            set(strict_ci.INVALID_VEC_OVERRIDES),
            {"invalid-env-before-vec-geometry"},
        )
        invalid_vec = strict_ci.INVALID_VEC_OVERRIDES["invalid-env-before-vec-geometry"]
        self.assertEqual(invalid_vec["num_buffers"], 0)
        self.assertTrue(
            math.isnan(invalid_vec["total_agents"]),
        )
        self.assertEqual(
            strict_ci.VALID_PROFILE_NAMES,
            (
                "full-51-key",
                "empty-defaults",
                "sparse-qualification",
                "exact-bool-transport",
                "scripted-both",
            ),
        )

    def test_compiled_identity_and_requirements_options_are_closed(self):
        self.assertEqual(strict_ci.EXPECTED_OBSERVATION_ABI, "obs-v6")
        self.assertEqual(strict_ci.EXPECTED_OBSERVATION_VERSION, 6)
        self.assertEqual(strict_ci.EXPECTED_ACTION_ABI, "exact-joint-v1")
        self.assertEqual(
            strict_ci.ROLLOUT_TRANSITION_CONTRACT,
            "tail-bootstrap-v1",
        )
        self.assertEqual(strict_ci.UNRELATED_ENVIRONMENT, "minimal")
        self.assertEqual(strict_ci.UNRELATED_TOTAL_AGENTS, 8)
        self.assertEqual(
            strict_ci.EXPECTED_REQUIREMENT_OPTIONS,
            ("--extra-index-url https://download.pytorch.org/whl/cpu",),
        )

    def test_full_installed_config_requires_51_finite_numeric_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = Path(temporary)
            config = puffer / "config/bloodbowl.ini"
            config.parent.mkdir(parents=True)
            config.write_text(
                "[env]\n"
                + "\n".join(
                    f"key_{index} = {index}"
                    for index in range(strict_ci.ENVIRONMENT_CONFIG_KEY_COUNT)
                )
                + "\n",
                encoding="utf-8",
            )
            observed = strict_ci.load_full_environment_config(puffer)
            self.assertEqual(len(observed), 51)
            self.assertEqual(observed["key_50"], 50.0)

            config.write_text(
                "[env]\n"
                + "\n".join(
                    "key_0 = nan" if index == 0 else f"key_{index} = {index}"
                    for index in range(strict_ci.ENVIRONMENT_CONFIG_KEY_COUNT)
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                strict_ci.StrictConfigCIError,
                "not finite",
            ):
                strict_ci.load_full_environment_config(puffer)

            config.write_text("[env]\nseed = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(
                strict_ci.StrictConfigCIError,
                "expected 51",
            ):
                strict_ci.load_full_environment_config(puffer)

    def test_team_count_accepts_utf8_generated_comments(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = Path(temporary)
            header = puffer / "ocean/bloodbowl/bb/gen_teams.h"
            header.parent.mkdir(parents=True)
            header.write_text(
                "// generated display name: Équipe\n"
                "typedef enum {\n"
                "  BB_TEAM_ONE,\n"
                "  BB_TEAM_TWO,\n"
                "  BB_TEAM_COUNT\n"
                "} bb_team_id;\n",
                encoding="utf-8",
            )
            self.assertEqual(strict_ci.installed_team_count(puffer), 2)

    def test_stage_evidence_is_exactly_typed_and_closed(self):
        expected = {
            "normalize_calls": 1,
            "normalize_gil_held_calls": 1,
            "create_static_vec_calls": 0,
            "cuda_get_device_count_calls": 0,
            "create_pufferl_impl_calls": 0,
        }
        self.assertEqual(
            strict_ci._require_stage_record(
                dict(expected),
                expected,
                location="test",
            ),
            expected,
        )
        for changed in (
            {**expected, "extra": 0},
            {**expected, "normalize_calls": True},
            {**expected, "normalize_calls": 2},
        ):
            with self.assertRaises(strict_ci.StrictConfigCIError):
                strict_ci._require_stage_record(
                    changed,
                    expected,
                    location="test",
                )

    def test_venv_identity_preserves_the_lexical_python_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = Path(temporary) / "PufferLib"
            binary = puffer / ".venv/bin"
            binary.mkdir(parents=True)
            python = binary / "python"
            python.symlink_to("/usr/bin/python3")
            prefix, executable = strict_ci._validated_venv_identity(
                puffer,
                prefix=puffer / ".venv",
                executable=python,
            )
            self.assertEqual(prefix, (puffer / ".venv").resolve())
            self.assertEqual(executable, python.absolute())
            self.assertNotEqual(executable.resolve(), executable)

    def test_venv_identity_accepts_a_lexical_root_alias_like_macos_var(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "private"
            alias = base / "alias"
            real.mkdir()
            alias.symlink_to(real, target_is_directory=True)
            puffer = alias / "PufferLib"
            binary = puffer / ".venv/bin"
            binary.mkdir(parents=True)
            python = binary / "python"
            python.symlink_to("/usr/bin/python3")
            prefix, executable = strict_ci._validated_venv_identity(
                puffer,
                prefix=puffer / ".venv",
                executable=python,
            )
            self.assertEqual(prefix, (real / "PufferLib/.venv").resolve())
            self.assertEqual(
                executable,
                (alias / "PufferLib/.venv/bin/python").absolute(),
            )

    def test_workflow_has_a_separate_pinned_cpu_integration_job(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        ordinary_job = workflow[: workflow.index("  strict-environment-config-cpu:")]
        self.assertIn(
            "tools.test_strict_environment_config_contract",
            ordinary_job,
        )
        job = workflow[workflow.index("  strict-environment-config-cpu:") :]
        for fragment in (
            "runs-on: ubuntu-24.04",
            strict_ci.PUFFER_COMMIT,
            strict_ci.RAYLIB_SHA256,
            "training/strict_environment_config_ci_requirements.txt",
            "tools/ci_strict_environment_config.py run",
            "tools/ci_strict_environment_config.py test-role",
            "unrelated-environment",
            "PUFFER_STRICT_ENV_CONFIG_TESTING=1",
            "./build.sh bloodbowl --cpu",
            "./build.sh bloodbowl --fast",
            "./build.sh minimal --cpu",
            "tools/install_puffer_env.sh --check",
            "python3-dev",
            "python3-venv",
            "git",
            'PUFFER_STRICT_TEST_ROOT="$RUNNER_TEMP/PufferLib"',
            "tools.test_strict_environment_config_contract",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, job)
        first_install_at = job.index(
            'bash tools/install_puffer_env.sh "$RUNNER_TEMP/PufferLib"'
        )
        second_install_at = job.index(
            'bash tools/install_puffer_env.sh "$RUNNER_TEMP/PufferLib"',
            first_install_at + 1,
        )
        pinned_source_contract_at = job.index(
            "tools.test_strict_environment_config_contract"
        )
        build_cpu_at = job.index("./build.sh bloodbowl --cpu")
        build_fast_at = job.index("./build.sh bloodbowl --fast")
        drift_at = job.index("tools/install_puffer_env.sh --check")
        self.assertLess(second_install_at, pinned_source_contract_at)
        self.assertLess(build_cpu_at, build_fast_at)
        self.assertLess(build_fast_at, drift_at)
        self.assertNotIn("pip install .", job)
        self.assertNotIn("pip install -e", job)


if __name__ == "__main__":
    unittest.main()

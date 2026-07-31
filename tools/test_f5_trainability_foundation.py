#!/usr/bin/env python3
"""Watched contract tests for the sealed F5 trainability foundation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_FULL_BBS = (
    "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1"
)
EXPECTED_F5_BBS = (
    "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71"
)
EXPECTED_MATCH = (
    "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2"
)


class F5FoundationSourceContract(unittest.TestCase):
    def test_required_owned_surfaces_exist(self) -> None:
        for relative in (
            "puffer/bloodbowl/f5_trainability.h",
            "puffer/bloodbowl/f5_trainability_fixture.generated.h",
            "tools/f5_trainability_foundation.c",
            "tools/f5_trainability_diagnostics.c",
            "tools/check_f5_trainability_module.py",
            "tools/run_f5_trainability_foundation.py",
            "tools/verify_f5_trainability_foundation.py",
            "tools/install_f5_trainability_env.sh",
            "training/f5_trainability_env.json",
            "training/puffer_f5_trainability_role.patch",
            "training/test_f5_trainability_role.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_state_bank_authorization_remains_empty(self) -> None:
        source = (ROOT / "tools/state_bank_contract.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            source,
            r"PRODUCTION_AUTHORIZED_PRODUCER_KINDS(?:\s*:\s*[^=\n]+)?"
            r"\s*=\s*frozenset\(\)",
        )
        self.assertIn("AUTHORED_NOT_IMPLEMENTED", source)
        self.assertNotIn("f5-fixed-state-v1", source)

    def test_ordinary_build_is_explicitly_role_none(self) -> None:
        source = (ROOT / "puffer/bloodbowl/state_bank_build.h").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '#define PUFFER_QUALIFICATION_FIXTURE_ROLE "none"', source
        )
        self.assertIn(
            "#define PUFFER_QUALIFICATION_FIXTURE_ENABLED 0", source
        )

    def test_generator_watches_complete_hashes_and_identity(self) -> None:
        source = (ROOT / "tools/f5_trainability_foundation.c").read_text(
            encoding="utf-8"
        )
        for expected in (
            EXPECTED_FULL_BBS,
            EXPECTED_F5_BBS,
            EXPECTED_MATCH,
            "0xA9000019",
            "0xAE00001A",
            "ad_build_authored_proof_bundle",
            "ad_identify_authored_proof_bundle",
        ):
            self.assertIn(expected, source)

    def test_production_launchers_reject_fixture_roles(self) -> None:
        for relative in (
            "tools/run_reward_ablation.sh",
            "tools/run_reward_screen.sh",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("qualification_fixture_role", source, relative)
            self.assertIn("f5-fixed-state-v1", source, relative)

    def test_checked_in_environment_config_is_complete_and_objective_only(
        self,
    ) -> None:
        config = json.loads(
            (ROOT / "training/f5_trainability_env.json").read_text(
                encoding="ascii"
            )
        )
        self.assertEqual(len(config), 51)
        self.assertEqual(config["seed"], 1)
        self.assertEqual(config["max_decisions"], 8)
        self.assertEqual(config["macro_moves"], 0)
        self.assertEqual(config["reward_td"], 1.0)
        self.assertEqual(config["reward_win"], 0.0)
        self.assertEqual(config["reward_draw"], 0.0)
        for key, value in config.items():
            if key.startswith("reward_") and key != "reward_td":
                self.assertEqual(value, 0, key)
        self.assertEqual(config["demo_reset_pct"], 0.0)
        self.assertEqual(config["state_bank_kind"], 0)
        self.assertEqual(config["exclude_team"], -1)
        self.assertEqual(config["force_home_team"], -1)
        self.assertEqual(config["force_away_team"], -1)

    def test_evidence_worker_cannot_author_its_verdict(self) -> None:
        runner = (
            ROOT / "tools/run_f5_trainability_foundation.py"
        ).read_text(encoding="utf-8")
        verifier = (
            ROOT / "tools/verify_f5_trainability_foundation.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"accepted":', runner)
        self.assertNotIn('"passed":', runner)
        self.assertIn('{"accepted", "passed"}', verifier)
        self.assertIn('"accepted": True', verifier)
        self.assertLess(
            verifier.index("verdict = verify(validated_root)"),
            verifier.index("atomic_write(verdict_path"),
        )
        verify_body = verifier.split(
            "def verify(root: Path)", 1
        )[1].split("\ndef parse_args(", 1)[0]
        self.assertIn(
            "evidence_payload = read_regular_bytes(", verify_body
        )
        self.assertIn(
            "evidence_sha256 = sha256_bytes(evidence_payload)", verify_body
        )
        self.assertIn(
            "evidence_payload != canonical_json(evidence)", verify_body
        )
        self.assertNotIn("sha256_file(evidence_path)", verify_body)


class F5FoundationCliContract(unittest.TestCase):
    def _load_runner(self):
        path = ROOT / "tools/run_f5_trainability_foundation.py"
        spec = importlib.util.spec_from_file_location("f5_foundation_runner", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _load_verifier(self):
        path = ROOT / "tools/verify_f5_trainability_foundation.py"
        spec = importlib.util.spec_from_file_location(
            "f5_foundation_verifier", path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _prepared_startup_venv(
        self,
        directory: str,
        runner,
        *,
        include_system_site_packages: bool = False,
    ) -> tuple[pathlib.Path, pathlib.Path]:
        root = pathlib.Path(directory).resolve() / "PufferLib"
        site_packages = (
            root / ".venv/lib/python3.12/site-packages"
        )
        site_packages.mkdir(parents=True)
        bin_directory = root / ".venv/bin"
        bin_directory.mkdir()
        python312_name = shutil.which("python3.12")
        self.assertIsNotNone(python312_name)
        python312 = pathlib.Path(python312_name).resolve(strict=True)
        python312_version = subprocess.run(
            [
                str(python312),
                "-B",
                "-I",
                "-S",
                "-c",
                (
                    "import sys;"
                    "print('.'.join(str(v) "
                    "for v in sys.version_info[:3]))"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (bin_directory / "python").symlink_to(python312)
        (root / ".venv/pyvenv.cfg").write_text(
            "\n".join(
                (
                    f"home = {python312.parent}",
                    "include-system-site-packages = "
                    + (
                        "true"
                        if include_system_site_packages
                        else "false"
                    ),
                    f"version = {python312_version}",
                    f"executable = {python312}",
                    f"command = {python312} -m venv {root / '.venv'}",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (site_packages / runner.DEFAULT_EDITABLE_PTH_NAME).write_text(
            (
                "import "
                "__editable___pufferlib_4_0_0_finder;"
                "__editable___pufferlib_4_0_0_finder.install()\n"
            ),
            encoding="utf-8",
        )
        (
            site_packages / runner.DEFAULT_EDITABLE_FINDER_NAME
        ).write_text("def install():\n    return None\n", encoding="utf-8")
        (site_packages / "distutils-precedence.pth").write_text(
            "import _distutils_hack\n", encoding="utf-8"
        )
        finder_cache = site_packages / "__pycache__"
        finder_cache.mkdir()
        (
            finder_cache
            / "__editable___pufferlib_4_0_0_finder.cpython-312.pyc"
        ).write_bytes(b"bounded synthetic finder bytecode")
        return root, site_packages

    @staticmethod
    def _startup_tree_snapshot(root: pathlib.Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }

    def test_runner_has_closed_schema_and_no_training_mode(self) -> None:
        module = self._load_runner()
        self.assertEqual(
            module.EVIDENCE_SCHEMA, "bloodbowl-f5-foundation-evidence-v1"
        )
        self.assertEqual(module.FIXTURE_ROLE, "f5-fixed-state-v1")
        self.assertNotIn("train", module.COMMANDS)
        self.assertNotIn("ppo", module.COMMANDS)

    def test_startup_sealer_migrates_only_known_editable_hooks(
        self,
    ) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-migration-"
        ) as directory:
            root, site_packages = self._prepared_startup_venv(
                directory, runner
            )
            receipt = runner.seal_puffer_python_startup(root)
            self.assertEqual(
                receipt["schema"],
                "bloodbowl-f5-python-startup-input-v1",
            )
            self.assertEqual(
                receipt["pth_path"],
                (
                    ".venv/lib/python3.12/site-packages/"
                    "pufferlib-editable.pth"
                ),
            )
            self.assertEqual(
                (site_packages / "pufferlib-editable.pth").read_text(
                    encoding="utf-8"
                ),
                runner.SEALED_SITE_BOOTSTRAP_LINE + f"{root}\n",
            )
            self.assertEqual(
                receipt["executable_pth_files"],
                [receipt["pth_path"]],
            )
            self.assertTrue(receipt["base_sitecustomize_blocked"])
            self.assertTrue(receipt["runtime"]["sitecustomize_is_sys"])
            self.assertFalse(receipt["runtime"]["user_site_enabled"])
            self.assertEqual(receipt["runtime"]["isolated"], 1)
            self.assertEqual(receipt["runtime"]["no_site"], 0)
            self.assertNotIn(
                "/opt/homebrew/lib/python3.12/site-packages",
                receipt["runtime"]["sys_path"],
            )
            self.assertFalse(
                (site_packages / runner.DEFAULT_EDITABLE_PTH_NAME).exists()
            )
            self.assertFalse(
                (
                    site_packages / runner.DEFAULT_EDITABLE_FINDER_NAME
                ).exists()
            )
            self.assertFalse(
                (site_packages / "distutils-precedence.pth").exists()
            )
            self.assertEqual(
                runner.puffer_python_startup_input(root), receipt
            )

    def test_sealed_startup_blocks_base_sitecustomize_under_real_site(
        self,
    ) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-sitecustomize-"
        ) as directory:
            root, site_packages = self._prepared_startup_venv(
                directory, runner
            )
            runner.seal_puffer_python_startup(root)
            output = subprocess.run(
                [
                    str(root / ".venv/bin/python"),
                    "-B",
                    "-I",
                    "-c",
                    (
                        "import json,sitecustomize,sys;"
                        "print(json.dumps({"
                        "'sentinel':sitecustomize is sys,"
                        "'path':sys.path"
                        "},sort_keys=True,separators=(',',':')))"
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
                env={
                    "PATH": os.defpath,
                    "LC_ALL": "C",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            observed = json.loads(output.stdout)
            self.assertTrue(observed["sentinel"])
            self.assertEqual(observed["path"].count(str(root)), 1)
            self.assertEqual(observed["path"].count(str(site_packages)), 1)
            self.assertNotIn(
                "/opt/homebrew/lib/python3.12/site-packages",
                observed["path"],
            )

    def test_startup_validation_rejects_mutated_bootstrap_line(
        self,
    ) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-bootstrap-mutation-"
        ) as directory:
            root, site_packages = self._prepared_startup_venv(
                directory, runner
            )
            runner.seal_puffer_python_startup(root)
            (site_packages / runner.SEALED_EDITABLE_PTH_NAME).write_text(
                f"{root}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                runner.FoundationRunError,
                "points outside the pinned root",
            ):
                runner.puffer_python_startup_input(root)

    def test_invalid_pyvenv_rejection_does_not_mutate_startup_files(
        self,
    ) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-invalid-pyvenv-"
        ) as directory:
            root, site_packages = self._prepared_startup_venv(
                directory,
                runner,
                include_system_site_packages=True,
            )
            before = self._startup_tree_snapshot(root)
            with self.assertRaisesRegex(
                runner.FoundationRunError,
                "exclude system site-packages",
            ):
                runner.seal_puffer_python_startup(root)
            self.assertEqual(self._startup_tree_snapshot(root), before)
            self.assertFalse(
                (site_packages / runner.SEALED_EDITABLE_PTH_NAME).exists()
            )

    def test_startup_sealer_rejects_unknown_executable_hook_unchanged(
        self,
    ) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-unknown-hook-"
        ) as directory:
            root, site_packages = self._prepared_startup_venv(
                directory, runner
            )
            (site_packages / "attacker.pth").write_text(
                "import attacker\n", encoding="utf-8"
            )
            before = self._startup_tree_snapshot(root)
            with self.assertRaisesRegex(
                runner.FoundationRunError,
                "unknown executable startup hooks",
            ):
                runner.seal_puffer_python_startup(root)
            self.assertEqual(self._startup_tree_snapshot(root), before)

    def test_startup_sealer_rejects_escaped_venv_bin_directory(
        self,
    ) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-escaped-bin-"
        ) as directory:
            root, _ = self._prepared_startup_venv(directory, runner)
            bin_directory = root / ".venv/bin"
            escaped = root.parent / "escaped-bin"
            bin_directory.rename(escaped)
            bin_directory.symlink_to(escaped, target_is_directory=True)
            with self.assertRaisesRegex(
                runner.FoundationRunError,
                "bin is not a real directory",
            ):
                runner.seal_puffer_python_startup(root)

    def test_startup_contract_rejects_lib64_interpreter_layout(
        self,
    ) -> None:
        runner = self._load_runner()
        verifier = self._load_verifier()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-lib64-"
        ) as directory:
            root, _ = self._prepared_startup_venv(directory, runner)
            version = next(
                line.split(" = ", 1)[1]
                for line in (
                    root / ".venv/pyvenv.cfg"
                ).read_text(encoding="utf-8").splitlines()
                if line.startswith("version = ")
            )
            runtime = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    '{"implementation":"cpython","platlibdir":"lib64",'
                    f'"version":"{version}"'
                    "}\n"
                ),
                stderr="",
            )
            for module, function, error in (
                (
                    runner,
                    runner._puffer_pyvenv_input,
                    runner.FoundationRunError,
                ),
                (
                    verifier,
                    verifier._expected_puffer_pyvenv_input,
                    verifier.FoundationVerificationError,
                ),
            ):
                with self.subTest(module=module.__name__), mock.patch.object(
                    module, "run_checked", return_value=runtime
                ) as run:
                    with self.assertRaisesRegex(error, "platlibdir=lib"):
                        function(root)
                    command = run.call_args.args[0]
                    self.assertEqual(command[1:4], ["-B", "-I", "-S"])

    def test_startup_sealer_rolls_back_late_cleanup_failure(
        self,
    ) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-startup-rollback-"
        ) as directory:
            root, site_packages = self._prepared_startup_venv(
                directory, runner
            )
            before = self._startup_tree_snapshot(root)
            modes_before = {
                relative: (
                    root / relative
                ).stat().st_mode
                for relative in before
            }
            real_unlink = runner.os.unlink
            injected = False
            quarantine_unlinks = 0

            def fail_one_quarantine_unlink(path, *args, **kwargs):
                nonlocal injected, quarantine_unlinks
                if "f5-startup-quarantine" in os.fspath(path):
                    quarantine_unlinks += 1
                    if quarantine_unlinks == 2:
                        injected = True
                        raise PermissionError(
                            "injected quarantine cleanup"
                        )
                return real_unlink(path, *args, **kwargs)

            with mock.patch.object(
                runner.os,
                "unlink",
                side_effect=fail_one_quarantine_unlink,
            ):
                with self.assertRaisesRegex(
                    runner.FoundationRunError,
                    "failed without mutation",
                ):
                    runner.seal_puffer_python_startup(root)
            self.assertTrue(injected)
            self.assertEqual(self._startup_tree_snapshot(root), before)
            self.assertEqual(
                {
                    relative: (
                        root / relative
                    ).stat().st_mode
                    for relative in before
                },
                modes_before,
            )
            self.assertFalse(
                (site_packages / runner.SEALED_EDITABLE_PTH_NAME).exists()
            )
            self.assertFalse(
                any(
                    "f5-startup-quarantine" in path.name
                    for path in root.rglob("*")
                )
            )

    def test_runner_and_verifier_scrub_shell_and_git_startup_injection(
        self,
    ) -> None:
        poisoned = {
            "BASH_ENV": "/tmp/attacker-bash-env",
            "ENV": "/tmp/attacker-env",
            "BASH_FUNC_git%%": "() { return 0; }",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "alias.status",
            "GIT_CONFIG_VALUE_0": "!exit 0",
            "GIT_CONFIG_PARAMETERS": "'alias.f5probe=!printf injected'",
            "GIT_COMMON_DIR": "/tmp/attacker-common-git-dir",
            "GIT_DIR": "/tmp/attacker-git-dir",
            "CCC_OVERRIDE_OPTIONS": "+-DF5_ENV_INJECTED=1",
            "CLANG_CONFIG_FILE": "/tmp/attacker-clang.cfg",
            "COMPILER_PATH": "/tmp/attacker-compilers",
            "LD_PRELOAD": "/tmp/attacker-library",
            "LD_AUDIT": "/tmp/attacker-audit-library",
            "LD_PROFILE": "attacker-profile",
            "DYLD_INSERT_LIBRARIES": "/tmp/attacker-library",
            "DYLD_FRAMEWORK_PATH": "/tmp/attacker-frameworks",
            "DYLD_IMAGE_SUFFIX": "_attacker",
            "PERL5OPT": "-Mstrict",
            "PYTHONPATH": "/tmp/attacker-python",
            "TAR_OPTIONS": "--checkpoint=1",
            "UNZIPOPT": "-d /tmp/attacker-unzip",
            "GZIP": "--name",
            "BZIP2": "-v",
            "XZ_OPT": "-T0",
            "OPENROUTER_API_KEY": "must-not-reach-child",
            "HOME": "/tmp/attacker-home",
        }
        build_poison = {
            "CPATH": "/tmp/attacker-headers",
            "C_INCLUDE_PATH": "/tmp/attacker-c-headers",
            "CPLUS_INCLUDE_PATH": "/tmp/attacker-cxx-headers",
            "LIBRARY_PATH": "/tmp/attacker-libraries",
            "LDFLAGS": "-L/tmp/attacker-libraries",
            "MAKEFLAGS": "-f/tmp/attacker-makefile",
            "SDKROOT": "/tmp/attacker-sdk",
        }
        for module in (self._load_runner(), self._load_verifier()):
            with self.subTest(module=module.__name__), mock.patch.dict(
                os.environ, poisoned | build_poison, clear=False
            ):
                environment = module.isolated_python_environment()
                build_environment = module.foundation_build_environment()
            for key in poisoned:
                self.assertNotIn(key, environment)
            for key in poisoned | build_poison:
                self.assertNotIn(key, build_environment)
            self.assertEqual(environment["GIT_CONFIG_GLOBAL"], "/dev/null")
            self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
            self.assertEqual(environment["PATH"], module.SAFE_SYSTEM_PATH)
            with mock.patch.dict(
                os.environ, poisoned | build_poison, clear=False
            ):
                shell = module.run_checked(
                    [
                        "/bin/bash",
                        "-c",
                        "test -z "
                        '"${BASH_ENV-}${ENV-}${PERL5OPT-}'
                        '${LD_AUDIT-}${DYLD_FRAMEWORK_PATH-}'
                        '${TAR_OPTIONS-}${OPENROUTER_API_KEY-}"',
                    ]
                )
                compiler = module.foundation_compiler()
                macros = module.run_checked(
                    [
                        str(compiler),
                        "-dM",
                        "-E",
                        "-x",
                        "c",
                        "/dev/null",
                    ]
                ).stdout
                git_config = module.run_checked(
                    ["git", "config", "--list"]
                ).stdout
            self.assertEqual(shell.returncode, 0)
            self.assertNotIn("F5_ENV_INJECTED", macros)
            self.assertNotIn("f5probe", git_config)

    def test_runner_and_verifier_bind_exact_fresh_lifecycle_order(
        self,
    ) -> None:
        runner = self._load_runner()
        verifier = self._load_verifier()
        runner_steps = [
            {
                "id": step_id,
                "command": command,
                "exit_code": exit_code,
            }
            for step_id, command, exit_code in runner.LIFECYCLE_COMMANDS
        ]
        self.assertEqual(
            runner_steps, verifier.EXPECTED_LIFECYCLE_STEPS
        )
        self.assertEqual(
            [step["id"] for step in runner_steps],
            [
                "ordinary-install",
                "ordinary-cpu-build",
                "ordinary-fast-build",
                "ordinary-check",
                "ordinary-module-none",
                "f5-check-rejects-ordinary",
                "f5-stage",
                "f5-cpu-rebuild",
                "f5-check",
                "f5-install-rejects-already-staged",
                "f5-module-proof",
                "ordinary-install-rejects-f5",
                "production-ablation-rejects-f5",
                "production-screen-rejects-f5",
            ],
        )
        self.assertEqual(
            [step["exit_code"] for step in runner_steps],
            [0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1],
        )

    def test_fresh_lifecycle_rejects_nonempty_starting_tree(self) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-already-staged-"
        ) as directory:
            root = pathlib.Path(directory).resolve()
            with mock.patch.object(
                runner,
                "git_output",
                side_effect=[
                    str(root),
                    runner.PUFFER_COMMIT,
                    " M src/bindings_cpu.cpp",
                ],
            ):
                with self.assertRaises(runner.FoundationRunError):
                    runner.validate_fresh_puffer_start(root)

    def test_fresh_lifecycle_rejects_ignored_native_inputs(self) -> None:
        runner = self._load_runner()
        with tempfile.TemporaryDirectory(
            prefix="f5-raylib-start-"
        ) as directory:
            root = pathlib.Path(directory).resolve()
            (root / "raylib-archives").mkdir()
            with mock.patch.object(
                runner,
                "git_output",
                side_effect=[
                    str(root),
                    runner.PUFFER_COMMIT,
                    "",
                ],
            ):
                with self.assertRaisesRegex(
                    runner.FoundationRunError,
                    "pre-existing ignored native build inputs",
                ):
                    runner.validate_fresh_puffer_start(root)

    def test_raylib_receipt_hashes_archive_and_library(self) -> None:
        runner = self._load_runner()
        archive_payload = b"sealed archive"
        library_payload = b"sealed library"
        with tempfile.TemporaryDirectory(
            prefix="f5-raylib-receipt-"
        ) as directory:
            root = pathlib.Path(directory).resolve()
            archive = root / "raylib-archives/test-raylib.tar.gz"
            library = root / "test-raylib/lib/libraylib.a"
            archive.parent.mkdir()
            library.parent.mkdir(parents=True)
            archive.write_bytes(archive_payload)
            library.write_bytes(library_payload)
            key = (
                runner.sys.platform,
                runner.platform.machine().lower(),
            )
            inputs = {
                key: {
                    "directory": "test-raylib",
                    "archive_sha256": hashlib.sha256(
                        archive_payload
                    ).hexdigest(),
                    "library_sha256": hashlib.sha256(
                        library_payload
                    ).hexdigest(),
                }
            }
            with mock.patch.object(runner, "RAYLIB_INPUTS", inputs):
                receipt = runner.puffer_raylib_input(root)
                self.assertEqual(
                    receipt["schema"],
                    "bloodbowl-f5-raylib-input-v2",
                )
                self.assertEqual(
                    receipt["archive_path"],
                    "raylib-archives/test-raylib.tar.gz",
                )
                archive.write_bytes(b"mutated archive")
                with self.assertRaises(runner.FoundationRunError):
                    runner.puffer_raylib_input(root)

    def test_fresh_lifecycle_rejects_missing_or_mutated_entrypoint(
        self,
    ) -> None:
        runner = self._load_runner()
        for mutation in ("missing", "mutated"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix=f"f5-entrypoint-{mutation}-"
            ) as directory:
                root = pathlib.Path(directory).resolve()
                binary_directory = root / ".venv/bin"
                binary_directory.mkdir(parents=True)
                python = binary_directory / "python"
                python.write_bytes(b"prepared test interpreter\n")
                python.chmod(0o755)
                if mutation == "mutated":
                    entrypoint = binary_directory / "puffer"
                    entrypoint.write_bytes(
                        f"#!{python}\n".encode("utf-8")
                        + runner.PUFFER_ENTRYPOINT_BODY
                        + b"# mutation\n"
                    )
                    entrypoint.chmod(0o755)
                with mock.patch.object(
                    runner,
                    "git_output",
                    side_effect=[
                        str(root),
                        runner.PUFFER_COMMIT,
                        "",
                    ],
                ):
                    with self.assertRaisesRegex(
                        runner.FoundationRunError,
                        r"\.venv/bin/puffer|console script",
                    ):
                        runner.validate_fresh_puffer_start(root)

    def test_lifecycle_stream_identity_is_mutation_sensitive(self) -> None:
        verifier = self._load_verifier()
        with tempfile.TemporaryDirectory(
            prefix="f5-lifecycle-stream-"
        ) as directory:
            root = pathlib.Path(directory)
            relative = "puffer-lifecycle/01-step.stdout.txt"
            path = root / relative
            path.parent.mkdir()
            payload = b"sealed output\n"
            path.write_bytes(payload)
            description = {
                "path": relative,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            self.assertEqual(
                verifier._read_lifecycle_stream(
                    root,
                    description,
                    expected_path=relative,
                    location="test stream",
                ),
                payload,
            )
            path.write_bytes(b"mutated output\n")
            with self.assertRaises(verifier.FoundationVerificationError):
                verifier._read_lifecycle_stream(
                    root,
                    description,
                    expected_path=relative,
                    location="test stream",
                )

    def test_outer_artifact_boundary_rejects_closed_mutation_matrix(
        self,
    ) -> None:
        verifier = self._load_verifier()
        payload = b"sealed artifact\n"
        canonical_description = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

        def prepare(root: pathlib.Path) -> dict[str, object]:
            root.mkdir()
            (root / "evidence.json").write_bytes(b"{}\n")
            (root / "artifact.bin").write_bytes(payload)
            return {
                "artifacts": {
                    "artifact.bin": dict(canonical_description)
                }
            }

        with tempfile.TemporaryDirectory(
            prefix="f5-artifact-boundary-"
        ) as directory:
            base = pathlib.Path(directory)
            canonical_root = base / "canonical"
            canonical_evidence = prepare(canonical_root)
            verifier.validate_artifacts(
                canonical_root, canonical_evidence
            )

            cases: list[tuple[str, object]] = []

            missing_root = base / "missing"
            missing_evidence = prepare(missing_root)
            (missing_root / "artifact.bin").unlink()
            cases.append(("missing", (missing_root, missing_evidence)))

            extra_root = base / "extra"
            extra_evidence = prepare(extra_root)
            (extra_root / "unexpected").write_bytes(b"x")
            cases.append(("extra", (extra_root, extra_evidence)))

            symlink_root = base / "symlink"
            symlink_evidence = prepare(symlink_root)
            symlink_target = base / "symlink-target"
            symlink_target.write_bytes(payload)
            (symlink_root / "artifact.bin").unlink()
            (symlink_root / "artifact.bin").symlink_to(symlink_target)
            cases.append(("symlink", (symlink_root, symlink_evidence)))

            hardlink_root = base / "hardlink"
            hardlink_evidence = prepare(hardlink_root)
            hardlink_target = base / "hardlink-target"
            hardlink_target.write_bytes(payload)
            (hardlink_root / "artifact.bin").unlink()
            os.link(hardlink_target, hardlink_root / "artifact.bin")
            cases.append(("hardlink", (hardlink_root, hardlink_evidence)))

            truncated_root = base / "truncated"
            truncated_evidence = prepare(truncated_root)
            (truncated_root / "artifact.bin").write_bytes(payload[:-1])
            cases.append(
                ("truncated", (truncated_root, truncated_evidence))
            )

            trailing_root = base / "trailing"
            trailing_evidence = prepare(trailing_root)
            (trailing_root / "artifact.bin").write_bytes(payload + b"x")
            cases.append(("trailing", (trailing_root, trailing_evidence)))

            count_root = base / "count"
            count_evidence = prepare(count_root)
            count_evidence["artifacts"]["artifact.bin"]["bytes"] += 1
            cases.append(("count", (count_root, count_evidence)))

            hash_root = base / "hash"
            hash_evidence = prepare(hash_root)
            hash_evidence["artifacts"]["artifact.bin"]["sha256"] = "0" * 64
            cases.append(("hash", (hash_root, hash_evidence)))

            for name, case in cases:
                root, evidence = case
                with self.subTest(mutation=name), self.assertRaises(
                    verifier.FoundationVerificationError
                ):
                    verifier.validate_artifacts(root, evidence)

    def test_generator_is_byte_deterministic(self) -> None:
        binary = ROOT / "build/f5_trainability_foundation"
        subprocess.run(
            ["make", str(binary.relative_to(ROOT))],
            cwd=ROOT,
            check=True,
        )
        with tempfile.TemporaryDirectory(prefix="f5-red-") as directory:
            first = pathlib.Path(directory) / "first"
            second = pathlib.Path(directory) / "second"
            for output in (first, second):
                subprocess.run(
                    [str(binary), "generate", "--output", str(output)],
                    cwd=ROOT,
                    check=True,
                )
            first_files = {
                path.relative_to(first): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)
            descriptor = json.loads(
                (first / "task.json").read_text(encoding="ascii")
            )
            self.assertEqual(descriptor["full_bundle_sha256"], EXPECTED_FULL_BBS)
            self.assertEqual(descriptor["f5_bbs_sha256"], EXPECTED_F5_BBS)
            self.assertEqual(descriptor["raw_match_sha256"], EXPECTED_MATCH)
            self.assertEqual(
                hashlib.sha256((first / "f5.bbs").read_bytes()).hexdigest(),
                EXPECTED_F5_BBS,
            )

    def test_generator_verify_rejects_closed_artifact_corruption(self) -> None:
        binary = ROOT / "build/f5_trainability_foundation"
        subprocess.run(
            ["make", str(binary.relative_to(ROOT))],
            cwd=ROOT,
            check=True,
        )

        def replace_bytes(path: pathlib.Path, payload: bytes) -> None:
            path.unlink()
            path.write_bytes(payload)

        def remove_task(root: pathlib.Path) -> None:
            (root / "task.json").unlink()

        def truncate_task(root: pathlib.Path) -> None:
            path = root / "task.json"
            replace_bytes(path, path.read_bytes()[:-1])

        def append_task_bytes(root: pathlib.Path) -> None:
            path = root / "task.json"
            replace_bytes(path, path.read_bytes() + b" ")

        def add_task_key(root: pathlib.Path) -> None:
            path = root / "task.json"
            payload = json.loads(path.read_text(encoding="ascii"))
            payload["unexpected"] = 1
            replace_bytes(
                path,
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
                .encode("ascii")
                + b"\n",
            )

        def reencode_task_noncanonically(root: pathlib.Path) -> None:
            path = root / "task.json"
            payload = json.loads(path.read_text(encoding="ascii"))
            original = path.read_bytes()
            candidate = (
                json.dumps(payload, sort_keys=True, indent=1) + "\n"
            ).encode("ascii")
            self.assertNotEqual(candidate, original)
            replace_bytes(path, candidate)

        def mutate_match(root: pathlib.Path) -> None:
            path = root / "f5.match"
            payload = bytearray(path.read_bytes())
            payload[len(payload) // 2] ^= 1
            replace_bytes(path, bytes(payload))

        def add_extra_artifact(root: pathlib.Path) -> None:
            (root / "extra").write_bytes(b"unexpected\n")

        mutations = (
            ("absent-task", remove_task),
            ("truncated-task", truncate_task),
            ("trailing-task", append_task_bytes),
            ("extra-task-key", add_task_key),
            ("noncanonical-task", reencode_task_noncanonically),
            ("mutated-match", mutate_match),
            ("extra-artifact", add_extra_artifact),
        )

        with tempfile.TemporaryDirectory(
            prefix="f5-generator-negative-"
        ) as directory:
            root = pathlib.Path(directory)
            canonical = root / "canonical"
            subprocess.run(
                [str(binary), "generate", "--output", str(canonical)],
                cwd=ROOT,
                check=True,
            )
            subprocess.run(
                [str(binary), "verify", "--input", str(canonical)],
                cwd=ROOT,
                check=True,
            )
            for name, mutate in mutations:
                with self.subTest(mutation=name):
                    candidate = root / name
                    shutil.copytree(canonical, candidate)
                    mutate(candidate)
                    result = subprocess.run(
                        [
                            str(binary),
                            "verify",
                            "--input",
                            str(candidate),
                        ],
                        cwd=ROOT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 1, result)
                    self.assertIn("f5 foundation:", result.stderr)

    def test_outer_verifier_rejects_bool_integer_aliases(self) -> None:
        verifier = self._load_verifier()
        self.assertFalse(verifier.exact_json_equal(True, 1))
        self.assertFalse(verifier.exact_json_equal(False, 0))
        self.assertFalse(verifier.exact_json_equal({"value": True}, {"value": 1}))
        self.assertTrue(verifier.exact_json_equal({"value": 1}, {"value": 1}))

    def test_outer_transition_binding_accepts_exact_and_rejects_leaf_drift(
        self,
    ) -> None:
        verifier = self._load_verifier()
        transitions = [
            verifier._expected_module_transition(index) for index in range(8)
        ]
        reference = [
            verifier._expected_reference_transition(index) for index in range(8)
        ]
        verifier.validate_module_transitions(transitions, reference)

        mutations = (
            lambda value: value[0].__setitem__("active_row", True),
            lambda value: value[3].__setitem__(
                "joint_support_sha256", "0" * 64
            ),
            lambda value: value[7]["rewards"].__setitem__(0, 0.0),
        )
        for mutate in mutations:
            candidate = json.loads(json.dumps(transitions))
            mutate(candidate)
            with self.assertRaises(verifier.FoundationVerificationError):
                verifier.validate_module_transitions(candidate, reference)

    def test_outer_rollout_binding_accepts_exact_and_rejects_leaf_drift(
        self,
    ) -> None:
        verifier = self._load_verifier()
        tail = {
            "slot": 8,
            "reward": [1.0, -1.0],
            "terminal": [1.0, 1.0],
            "terminal_bootstrap": [0.0, 0.0],
            "ninth_environment_action": False,
            "environment_step_calls": 8,
            "policy_forward_calls": 9,
            "policy_tail_value_emission": ["nan", "+inf"],
            "recurrent_state_inputs": [
                0.0,
                1.0,
                2.0,
                3.0,
                4.0,
                5.0,
                6.0,
                7.0,
                0.0,
            ],
            "recurrent_state_after_actions": [8.0],
            "recurrent_initial_state_was_cleared": True,
            "recurrent_tail_state_was_cleared": True,
            "collector": {
                "rewards": [[0.0, 0.0] for _ in range(8)],
                "terminals": [[0.0, 0.0] for _ in range(8)],
                "actions": [
                    [list(heads), [0, 32, 390]]
                    for heads in verifier.REFERENCE_HEADS
                ],
                "obs_sha256": [
                    list(rows) for rows in verifier.REFERENCE_OBS_SHA256
                ],
                "effective_mask_sha256": [
                    list(rows)
                    for rows in verifier.ROLLOUT_EFFECTIVE_MASK_SHA256
                ],
                "pending_rewards": [1.0, -1.0],
                "pending_terminals": [1.0, 1.0],
                "global_step": 16,
                "tail_valid": True,
            },
            "advantage": {
                "consumer": "puff_advantage_cpu",
                "calls": 1,
                "gamma": 0.99,
                "gae_lambda": 0.95,
                "values": [
                    [
                        sign * math.pow(0.99 * 0.95, 7 - step)
                        for step in range(8)
                    ]
                    for sign in (1.0, -1.0)
                ],
                "final_slot": [1.0, -1.0],
            },
            "log": dict(verifier.EXPECTED_MODULE_LOG),
        }
        verifier.validate_rollout_tail(tail)

        mutations = (
            lambda value: value.__setitem__(
                "ninth_environment_action", True
            ),
            lambda value: value["collector"].__setitem__("global_step", True),
            lambda value: value["advantage"].__setitem__("calls", 2),
            lambda value: value["log"].__setitem__("demo_fallbacks", 1.0),
        )
        for mutate in mutations:
            candidate = json.loads(json.dumps(tail))
            mutate(candidate)
            with self.assertRaises(verifier.FoundationVerificationError):
                verifier.validate_rollout_tail(candidate)

    def test_outer_masked_random_binding_is_closed_and_mutation_sensitive(
        self,
    ) -> None:
        verifier = self._load_verifier()
        receipt = json.loads(json.dumps(verifier.EXPECTED_MASKED_RANDOM))
        verifier.validate_masked_random(receipt)
        mutations = (
            lambda value: value.__setitem__("projection_collisions", True),
            lambda value: value.__setitem__(
                "joint_support_rows_checked", 18_001
            ),
            lambda value: value["integrity"].__setitem__(
                "reward_component_residual", 1.0
            ),
            lambda value: value["integrity"].__setitem__(
                "reward_samples_per_episode", 16
            ),
        )
        for mutate in mutations:
            candidate = json.loads(json.dumps(receipt))
            mutate(candidate)
            with self.assertRaises(verifier.FoundationVerificationError):
                verifier.validate_masked_random(candidate)

    def test_outer_vectorization_binding_is_closed(self) -> None:
        verifier = self._load_verifier()
        receipt = {
            "total_agents": 4,
            "environments": 2,
            "episode_decisions": 8,
            "completed_episodes": 2,
            "terminal_rewards": [1.0, -1.0, 1.0, -1.0],
            "all_terminal": True,
            "exact_autoreset": True,
        }
        verifier.validate_vectorization(receipt)
        for key, value in (
            ("total_agents", 2),
            ("environments", 1),
            ("exact_autoreset", False),
        ):
            with self.subTest(key=key):
                candidate = dict(receipt)
                candidate[key] = value
                with self.assertRaises(
                    verifier.FoundationVerificationError
                ):
                    verifier.validate_vectorization(candidate)

    def test_independent_ordinary_replay_rejects_forged_history(self) -> None:
        verifier = self._load_verifier()
        worker = {
            "schema": "ordinary-test",
            "module_sha256": "1" * 64,
        }
        authority = "2" * 64
        worker_status = [" M build.sh"]
        independent = {
            "schema": "bloodbowl-f5-independent-ordinary-replay-v1",
            "commit": verifier.PUFFER_COMMIT,
            "git_tree": "3" * 40,
            "initial_git_status_sha256": hashlib.sha256(
                b"[]\n"
            ).hexdigest(),
            "final_git_status": list(worker_status),
            "final_git_status_sha256": hashlib.sha256(
                b'[" M build.sh"]\n'
            ).hexdigest(),
            "environment_source_sha256": "6" * 64,
            "authority_sha256": authority,
            "module_receipt": dict(worker),
            "native_build_inputs": {"raylib": {}},
            "python_startup_input": {},
        }
        verifier._require_independent_ordinary_binding(
            worker, authority, worker_status, independent
        )
        forged_module = dict(worker)
        forged_module["module_sha256"] = "0" * 64
        with self.assertRaises(verifier.FoundationVerificationError):
            verifier._require_independent_ordinary_binding(
                forged_module, authority, worker_status, independent
            )
        with self.assertRaises(verifier.FoundationVerificationError):
            verifier._require_independent_ordinary_binding(
                worker, "0" * 64, worker_status, independent
            )
        with self.assertRaises(verifier.FoundationVerificationError):
            verifier._require_independent_ordinary_binding(
                worker, authority, [" M attacker"], independent
            )

    def test_independent_replay_scrubs_puffer_build_knobs(self) -> None:
        runner = self._load_runner()
        verifier = self._load_verifier()
        poison = {
            name: "hostile"
            for name in (
                "EXTRA_CFLAGS",
                "PRECISION",
                "PUFFER_STRICT_ENV_CONFIG_TESTING",
                "CUDA_HOME",
                "CUDA_PATH",
                "NVCC_ARCH",
            )
        }
        toolchain = {
            "cc": {"path": "/sealed/clang"},
            "cxx": {"path": "/sealed/clang++"},
        }
        for module, builder in (
            (runner, runner.puffer_lifecycle_environment),
            (verifier, verifier._puffer_replay_environment),
        ):
            with self.subTest(module=module.__name__), mock.patch.dict(
                os.environ, poison, clear=False
            ):
                environment = builder(
                    pathlib.Path("/sealed/PufferLib"), toolchain
                )
            for name in poison:
                self.assertNotIn(name, environment)
            self.assertEqual(environment["CC"], "/sealed/clang")
            self.assertEqual(environment["CXX"], "/sealed/clang++")
            self.assertEqual(environment["PATH"], module.SAFE_SYSTEM_PATH)
            self.assertEqual(
                environment["PUFFER_BUILD_PYTHON"],
                "/sealed/PufferLib/.venv/bin/python",
            )

    def test_rejected_symlink_root_cannot_delete_target_verdict(self) -> None:
        verifier = self._load_verifier()
        with tempfile.TemporaryDirectory(
            prefix="f5-verdict-root-"
        ) as directory:
            base = pathlib.Path(directory)
            target = base / "target"
            target.mkdir()
            verdict = target / "verdict.json"
            sentinel = b'{"sentinel":true}\n'
            verdict.write_bytes(sentinel)
            alias = base / "alias"
            alias.symlink_to(target, target_is_directory=True)
            self.assertEqual(verifier.main([str(alias)]), 2)
            self.assertEqual(verdict.read_bytes(), sentinel)

    def test_preexisting_verdict_directory_fails_cleanly(self) -> None:
        verifier = self._load_verifier()
        with tempfile.TemporaryDirectory(
            prefix="f5-verdict-directory-"
        ) as directory:
            root = pathlib.Path(directory)
            (root / "verdict.json").mkdir()
            self.assertEqual(verifier.main([str(root)]), 2)
            self.assertTrue((root / "verdict.json").is_dir())


if __name__ == "__main__":
    unittest.main()

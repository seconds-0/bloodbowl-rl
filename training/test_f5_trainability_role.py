#!/usr/bin/env python3
"""Source and exact-install contracts for the F5 qualification role."""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training/puffer_f5_trainability_role.patch"
REQUIREMENTS = ROOT / "training/f5_trainability_requirements.txt"
REQUIREMENTS_SHA256 = (
    "010a1f6a785d9c7e7b421f345eeae10a177891fae7e56454111da18c0bed9aa6"
)


class F5RolePatchContract(unittest.TestCase):
    def _run_installer(
        self, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            "PATH": (
                "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:"
                "/opt/homebrew/bin:/opt/homebrew/sbin"
            ),
            "LC_ALL": "C",
            "PUFFER_INSTALL_PYTHON": sys.executable,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        return subprocess.run(
            [
                "/bin/bash",
                str(ROOT / "tools/install_f5_trainability_env.sh"),
                *arguments,
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_patch_exports_role_in_both_bindings(self) -> None:
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("+++ b/src/bindings_cpu.cpp", source)
        self.assertIn("+++ b/src/bindings.cu", source)
        fields = {
            "enabled": "PUFFER_QUALIFICATION_FIXTURE_ENABLED",
            "role": "PUFFER_QUALIFICATION_FIXTURE_ROLE",
            "schema": "PUFFER_QUALIFICATION_FIXTURE_SCHEMA",
            "qualification_only":
                "PUFFER_QUALIFICATION_FIXTURE_QUALIFICATION_ONLY",
            "environment_source_sha256": "PUFFER_ENV_SOURCE_HASH",
            "match_sha256": "PUFFER_QUALIFICATION_FIXTURE_MATCH_SHA256",
            "bbs_sha256": "PUFFER_QUALIFICATION_FIXTURE_BBS_SHA256",
            "bundle_sha256": "PUFFER_QUALIFICATION_FIXTURE_BUNDLE_SHA256",
            "bbs_source_id": "PUFFER_QUALIFICATION_FIXTURE_BBS_SOURCE_ID",
            "authored_source_id":
                "PUFFER_QUALIFICATION_FIXTURE_AUTHORED_SOURCE_ID",
            "reference_trace_schema":
                "PUFFER_QUALIFICATION_FIXTURE_REFERENCE_TRACE_SCHEMA",
            "reference_trace_sha256":
                "PUFFER_QUALIFICATION_FIXTURE_REFERENCE_TRACE_SHA256",
            "max_decisions":
                "PUFFER_QUALIFICATION_FIXTURE_MAX_DECISIONS",
            "reward_contract":
                "PUFFER_QUALIFICATION_FIXTURE_REWARD_CONTRACT",
        }
        binding_diffs = [
            "diff --git" + chunk
            for chunk in source.split("diff --git")[1:]
        ]
        self.assertEqual(len(binding_diffs), 2)
        casts = {
            "enabled": "(bool)",
            "qualification_only": "(bool)",
            "bbs_source_id": "(unsigned long long)",
            "authored_source_id": "(unsigned long long)",
        }
        for field, macro in fields.items():
            with self.subTest(field=field):
                export = f'm.attr("qualification_fixture_{field}")'
                self.assertEqual(source.count(export), 2)
                for binding_diff in binding_diffs:
                    self.assertEqual(binding_diff.count(export), 1)
                    additions = "\n".join(
                        line[1:]
                        for line in binding_diff.splitlines()
                        if line.startswith("+") and not line.startswith("+++")
                    )
                    normalized = " ".join(additions.split())
                    assignment = (
                        f"{export} = {casts.get(field, '')}{macro};"
                    )
                    self.assertIn(assignment, normalized)

    def test_patch_does_not_add_state_bank_authority(self) -> None:
        source = PATCH.read_text(encoding="utf-8")
        added = "\n".join(
            line[1:]
            for line in source.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        self.assertNotIn("test_only_allow_authored", added)
        self.assertNotIn("PRODUCTION_AUTHORIZED_PRODUCER_KINDS", added)
        self.assertNotIn("BBE_STATE_BANK_AUTHORED_SCENARIO", added)

    def test_installer_has_separate_role_checker(self) -> None:
        source = (ROOT / "tools/install_f5_trainability_env.sh").read_text(
            encoding="utf-8"
        )
        for exact in (
            "f5-fixed-state-v1",
            "bloodbowl-trainability-task-v1",
            "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2",
            "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71",
            "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1",
            "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300",
            "touchdown-zero-sum-only-v1",
            "0xA9000019",
            "0xAE00001A",
        ):
            self.assertIn(exact, source)
        self.assertIn("--check", source)
        for forbidden in (
            "--fixture",
            "--fixture-path",
            "--fixture-sha256",
            "--authored-source-id",
            "--durable-source-id",
            "--role",
            "--task",
            "--match-sha256",
            "--bbs-sha256",
            "--requirements",
            "--torch",
            "--index-url",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("check_no_bank_install", source)
        self.assertIn("qualification_fixture_from_module", source)
        self.assertIn("known_ordinary_status_only", source)

    def test_role_installer_rejects_already_staged_role(self) -> None:
        source = (ROOT / "tools/install_f5_trainability_env.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "if check_exact_f5_authority >/dev/null 2>&1; then",
            source,
        )
        already_staged = source.split(
            "if check_exact_f5_authority >/dev/null 2>&1; then", 1
        )[1].split("else", 1)[0]
        self.assertIn("already staged", already_staged)
        self.assertIn("exit 1", already_staged)
        self.assertNotIn("known_ordinary_status_only", already_staged)
        self.assertNotIn("validate_staged_source_closure", already_staged)

    def test_role_installer_executes_closed_argument_boundary(self) -> None:
        for option in (
            "--fixture",
            "--fixture-path",
            "--role",
            "--match-sha256",
            "--bbs-sha256",
            "--requirements",
            "--torch",
            "--index-url",
        ):
            with self.subTest(option=option):
                completed = self._run_installer(option, "forbidden")
                self.assertEqual(completed.returncode, 2)
                self.assertIn(
                    f"unknown F5 installer option: {option}",
                    completed.stderr,
                )
        missing = self._run_installer()
        self.assertEqual(missing.returncode, 2)
        self.assertIn(
            "an explicit fresh PufferLib path is required",
            missing.stderr,
        )
        multiple = self._run_installer("/first", "/second")
        self.assertEqual(multiple.returncode, 2)
        self.assertIn(
            "multiple PufferLib paths supplied", multiple.stderr
        )

    def test_role_installer_executes_checkout_identity_rejections(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="f5-installer-negative-"
        ) as directory:
            base = pathlib.Path(directory).resolve()
            missing = self._run_installer(str(base / "missing"))
            self.assertEqual(missing.returncode, 1)
            self.assertIn("is not a PufferLib tree", missing.stderr)

            nongit = base / "nongit"
            nongit.mkdir()
            (nongit / "build.sh").write_text(
                "#!/usr/bin/env bash\n", encoding="utf-8"
            )
            rejected_nongit = self._run_installer(str(nongit))
            self.assertEqual(rejected_nongit.returncode, 1)
            self.assertIn(
                "is not a PufferLib Git worktree",
                rejected_nongit.stderr,
            )

            wrong_root = base / "wrong-root"
            nested = wrong_root / "nested"
            nested.mkdir(parents=True)
            subprocess.run(
                ["git", "init", "--quiet", str(wrong_root)],
                check=True,
                capture_output=True,
                text=True,
            )
            (nested / "build.sh").write_text(
                "#!/usr/bin/env bash\n", encoding="utf-8"
            )
            rejected_nested = self._run_installer(str(nested))
            self.assertEqual(rejected_nested.returncode, 1)
            self.assertIn(
                "PufferLib path is not the Git worktree root",
                rejected_nested.stderr,
            )

            unpinned = base / "unpinned"
            unpinned.mkdir()
            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=unpinned,
                check=True,
                capture_output=True,
                text=True,
            )
            (unpinned / "build.sh").write_text(
                "#!/usr/bin/env bash\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "build.sh"],
                cwd=unpinned,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=F5 Test",
                    "-c",
                    "user.email=f5-test@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "unpinned",
                ],
                cwd=unpinned,
                check=True,
                capture_output=True,
                text=True,
            )
            rejected_unpinned = self._run_installer(str(unpinned))
            self.assertEqual(rejected_unpinned.returncode, 1)
            self.assertIn(
                "PufferLib HEAD must be "
                "9836f0d2e78889c1aaf189c04d161b6fc61a9386",
                rejected_unpinned.stderr,
            )

    def test_role_installer_separates_backend_evidence(self) -> None:
        source = (ROOT / "tools/install_f5_trainability_env.sh").read_text(
            encoding="utf-8"
        )
        for exact_base_gate in (
            "PUFFER_EXACT_ACTION_SOURCE_HASH",
            "PUFFER_ENV_SOURCE_HASH",
            "PUFFER_OBSERVATION_ABI",
            "PUFFER_OBSERVATION_VERSION",
            "PUFFER_ACTION_ABI",
            "sealed F5 tree retains state-bank artifacts",
            "sealed F5 state-bank bridge is not exact",
        ):
            self.assertIn(exact_base_gate, source)
        self.assertIn('if [ "$COMPILED_GPU" -eq 0 ]; then', source)
        self.assertIn("CPU exact runtime oracle", source)
        self.assertIn("CUDA metadata/source closure", source)
        self.assertIn("external GPU gate", source)

    def test_role_installer_imports_module_with_explicit_isolated_path(
        self,
    ) -> None:
        source = (ROOT / "tools/install_f5_trainability_env.sh").read_text(
            encoding="utf-8"
        )
        module_probe = source.split('MODULE_PATH="$(', 1)[1].split(
            '\n)" || {', 1
        )[0]
        self.assertIn('"$PYBIN" -B -I - "$PUFFER"', module_probe)
        self.assertIn(
            "puffer_root = Path(sys.argv[1]).resolve(strict=True)",
            module_probe,
        )
        self.assertIn(
            "sys.path.insert(0, str(puffer_root))",
            module_probe,
        )
        self.assertNotIn("-I -c", module_probe)

    def test_ordinary_installer_imports_only_the_explicit_target_root(
        self,
    ) -> None:
        source = (ROOT / "tools/install_puffer_env.sh").read_text(
            encoding="utf-8"
        )
        current_module = source.split(
            'current_module="$(cd "$PUFFER"', 1
        )[1].split("\n    if [ ! -f", 1)[0]
        compiled_contract = source.split(
            'compiled_contract="$(cd "$PUFFER"', 1
        )[1].split("\n    read -r", 1)[0]
        for probe in (current_module, compiled_contract):
            self.assertIn('"$PYBIN" -B -I -c', probe)
            self.assertIn(
                "sys.path.insert(0, sys.argv[1])", probe
            )
            self.assertIn('"$PUFFER"', probe)
        self.assertEqual(
            source.count(
                '"$PYBIN" -B -I - "$ROOT/tools" "$PUFFER"'
            ),
            2,
        )
        self.assertEqual(
            source.count("sys.path.insert(0, sys.argv[2])"),
            2,
        )

    def test_sealed_torch_cpu_requirements_are_minimal_and_platform_exact(
        self,
    ) -> None:
        payload = REQUIREMENTS.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), REQUIREMENTS_SHA256)
        self.assertEqual(
            payload.decode("ascii").splitlines(),
            [
                "--index-url https://pypi.org/simple",
                "--extra-index-url https://download.pytorch.org/whl/cpu",
                "--only-binary=:all:",
                "",
                "numpy==2.5.1",
                'torch==2.9.1 ; sys_platform == "darwin"',
                'torch==2.9.1+cpu ; sys_platform == "linux"',
                "rich==15.0.0",
                "rich-argparse==1.8.0",
            ],
        )

    def test_role_installer_seals_dependency_lifecycle_and_snapshot(
        self,
    ) -> None:
        source = (ROOT / "tools/install_f5_trainability_env.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            f'QUALIFICATION_REQUIREMENTS_SHA256="{REQUIREMENTS_SHA256}"',
            source,
        )
        for required in (
            "check_qualification_requirements_identity",
            "check_qualification_python_platform",
            "verify_qualification_direct_dependencies",
            "install_qualification_dependencies",
            "qualification_dependency_snapshot",
            "verify_qualification_dependencies",
            '"$PYBIN" -B -I -',
            "--isolated",
            "--disable-pip-version-check",
            "--no-input",
            "--no-cache-dir",
            "pip",
            "check",
            "bloodbowl-f5-python-distributions-v1",
            "f5_trainability_distributions.json",
            "f5_trainability_distributions.sha256",
            "torch.version.cuda is not None",
            "torch.cuda.is_available() is not False",
            "pufferlib.torch_pufferl",
        ):
            self.assertIn(required, source)
        for platform_tuple in (
            '("cpython", (3, 12), "darwin", "arm64")',
            '("cpython", (3, 12), "linux", "x86_64")',
        ):
            self.assertIn(platform_tuple, source)

        install_branch = source.split(
            'if [ "$MODE" = "install" ]; then', 1
        )[1].split("\nfi\n", 1)[0]
        fresh_branch = install_branch.split("else", 1)[1]
        self.assertLess(
            fresh_branch.index("install_qualification_dependencies"),
            fresh_branch.index("stage_exact_f5_authority"),
        )
        already_staged_branch = install_branch.split("else", 1)[0]
        self.assertIn("exit 1", already_staged_branch)
        self.assertNotIn(
            "install_qualification_dependencies",
            already_staged_branch,
        )
        source_closure = source.split(
            "validate_staged_source_closure() {", 1
        )[1].split("\n}", 1)[0]
        self.assertIn(
            "check_qualification_requirements_identity",
            source_closure,
        )

    def test_standard_installer_has_no_role_enable_option(self) -> None:
        source = (ROOT / "tools/install_puffer_env.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--f5-trainability", source)
        self.assertNotIn("--qualification-fixture", source)

    def test_ordinary_installer_owns_portable_simd_patch(self) -> None:
        patch = (
            ROOT / "training/puffer_portable_simd_flags.patch"
        ).read_text(encoding="utf-8")
        raylib_patch = (
            ROOT / "training/puffer_raylib_pin.patch"
        ).read_text(encoding="utf-8")
        self.assertIn("Linux:x86_64", patch)
        self.assertIn("SIMD_FLAGS=(-mavx2 -mfma)", patch)
        self.assertIn("CPU_OMP_COMPILE_FLAGS=(-fopenmp)", patch)
        self.assertIn('CPU_OMP_LINK_FLAGS=(-fopenmp "$OMP_LIB")', patch)
        self.assertIn("STANDALONE_OMP_LINK_FLAGS=(-fopenmp)", patch)
        self.assertIn("Darwin:arm64", patch)
        self.assertIn("SIMD_FLAGS=()", patch)
        self.assertIn("CPU_OMP_COMPILE_FLAGS=()", patch)
        self.assertIn("CPU_OMP_LINK_FLAGS=()", patch)
        self.assertIn("STANDALONE_OMP_LINK_FLAGS=()", patch)
        self.assertIn("#ifdef _OPENMP", patch)
        self.assertIn("#include <omp.h>", patch)
        self.assertIn("#endif", patch)
        self.assertNotIn("PUFFER_DARWIN_OMP_INCLUDE", patch)
        self.assertNotIn("DARWIN_OMP_INCLUDE", patch)
        self.assertIn(
            '-fPIC "${CPU_OMP_COMPILE_FLAGS[@]}"', patch
        )
        self.assertIn(
            '-lm -lpthread "${CPU_OMP_LINK_FLAGS[@]}"', patch
        )
        self.assertIn(
            '-lm -lpthread "${STANDALONE_OMP_LINK_FLAGS[@]}"', patch
        )
        self.assertIn(
            "unsupported Blood Bowl build platform", patch
        )
        for expected in (
            "3d95ef03d5b38dfa55c0a16ca122d382134b078f0e5b270b52fe7eae0549c000",
            "3323cbf14ec6e640e19d63e230e68c3a530be3e9a9d416435eab82160e9e9ccc",
            "930c67b676963c6cffbd965814664523081ecbf3d30fc9df4211d0064aa6ba39",
            "5517f19555ce6e19540ac534bb5d5bf08ba45660d14642db4878f079a9f1b7da",
            "curl --disable --fail --silent --show-error --location",
            '"$RAYLIB_ARCHIVE_SHA256" "$RAYLIB_LIBRARY_SHA256"',
            "archive_directory='raylib-archives'",
            'archive="$archive_directory/$archive"',
            'rm -rf "./$name"',
            'BUILD_PYTHON="${PUFFER_BUILD_PYTHON:-python}"',
            '"$BUILD_PYTHON" -B -I -c',
        ):
            self.assertIn(expected, raylib_patch)
        self.assertEqual(
            raylib_patch.count('"$BUILD_PYTHON" -B -I -c'),
            8,
        )
        for relative in (
            "tools/install_puffer_env.sh",
            "tools/install_f5_trainability_env.sh",
        ):
            installer = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                "training/puffer_portable_simd_flags.patch",
                installer,
                relative,
            )
            self.assertIn(
                "puffer_portable_simd_flags.patch",
                installer,
                relative,
            )
            self.assertIn(
                "training/puffer_raylib_pin.patch",
                installer,
                relative,
            )

    def test_production_launchers_reject_every_non_none_role(self) -> None:
        for relative in (
            "tools/run_reward_ablation.sh",
            "tools/run_reward_screen.sh",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("qualification_fixture_role", source, relative)
            self.assertIn("f5-fixed-state-v1", source, relative)
            self.assertIn('!= "none"', source, relative)

    def test_production_role_gate_precedes_host_and_artifact_preflight(
        self,
    ) -> None:
        cases = {
            "tools/run_reward_ablation.sh": (
                "production reward launcher requires an ordinary role-none",
                ("command -v flock", "nvidia-smi", "exec 9>"),
            ),
            "tools/run_reward_screen.sh": (
                "production reward screen requires an ordinary role-none",
                ("command -v flock", 'mkdir -p "$OUT_DIR"', 'PYBIN="$ROOT/vendor'),
            ),
        }
        for relative, (marker, later_markers) in cases.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            gate = source.index(marker)
            for later in later_markers:
                with self.subTest(relative=relative, later=later):
                    self.assertLess(gate, source.index(later))

    def test_ordinary_check_rejects_role_before_snapshot_checks(self) -> None:
        source = (ROOT / "tools/install_puffer_env.sh").read_text(
            encoding="utf-8"
        )
        call = source.index("\nrequire_ordinary_qualification_role\n")
        check_branch = source.index('if [ "$MODE" = "check" ]; then')
        snapshot = source.index('want="$(snapshot_hash', check_branch)
        self.assertLess(call, check_branch)
        self.assertLess(call, snapshot)


if __name__ == "__main__":
    unittest.main()

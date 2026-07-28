#!/usr/bin/env python3
"""Source contracts for the strict Blood Bowl environment configuration.

Set ``PUFFER_STRICT_TEST_ROOT`` to an exact-pinned PufferLib checkout to enable
the binding checks.  They are skipped when no checkout is supplied.
"""

from __future__ import annotations

import configparser
import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "puffer" / "bloodbowl" / "binding.c"
HEADER = ROOT / "puffer" / "bloodbowl" / "bloodbowl.h"
ENVIRONMENT_CONFIG_HEADER = ROOT / "puffer" / "bloodbowl" / "environment_config.h"
CONFIG = ROOT / "puffer" / "config" / "bloodbowl.ini"
EXPECTED_ENV_KEY_COUNT = 51
PINNED_PUFFER_COMMIT = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"


def _strip_c_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def _top_level_brace_bodies(source: str) -> list[str]:
    """Return top-level C/C++ brace bodies.

    The two pinned binding files do not contain braces in comments or string
    literals, so a small brace balancer is sufficient and keeps this watched
    contract independent of a C++ parser.
    """

    bodies: list[str] = []
    depth = 0
    start: int | None = None
    for index, character in enumerate(source):
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise AssertionError("unbalanced closing brace in Puffer source")
            if depth == 0 and start is not None:
                bodies.append(source[start : index + 1])
                start = None
    if depth != 0:
        raise AssertionError("unbalanced opening brace in Puffer source")
    return bodies


def _environment_ledger_entries() -> list[tuple[str, str, str, str, str]]:
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
        r"\bX\(\s*([a-z0-9_]+)\s*,\s*([^,]+?)\s*,\s*"
        r"([^,]+?)\s*,\s*([A-Z0-9_]+)\s*,\s*([^)]+?)\s*\)",
        joined,
    )
    return [tuple(part.strip() for part in entry) for entry in entries]


class StrictEnvironmentConfigSourceTests(unittest.TestCase):
    def test_binding_and_ini_have_the_same_51_environment_keys(self) -> None:
        entries = _environment_ledger_entries()
        ledger_keys = [entry[0] for entry in entries]
        ledger_defaults = {entry[0]: float(entry[2]) for entry in entries}
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        with CONFIG.open(encoding="utf-8") as handle:
            parser.read_file(handle)
        ini_keys = list(parser["env"])

        self.assertEqual(len(ledger_keys), EXPECTED_ENV_KEY_COUNT)
        self.assertEqual(len(set(ledger_keys)), EXPECTED_ENV_KEY_COUNT)
        self.assertEqual(len(ini_keys), EXPECTED_ENV_KEY_COUNT)
        self.assertEqual(set(ledger_keys), set(ini_keys))
        self.assertEqual(
            ledger_defaults,
            {key: float(parser["env"][key]) for key in ini_keys},
        )

        environment_header = ENVIRONMENT_CONFIG_HEADER.read_text(encoding="utf-8")
        self.assertIn(
            "BBE_ENVIRONMENT_CONFIG_LEDGER(BBE_ENV_DESCRIPTOR)",
            environment_header,
        )
        self.assertRegex(
            environment_header,
            r"#define\s+BBE_ENV_DESCRIPTOR\([^)]*\)\s*\\\n"
            r"\s*\{#key,\s*#raw,\s*default_value,\s*"
            r"BBE_ENV_DOMAIN_##domain,\s*#destination\}",
        )
        binding = BINDING.read_text(encoding="utf-8")
        self.assertIn('#include "environment_config.h"', binding)
        self.assertIn("#define PUFFER_HAS_STRICT_ENV_CONFIG 1", binding)

    def test_binding_has_no_silent_enum_or_decision_limit_clamps(self) -> None:
        binding = _strip_c_comments(BINDING.read_text(encoding="utf-8"))
        clamps = (
            (
                "scripted_opponent_team",
                r"\benv->scripted_opponent_team\s*=\s*1\s*;",
            ),
            (
                "scripted_opponent_type",
                r"\benv->scripted_opponent_type\s*=\s*0\s*;",
            ),
            (
                "max_decisions",
                r"\benv->max_decisions\s*=\s*BBE_MAX_DECISIONS\s*;",
            ),
        )
        for field, pattern in clamps:
            with self.subTest(field=field):
                self.assertIsNone(
                    re.search(pattern, binding),
                    f"{field} still rewrites invalid input to a valid default",
                )

    def test_scripted_team_runtime_preserves_documented_both_mode(self) -> None:
        header = _strip_c_comments(HEADER.read_text(encoding="utf-8"))
        self.assertIsNotNone(
            re.search(
                r"\bscripted_both\s*=\s*" r"env->scripted_opponent_team\s*==\s*2\s*;",
                header,
            ),
            "the runtime no longer recognizes scripted_opponent_team=2 as BOTH",
        )
        self.assertIsNotNone(
            re.search(
                r"env->scripted_opponent\s*&&\s*"
                r"\(\s*scripted_both\s*\|\|\s*agent\s*==\s*scripted_team\s*\)",
                header,
            ),
            "the scripted action branch no longer dispatches for BOTH teams",
        )


class PinnedPufferStrictEnvironmentBoundaryTests(unittest.TestCase):
    def _root(self) -> Path:
        configured = os.environ.get("PUFFER_STRICT_TEST_ROOT")
        if not configured:
            self.skipTest("PUFFER_STRICT_TEST_ROOT is not set")

        root = Path(configured).resolve()
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout.strip(), PINNED_PUFFER_COMMIT)
        return root

    def _sources(self) -> list[tuple[str, str]]:
        root = self._root()
        sources: list[tuple[str, str]] = []
        for relative in ("src/bindings_cpu.cpp", "src/bindings.cu"):
            path = root / relative
            self.assertTrue(path.is_file(), f"missing pinned Puffer source: {path}")
            sources.append((relative, path.read_text(encoding="utf-8")))
        return sources

    def test_both_bindings_keep_the_full_python_key_length(self) -> None:
        for relative, source in self._sources():
            with self.subTest(binding=relative):
                self.assertIsNotNone(
                    re.search(r"\bPyUnicode_AsUTF8AndSize\s*\(", source),
                    f"{relative} still discards the Python key byte length",
                )
                length_is_consumed = False
                for declaration in re.finditer(
                    r"\bPy_ssize_t\s+([A-Za-z_][A-Za-z0-9_]*)" r"\s*(?:=[^;]*)?;",
                    source,
                ):
                    name = declaration.group(1)
                    if not re.search(
                        rf"PyUnicode_AsUTF8AndSize\s*\("
                        rf"[^;]*,\s*&\s*{re.escape(name)}\s*\)",
                        source,
                    ):
                        continue
                    # Declaration + API output argument + a later semantic use.
                    if len(re.findall(rf"\b{re.escape(name)}\b", source)) >= 3:
                        length_is_consumed = True
                        break
                self.assertTrue(
                    length_is_consumed,
                    f"{relative} obtains no key length that it then checks",
                )

    def test_length_aware_paths_do_not_swallow_numeric_cast_failures(self) -> None:
        catch_pattern = re.compile(
            r"catch\s*\(\s*const\s+py::cast_error\s*&[^)]*\)"
            r"\s*\{(?P<body>[^{}]*)\}",
            re.DOTALL,
        )
        for relative, source in self._sources():
            with self.subTest(binding=relative):
                strict_bodies = [
                    body
                    for body in _top_level_brace_bodies(source)
                    if "PyUnicode_AsUTF8AndSize" in body
                ]
                self.assertTrue(
                    strict_bodies,
                    f"{relative} has no length-aware environment-key path",
                )
                silent_catches = [
                    match.group("body")
                    for body in strict_bodies
                    for match in catch_pattern.finditer(body)
                    if not re.search(r"\bthrow\b", match.group("body"))
                ]
                self.assertEqual(
                    silent_catches,
                    [],
                    f"{relative} silently drops a nonnumeric environment value",
                )

    def test_strict_helper_is_env_only_and_precedes_constructor_work(self) -> None:
        sources = dict(self._sources())
        cpu = sources["src/bindings_cpu.cpp"]
        cuda = sources["src/bindings.cu"]

        self.assertEqual(
            cpu.count("static py::dict bloodbowl_normalize_and_preflight_env("),
            1,
        )
        self.assertEqual(
            cuda.count("static py::dict bloodbowl_normalize_and_preflight_env("),
            1,
        )
        self.assertEqual(
            cpu.count(
                "env_kwargs = " "bloodbowl_normalize_and_preflight_env(env_kwargs);"
            ),
            1,
        )
        self.assertEqual(
            cuda.count(
                "env_kwargs = " "bloodbowl_normalize_and_preflight_env(env_kwargs);"
            ),
            2,
        )

        for relative, source in sources.items():
            with self.subTest(binding=relative):
                helper_start = source.index(
                    "static py::dict " "bloodbowl_normalize_and_preflight_env("
                )
                helper_end = source.index("\n}\n\n} // namespace", helper_start)
                helper = source[helper_start:helper_end]
                self.assertLess(
                    helper.index("PyDict_Size(source.ptr())"),
                    helper.index("py::dict normalized"),
                )
                self.assertIn("PyUnicode_CheckExact", helper)
                self.assertIn("PyLong_CheckExact", helper)
                self.assertIn("PyFloat_CheckExact", helper)
                self.assertIn("PyBool_Check", helper)
                self.assertIn("my_environment_config_preflight(", helper)
                self.assertIn("PyGILState_Check()", helper)
                self.assertIn('m.attr("environment_config_schema")', source)
                self.assertIn('m.attr("strict_env_config_testing")', source)

        cpu_vec = cpu[
            cpu.index("static std::unique_ptr<VecEnv> create_vec(") : cpu.index(
                "static void vec_reset("
            )
        ]
        self.assertLess(
            cpu_vec.index("bloodbowl_normalize_and_preflight_env"),
            cpu_vec.index('get_config(vec_kwargs, "total_agents")'),
        )
        self.assertLess(
            cpu_vec.index("bloodbowl_normalize_and_preflight_env"),
            cpu_vec.index("py_dict_to_c_dict(vec_kwargs)"),
        )

        cuda_vec = cuda[
            cuda.index("std::unique_ptr<VecEnv> create_vec(") : cuda.index(
                "void vec_reset("
            )
        ]
        self.assertLess(
            cuda_vec.index("bloodbowl_normalize_and_preflight_env"),
            cuda_vec.index('get_config(vec_kwargs, "total_agents")'),
        )

        cuda_pufferl = cuda[
            cuda.index("std::unique_ptr<PuffeRL> create_pufferl(") : cuda.index(
                "PYBIND11_MODULE(_C",
                cuda.index("std::unique_ptr<PuffeRL> create_pufferl("),
            )
        ]
        self.assertLess(
            cuda_pufferl.index("bloodbowl_normalize_and_preflight_env"),
            cuda_pufferl.index('args["train"].cast<py::dict>()'),
        )
        self.assertLess(
            cuda_pufferl.index("bloodbowl_normalize_and_preflight_env"),
            cuda_pufferl.index('get_config(vec_kwargs, "total_agents")'),
        )
        self.assertLess(
            cuda_pufferl.index("bloodbowl_normalize_and_preflight_env"),
            cuda_pufferl.index("cudaGetDeviceCount(&device_count)"),
        )
        self.assertIn(
            "Dict* env_dict = " "py_dict_to_c_dict(env_kwargs.cast<py::dict>());",
            cuda_pufferl,
        )

    def test_build_marker_propagates_strict_and_test_roles(self) -> None:
        build = (self._root() / "build.sh").read_text(encoding="utf-8")
        self.assertIn(
            "grep -Fxq '#define PUFFER_HAS_STRICT_ENV_CONFIG 1' " '"$BINDING_SRC"',
            build,
        )
        self.assertIn(
            'STRICT_ENV_CONFIG_CFLAGS="-DPUFFER_STRICT_ENV_CONFIG=1"',
            build,
        )
        self.assertIn("-DPUFFER_STRICT_ENV_CONFIG_TESTING=1", build)
        self.assertGreaterEqual(
            build.count("$STRICT_ENV_CONFIG_CFLAGS"),
            3,
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Fail-closed contract for Blood Bowl's fixed-capacity Puffer log dict."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "puffer" / "bloodbowl" / "binding.c"
HEADER = ROOT / "puffer" / "bloodbowl" / "bloodbowl.h"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
CAPACITY_PATCH = ROOT / "training" / "puffer_dict_capacity.patch"
EXPECTED_CAPACITY = 160


class PufferLogContractTests(unittest.TestCase):
    def test_binding_keys_plus_vec_n_fit_patched_capacity(self) -> None:
        binding = BINDING.read_text()
        emitted_keys = len(re.findall(r"\bdict_set\s*\(\s*out\s*,", binding))
        # Kept exact on purpose: the count is load-bearing history (37 keys vs
        # capacity 32 corrupted the heap at ~786K steps). binding.c's my_log
        # CAPACITY comment is the authority -- update both together.
        self.assertEqual(emitted_keys, 144)
        self.assertLessEqual(emitted_keys + 1, EXPECTED_CAPACITY)

    def test_both_puffer_backends_and_installer_pin_same_capacity(self) -> None:
        patch = CAPACITY_PATCH.read_text()
        self.assertEqual(patch.count(f"create_dict({EXPECTED_CAPACITY})"), 2)
        self.assertEqual(
            re.findall(r"^diff --git a/(\S+) b/", patch, re.MULTILINE),
            ["src/bindings.cu", "src/bindings_cpu.cpp", "src/vecenv.h"],
        )
        self.assertIn("dict_set: capacity %d exceeded", patch)
        self.assertNotIn("src/kernels.cu", patch)
        self.assertNotIn("action_mask_ptr", patch)

        installer = INSTALLER.read_text()
        self.assertIn(
            'DICT_CAPACITY_PATCH="$ROOT/training/puffer_dict_capacity.patch"',
            installer,
        )
        capacity_install = installer.split("DICT_CAPACITY_PATCH=", 1)[1]
        capacity_install = capacity_install.split("\n# ", 1)[0]
        self.assertIn("apply --reverse --check --no-index", capacity_install)
        self.assertIn("apply --check --no-index", capacity_install)
        self.assertNotIn("'s/create_dict\\(", installer)

        launcher = (ROOT / "tools/run_reward_ablation.sh").read_text()
        self.assertIn(
            "patch_bundle_line training/puffer_dict_capacity.patch",
            launcher,
        )
        dashboard_patch = (
            ROOT / "training" / "pufferl_env_dashboard_limit.patch"
        ).read_text()
        self.assertIn("if i == 160:", dashboard_patch)
        self.assertIn("if i == 160:", installer)

    def test_every_ordinary_reward_mutation_uses_the_component_seam(self) -> None:
        header = HEADER.read_text()
        self.assertEqual(
            len(re.findall(r"reward_ptr\[[^\n;]*\]\[0\]\s*[+-]=", header)),
            1,
        )
        self.assertEqual(
            len(re.findall(r"ep_return\[[^\n;]*\]\s*[+-]=", header)), 1
        )
        self.assertIn("static inline void bbe_reward_add", header)

    def test_every_component_has_a_literal_binding_key(self) -> None:
        header = HEADER.read_text()
        binding = BINDING.read_text()
        enum_body = re.search(
            r"typedef enum \{(?P<body>.*?)BBE_REWARD_COMPONENT_COUNT,\s*\}",
            header,
            re.DOTALL,
        )
        self.assertIsNotNone(enum_body)
        components = re.findall(r"\b(BBE_REWARD_[A-Z0-9_]+)\s*,", enum_body["body"])
        self.assertEqual(len(components), 28)
        for component in components:
            with self.subTest(component=component):
                self.assertIn(f"log->reward_component[{component}]", binding)


if __name__ == "__main__":
    unittest.main()

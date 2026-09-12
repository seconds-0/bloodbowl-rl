"""Regression tests for Puffer's post-run metric reducer."""

import ast
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE = (
    ROOT / "audit-artifacts/puffer-metric-reducer-20260905/pufferl-failing.py"
)
VENDOR_HEAD = (
    ROOT / "audit-artifacts/puffer-metric-reducer-20260905/pufferl-vendor-head.py"
)
PATCH = ROOT / "training/pufferl_metrics_keyerror.patch"
PRIOR_PATCHES = (
    "pufferl_env_dashboard_limit.patch",
    "pufferl_env_json.patch",
    "pufferl_env_phase_contract.patch",
    "pufferl_eval_episode_gate.patch",
)


def load_function(source: Path, name: str):
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"np": np}
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    return namespace[name]


def run_original_reducer(source: Path, all_logs, n):
    """Execute the reducer block from the copied failing _train AST."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    train = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_train"
    )
    start = next(
        i for i, node in enumerate(train.body)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "metrics"
                for target in node.targets)
    )
    end = next(
        i for i in range(start, len(train.body))
        if isinstance(train.body[i], ast.If)
        and isinstance(train.body[i].test, ast.Name)
        and train.body[i].test.id == "match_mode"
    )
    body = train.body[start:end]
    body.append(ast.Return(value=ast.Name(id="metrics", ctx=ast.Load())))
    function = ast.FunctionDef(
        name="reduce", args=ast.arguments(
            posonlyargs=[], args=[ast.arg(arg="all_logs"), ast.arg(arg="n")],
            kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=body, decorator_list=[])
    namespace = {"np": np}
    exec(compile(ast.fix_missing_locations(ast.Module(
        body=[function], type_ignores=[])), str(source), "exec"), namespace)
    return namespace["reduce"](all_logs, n)


class PufferMetricReducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REAL_SOURCE.exists():
            raise unittest.SkipTest("copied failing Puffer source unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.checkout = Path(cls.temporary.name)
        target = cls.checkout / "pufferlib/pufferl.py"
        target.parent.mkdir(parents=True)
        source = REAL_SOURCE.read_text(encoding="utf-8")
        # The captured runtime already contains the previous version of this
        # patch. Reconstruct its upstream reducer so the amended patch is
        # exercised exactly as the clean installer applies it.
        source = source.replace(
            "metrics.setdefault(k, [[]])[-1].append(v)",
            "metrics[k][-1].append(v)")
        source = source.replace(
            "metrics[k][-1] = (\n"
            "                np.mean(metrics[k][-1]) if metrics[k][-1] else float(\"nan\"))",
            "metrics[k][-1] = np.mean(metrics[k][-1])")
        source = source.replace(
            "if k in all_logs[-1]:\n"
            "            metrics[k][-1] = all_logs[-1][k]\n"
            "        elif metrics[k][-1]:\n"
            "            metrics[k][-1] = np.mean(metrics[k][-1])\n"
            "        else:\n"
            "            metrics[k][-1] = float(\"nan\")",
            "metrics[k][-1] = all_logs[-1][k]")
        target.write_text(source, encoding="utf-8")
        subprocess.run(
            ["git", "apply", str(PATCH)], cwd=cls.checkout,
            check=True, capture_output=True, text=True)
        cls.reduce = staticmethod(load_function(target, "_downsample_logs"))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_copied_real_reducer_reproduces_u46_string_crash(self):
        logs = [{
            "agent_steps": 1,
            "entropy_schedule/entropy_schedule_contract":
                "cosine-update-index-over-total-updates-fp32-v1",
        }]
        with self.assertRaises(TypeError):
            run_original_reducer(REAL_SOURCE, logs, 2)

    def test_patch_applies_at_its_real_install_position(self):
        self.assertTrue(VENDOR_HEAD.exists(), "pristine vendor pufferl.py missing")
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            target = checkout / "pufferlib/pufferl.py"
            target.parent.mkdir(parents=True)
            shutil.copy2(VENDOR_HEAD, target)
            for name in (*PRIOR_PATCHES, PATCH.name):
                result = subprocess.run(
                    ["git", "apply", str(ROOT / "training" / name)],
                    cwd=checkout, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, (name, result.stderr))
            reduce = load_function(target, "_downsample_logs")
            metrics, metadata = reduce([
                {"agent_steps": 1, "diagnostic": "ready", "score": 2.0}
            ], 2)
            self.assertEqual(metrics["score"], [2.0, 2.0])
            self.assertEqual(metadata, {"diagnostic": "ready"})

    def test_numeric_curves_and_late_keys_keep_final_value_behavior(self):
        logs = [
            {"agent_steps": 0, "loss": 2.0},
            {"agent_steps": 5, "loss": 4.0, "late": 8.0},
            {"agent_steps": 10, "loss": 9.0},
        ]
        metrics, metadata = self.reduce(logs, 3)
        self.assertEqual(metadata, {})
        self.assertEqual(metrics["loss"], [3.0, 9.0, 9.0])
        self.assertEqual(metrics["agent_steps"], [2.5, 10, 10])
        self.assertEqual(metrics["late"][0], 8.0)
        self.assertTrue(np.isnan(metrics["late"][1]))
        self.assertTrue(np.isnan(metrics["late"][2]))

    def test_text_diagnostics_are_visible_as_latest_metadata(self):
        logs = [
            {"agent_steps": 0,
             "entropy_schedule/entropy_schedule_contract":
                "cosine-update-index-over-total-updates-fp32-v1",
             "entropy_schedule/interval_role": "training",
             "entropy_schedule/schedule_update_count": 1},
            {"agent_steps": 10,
             "entropy_schedule/entropy_schedule_contract":
                "cosine-update-index-over-total-updates-fp32-v1",
             "entropy_schedule/interval_role": "empty",
             "entropy_schedule/schedule_update_count": 0},
        ]
        metrics, metadata = self.reduce(logs, 2)
        self.assertNotIn("entropy_schedule/interval_role", metrics)
        self.assertEqual(metadata["entropy_schedule/interval_role"], "empty")
        self.assertEqual(
            metadata["entropy_schedule/entropy_schedule_contract"],
            "cosine-update-index-over-total-updates-fp32-v1")
        self.assertEqual(metrics["entropy_schedule/schedule_update_count"][-1], 0)

    def test_mixed_numeric_and_text_key_is_rejected(self):
        logs = [
            {"agent_steps": 0, "diagnostic": 1.0},
            {"agent_steps": 10, "diagnostic": "bad"},
        ]
        with self.assertRaisesRegex(
                TypeError, "'diagnostic' changed from metric to metadata"):
            self.reduce(logs, 2)

    def test_unsupported_metadata_type_is_rejected(self):
        with self.assertRaisesRegex(
                TypeError, "'diagnostic'.*unsupported value type dict"):
            self.reduce([{"agent_steps": 1, "diagnostic": {"x": 1}}], 2)


if __name__ == "__main__":
    unittest.main()

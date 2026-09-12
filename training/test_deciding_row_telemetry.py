"""Contracts for the opt-in deciding-row PPO telemetry patch (audit B6).

A waiting coach's rollout row carries the singleton BB_A_NONE support
(puffer/bloodbowl/binding.c): one enabled action per head, so zero entropy,
ratio exactly 1 and no policy gradient. The stock native PPO kernel still
averages entropy, kl and clipfrac over every row, which roughly halves the
displayed values in self-play. training/puffer_deciding_row_telemetry.patch
adds deciding-row means, full-precision loss records, grad norm and explained
variance WITHOUT touching the loss or any gradient, and the installer applies it
only when BBE_DECIDING_ROW_TELEMETRY=1 so the default patch bundle (and every
lineage digest bound to it) stays byte-identical.

The CUDA kernel cannot run on a Mac, so the formula checks below lift the
patch's own C statements (channel writes, binding reductions, grad-norm
accumulator) into Python and run them on a synthetic minibatch. The installer
integration test runs when BBE_PINNED_PUFFER_TREE names a clean PufferLib
checkout at the pinned SHA.
"""

from __future__ import annotations

import hashlib
import math
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_deciding_row_telemetry.patch"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
SCREEN = ROOT / "tools" / "run_reward_screen.sh"
ABLATION = ROOT / "tools" / "run_reward_ablation.sh"
BINDING = ROOT / "puffer" / "bloodbowl" / "binding.c"
FLAG = "BBE_DECIDING_ROW_TELEMETRY"

# Recorded by the chain 9 ladder rung on the rig
# (/home/rache/bloodbowl-rl-qualification-candidate-10619e2/runs/
# ladder-d0-r0chain9-20260824, puffer_patch_bundle_sha256). Chain 23 launches
# from the same tree with the same training/*.patch bytes; the screen labels
# each patch with its absolute path, so the pin is bound to that root.
RIG_ROOT = "/home/rache/bloodbowl-rl-qualification-candidate-10619e2"
CHAIN9_PATCH_BUNDLE_SHA256 = (
    "de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad")
# PUFFER_EXACT_ACTION_SOURCE_HASH in the same tree's
# vendor/PufferLib/src/exact_action_build_hash.h (default install).
RIG_DEFAULT_BACKEND_SHA256 = (
    "85fa29c01a5349984322bcc26060919e8a3efe68ccb59e49187f97810407173f")
PINNED_PUFFER_SHA = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"

STOCK_CHANNELS = ("LOSS_PG", "LOSS_VF", "LOSS_ENT", "LOSS_TOTAL",
                  "LOSS_OLD_APPROX_KL", "LOSS_APPROX_KL", "LOSS_CLIPFRAC")


def patch_files(text):
    """{path: [(kind, line)]} with kind in ' ', '+', '-'."""
    files = {}
    current = None
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            current = files.setdefault(line[6:], [])
            continue
        if line.startswith(("--- ", "diff --git", "index ", "@@")):
            continue
        if current is None or not line:
            continue
        if line[0] in " +-":
            current.append((line[0], line[1:]))
    return files


def added(text, path):
    return [line for kind, line in patch_files(text).get(path, []) if kind == "+"]


def new_side(text, path):
    return [line for kind, line in patch_files(text).get(path, []) if kind in " +"]


def c_expr(expr):
    expr = re.sub(r"\b(\d+(?:\.\d+)?(?:e-?\d+)?)f\b", r"\1", expr)
    expr = re.sub(r"\((?:double|float)\)\s*", "", expr)
    expr = expr.replace("fabsf(", "abs(").replace("sqrtf(", "math.sqrt(")
    expr = re.sub(r"\(\*(\w+)\)", r"(\1[0])", expr)
    expr = expr.replace("||", " or ").replace("&&", " and ")
    ternary = re.match(r"^(.*?)\s+\?\s+(.*?)\s+:\s+(.*)$", expr)
    if ternary:
        cond, yes, no = ternary.groups()
        expr = f"(({yes}) if ({cond}) else ({no}))"
    return expr


def c_block_to_python(lines):
    """Lift simple one-line C statements (and if-blocks) into Python."""
    out = []
    depth = 0
    for raw in lines:
        stmt = raw.strip()
        if not stmt or stmt.startswith("//"):
            continue
        if stmt == "}":
            depth -= 1
            continue
        pad = "    " * depth
        match = re.match(r"^if \((.*)\) \{$", stmt)
        if match:
            out.append(f"{pad}if {c_expr(match.group(1))}:")
            depth += 1
            continue
        match = re.match(r"^(?:const\s+)?(?:float|double|bool|int) (\w+) = (.*);$", stmt)
        if match:
            out.append(f"{pad}{match.group(1)} = {c_expr(match.group(2))}")
            continue
        match = re.match(r"^(.*?)\s(=|\+=)\s(.*);$", stmt)
        if match:
            target, op, value = match.groups()
            out.append(f"{pad}{c_expr(target)} {op} {c_expr(value)}")
            continue
        raise AssertionError(f"statement is not in the liftable subset: {stmt!r}")
    if depth != 0:
        raise AssertionError("unbalanced braces in lifted block")
    return "\n".join(out) + "\n"


def marked_block(lines, begin, end, exact=False):
    """Lines strictly between the first line containing `begin` and `end`."""
    start = next(i for i, line in enumerate(lines) if begin in line)
    stop = next(i for i in range(start + 1, len(lines))
                if (lines[i] == end if exact else end in lines[i]))
    return lines[start + 1:stop]


def loss_enum(text):
    enum_lines = marked_block(new_side(text, "src/pufferlib.cu"), "enum LossIdx {", "};")
    values = {}
    for name, value in re.findall(r"(\w+)\s*=\s*(\d+)", " ".join(enum_lines)):
        values[name] = int(value)
    return values


def act_sizes():
    match = re.search(r"#define ACT_SIZES \{([^}]*)\}", BINDING.read_text(encoding="utf-8"))
    return [int(part) for part in match.group(1).split(",")]


def masked_log_softmax(logits, mask):
    enabled = logits[mask]
    top = enabled.max()
    lse = top + math.log(np.exp(enabled - top).sum())
    return logits - lse


class SyntheticMinibatch:
    """One (N*T)-row minibatch with a known deciding share."""

    def __init__(self, rng, rows, singleton_share, clip_coef):
        sizes = act_sizes()
        self.sizes = sizes
        self.rows = rows
        self.mask = np.zeros((rows, sum(sizes)), dtype=np.float32)
        self.entropy = np.zeros(rows)
        self.logratio = np.zeros(rows)
        self.deciding = np.ones(rows, dtype=bool)
        singleton = rng.permutation(rows) < int(round(rows * singleton_share))
        self.deciding[singleton] = False
        for row in range(rows):
            offset = 0
            for head, size in enumerate(sizes):
                logits = rng.normal(0.0, 1.5, size)
                if singleton[row]:
                    enabled = np.zeros(size, dtype=bool)
                    enabled[0] = True
                else:
                    # The type head always has a real choice; later heads are
                    # conditional supports and may themselves be singletons.
                    low = 2 if head == 0 else 1
                    count = rng.integers(low, min(size, 12) + 1)
                    enabled = np.zeros(size, dtype=bool)
                    enabled[rng.choice(size, count, replace=False)] = True
                self.mask[row, offset:offset + size] = enabled
                logp = masked_log_softmax(logits, enabled)
                p = np.exp(logp[enabled])
                self.entropy[row] += float(-(p * logp[enabled]).sum())
                offset += size
            if self.deciding[row]:
                self.logratio[row] = rng.normal(0.0, 0.15)
        self.ratio = np.exp(self.logratio)
        self.clip_coef = clip_coef
        self.values = rng.normal(0.3, 0.8, rows)
        self.returns = self.values + rng.normal(0.1, 0.5, rows)
        self.grad_sum_sq = float(rng.uniform(0.5, 9.0))


def row_has_choice_reference(mask, row, sizes):
    offset = 0
    for size in sizes:
        if mask[row, offset:offset + size].sum() > 1:
            return True
        offset += size
    return False


class PatchedTelemetry:
    """Runs the patch's own C statements over synthetic minibatches."""

    def __init__(self, text):
        self.enum = loss_enum(text)
        cu = added(text, "src/pufferlib.cu")
        self.kernel = compile(c_block_to_python(marked_block(
            cu, "BEGIN deciding-row telemetry channels",
            "END deciding-row telemetry channels")), "<kernel>", "exec")
        self.grad_norm = compile(c_block_to_python(marked_block(
            cu, "__global__ void accumulate_grad_norm(", "}", exact=True)),
            "<grad_norm>", "exec")
        self.binding = compile(c_block_to_python(marked_block(
            added(text, "src/bindings.cu"),
            "BEGIN deciding-row telemetry log", "END deciding-row telemetry log")),
            "<binding>", "exec")

    def run(self, minibatches):
        num = self.enum["NUM_LOSSES"]
        acc = np.zeros(num, dtype=np.float64)
        for mb in minibatches:
            inv_NT = 1.0 / mb.rows
            channels = np.zeros(num, dtype=np.float64)
            for row in range(mb.rows):
                block_losses = np.zeros((num, 1), dtype=np.float64)
                env = dict(self.enum)
                env.update({
                    "math": math, "abs": abs, "tid": 0, "inv_NT": inv_NT,
                    "block_losses": block_losses,
                    "total_entropy": mb.entropy[row],
                    "logratio": mb.logratio[row], "ratio": mb.ratio[row],
                    "val": mb.values[row], "ret": mb.returns[row],
                    "mask_base": row,
                    "a": type("Args", (), {
                        "clip_coef": mb.clip_coef, "is_continuous": False,
                        "action_mask": mb.mask, "act_sizes": mb.sizes,
                        "num_atns": len(mb.sizes)}),
                    "row_has_choice": lambda mask, base, sizes, heads:
                        row_has_choice_reference(mask, base, sizes[:heads]),
                })
                # Stock channels, verbatim from the pinned tree's
                # ppo_loss_compute (unchanged by the patch).
                block_losses[self.enum["LOSS_ENT"]][0] = mb.entropy[row] * inv_NT
                block_losses[self.enum["LOSS_APPROX_KL"]][0] = (
                    (mb.ratio[row] - 1.0) - mb.logratio[row]) * inv_NT
                block_losses[self.enum["LOSS_CLIPFRAC"]][0] = (
                    1.0 if abs(mb.ratio[row] - 1.0) > mb.clip_coef else 0.0) * inv_NT
                exec(self.kernel, env)
                channels += block_losses[:, 0]
            # ppo_loss_reduce: channel c lands in losses_acc[c]; one count per
            # minibatch in losses_acc[LOSS_N].
            acc[:self.enum["LOSS_N"]] += channels[:self.enum["LOSS_N"]]
            acc[self.enum["LOSS_N"]] += 1.0
            env = dict(self.enum)
            env.update({"math": math, "losses_acc": acc,
                        "grad_norm_sq": np.array([mb.grad_sum_sq])})
            exec(self.grad_norm, env)
        losses_dict = {}
        n = acc[self.enum["LOSS_N"]]
        env = dict(self.enum)
        env.update({"math": math, "losses_host": acc, "losses_dict": losses_dict,
                    "n": n, "inv_n": 1.0 / n})
        # Stock reductions (bindings.cu, unchanged by the patch).
        losses_dict["entropy"] = acc[self.enum["LOSS_ENT"]] / n
        losses_dict["kl"] = acc[self.enum["LOSS_APPROX_KL"]] / n
        losses_dict["clipfrac"] = acc[self.enum["LOSS_CLIPFRAC"]] / n
        exec(self.binding, env)
        return losses_dict


class DecidingRowFormulaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        rng = np.random.default_rng(20260911)
        cls.clip = 0.2
        cls.minibatches = [SyntheticMinibatch(rng, 256, 0.5, cls.clip)
                           for _ in range(2)]
        cls.logs = PatchedTelemetry(cls.text).run(cls.minibatches)

    def pooled(self, field, rows_filter=None):
        values = np.concatenate([getattr(mb, field) for mb in self.minibatches])
        if rows_filter is None:
            return values
        keep = np.concatenate([rows_filter(mb) for mb in self.minibatches])
        return values[keep]

    def test_half_singleton_rows_halve_the_stock_entropy_kl_clipfrac(self):
        deciding_entropy = self.pooled("entropy", lambda mb: mb.deciding).mean()
        self.assertGreater(deciding_entropy, 0.5)
        self.assertAlmostEqual(self.logs["entropy"], 0.5 * deciding_entropy, places=9)

    def test_reported_deciding_entropy_equals_deciding_row_entropy(self):
        deciding_entropy = self.pooled("entropy", lambda mb: mb.deciding).mean()
        self.assertAlmostEqual(self.logs["entropy_deciding"], deciding_entropy, places=9)
        self.assertAlmostEqual(self.logs["deciding_frac"], 0.5, places=12)

    def test_reported_deciding_kl_and_clipfrac_equal_deciding_row_means(self):
        ratio = self.pooled("ratio", lambda mb: mb.deciding)
        logratio = self.pooled("logratio", lambda mb: mb.deciding)
        kl = ((ratio - 1.0) - logratio).mean()
        clipfrac = (np.abs(ratio - 1.0) > self.clip).mean()
        self.assertGreater(clipfrac, 0.0)
        self.assertAlmostEqual(self.logs["kl_deciding"], kl, places=9)
        self.assertAlmostEqual(self.logs["clipfrac_deciding"], clipfrac, places=9)
        self.assertAlmostEqual(self.logs["kl"], 0.5 * kl, places=9)
        self.assertAlmostEqual(self.logs["clipfrac"], 0.5 * clipfrac, places=9)

    def test_explained_variance_is_pooled_one_minus_residual_over_return_variance(self):
        returns = self.pooled("returns")
        values = self.pooled("values")
        expected = 1.0 - np.var(returns - values) / np.var(returns)
        self.assertAlmostEqual(self.logs["explained_variance"], expected, places=9)

    def test_grad_norm_is_the_mean_pre_clip_norm_per_minibatch(self):
        expected = np.mean([math.sqrt(mb.grad_sum_sq) for mb in self.minibatches])
        self.assertAlmostEqual(self.logs["grad_norm"], expected, places=12)

    def test_all_singleton_batch_reports_no_deciding_means(self):
        rng = np.random.default_rng(7)
        logs = PatchedTelemetry(self.text).run(
            [SyntheticMinibatch(rng, 64, 1.0, self.clip)])
        self.assertEqual(logs["deciding_frac"], 0.0)
        for key in ("entropy_deciding", "kl_deciding", "clipfrac_deciding"):
            self.assertNotIn(key, logs)


class PatchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.files = patch_files(cls.text)

    def test_patch_touches_only_the_native_trainer_binding_and_dashboard(self):
        self.assertEqual(sorted(self.files),
                         ["pufferlib/pufferl.py", "src/bindings.cu", "src/pufferlib.cu"])

    def test_stock_loss_channels_keep_their_indices(self):
        enum = loss_enum(self.text)
        for index, name in enumerate(STOCK_CHANNELS):
            self.assertEqual(enum[name], index)
        new = sorted((value, name) for name, value in enum.items()
                     if name not in STOCK_CHANNELS + ("LOSS_N", "NUM_LOSSES"))
        self.assertEqual([value for value, _ in new if value < enum["LOSS_N"]],
                         list(range(len(STOCK_CHANNELS), enum["LOSS_N"])))
        self.assertEqual(enum["LOSS_GRAD_NORM"], enum["LOSS_N"] + 1)
        self.assertEqual(enum["NUM_LOSSES"], enum["LOSS_GRAD_NORM"] + 1)

    def test_removed_lines_are_only_the_enum_and_the_dashboard_format(self):
        removed = [(path, line.strip()) for path, lines in self.files.items()
                   for kind, line in lines if kind == "-"]
        allowed = {
            ("src/pufferlib.cu", "LOSS_N = 7, NUM_LOSSES = 8,"),
            ("pufferlib/pufferl.py",
             "l.add_column(f'{c1}Value', justify=\"right\", width=8)"),
            ("pufferlib/pufferl.py", "l.add_row(f'{b2}{k[5:]}', f'{b2}{v:.3f}')"),
        }
        self.assertEqual(set(removed) - allowed, set())

    def test_added_code_never_writes_the_loss_or_a_gradient(self):
        forbidden = re.compile(
            r"grad_logits\[|grad_logstd\[|grad_values_pred\[|thread_loss|"
            r"loss_output|\*loss\s*\+=|muon_clip_norm|"
            r"block_losses\[(LOSS_PG|LOSS_VF|LOSS_ENT|LOSS_TOTAL|"
            r"LOSS_OLD_APPROX_KL|LOSS_APPROX_KL|LOSS_CLIPFRAC)\]")
        for path in ("src/pufferlib.cu", "src/bindings.cu"):
            for line in added(self.text, path):
                self.assertIsNone(forbidden.search(line), f"{path}: {line}")

    def test_grad_norm_accumulates_inside_the_captured_train_graph(self):
        lines = self.files["src/pufferlib.cu"]
        launch = next(i for i, (kind, line) in enumerate(lines)
                      if kind == "+" and "accumulate_grad_norm<<<" in line)
        before = [line for _, line in lines[max(0, launch - 4):launch]]
        self.assertTrue(any("muon_step(&pufferl.muon" in line for line in before))
        self.assertIn("pufferl.muon.grad_norm_ptr", lines[launch][1])
        self.assertIn("pufferl.losses_puf.data", lines[launch][1])

    def test_row_choice_counts_enabled_actions_per_head(self):
        body = "\n".join(marked_block(added(self.text, "src/pufferlib.cu"),
                                      "row_has_choice(", "}", exact=True))
        self.assertIn("action_enabled(mask, mask_base, logits_offset, j)", body)
        self.assertIn("int enabled = 0;", body)
        self.assertRegex(body, r"\+\+enabled > 1")
        self.assertIn("logits_offset += act_sizes[h];", body)

    def test_full_precision_record_cannot_raise_or_collide_with_the_env_panel(self):
        py = "\n".join(added(self.text, "pufferlib/pufferl.py"))
        self.assertIn("PUFFER_LOSS_JSON ", py)
        self.assertNotIn("PUFFER_ENV_JSON", py)
        self.assertIn("np.isfinite(value)", py)
        self.assertIn("os.write(sys.stdout.fileno()", py)


def bundle_list(script, pattern):
    return re.findall(pattern, script.read_text(encoding="utf-8"))


def screen_bundle_sha(root_label, names):
    return hashlib.sha256(b"".join(
        f"{hashlib.sha256((ROOT / 'training' / name).read_bytes()).hexdigest()}"
        f"  {root_label}/training/{name}\n".encode()
        for name in names)).hexdigest()


class DefaultBundleTests(unittest.TestCase):
    def test_screen_and_arm_bundles_exclude_the_opt_in_patch(self):
        screen = bundle_list(SCREEN, r'root / "training/([\w.]+\.patch)"')
        arm = bundle_list(ABLATION, r'sha256sum "\$ROOT/training/([\w.]+\.patch)"')
        self.assertEqual(screen, arm)
        self.assertEqual(len(screen), 13)
        self.assertNotIn(PATCH.name, screen)

    def test_default_bundle_digest_is_the_chain9_lineage_digest(self):
        names = bundle_list(SCREEN, r'root / "training/([\w.]+\.patch)"')
        self.assertEqual(screen_bundle_sha(RIG_ROOT, names), CHAIN9_PATCH_BUNDLE_SHA256)

    def test_installer_gates_the_patch_on_the_flag(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("training/puffer_deciding_row_telemetry.patch", installer)
        self.assertIn(f'"${{{FLAG}:-0}}" = "1"', installer)
        applies = [line for line in installer.splitlines()
                   if "apply --no-index \"$TELEMETRY_PATCH\"" in line]
        self.assertEqual(len(applies), 1)


def run(cmd, **kwargs):
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False, **kwargs)


@unittest.skipUnless(os.environ.get("BBE_PINNED_PUFFER_TREE"),
                     "set BBE_PINNED_PUFFER_TREE to a clean PufferLib checkout "
                     f"at {PINNED_PUFFER_SHA}")
class InstallerIntegrationTests(unittest.TestCase):
    """Drive the real installer over a scratch clone of the pinned tree."""

    TRACKED = ("src/pufferlib.cu", "src/bindings.cu", "pufferlib/pufferl.py")

    @classmethod
    def setUpClass(cls):
        source = pathlib.Path(os.environ["BBE_PINNED_PUFFER_TREE"])
        head = run(["git", "-C", str(source), "rev-parse", "HEAD"]).stdout.strip()
        if head != PINNED_PUFFER_SHA:
            raise unittest.SkipTest(f"{source} is at {head}, not {PINNED_PUFFER_SHA}")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.puffer = pathlib.Path(cls.tmp.name) / "PufferLib"
        clone = run(["git", "clone", "-q", str(source), str(cls.puffer)])
        assert clone.returncode == 0, clone.stderr
        dirty = run(["git", "-C", str(cls.puffer), "status", "--porcelain",
                     "--untracked-files=no"]).stdout
        assert dirty == "", dirty

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def install(self, flag=None, check=False):
        env = {k: v for k, v in os.environ.items() if k != FLAG}
        if flag is not None:
            env[FLAG] = flag
        args = ["bash", str(INSTALLER)] + (["--check"] if check else []) + [str(self.puffer)]
        return run(args, env=env)

    def digest(self):
        header = (self.puffer / "src/exact_action_build_hash.h").read_text(encoding="utf-8")
        return re.search(r'PUFFER_EXACT_ACTION_SOURCE_HASH "([0-9a-f]{64})"', header).group(1)

    def file_hashes(self):
        return {rel: hashlib.sha256((self.puffer / rel).read_bytes()).hexdigest()
                for rel in self.TRACKED}

    # Patches the installer proves present by full reverse applicability.
    REVERSE_CHECKED = ("selfplay_league.patch",
                       "puffer_frozen_prio_mask.patch",
                       "puffer_recurrent_cuda_qualification.patch",
                       "puffer_reward_clamp_range.patch",
                       "pufferl_scripted_training_guard.patch",
                       "pufferl_warm_start.patch")
    # Proven by markers only: later patches overlap their context lines.
    MARKER_CHECKED = ("puffer_exact_joint_actions.patch",
                      "puffer_recurrent_eval_state.patch")

    def reverse_outcomes(self):
        return {name: run(["git", "-C", str(self.puffer), "apply", "--reverse",
                           "--check", "--no-index", str(ROOT / "training" / name)]
                          ).returncode
                for name in self.REVERSE_CHECKED + self.MARKER_CHECKED}

    def test_default_flag_round_trip(self):
        default = self.install()
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertNotIn("telemetry", default.stdout)
        self.assertEqual(self.digest(), RIG_DEFAULT_BACKEND_SHA256)
        default_files = self.file_hashes()
        default_outcomes = self.reverse_outcomes()
        for name in self.REVERSE_CHECKED:
            self.assertEqual(default_outcomes[name], 0, name)
        self.assertEqual(run(["git", "-C", str(self.puffer), "apply", "--check",
                              "--no-index", str(PATCH)]).returncode, 0)

        opted = self.install("1")
        self.assertEqual(opted.returncode, 0, opted.stderr)
        self.assertIn("applied:   deciding-row PPO telemetry", opted.stdout)
        opted_digest = self.digest()
        self.assertNotEqual(opted_digest, RIG_DEFAULT_BACKEND_SHA256)
        self.assertIn("LOSS_DECIDING_FRAC",
                      (self.puffer / "src/pufferlib.cu").read_text(encoding="utf-8"))
        self.assertEqual(self.reverse_outcomes(), default_outcomes)

        again = self.install("1")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.digest(), opted_digest)

        # --check has no vendored venv here, so it stops at the Python probe;
        # reaching that message means every marker gate before it passed.
        mismatch = self.install(check=True)
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("opt-in deciding-row telemetry patch", mismatch.stderr)
        matched = self.install("1", check=True)
        self.assertEqual(matched.returncode, 1)
        self.assertIn("vendored Python is missing", matched.stderr)

        bad = self.install("yes")
        self.assertEqual(bad.returncode, 1)
        self.assertIn(FLAG, bad.stderr)

        restored = self.install()
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertIn("reversed:  deciding-row PPO telemetry", restored.stdout)
        self.assertEqual(self.digest(), RIG_DEFAULT_BACKEND_SHA256)
        self.assertEqual(self.file_hashes(), default_files)
        plain_check = self.install(check=True)
        self.assertIn("vendored Python is missing", plain_check.stderr)


if __name__ == "__main__":
    unittest.main()

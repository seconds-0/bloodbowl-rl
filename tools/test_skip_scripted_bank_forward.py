#!/usr/bin/env python3
"""The opt-in scripted-bank forward skip (audit S4).

training/puffer_skip_scripted_bank_forward.patch removes the frozen-policy
forward for the rows of the bank the scripted bot plays: bloodbowl.h c_step
never decodes a sampled action on those seats. It is opt-in
(PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1), so the default tree and the default
patch bundle stay byte-identical.

No vendored Puffer tree exists on a Mac checkout and nvcc does not run here,
so these tests
  * extract the host-only keying/routing header from the patch, compile it with
    the system C compiler, and drive it with selfplay routing layouts;
  * pin the CUDA hunks statically: what they key on and where they sit;
  * pin the env semantics the skip depends on;
  * run the installer's opt-in and --check blocks against a synthetic tree
    assembled from the patch's own old-side context;
  * with PUFFER_PIN_TREE naming a pinned, fully installed Puffer tree, run the
    whole installer through the opt-in and back, require the default tree byte
    for byte, and cross-check the routing mirror against the real
    pufferlib/selfplay.py. Without it those tests skip.
"""

from __future__ import annotations

import ast
import filecmp
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training/puffer_skip_scripted_bank_forward.patch"
INSTALLER = ROOT / "tools/install_puffer_env.sh"
BINDING = ROOT / "puffer/bloodbowl/binding.c"
ENV_HEADER = ROOT / "puffer/bloodbowl/bloodbowl.h"
BB_TYPES = ROOT / "engine/include/bb/bb_types.h"
HEADER = "src/scripted_bank_skip.h"
PIN_TREE = os.environ.get("PUFFER_PIN_TREE", "")


def parse_patch(path=PATCH):
    """{file: {"new": bool, "hunks": [(old_lines, new_lines)]}} for a git diff."""
    files = {}
    current = None
    hunk = None
    in_header = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("diff --git "):
            current = files.setdefault(
                line.split(" b/", 1)[1], {"new": False, "hunks": []})
            hunk = None
            in_header = True
            continue
        if current is None:
            continue
        if line.startswith("@@"):
            hunk = ([], [])
            current["hunks"].append(hunk)
            in_header = False
            continue
        if in_header:
            if line.startswith("new file mode"):
                current["new"] = True
            continue
        if line.startswith("\\"):
            continue
        tag, body = line[:1], line[1:]
        if tag in (" ", ""):
            hunk[0].append(body)
            hunk[1].append(body)
        elif tag == "-":
            hunk[0].append(body)
        elif tag == "+":
            hunk[1].append(body)
    return files


def added_lines(name):
    lines = []
    for raw in PATCH.read_text(encoding="utf-8").split("diff --git ")[1:]:
        if raw.split("\n", 1)[0].endswith(" b/" + name):
            lines.extend(line[1:] for line in raw.splitlines()
                         if line.startswith("+") and not line.startswith("+++"))
    return lines


def header_text():
    entry = parse_patch()[HEADER]
    return "".join(line + "\n" for _, new in entry["hunks"] for line in new)


def write_synthetic_tree(directory):
    """Old-side context of every modified file; git apply tolerates offsets."""
    for name, entry in parse_patch().items():
        if entry["new"]:
            continue
        path = pathlib.Path(directory) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = []
        for old, _ in entry["hunks"]:
            body.extend(old)
            body.append("// synthetic gap")
        path.write_text("\n".join(body) + "\n", encoding="utf-8")


def tree_bytes(directory):
    root = pathlib.Path(directory)
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def build_perm_tags(num_buffers, agents_per_buffer, agents_per_env,
                    frozen_sizes, num_envs):
    """Mirror of pufferlib/selfplay.py build_perm_tags at the vendored pin
    (9836f0d2 plus training/selfplay_league.patch). With PUFFER_PIN_TREE set,
    test_mirror_matches_the_real_selfplay_routing checks it against the real one."""
    team_size = agents_per_env // 2
    envs_per_buffer = agents_per_buffer // agents_per_env
    num_banks = len(frozen_sizes)
    total_frozen = sum(frozen_sizes)
    hist_per_bank = [fs // team_size for fs in frozen_sizes]
    selfplay_envs = envs_per_buffer - sum(hist_per_bank)
    perm = [0] * (num_buffers * agents_per_buffer)
    tags = [0] * num_envs
    env_idx = 0
    for b_buf in range(num_buffers):
        buf_start = b_buf * agents_per_buffer
        hist_primary_start = buf_start + agents_per_buffer - 2 * total_frozen
        bank_starts = []
        offset = buf_start + agents_per_buffer - total_frozen
        for bank in range(num_banks):
            bank_starts.append(offset)
            offset += frozen_sizes[bank]
        h_within_buffer = 0
        for e in range(envs_per_buffer):
            slot_base = buf_start + e * agents_per_env
            if e < selfplay_envs:
                for s in range(agents_per_env):
                    perm[slot_base + s] = slot_base + s
                tags[env_idx] = 0
            else:
                bank_idx = 0
                cum = hist_per_bank[0]
                while h_within_buffer >= cum and bank_idx < num_banks - 1:
                    bank_idx += 1
                    cum += hist_per_bank[bank_idx]
                h_in_bank = h_within_buffer - (cum - hist_per_bank[bank_idx])
                team_a = hist_primary_start + h_within_buffer * team_size
                team_b = bank_starts[bank_idx] + h_in_bank * team_size
                for s in range(team_size):
                    perm[slot_base + s] = team_a + s
                    perm[slot_base + team_size + s] = team_b + s
                tags[env_idx] = bank_idx + 1
                h_within_buffer += 1
            env_idx += 1
    return perm, tags


def c_bank_layout(agents_per_buffer, num_frozen, frozen_bank_pct):
    """pufferlib.cu create_pufferl_impl + pufferl_add_frozen_bank."""
    size = int(agents_per_buffer * frozen_bank_pct)
    layout = [0, agents_per_buffer - size * num_frozen]
    for _ in range(num_frozen):
        layout.append(layout[-1] + size)
    return layout, size


def routing(total_agents, num_buffers, num_frozen, pct):
    apb = total_agents // num_buffers
    layout, size = c_bank_layout(apb, num_frozen, pct)
    envs = total_agents // 2
    perm, tags = build_perm_tags(num_buffers, apb, 2, [size] * num_frozen, envs)
    return {"buffers": num_buffers, "apb": apb, "layout": layout,
            "envs": envs, "tags": tags, "perm": perm}


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include "scripted_bank_skip.h"

static int read_int(void) {
    int value;
    if (scanf("%d", &value) != 1) exit(3);
    return value;
}

int main(void) {
    int mode = read_int();
    if (mode == 0) {
        int cases = read_int();
        for (int i = 0; i < cases; i++) {
            int is_bb = read_int(), so = read_int(), team = read_int();
            int tag = read_int(), banks = read_int();
            printf("%d\n", scripted_bank_skip_index(is_bb, so, team, tag, banks));
        }
        return 0;
    }
    int skip = read_int(), buffers = read_int(), apb = read_int();
    int num_banks = read_int(), envs = read_int(), ape = read_int();
    int has_perm = read_int();
    int* layout = malloc(sizeof(int) * (size_t)(num_banks + 1));
    for (int i = 0; i <= num_banks; i++) layout[i] = read_int();
    int* tags = malloc(sizeof(int) * (size_t)envs);
    for (int i = 0; i < envs; i++) tags[i] = read_int();
    int* perm = NULL;
    if (has_perm) {
        perm = malloc(sizeof(int) * (size_t)(envs * ape));
        for (int i = 0; i < envs * ape; i++) perm[i] = read_int();
    }
    char err[256] = "";
    int rc = scripted_bank_skip_validate(skip, buffers, apb, layout, num_banks,
        envs, ape, tags, perm, err, sizeof(err));
    printf("%d %s\n", rc, err);
    return 0;
}
"""


class HeaderHarness(unittest.TestCase):
    """The shipped keying and routing rules, compiled and executed."""

    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if compiler is None:
            raise unittest.SkipTest("no C compiler")
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(cls.tmp.name)
        (tmp / "scripted_bank_skip.h").write_text(header_text(), encoding="utf-8")
        (tmp / "harness.c").write_text(HARNESS, encoding="utf-8")
        cls.binary = tmp / "harness"
        subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(tmp),
             str(tmp / "harness.c"), "-o", str(cls.binary)],
            check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_harness(self, text):
        return subprocess.run([str(self.binary)], input=text, text=True,
                              capture_output=True, check=True).stdout

    def validate(self, skip, route, *, perm=True, envs=None, ape=2):
        envs = route["envs"] if envs is None else envs
        parts = [1, skip, route["buffers"], route["apb"], len(route["layout"]) - 1,
                 envs, ape, int(perm), *route["layout"], *route["tags"][:envs]]
        if perm:
            parts.extend(route["perm"][:envs * ape])
        out = self.run_harness(" ".join(map(str, parts)))
        rc, _, message = out.strip().partition(" ")
        return int(rc), message

    def test_skip_index_matches_the_env_bot_seat_rule(self):
        # bloodbowl.h c_step hands a seat to the bot when scripted_opponent != 0
        # and (scripted_bank_tag <= 0 or env->tag == scripted_bank_tag), on the
        # scripted_opponent_team side; binding.c refuses tag > 0 off AWAY.
        # Only the confined case owns a whole frozen bank of bot seats: frozen
        # bank b-1 carries tag b, and its slice is exactly its envs' AWAY seats.
        # Global mode (tag <= 0) and every learned bank keep their forward.
        cases, expected = [], []
        for is_bb in (0, 1):
            for so in (0, 1, 2):
                for team in (0, 1, 2):
                    for tag in range(-1, 10):
                        for banks in range(0, 9):
                            cases.append((is_bb, so, team, tag, banks))
                            bot_banks = [
                                b for b in range(1, banks + 1)
                                if is_bb and so != 0 and team == 1 and tag > 0
                                and b == tag]
                            expected.append(bot_banks[0] if bot_banks else 0)
        text = " ".join(map(str, [0, len(cases), *[v for c in cases for v in c]]))
        got = [int(v) for v in self.run_harness(text).split()]
        self.assertEqual(got, expected)
        # The recipes the rig runs.
        self.assertEqual(got[cases.index((1, 1, 1, 4, 4))], 4)   # chain 9
        self.assertEqual(got[cases.index((1, 1, 1, 8, 8))], 8)   # chain 23
        self.assertEqual(got[cases.index((1, 0, 1, 4, 4))], 0)   # no bot
        self.assertEqual(got[cases.index((1, 1, 1, 0, 4))], 0)   # global bot mode
        self.assertEqual(got[cases.index((1, 1, 1, 5, 4))], 0)   # tag past banks

    def test_chain_recipes_route_only_bot_seats_into_the_skipped_slice(self):
        for total, buffers, frozen, pct, tag in (
                (2048, 2, 4, 0.12, 4),   # chain 9: /home/rache/r0chain9.sh
                (2048, 2, 8, 0.06, 8),   # chain 23: /home/rache/r0chain23.sh
                (512, 2, 4, 0.12, 4),    # probe layout
                (512, 2, 8, 0.06, 8),
                (2048, 2, 1, 0.12, 1)):
            with self.subTest(total=total, frozen=frozen, tag=tag):
                route = routing(total, buffers, frozen, pct)
                self.assertEqual(self.validate(tag, route), (0, ""))

    def test_every_frozen_bank_routes_by_tag(self):
        # Routing is tag-exact for any frozen bank; the keying above is what
        # restricts the skip to the scripted one.
        route = routing(2048, 2, 4, 0.12)
        for bank in range(1, 5):
            self.assertEqual(self.validate(bank, route), (0, ""))

    def test_routing_violations_are_refused(self):
        base = routing(2048, 2, 4, 0.12)
        apb = base["apb"]
        lo, hi = base["layout"][4], base["layout"][5]
        tagged = [e for e, t in enumerate(base["tags"]) if t == 4]

        rc, message = self.validate(0, base)
        self.assertEqual(rc, 1)
        self.assertIn("outside frozen banks", message)
        rc, message = self.validate(5, base)
        self.assertEqual(rc, 1)

        rc, message = self.validate(4, base, perm=False)
        self.assertEqual(rc, 1)
        self.assertIn("no selfplay routing", message)

        untagged = dict(base, tags=[0] * base["envs"])
        rc, message = self.validate(4, untagged)
        self.assertEqual(rc, 1)
        self.assertIn("inside bank 4", message)

        seat_swap = dict(base, perm=list(base["perm"]))
        e = tagged[0]
        seat_swap["perm"][2 * e], seat_swap["perm"][2 * e + 1] = (
            seat_swap["perm"][2 * e + 1], seat_swap["perm"][2 * e])
        rc, message = self.validate(4, seat_swap)
        self.assertEqual(rc, 1)

        retagged = dict(base, tags=list(base["tags"]))
        retagged["tags"][tagged[-1]] = 3
        rc, message = self.validate(4, retagged)
        self.assertEqual(rc, 1)

        rc, message = self.validate(4, base, envs=base["envs"] - 1)
        self.assertEqual(rc, 1)
        self.assertIn("does not tile", message)

        # A learned-bank row in the scripted slice is refused even when the
        # tags are right: that seat's action would be read.
        crossed = dict(base, perm=list(base["perm"]))
        learned = [e for e, t in enumerate(base["tags"]) if t == 3][0]
        a, b = 2 * tagged[0] + 1, 2 * learned + 1
        crossed["perm"][a], crossed["perm"][b] = crossed["perm"][b], crossed["perm"][a]
        self.assertTrue(lo <= crossed["perm"][b] % apb < hi)
        rc, _ = self.validate(4, crossed)
        self.assertEqual(rc, 1)

    @unittest.skipUnless(PIN_TREE, "PUFFER_PIN_TREE not set")
    def test_mirror_matches_the_real_selfplay_routing(self):
        source = (pathlib.Path(PIN_TREE) / "pufferlib/selfplay.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "build_perm_tags")
        namespace = {"np": np}
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     "selfplay.py", "exec"), namespace)
        for total, buffers, frozen, pct in ((2048, 2, 4, 0.12), (2048, 2, 8, 0.06),
                                            (512, 2, 4, 0.12)):
            apb = total // buffers
            _, size = c_bank_layout(apb, frozen, pct)
            real_perm, real_tags, _ = namespace["build_perm_tags"](
                buffers, apb, 2, [size] * frozen, total // 2)
            perm, tags = build_perm_tags(buffers, apb, 2, [size] * frozen, total // 2)
            self.assertEqual(real_perm.tolist(), perm)
            self.assertEqual(real_tags.tolist(), tags)


class PatchContract(unittest.TestCase):
    """The CUDA hunks cannot compile here; pin what they key on and where."""

    def test_patch_touches_only_the_native_backend(self):
        files = parse_patch()
        self.assertEqual(set(files), {"src/pufferlib.cu", "src/bindings.cu", HEADER})
        self.assertTrue(files[HEADER]["new"])
        # Purely additive: no default-tree line is removed or rewritten.
        removed = [line for line in PATCH.read_text(encoding="utf-8").splitlines()
                   if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(removed, [])

    def test_forward_skip_is_keyed_to_the_scripted_bank_only(self):
        added = added_lines("src/pufferlib.cu")
        joined = "\n".join(added)
        skips = [line.strip() for line in added
                 if line.strip().startswith("if (") and "b == " in line]
        self.assertEqual(
            skips,
            ["if (pufferl->scripted_skip_bank > 0 && b == pufferl->scripted_skip_bank) {"])
        assignments = [line for line in added
                       if re.search(r"scripted_skip_bank\s*=(?!=)", line)]
        self.assertEqual(len(assignments), 1)
        self.assertIn("= scripted_bank_skip_index(", assignments[0])
        for key in ("scripted_opponent", "scripted_opponent_team", "scripted_bank_tag"):
            self.assertIn(f'dict_get_unsafe(env_kwargs, "{key}")', joined)
        self.assertIn('env_name == "bloodbowl"', joined)
        self.assertIn("team_item ? (int)team_item->value : 1", joined)
        self.assertIn("pufferl->num_frozen_banks);", joined)

    def test_skip_sits_before_the_forward_and_zero_fills_the_slice(self):
        hunk = next(new for old, new in parse_patch()["src/pufferlib.cu"]["hunks"]
                    if any("scripted_skip_bank > 0 && b ==" in l for l in new))
        text = [line.strip() for line in hunk]
        start = next(i for i, l in enumerate(text) if "b == pufferl->scripted_skip_bank" in l)
        end = text.index("continue;", start)
        forward = next(i for i, l in enumerate(text)
                       if l.startswith("reset_recurrent_state_on_terminal<<<"))
        self.assertLess(end, forward)
        self.assertIn("mask_stride_b = mask_stride;", text[:start])
        block = "\n".join(text[start:end])
        self.assertNotIn("policy_forward", block)
        self.assertNotIn("sample_logits", block)
        self.assertNotIn("rng_states", block)
        for target in ("act_b.data", "lp_b.data", "val_b.data"):
            self.assertIn(f"{target}, from_float(0.0f)", block)
        self.assertIn("env.actions.data + (long)sub_start * act_cols, act_b.data", block)

    def test_key_is_decided_after_bank_creation_and_routing_is_enforced(self):
        hunks = parse_patch()["src/pufferlib.cu"]["hunks"]
        create = next(new for _, new in hunks
                      if any("scripted_bank_skip_index(" in l for l in new))
        joined = "\n".join(create)
        # Trailing context is the joint-metadata upload that precedes graph
        # warmup; PinnedTreeRoundTrip checks the full-file order (after the
        # banks exist, before capture).
        self.assertLess(joined.index("scripted_bank_skip_index("),
                        joined.index("before graph warmup calls"))
        tags = next(new for _, new in hunks
                    if any("pufferl_set_env_tags(PuffeRL*" in l for l in new))
        joined = "\n".join(tags)
        self.assertIn("scripted_bank_skip_validate(pufferl->scripted_skip_bank", joined)
        self.assertLess(joined.index("static_vec_set_env_tags("),
                        joined.index("scripted_bank_skip_validate("))
        self.assertIn("abort();", joined)
        self.assertIn("pufferl->scripted_skip_routed = true;", joined)
        bindings = "\n".join(added_lines("src/bindings.cu"))
        self.assertIn(
            "if (pufferl.scripted_skip_bank > 0 && !pufferl.scripted_skip_routed) {",
            bindings)
        self.assertIn('m.attr("scripted_bank_forward_skip") = true;', bindings)
        self.assertIn('m.def("scripted_bank_skip"', bindings)

    def test_env_still_ignores_the_policy_action_on_bot_seats(self):
        env = ENV_HEADER.read_text(encoding="utf-8")
        self.assertIn(
            "int scripted_env = env->scripted_opponent &&\n"
            "            (env->scripted_bank_tag <= 0 || env->tag == env->scripted_bank_tag);",
            env)
        c_step = env[env.index("static void c_step(Bloodbowl* env) {"):]
        gate = c_step.index("if (scripted_env && (scripted_both || agent == scripted_team)) {")
        bot = c_step.index("bbe_contact_bot_pick(", gate)
        decode = c_step.index("act = bbe_decode(env, agent, env->action_ptr[agent]);", gate)
        self.assertLess(bot, decode)
        self.assertEqual(c_step[bot:decode].count("} else {"), 1)
        # c_step's decode is the only place the env reads a sampled action.
        reads = [m.start() for m in re.finditer(r"action_ptr\[agent\]\)", env)]
        self.assertEqual(len(reads), 1)
        binding = BINDING.read_text(encoding="utf-8")
        self.assertIn("if (env->scripted_bank_tag > 0 && env->scripted_opponent_team != BB_AWAY) {",
                      binding)
        self.assertIn("#define BB_AWAY 1", BB_TYPES.read_text(encoding="utf-8"))


def installer_block(start_marker, end_marker):
    text = INSTALLER.read_text(encoding="utf-8")
    start = text.index(start_marker)
    return text[start:text.index(end_marker, start)]


INSTALL_BLOCK = ("# Opt-in, off by default (audit S4)",
                 'EXACT_BACKEND_HASH="$(exact_backend_hash)"')
CHECK_BLOCK = ("# Opt-in scripted-bank forward skip: absent, or exactly the tracked patch.",
               'PYBIN="$PUFFER/.venv/bin/python"')


class InstallerOptIn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.puffer = pathlib.Path(self.tmp.name) / "PufferLib"
        write_synthetic_tree(self.puffer)
        self.default = tree_bytes(self.puffer)

    def tearDown(self):
        self.tmp.cleanup()

    def run_block(self, markers, request=None):
        env = {k: v for k, v in os.environ.items()
               if k != "PUFFER_SKIP_SCRIPTED_BANK_FORWARD"}
        if request is not None:
            env["PUFFER_SKIP_SCRIPTED_BANK_FORWARD"] = request
        script = (f'set -euo pipefail\nROOT="{ROOT}"\nPUFFER="{self.puffer}"\n'
                  + installer_block(*markers))
        return subprocess.run(["bash", "-c", script], env=env, text=True,
                              capture_output=True, check=False)

    def installed(self):
        return subprocess.run(
            ["git", "-C", str(self.puffer), "apply", "--reverse", "--check",
             "--no-index", str(PATCH)], capture_output=True, check=False
        ).returncode == 0

    def test_default_install_leaves_the_tree_untouched(self):
        for request in (None, "0"):
            result = self.run_block(INSTALL_BLOCK, request)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(tree_bytes(self.puffer), self.default)
        self.assertFalse((self.puffer / HEADER).exists())

    def test_opt_in_applies_once_and_default_install_restores_bytes(self):
        result = self.run_block(INSTALL_BLOCK, "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("applied:   opt-in scripted-bank forward skip", result.stdout)
        self.assertTrue(self.installed())
        self.assertEqual((self.puffer / HEADER).read_text(encoding="utf-8"),
                         header_text())
        opted = tree_bytes(self.puffer)
        self.assertNotEqual(opted, self.default)

        again = self.run_block(INSTALL_BLOCK, "1")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout, "")
        self.assertEqual(tree_bytes(self.puffer), opted)

        check = self.run_block(CHECK_BLOCK)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("opt-in scripted-bank forward skip is installed", check.stdout)

        restored = self.run_block(INSTALL_BLOCK, "0")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertIn("reversed:  opt-in scripted-bank forward skip", restored.stdout)
        self.assertEqual(tree_bytes(self.puffer), self.default)
        check = self.run_block(CHECK_BLOCK)
        self.assertEqual((check.returncode, check.stdout), (0, ""))

    def test_invalid_request_is_refused(self):
        result = self.run_block(INSTALL_BLOCK, "yes")
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be 0 or 1", result.stderr)
        self.assertEqual(tree_bytes(self.puffer), self.default)

    def test_stale_skip_is_refused_by_install_and_check(self):
        self.assertEqual(self.run_block(INSTALL_BLOCK, "1").returncode, 0)
        with (self.puffer / HEADER).open("a", encoding="utf-8") as handle:
            handle.write("// drift\n")
        for request in ("0", "1"):
            result = self.run_block(INSTALL_BLOCK, request)
            self.assertEqual(result.returncode, 1)
            self.assertIn("scripted-bank forward skip is stale", result.stderr)
        check = self.run_block(CHECK_BLOCK)
        self.assertEqual(check.returncode, 1)
        self.assertIn("scripted-bank forward skip is stale", check.stderr)


@unittest.skipUnless(PIN_TREE, "PUFFER_PIN_TREE not set")
class PinnedTreeRoundTrip(unittest.TestCase):
    """The real installer on a pinned, fully installed Puffer tree."""

    def test_opt_in_round_trip_on_the_pinned_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            puffer = pathlib.Path(tmp) / "PufferLib"
            shutil.copytree(
                PIN_TREE, puffer, symlinks=True,
                ignore=shutil.ignore_patterns(".git", "build", ".venv", "checkpoints",
                                              "logs", "experiments", "wandb"))
            before = {name: tree_bytes(puffer / name) for name in ("src", "pufferlib")}

            def install(request):
                env = dict(os.environ, PUFFER_SKIP_SCRIPTED_BANK_FORWARD=request)
                return subprocess.run(["bash", str(INSTALLER), str(puffer)], env=env,
                                      text=True, capture_output=True, check=False)

            opted = install("1")
            self.assertEqual(opted.returncode, 0, opted.stderr)
            self.assertIn("applied:   opt-in scripted-bank forward skip", opted.stdout)
            source = (puffer / "src/pufferlib.cu").read_text(encoding="utf-8")
            loop = source.index("extern \"C\" void net_callback_wrapper(")
            self.assertLess(loop, source.index("b == pufferl->scripted_skip_bank"))
            self.assertLess(source.index("b == pufferl->scripted_skip_bank"),
                            source.index("policy_forward(p_bank", loop))
            self.assertLess(source.index("= scripted_bank_skip_index("),
                            source.index("// Cudagraph rolluts and entire training step"))
            self.assertNotEqual(
                (puffer / "src/exact_action_build_hash.h").read_bytes(),
                before["src"]["exact_action_build_hash.h"])

            restored = install("0")
            self.assertEqual(restored.returncode, 0, restored.stderr)
            self.assertIn("reversed:  opt-in scripted-bank forward skip", restored.stdout)
            for name in ("src", "pufferlib"):
                self.assertEqual(tree_bytes(puffer / name), before[name], name)
            self.assertTrue(filecmp.cmp(puffer / "src/exact_action_build_hash.h",
                                        pathlib.Path(PIN_TREE) / "src/exact_action_build_hash.h",
                                        shallow=False))


if __name__ == "__main__":
    unittest.main()

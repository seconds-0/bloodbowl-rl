"""Shared pieces of the search-distillation tools (PLAN.md beside this file).

Nothing here runs by itself. The tools import it, and the plan binds it by hash
with them (TOOL_FILES). It holds: the plan loader that refuses a plan whose
hash is not the one handed over, the loader of the harness export, the split
rule, the kick-off turn rule, the replay of a stored action trail, and the
exact joint distribution of the policy over a support, written once so that
the fine-tune, the evaluation and the tests all use the same arithmetic.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BLOB = "0000002999975936.bin"
PLAN_SCHEMA = "search-distill-plan-v2"
DEV_PLAN = "search-distill-dev"
# The files that decide what the records and the blobs are. The plan binds them
# by hash (tool_sha256) and every tool refuses to run under a plan when any of
# them is not the file the plan names. The droplet launcher decides nothing in
# a record: the plan names it apart (launcher_sha256) and only it checks that.
TOOL_FILES = ("distill_common.py", "distill_screen.py", "distill_accept.py",
              "distill_dataset.py", "distill_finetune.py", "distill_eval.py")
LAUNCHER_FILE = "distill_droplet.py"
SPLITS = ("train", "validation", "test", "reserve")
# (engine seed - seed0) // 2 % 10 -> split. Dividing by two keeps one HOME and
# one AWAY game of seat A together, so every split has both sides.
SPLIT_OF_GROUP = ("train",) * 7 + ("validation", "test", "reserve")
SCOPE = ("turn", "after_declare")
CLASS_CODES = {"turn": 0, "after_declare": 1, "declare": 2, None: 3, "other": 3}
SURE = 0.999999          # the original policy "was sure": its top action's probability


class IntegrityError(RuntimeError):
    """A failed integrity check. It ends the worker and with it the shard."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_sha256():
    return {name: sha256_file(os.path.join(HERE, name)) for name in TOOL_FILES}


def load_plan(path, expect, check_tools=True):
    """The plan, only when the file hashes to `expect` and (check_tools) every
    tool file is the one it names. Returns (plan, sha256)."""
    with open(path, "rb") as f:
        raw = f.read()
    got = hashlib.sha256(raw).hexdigest()
    if got != str(expect).strip().lower():
        raise SystemExit(f"{path} hashes to {got}, not to --expect-sha256 {expect}")
    plan = json.loads(raw)
    if plan.get("schema") != PLAN_SCHEMA:
        raise SystemExit(f"{path} is not a {PLAN_SCHEMA} file")
    # Tool work only: the dev plan (never a registered, milestone or rehearsal
    # plan) may be used while a tool file is being edited.
    if plan.get("name") == DEV_PLAN and os.environ.get("DISTILL_DEV_SKIP_TOOL_CHECK") == "1":
        check_tools = False
    if check_tools:
        mine = tool_sha256()
        differ = sorted(name for name in TOOL_FILES if plan["tool_sha256"].get(name) != mine[name])
        if differ:
            raise SystemExit(f"these tool files are not the ones the plan names: {differ}")
    return plan, got


def split_of(engine_seed, seed0):
    index = int(engine_seed) - int(seed0)
    if index < 0:
        raise ValueError(f"engine seed {engine_seed} is below the block's first seed {seed0}")
    return SPLIT_OF_GROUP[(index // 2) % 10]


class Harness:
    """The exported harness, imported once per process. Never a worktree: the
    export carries SOURCE_COMMIT and its own compiled shim, and this refuses a
    directory without them or a shim that the harness would rebuild."""

    def __init__(self, export):
        export = os.path.abspath(export)
        commit_file = os.path.join(export, "SOURCE_COMMIT")
        if not os.path.isfile(commit_file):
            raise SystemExit(f"{export} is not a harness export (no SOURCE_COMMIT)")
        with open(commit_file) as f:
            self.commit = f.read().strip()
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.pop("BBPLAY_LIB", None)
        sys.dont_write_bytecode = True
        if export not in sys.path:
            sys.path.insert(0, export)
        import torch
        torch.set_num_threads(1)
        from play_harness import engine as E
        from play_harness import search as S
        from play_harness import tournament as T
        from play_harness import policy as P
        if os.path.abspath(E.ROOT) != export:
            raise SystemExit(f"play_harness was imported from {E.ROOT}, not from {export}")
        if E.library_is_stale(E.DEFAULT_LIB):
            raise SystemExit(f"{E.DEFAULT_LIB} is missing or older than its sources; run "
                             "export_harness.sh into a fresh directory")
        self.root, self.torch, self.E, self.S, self.T, self.P = export, torch, E, S, T, P
        self.lib = E.load_library()
        self.library_sha256 = sha256_file(E.DEFAULT_LIB)
        self.manifest = S.pinned_reward_manifest(self.lib)
        self.reward_threshold = float(S.reward_clip_threshold(self.manifest["rewards"]))
        self.reward_limit = self.reward_threshold * (1.0 + 1e-6)

    def load_policy(self, blob):
        """(policy, provenance) through the harness's own loader, sidecar required."""
        return self.P.load_checkpoint(blob)

    def versions(self):
        return {"torch": self.torch.__version__, "numpy": np.__version__,
                "python": sys.version.split()[0]}


def in_kickoff_turn(E, match):
    """True while a KICKOFF frame is on the engine's procedure stack (D439's rule).
    An in-scope decision there is the kicking team's free turn from a Blitz
    kick-off result: ending it does not advance the completed-turn counter, so
    a rollout from it runs to the end of the team's next real turn."""
    kickoff = E.PROCS.index("KICKOFF")
    return any(match.stack[i].proc == kickoff for i in range(int(match.stack_top)))


def trail_sha256(trail):
    """sha256 over (team, type, arg, square) of every engine step, in order."""
    h = hashlib.sha256()
    for team, t, arg, sq in trail:
        h.update(bytes((int(team),)) + int(t).to_bytes(4, "little")
                 + int(arg).to_bytes(4, "little") + int(sq).to_bytes(4, "little"))
    return h.hexdigest()


def replay(hx, game, want_rows=(0, 1)):
    """Replay a game record's action trail through a fresh engine on its seed.

    Yields, before every engine step: (step, deciding team, {row: observation},
    {row: joint support}). After the last step it checks the terminal status
    and returns through StopIteration the dict {"obs_sha256", "final_digest",
    "score"}; the caller compares them with the record. Raises IntegrityError
    when the engine refuses a recorded action.
    """
    E = hx.E
    eng = E.Engine(int(game["engine_seed"]), rewards=hx.manifest["rewards"])
    hashes = [hashlib.sha256(), hashlib.sha256()]
    try:
        last = len(game["trail"]) - 1
        for step, (team, t, arg, sq) in enumerate(game["trail"]):
            if eng.decision_team != team:
                raise IntegrityError(f"replay of seed {game['engine_seed']}: step {step} is "
                                     f"team {eng.decision_team}'s, the trail says {team}")
            obs = {row: eng.obs(row) for row in (0, 1)}
            for row in (0, 1):
                hashes[row].update(obs[row].tobytes())
            yield step, team, {r: obs[r] for r in want_rows}, \
                {r: eng.joint_support(r) for r in want_rows}
            rc = eng.step(t, arg, sq)
            if rc != (E.STEP_TERMINAL if step == last else E.STEP_OK):
                raise IntegrityError(f"replay of seed {game['engine_seed']}: step {step} "
                                     f"returned {rc}")
        final = eng.final_match()
        if final is None or final.status != E.STATUS_MATCH_OVER:
            raise IntegrityError(f"replay of seed {game['engine_seed']}: no natural end")
        return {"obs_sha256": [h.hexdigest() for h in hashes],
                "final_digest": f"{eng.digest():016x}",
                "score": [int(final.score[0]), int(final.score[1])]}
    finally:
        eng.close()


def drain(generator):
    """Run a generator to its end and hand back its return value."""
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            return stop.value


# ---- the exact joint distribution over a support ---------------------------------------
class Joint:
    """The policy's exact joint distribution over the supports of a batch of
    decisions, as play_harness.policy.select_joint samples it: type, then
    argument given type, then square given both, each a softmax over the values
    the support allows after that prefix. Inactive heads are singletons and
    contribute zero. Differentiable in the logits.

    supports  a list of 1-D integer arrays of packed tuples (type | arg << 10 |
              square << 20), one per decision; duplicates are removed.
    logp(logits) takes (decisions, 454) logits and returns the log-probability
    of every tuple, concatenated in decision order with each decision's tuples
    in ascending packed order (self.first[i] : self.first[i + 1]).
    """

    def __init__(self, supports, act_sizes=(30, 33, 391)):
        import torch
        self.torch = torch
        packed = [np.unique(np.asarray(s, dtype=np.int64).reshape(-1)) for s in supports]
        if any(p.size == 0 for p in packed):
            raise ValueError("empty joint support")
        sizes = np.array([p.size for p in packed], dtype=np.int64)
        self.n = len(packed)
        self.first = np.concatenate([[0], np.cumsum(sizes)])
        self.total = int(self.first[-1])
        self.packed = np.concatenate(packed) if packed else np.zeros(0, dtype=np.int64)
        ex = np.repeat(np.arange(self.n, dtype=np.int64), sizes)
        self.example = torch.from_numpy(ex)
        offsets = (0, act_sizes[0], act_sizes[0] + act_sizes[1])
        prefix = ex                                # head 0's prefix is the decision itself
        self.cell_row, self.cell_col, self.cell_group, self.tuple_cell, self.groups = \
            [], [], [], [], []
        row_of_prefix = np.arange(self.n, dtype=np.int64)
        for h in range(3):
            value = (self.packed >> (10 * h)) & 1023
            if value.size and int(value.max()) >= act_sizes[h]:
                raise ValueError(f"head {h} value {int(value.max())} outside the action space")
            # one cell per distinct (prefix, value): a value counts once in its
            # head's softmax however many tuples continue it
            cells, cell_of = np.unique(prefix * 1024 + value, return_inverse=True)
            group = cells // 1024                  # the prefix a cell belongs to
            row = row_of_prefix[group]
            self.cell_row.append(torch.from_numpy(row))
            self.cell_col.append(torch.from_numpy(offsets[h] + cells % 1024))
            self.cell_group.append(torch.from_numpy(group))
            self.tuple_cell.append(torch.from_numpy(cell_of.astype(np.int64)))
            self.groups.append(int(group.max()) + 1 if group.size else 0)
            prefix, row_of_prefix = cell_of.astype(np.int64), row
        self._index = {}

    def logp(self, logits):
        torch = self.torch
        out = torch.zeros(self.total, dtype=logits.dtype)
        for h in range(3):
            cell = logits[self.cell_row[h], self.cell_col[h]]
            group = self.cell_group[h]
            top = torch.full((self.groups[h],), -float("inf"), dtype=logits.dtype)
            top = top.scatter_reduce(0, group, cell.detach(), "amax", include_self=True)
            mass = torch.zeros(self.groups[h], dtype=logits.dtype).index_add(
                0, group, torch.exp(cell - top[group]))
            out = out + (cell - top[group] - torch.log(mass[group]))[self.tuple_cell[h]]
        return out

    def per_decision_sum(self, values):
        torch = self.torch
        return torch.zeros(self.n, dtype=values.dtype).index_add(0, self.example, values)

    def index_of(self, actions):
        """For each decision the global index of its tuple `actions[i]` (packed),
        or -1 where actions[i] < 0. A tuple outside its support is an error."""
        out = np.full(self.n, -1, dtype=np.int64)
        for i, action in enumerate(np.asarray(actions, dtype=np.int64)):
            if action < 0:
                continue
            a, b = int(self.first[i]), int(self.first[i + 1])
            j = a + int(np.searchsorted(self.packed[a:b], action))
            if j >= b or self.packed[j] != action:
                raise ValueError(f"decision {i}: tuple {int(action)} is not in its support")
            out[i] = j
        return out

    def top(self, logp):
        """Per decision: (global index of the most probable tuple, its log-probability).
        Ties go to the smaller packed tuple, as joint_log_probabilities orders them."""
        values = logp.detach().numpy()
        index = np.empty(self.n, dtype=np.int64)
        for i in range(self.n):
            a, b = int(self.first[i]), int(self.first[i + 1])
            index[i] = a + int(np.argmax(values[a:b]))
        return index, values[index]

    def conditional_kl(self, logits0, logits):
        """KL(p0 || p) per decision by the chain rule: for every head, the sum
        over prefixes of p0(prefix) times the KL of the two conditional
        distributions after that prefix. Equal to the sum over tuples of
        p0 * (log p0 - log p); kept as an independent form for the tests."""
        torch = self.torch
        total = torch.zeros(self.n, dtype=logits.dtype)
        with torch.no_grad():
            p0_tuple = torch.exp(self.logp(logits0))
        for h in range(3):
            group = self.cell_group[h]
            parts = []
            for z in (logits0, logits):
                cell = z[self.cell_row[h], self.cell_col[h]]
                top = torch.full((self.groups[h],), -float("inf"), dtype=z.dtype)
                top = top.scatter_reduce(0, group, cell.detach(), "amax", include_self=True)
                mass = torch.zeros(self.groups[h], dtype=z.dtype).index_add(
                    0, group, torch.exp(cell - top[group]))
                parts.append(cell - top[group] - torch.log(mass[group]))
            lp0, lp = parts
            cells = lp0.numel()
            # p0 of a cell = the p0 mass of the tuples that pass through it
            p0_cell = torch.zeros(cells, dtype=logits.dtype).index_add(
                0, self.tuple_cell[h], p0_tuple)
            total = total.index_add(0, self.cell_row[h], p0_cell * (lp0 - lp))
        return total


# ---- a dataset file, and what a weight matrix does on it --------------------------------
LOCKED_DIR = "locked"


def dataset_meta(dataset_dir):
    with open(os.path.join(dataset_dir, "DATASET.json")) as f:
        return json.load(f)


def open_split(dataset_dir, split, meta=None, unlock_test=False):
    """One split of a dataset directory, by the path DATASET.json records for it.

    Everything is decided before a byte of the file is deserialised: the split
    must be one the dataset tool writes; a recorded path under locked/ is
    opened only for "test"; "test" is opened only with unlock_test, which the
    evaluation tool sets after it has checked the selection; and the file must
    hash to the value DATASET.json recorded. After loading, the split the file
    names inside itself must be the one asked for.
    """
    import torch
    if split not in ("train", "validation", "test"):
        raise SystemExit(f"the {split} split is never written and never read")
    meta = meta or dataset_meta(dataset_dir)
    record = (meta.get("files") or {}).get(split)
    if not record:
        raise SystemExit(f"DATASET.json in {dataset_dir} records no {split} file")
    relative = os.path.normpath(record["path"])
    locked = relative.split(os.sep)[0] == LOCKED_DIR
    if os.path.isabs(relative) or relative.startswith(".."):
        raise SystemExit(f"DATASET.json records a {split} path outside the dataset directory")
    if locked != (split == "test"):
        raise SystemExit(f"DATASET.json records {relative!r} for the {split} split: a file "
                         f"under {LOCKED_DIR}/ is the test split's and no other's; nothing "
                         "was read")
    if split == "test" and not unlock_test:
        raise SystemExit("the test split stays closed: it is opened by the evaluation tool's "
                         "heldout step, after the selection is checked; nothing was read")
    path = os.path.join(dataset_dir, relative)
    if sha256_file(path) != record["sha256"]:
        raise SystemExit(f"{path} is not the file DATASET.json recorded; nothing was read")
    data = torch.load(path, weights_only=False)
    if data.get("split") != split:
        raise SystemExit(f"{path} holds the {data.get('split')!r} split, not {split!r}")
    return data


def supports_of(data, index=None):
    ptr, flat = data["support_ptr"], data["support"]
    index = range(len(ptr) - 1) if index is None else index
    return [flat[ptr[i]:ptr[i + 1]] for i in index]


def score(data, w0, w, chunk=8192, precision="float32"):
    """What the policy rows `w` do at every loss decision of a dataset file,
    against the original rows `w0`. Both are (454, 512) tensors.

    precision "float32" (every reported number): the logits are computed as the
    harness computes them at play, the blob's float32 weights on the float32
    features with a zero bias, and the joint distribution is then formed in
    float64. precision "float64": the logits are float64 products, which is the
    training arithmetic; it is printed once beside the fit value and decides
    nothing. Returns numpy arrays, one entry per decision:
      p_label     probability of the label (nan where the decision has none)
      p0_label    the original's probability of the label (nan likewise)
      tv          total variation between the two joint distributions
      changed     the most probable action differs from the original's
      p0_top      the original's probability of its most probable action
    """
    import torch
    n = len(data["a0"])
    out = {"p_label": np.full(n, np.nan), "p0_label": np.full(n, np.nan), "tv": np.zeros(n),
           "changed": np.zeros(n, dtype=bool), "p0_top": np.zeros(n)}
    if precision not in ("float32", "float64"):
        raise ValueError(f"unknown precision {precision!r}")
    if precision == "float32":
        # The harness's decoder is a Linear whose bias the conversion zero-fills:
        # the same call, with that zero bias.
        w0, w = w0.float(), w.float()
        bias = torch.zeros(w.shape[0])
        logits = lambda h, m: torch.nn.functional.linear(h.float(), m, bias).double()  # noqa: E731
    else:
        w0, w = w0.double(), w.double()
        logits = lambda h, m: h.double() @ m.T  # noqa: E731
    with torch.no_grad():
        for a in range(0, n, chunk):
            index = np.arange(a, min(a + chunk, n))
            joint = Joint(supports_of(data, index))
            h = data["h"][index]
            lp0, lp = joint.logp(logits(h, w0)), joint.logp(logits(h, w))
            p0, p = torch.exp(lp0), torch.exp(lp)
            out["tv"][index] = 0.5 * joint.per_decision_sum((p - p0).abs()).numpy()
            top0, lp0_top = joint.top(lp0)
            top1, _ = joint.top(lp)
            out["changed"][index] = top0 != top1
            out["p0_top"][index] = np.exp(lp0_top)
            at = joint.index_of(data["label"][index])
            has = at >= 0
            out["p_label"][index[has]] = p.numpy()[at[has]]
            out["p0_label"][index[has]] = p0.numpy()[at[has]]
    return out


def weighted_mean(values, weights):
    values, weights = np.asarray(values, dtype=np.float64), np.asarray(weights, dtype=np.float64)
    total = weights.sum()
    return float((values * weights).sum() / total) if total > 0 else float("nan")


def selection_score(data, scored, price):
    """J = q * M * g - price * U on a dataset file (PLAN.md section 3), with its
    parts. No rollouts: g is the mean fresh gain the label tool stored. J is a
    reported diagnostic: the registered arm is named in the plan and nothing
    reads J."""
    w = data["weight"]
    dev = data["label"] >= 0
    judged = dev & data["judged"]
    q = float(w[dev].sum() / w.sum()) if w.sum() > 0 else float("nan")
    m = weighted_mean(scored["p_label"][dev], w[dev])
    g = weighted_mean(data["fresh_gain"][judged], w[judged])
    u = weighted_mean(scored["tv"][~dev], w[~dev])
    return {"J": q * m * g - price * u, "q": q, "M": m, "g": g, "U": u,
            "deviation_roots": int(dev.sum()), "judged_labels": int(judged.sum())}

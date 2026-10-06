#!/usr/bin/env python3
"""selfplay_dump.py: record a checkpoint's own decisions in self-play.

Offline audit input only. It drives the play harness through its public
Python API (play_harness.engine, play_harness.policy, play_harness.tournament
in a separate, read-only checkout) and writes, for every decision of every
game:

  obs        the deciding seat's observation (u8, obs-v6)
  support    the exact joint support as packed (type, arg, square) tuples
  logits     the acting policy's raw logits with recurrent state carried as in
             play (PolicySeat contract: one forward per seat per c_step, state
             zeroed at match start), then one row per --shadow policy
  action     the sampled (type, arg, square) tuple
  match      the raw bb_match bytes before the action (for readable examples)
  legal      the engine's legal actions with their head projections, unless
             the list is longer than --legal-cap (set-up placement)

A shadow policy never acts. It is stepped on the same observation stream as
the acting policy, both seats, every c_step, with its own recurrent state, so
its logits are "what this other policy would do here, having watched the same
game".

The engine shim is compiled from THIS worktree's engine and env sources (the
harness's own bbplay.c, which is only read), so the states come from the env
build this branch carries, not from the harness checkout's older engine.

  <harness>/.venv/bin/python tools/selfplay_dump.py \\
      --checkpoint <dir>/chain41/0000002999975936.bin \\
      --shadow chain9=<dir>/chain9/0000002999975936.bin \\
      --games 200 --out-dir runs/x/selfplay
"""
import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_HARNESS = os.path.expanduser("~/Code/bb-play-harness")


def build_shim(harness_root, out_dir):
    """Compile the harness's bbplay.c against this worktree's engine and env."""
    os.makedirs(out_dir, exist_ok=True)
    ext = "dylib" if sys.platform == "darwin" else "so"
    out = os.path.join(out_dir, f"libbbplay.{ext}")
    src = os.path.join(harness_root, "play_harness", "native", "bbplay.c")
    cmd = [os.environ.get("CC", "cc"), "-std=c11", "-O2", "-g",
           "-ffp-contract=off", "-fPIC", "-shared", "-Wall", "-Wextra",
           "-Wno-unused-function",
           f"-I{os.path.join(ROOT, 'engine', 'include')}",
           f"-I{os.path.join(ROOT, 'puffer', 'bloodbowl')}",
           src, "-o", out, "-lm"]
    subprocess.run(cmd, check=True)
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ChunkWriter:
    """Buffers decisions and writes uncompressed .npz chunks."""

    def __init__(self, out_dir, n_policies, match_size, chunk=20000):
        self.out_dir, self.chunk = out_dir, int(chunk)
        self.n_policies, self.match_size = n_policies, match_size
        self.index = 0
        self.total = 0
        self._reset()

    def _reset(self):
        self.obs, self.logits, self.action, self.meta = [], [], [], []
        self.match, self.support, self.legal = [], [], []

    def add(self, obs, logits, action, meta, match, support, legal):
        self.obs.append(obs)
        self.logits.append(logits)
        self.action.append(action)
        self.meta.append(meta)
        self.match.append(match)
        self.support.append(support)
        self.legal.append(legal)
        if len(self.obs) >= self.chunk:
            self.flush()

    def flush(self):
        n = len(self.obs)
        if not n:
            return
        sup_off = np.zeros(n + 1, dtype=np.int64)
        sup_off[1:] = np.cumsum([len(s) for s in self.support])
        leg_off = np.zeros(n + 1, dtype=np.int64)
        leg_off[1:] = np.cumsum([len(l) for l in self.legal])
        path = os.path.join(self.out_dir, f"chunk_{self.index:04d}.npz")
        np.savez(
            path,
            obs=np.stack(self.obs),
            logits=np.stack(self.logits),
            action=np.asarray(self.action, dtype=np.int16),
            meta=np.asarray(self.meta, dtype=np.int32),
            match=np.stack(self.match),
            support=np.concatenate(self.support).astype(np.uint32),
            support_off=sup_off,
            legal=(np.concatenate(self.legal) if leg_off[-1]
                   else np.zeros((0, 6), dtype=np.int16)),
            legal_off=leg_off,
        )
        self.total += n
        self.index += 1
        self._reset()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--harness-root", default=DEFAULT_HARNESS)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--shadow", action="append", default=[],
                    help="NAME=PATH; a policy stepped on the same stream that never acts")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed0", type=int, default=20261005)
    ap.add_argument("--slots", type=int, default=64, help="games in flight")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--legal-cap", type=int, default=512)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--kernel", default="native")
    a = ap.parse_args()

    import torch
    torch.set_num_threads(a.threads)
    sys.path.insert(0, os.path.abspath(a.harness_root))
    from play_harness import engine as E
    from play_harness.policy import batched_forward, load_checkpoint
    from play_harness.tournament import Match

    os.makedirs(a.out_dir, exist_ok=True)
    lib_path = build_shim(a.harness_root, os.path.join(ROOT, "build", "play_harness_probe"))
    lib = E.load_library(lib_path, build_if_missing=False)

    policy, prov = load_checkpoint(a.checkpoint, kernel=a.kernel)
    shadows = []
    for item in a.shadow:
        name, path = item.split("=", 1)
        pol, sprov = load_checkpoint(path, kernel=a.kernel)
        shadows.append((name, pol, sprov))
    names = ["actor"] + [s[0] for s in shadows]
    match_size = ctypes.sizeof(E.BbMatch)
    writer = ChunkWriter(a.out_dir, len(names), match_size)

    todo = list(range(a.games))[::-1]
    live = []                      # dicts: game, match, shadow_state
    records = []
    t0 = last = time.time()
    steps = 0

    def start(game):
        m = Match(policy, policy, a.seed0 + game, mode="sample", lib=lib)
        return {"game": game, "match": m,
                "shadow": [[pol.initial_state(1), pol.initial_state(1)]
                           for _n, pol, _p in shadows]}

    while todo or live:
        while todo and len(live) < a.slots:
            live.append(start(todo.pop()))
        teams, inputs, seats, obs_rows = [], [], [], []
        for g in live:
            m = g["match"]
            team = m.observe()
            ins = [m.seat_inputs(s) for s in (0, 1)]
            teams.append(team)
            inputs.append(ins)
            for s in (0, 1):
                seats.append(m.seats[s])
                obs_rows.append(ins[s][0])
        logits = batched_forward(policy, seats, obs_rows).numpy()
        shadow_logits = []
        if shadows:
            obs_t = torch.from_numpy(np.stack(obs_rows))
            for k, (_name, pol, _p) in enumerate(shadows):
                state = torch.cat([g["shadow"][k][s] for g in live for s in (0, 1)], dim=1)
                lg, _v, new_state = pol.forward_eval(obs_t, state)
                shadow_logits.append(lg.numpy())
                row = 0
                for g in live:
                    for s in (0, 1):
                        g["shadow"][k][s] = new_state[:, row:row + 1].clone()
                        row += 1
        still = []
        for i, g in enumerate(live):
            m, team, ins = g["match"], teams[i], inputs[i]
            outs = []
            for s in (0, 1):
                action, logprob = m.seats[s].decide(
                    torch.from_numpy(logits[2 * i + s]), ins[s][1], s == team)
                outs.append({"tuple": action, "logprob": logprob})
            row = 2 * i + team
            legal = m.eng.legal()
            if len(legal) <= a.legal_cap:
                legal_arr = np.asarray(
                    [(x.type, x.arg, x.x, x.y, x.proj_arg, x.proj_sq) for x in legal],
                    dtype=np.int16).reshape(-1, 6)
            else:
                legal_arr = np.zeros((0, 6), dtype=np.int16)
            writer.add(
                np.asarray(ins[team][0], dtype=np.uint8),
                np.stack([logits[row]] + [sl[row] for sl in shadow_logits]).astype(np.float32),
                tuple(int(v) for v in outs[team]["tuple"]),
                (g["game"], m.c_steps, team, len(legal)),
                np.frombuffer(bytes(m.eng.match()), dtype=np.uint8).copy(),
                np.asarray(ins[team][1], dtype=np.uint32),
                legal_arr,
            )
            if m.apply(team, outs):
                try:
                    rec = m.record()
                finally:
                    m.close()
                rec["game"] = g["game"]
                records.append(rec)
            else:
                m.check_step_budget()
                still.append(g)
        live = still
        steps += 1
        now = time.time()
        if now - last > 30:
            last = now
            print(f"[{now - t0:6.0f}s] steps {steps} decisions {writer.total + len(writer.obs)} "
                  f"games done {len(records)}/{a.games} in flight {len(live)}", flush=True)
    writer.flush()
    manifest = {
        "schema": "selfplay-dump-v1",
        "policies": names,
        "actor": prov,
        "shadows": {n: p for n, _pol, p in shadows},
        "kernel": a.kernel, "mode": "sample", "temperature": 1.0,
        "games": a.games, "seed0": a.seed0, "slots": a.slots,
        "decisions": writer.total, "chunks": writer.index,
        "match_size": match_size,
        "shim": {"path": lib_path, "sha256": sha256_file(lib_path),
                 "engine_root": ROOT,
                 "bbplay_c_sha256": sha256_file(os.path.join(
                     a.harness_root, "play_harness", "native", "bbplay.c"))},
        "meta_columns": ["game", "c_step", "seat", "n_legal"],
        "legal_columns": ["type", "arg", "x", "y", "proj_arg", "proj_sq"],
        "seconds": round(time.time() - t0, 1),
        "records": records,
    }
    with open(os.path.join(a.out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"done: {writer.total} decisions, {len(records)} games, "
          f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

"""Exploratory: is ending the turn (or ending a block activation) right under the policy's own objective?
Plain play, no masks. Roots: (1) turn-level decisions where plain play chose END_TURN while an ACTIVATE
was legal; (2) decisions where it chose END_ACTIVATION while a BLOCK_TARGET was legal.
Candidates: a0, then the most probable ACTIVATE (or BLOCK_TARGET) actions. Evaluator: the search probe's
(shaped n-step return to the end of the searcher's own team turn plus the value output), common random numbers.
Reads the harness and its tool as libraries; writes only to the directory given."""
import sys, os, json, random, time
import numpy as np
H = "/Users/alexanderhuth/Code/bb-harness-search"
sys.path.insert(0, H); sys.path.insert(0, os.path.join(H, "tools"))
import search_probe_diag as D

ckpt_name, out_dir, games, per_game, n_roll, seed0 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
CK = "/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/checkpoints/%s/0000002999975936.bin" % ckpt_name
h = D.Harness(CK, os.path.join(H, "puffer", "config", "rewards", "r0_poss_half.json"), ())
E, S, T, torch = h.E, h.S, h.T, h.torch
KINDS = ("end_turn", "decline_block", "activate")
BUDGET = 330.0

from play_harness.policy import PolicySeat
class PlainSeat(PolicySeat):
    """Plain play that also tracks whether its previous decision was a DECLARE."""
    _after_declare = False
    def reset_match(self):
        super().reset_match(); self._after_declare = False
    def decide(self, logits, support, deciding):
        action, logprob = super().decide(logits, support, deciding)
        if deciding: self._after_declare = action[0] == E.A["DECLARE"]
        return action, logprob

def play(engine_seed, a):
    seeds = [T.sampling_seed(engine_seed, side) for side in (0, 1)]
    seeds[1 - a] = (seeds[1 - a] + T.SEED_OFFSET_STRIDE) % (1 << 62)
    seats = [PlainSeat(h.policy, side, seed=seeds[side]) for side in (0, 1)]
    for s in seats: s.reset_match()
    eng = E.Engine(engine_seed, rewards=h.manifest["rewards"])
    shadow = h.policy.initial_state(1)
    pick = random.Random(engine_seed)
    kept = {k: [] for k in KINDS}; seen = {k: 0 for k in KINDS}
    step = 0
    while True:
        team = eng.decision_team
        was_declare = seats[a]._after_declare
        obs = [eng.obs(0), eng.obs(1)]
        supports = [eng.joint_support(0), eng.joint_support(1)]
        outs = [seats[s].step(obs[s], supports[s], s == team) for s in (0, 1)]
        _, _, shadow = h.policy.forward_eval(torch.from_numpy(obs[1 - a]).reshape(1, -1), shadow)
        if team == a:
            support = np.asarray(supports[a], dtype=np.int64).reshape(-1)
            types = {int(t) & 1023 for t in support}
            a0 = tuple(int(v) for v in outs[a]["tuple"])
            kind = None
            if a0[0] == E.A["END_TURN"] and E.A["ACTIVATE"] in types: kind = "end_turn"
            elif a0[0] == E.A["END_ACTIVATION"] and E.A["BLOCK_TARGET"] in types: kind = "decline_block"
            elif a0[0] == E.A["ACTIVATE"] and E.A["END_TURN"] in types: kind = "activate"
            if kind:
                seen[kind] += 1
                slot = len(kept[kind]) if len(kept[kind]) < per_game else pick.randrange(seen[kind])
                if slot < per_game:
                    root = {"clone": eng.clone_for_search(0, S.SEARCH_DICE_STREAM), "own": seats[a].state.clone(),
                            "opp": shadow.clone(), "logits": outs[a]["logits"].copy(), "support": support,
                            "a0": a0, "step": step, "flags": (was_declare, seats[1 - a]._after_declare),
                            "clock": (int(eng.match().half), int(eng.match().turn[a]))}
                    if slot < len(kept[kind]):
                        kept[kind][slot]["clone"].close(); kept[kind][slot] = root
                    else:
                        kept[kind].append(root)
        rc = eng.step(*outs[team]["tuple"]); step += 1
        if rc == E.STEP_TERMINAL: break
        if rc != E.STEP_OK: raise SystemExit(f"engine refused a step: rc={rc}")
    eng.close()
    return kept, seeds[a], seen

os.makedirs(out_dir, exist_ok=True)
path = os.path.join(out_dir, f"roots_{ckpt_name}.jsonl")
if os.path.exists(path): raise SystemExit(path + " exists")
rollouts = [S.Rollouts(h.policy, seat, masks=()) for seat in (0, 1)]
t0 = time.time(); n_roots = 0; seen_tot = {k: 0 for k in KINDS}
with open(path, "w") as sink:
    for g in range(games):
        if time.time() - t0 > BUDGET:
            print("time budget reached before game", g); break
        engine_seed = seed0 + g; a = g % 2
        kept, seed, seen = play(engine_seed, a)
        for k in KINDS:
            seen_tot[k] += seen[k]
            want = {"end_turn": E.A["ACTIVATE"], "decline_block": E.A["BLOCK_TARGET"], "activate": E.A["END_TURN"]}[k]
            for root in kept[k]:
                tuples, logp = S.joint_log_probabilities(root["logits"], root["support"])
                first = int(np.flatnonzero(tuples == E.pack_tuple(*root["a0"]))[0])
                alts = [i for i in range(len(tuples)) if (int(tuples[i]) & 1023) == want][:3]
                order = [first] + alts
                cands = [E.unpack_tuple(tuples[i]) for i in order]
                batch = rollouts[a].evaluate(root["clone"], root["own"], root["opp"], cands, n_roll, seed,
                                             root["step"], after_declare=root["flags"])
                sink.write(json.dumps({"kind": k, "game": g, "engine_seed": engine_seed, "seat": a, "step": root["step"],
                    "clock": root["clock"], "support": int(len(tuples)), "logp": [float(logp[i]) for i in order],
                    "tuples": [list(c) for c in cands],
                    "returns": [[None if not np.isfinite(v) else float(v) for v in row] for row in batch.returns],
                    "steps": batch.steps.mean(axis=1).tolist(),
                    "reward_part": np.asarray(batch.rewards, float).tolist(),
                    "bootstrap": np.asarray(batch.bootstraps, float).tolist(),
                    "steps_each": np.asarray(batch.steps, float).tolist()}) + "\n")
                sink.flush(); root["clone"].close(); n_roots += 1
        print(f"game {g+1}/{games} roots {n_roots} elapsed {time.time()-t0:.0f}s", flush=True)
print("done", n_roots, "roots; chosen-END decisions seen per kind:", seen_tot, f"{time.time()-t0:.0f}s")

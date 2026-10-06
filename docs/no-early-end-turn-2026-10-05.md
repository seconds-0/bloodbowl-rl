# no_early_end_turn: a training restriction, its launcher knob, and the rig runbook (2026-10-05)

**Status: built and tested off the rig. Nothing was trained. Default off. No default was changed.**
Branch `feat/no-early-end-turn-20261005`, on top of `origin/opt/long-run-20261001` (`adebf3d`).

This is not a Blood Bowl rule. The rulebook lets a coach end the team turn whenever they like, and the
engine still offers it. `no_early_end_turn` is a restriction the training environment places on policy
seats, for one experiment. `AGENTS.md` says every rulebook "may" is policy surface; this flag takes one
away on purpose, at the env layer only, and that is why it is off by default, recorded wherever it is on,
and written up here with what would let it be removed.

## 1. Why

Chain 41 activates about 3 players a team turn where humans activate about 7, and ends 62% of its team
turns by choice with a player left. The play-harness test of 2026-10-05
(`docs/play-harness/masked-copy-2026-10-05.md` on branch `feat/play-masks-20261005`, mask m1) found that a
copy of chain 41 that is not allowed to do that beats plain chain 41 by +32.5 decisive-Elo [18.3, 47.1]
over 3,200 games, with no training. The next experiment is one training rung under the same rule, paired
against chain 42.

## 2. The rule, exactly

At a decision of a policy-controlled seat, if the engine's legal list holds an END_TURN and at least one
ACTIVATE, END_TURN is removed from the list. Nothing else changes. An activated player may still end its
activation at once. The code, `puffer/bloodbowl/bloodbowl.h`:

```c
static void bbe_restrict_end_turn(Bloodbowl* env) {
    bool has_activate = false, has_end_turn = false;
    for (int i = 0; i < env->n_legal; i++) {
        has_activate |= env->legal[i].type == BB_A_ACTIVATE;
        has_end_turn |= env->legal[i].type == BB_A_END_TURN;
    }
    if (!has_activate || !has_end_turn) return;
    int kept = 0;
    for (int i = 0; i < env->n_legal; i++) {
        if (env->legal[i].type == BB_A_END_TURN) continue;
        env->legal[kept++] = env->legal[i];
    }
    env->n_legal = kept;
    env->legal_end_turn_removed = 1;
}

static void bbe_refresh_legal(Bloodbowl* env) {
    env->n_legal = env->match.status == BB_STATUS_DECISION
                       ? bb_legal_actions(&env->match, env->legal)
                       : 0;
    env->legal_end_turn_removed = 0;
    if (env->no_early_end_turn && env->n_legal > 0 &&
        !bbe_seat_is_scripted(env, env->match.decision_team)) {
        bbe_restrict_end_turn(env);
    }
}
```

- **It is the harness's m1.** m1 removes END_TURN from a seat's exact joint support when an ACTIVATE is in
  it, by action type, and never removes the last legal action. This is the same test on the same types. A
  list that holds an ACTIVATE is never emptied by taking END_TURN out.
- **One list.** `env->legal` is what the marginal masks (`bbe_fill_mask`), the packed joint support
  (`binding.c`, `my_pack_joint_actions`), the reference sampler and `bbe_decode` all read, so they shrink
  together. A policy tuple for the removed END_TURN is outside support and takes the existing abort path.
- **The engine is untouched.** No file under `engine/` changed; `bb_legal_actions` still returns END_TURN.
- **Seats.** Every policy seat: the learner and the frozen-bank policies. Never a scripted-bot seat:
  `bbe_seat_is_scripted` is the predicate `c_step` already used to route a seat to the bot, and the bot is
  handed the engine's own list. Selfplay tags are assigned after the first reset, so a scripted-bank seat
  can meet a list that was shortened while its env was still untagged; `c_step` restores the engine's list
  before the bot picks (`bbe_unrestrict_legal`).
- **Two windows.** The engine offers END_TURN beside ACTIVATE in a team turn and in the Charge! kickoff
  result. The rule applies in both, as m1 does.
- **Observation.** Unchanged, byte for byte. No observation byte says whether the flag is on, and the
  policy's forward pass does not see masks: they are applied when the action is sampled. The policy can
  therefore not tell at any one decision. What it can see is the consequence: boards on which more of its
  players have been used.
- **Flag off** is today's env in trajectories, masks and observations (section 4).
- **Panel.** `end_turn_removed` is the number of policy-seat decisions per episode at which END_TURN had
  been removed. It is exactly 0 with the flag off and above zero with it on. `truncated_episodes` counts
  episodes ended by the `max_decisions` cap; it existed as a behaviour before and now has a number.

## 3. What the rule does in practice

1. **END_TURN is never offered in a team turn at all.** The design said END_TURN stays when no ACTIVATE is
   legal. The engine never asks in that case: with nobody left to activate it ends the team turn itself
   (`engine/src/proc_turn.c`). In 300 random episodes under the rule there were 77,998 removals and zero
   decisions inside a team turn that still listed END_TURN. Under the rule a team turn ends when every
   player has been activated, on a turnover, or on a touchdown. A lone END_TURN can still appear in the
   Charge! window when no player is Open, where it is the only action.
2. **Nothing trains the early END_TURN away.** A masked action is never sampled and has zero probability
   in the PPO recompute, so at those decisions no gradient acts on END_TURN directly. Chain 41 put about
   0.6 of the type head's mass on it there (the harness's count). The logit is still a function of shared
   weights that keep moving, so where that mass ends up after a rung is unknown; nothing pushes it down. A
   policy trained under the rule must therefore be played under it, and how much of the habit is left
   without it has to be measured (section 7.6), not assumed either way.
3. **An empty activation is not a free skip.** Activating a player and ending the activation at once
   clears Distracted, can roll a negative trait at the declaration (Bone Head, Really Stupid, Unchannelled
   Fury, Animal Savagery, Take Root), spends the turn's Blitz, Pass, Hand-off, Foul or Secure the Ball
   allowance if that is what was declared, and marks the player used. Stalling is checked when the ball
   carrier is activated, so the "end the turn without activating the carrier" route to the crowd roll is
   closed for a policy seat and the "activate the carrier and do not score" route is the one left.
4. **Games are longer in decisions.** Random play, mixed rosters, 300 episodes: 258 decisions an episode
   without the rule, 1,156 with it (4.5 times). That is a large effect because a uniform policy ends its
   turn at once 97% of the time; it is not a bound. For chain 41 the harness measured 697 engine steps a game
   plain and 961 with one side under m1 (+38%); both sides under the rule were not measured. A 3B-step
   rung therefore plays fewer games, and a per-decision discount reaches less far: at gamma 0.999 the
   final result seen from the kick-off is weighted 0.50 over 697 decisions and 0.38 over 961.
5. **The decision cap.** An episode that reaches `max_decisions` (4,096) is cut and scored from the score
   at the cap. Random play under the rule peaked at 1,522 decisions, and a random policy that never ends
   an activation or a turn by choice at 1,462. Neither is the longest possible game: both lose turns to
   failed dice early. A policy that learns to move eleven players a turn square by square, safely, would
   approach the cap (32 team turns of 11 players at about a dozen decisions each is past 4,000). Watch
   `truncated_episodes` (expected 0) and `episode_length`.
6. **Frozen opponents were not trained under it.** With the flag on the frozen-bank policies are also
   restricted. They play off the distribution they were trained on (in the harness, 44% of the masked
   copy's activations ended at once), and the harness says chain 41 is stronger that way. So the rung's
   opponents differ from chain 42's opponents even though the pool files are the same, and the in-run bank
   scores are not comparable with chain 42's. The scripted bots are not affected: the contact bot never
   ends a turn with a player left (0 of 40,493 such decisions in 300 bot games) and the offense bot does so
   rarely (19 of 63,508), and both keep the option.

## 4. Evidence

All of this is on the Mac: the C test binaries and the Python suites. No trainer was built or run.

**Flag off is the unmodified env.** `tools/bb_legal_digest.c` plays seeded games through the engine and
through `c_reset` / `c_step`, hashing every observation, mask, legal list, projection, action, reward and
terminal. Built from a pristine export of `adebf3d` and from this branch:

| seed | unmodified tool, 200 engine games + 200 env episodes | mixed rosters, 300 env episodes |
|---|---|---|
| 1 | identical (`2afba067492004ca`) | identical (`ae74fd270a9f6435`) |
| 42 | identical (`4423a8e41bcfee6e`) | identical (`018e84706d01bd13`) |
| 777 | identical (`3dbad3e3b8c04dc0`) | identical (`305bd7257fd8165a`) |
| 20261005 | identical (`14d576fc246d8c5a`) | identical (`7b4e97b17918ffa3`) |

The first column is the tool as it was, which pins roster 0 on both sides (a zero-filled env does that).
The second is the extended tool with `--mixed-rosters`, compiled against the pristine tree with
`-DBB_DIGEST_PRE_FLAG_TREE`. The values are the env totals.

**Flag on** (`puffer/bloodbowl/test_observation.c`, 300 episodes, 30 rosters seen, uniform sampling from
the exact joint support). At every one of 346,909 decisions: the env list is the engine's list in order
minus END_TURN exactly when the engine's list holds both types; the list is never empty; the marginal
masks equal the union of the joint support's conditional slices head by head; every listed tuple decodes
to its engine action and the removed END_TURN tuple is rejected by `bbe_decode`. At every removal in the
first 30 episodes the same state with the flag off gives byte-identical observations for both agents and
masks that differ only at END_TURN's own bits. Every episode ended at match end, none at the cap, with no
error episode and no abort. With `macro_moves=1` (60 episodes) the list, removal, decode and completion
checks hold; the marginal-against-joint mask comparison is not made there, because the macro STEP head
marks its virtual destinations from a different condition, which is not this rule's surface. A random
policy that never stops by choice plays the same games with and without the rule (the rule only binds a
policy that would have stopped).

| measurement | without the rule | with the rule |
|---|---|---|
| decisions per episode, uniform play, 300 episodes | 258.2 (max 359) | 1,156.4 (max 1,451) |
| same, digest tool, four seeds | 257.9 to 262.0 | 1,148.4 to 1,159.6 (max 1,522) |
| same with `macro_moves=1`, 60 episodes | 248.4 | 893.0 (max 1,107) |
| a random policy that never ends an activation or a turn by choice, 100 episodes | 920.2 (max 1,462) | 920.2 (max 1,462) |
| episodes cut by the 4,096 cap | 0 | 0 |

**Scripted seats** (`test_contact_bot.c`). With the rule on and a bot on one seat, the bot's list equals
the engine's at every bot decision (600 and 728 of them held END_TURN beside an ACTIVATE) while the policy
seat in the same games lost END_TURN 1,506 and 1,476 times. Bot against bot is identical with the flag on
and off in observations, masks, actions, rewards and terminals. The offense bot, on both seats with the
rule on, ended a turn early 7 times in 60 games, in the same games as with the rule off. A seat tagged as
a bot after its list was shortened gets the engine's list back.

`make test` and `make asan` pass (459 engine tests, 34 observation tests, 8 contact-bot tests).

## 5. Launcher knob

`LADDER_NO_EARLY_END_TURN=1` goes `chain_stage.sh` -> `ladder_stage.sh` -> `launch_ladder_rung.sh` ->
`run_reward_screen.sh` -> `run_reward_ablation.sh` -> trainer `--env.no-early-end-turn 1`. Where it is
recorded when on:

| record | field |
|---|---|
| `SCREEN_MANIFEST.json` | `contract.ladder.no_early_end_turn: 1` |
| run manifest (`<log>.manifest.json`) | `no_early_end_turn: "1"` and the flag in `command` |
| `LADDER_RUNG_COMPLETE.json` | `no_early_end_turn: 1`, read from the run manifest, not from the variable |
| exam cell log, `BB_EVAL_MANIFEST` | `no_early_end_turn: 1` and the flag in `command` |
| `EXAM_VERDICT.json` | `no_early_end_turn: 1`, and per cell with its `end_turn_removed` |

Unset, empty or 0, none of those keys exists and no flag is passed, so **the absence of the key is the
record that the rule was off**. Two things make that true. The launcher and the eval script refuse an
installed `bloodbowl.ini` whose own default is not 0. And the screen's acceptance step and the exam verdict
both read the env's own `end_turn_removed`: above zero when the rule is declared, zero or absent when it
is not, or the arm is not accepted and no verdict is registered. That closes the case of an env module
compiled before the flag existed, which would take the kwarg and ignore it.

A stage that trains under the rule examines under it: `chain_stage.sh` passes the knob to the six exam
cells itself, the champion's seat is restricted and the bot's is not, and the verdict says so. Which exam
to run is decided by the rung marker, and a launch whose variable disagrees with the marker or with a
registered verdict exits 7, including a relaunch of a finished stage and a plan-only pass.

**Knob unset, before and after.** The existing launcher suites pass unchanged. The pristine tree's scripts
and this branch's, given the same inputs:

| output | result |
|---|---|
| trainer argv, chain 42's recipe (111 words) | identical; with the knob, the same plus `--env.no-early-end-turn 1` |
| run-manifest pairs (88 keys) | identical; with the knob, the same plus `no_early_end_turn 1` |
| `SCREEN_MANIFEST` contract, rung plan on the tests' stand-in build (78 fields) | identical except `implementation.screen_script_sha256` and `implementation.checkpoint_lineage_sha256`; with the knob, plus `ladder.no_early_end_turn` |
| same, graft plan with one declared old build (83 fields) | the same two fields differ; `contract.graft` identical |
| `LADDER_RUNG_COMPLETE.json` | identical bytes |
| `EXAM_VERDICT.json` (time masked) | identical bytes |
| exam cell argv and `BB_EVAL_MANIFEST` line | identical |

The two differing contract fields are recorded hashes of tool files this branch edits. On the rig the
launcher's own hash and `game_stats.py`'s are recorded too and change for the same reason. So a contract
written by this branch never has the same sha256 as one written before it, with or without the knob;
nothing else in it moves.

## 6. Lineage: more than one old build

`graft_bridge` accepted sidecars that bind this build or one declared old build. The paired rung starts
from chain 41 (long-run build) with a pool that also holds the original build's checkpoints, on a third
build. `GRAFT_FROM_SOURCE_SHA256` and `GRAFT_FROM_PATCH_BUNDLE_SHA256` now also take comma-separated lists
of the same length, read pairwise.

- Every sidecar must bind this build exactly or one declared (source, patch bundle) pair, with any module.
- Every declared pair must be bound by at least one sidecar. A pair declared and absent is refused, as a
  graft with nothing old always was.
- Each declared pair's sidecars must share one compiled module.
- A pair may not be this build, and may not be declared twice.
- The run manifest carries the lists as declared and `graft_from_module_sha256` as the modules in the same
  order. The sidecar keeps `ancestry.grafted_from` for the first pair in its existing shape and records the
  others, in order, as `ancestry.grafted_from_also` (source, module and patch bundle each).

One declared pair behaves and records exactly as before: the sidecar bytes from the pristine tool and from
this branch are equal for the same run manifest. A two-pair sidecar validates with the pristine tool too,
which ignores the extra key and so cannot audit it.

**The absent rule will bite as the pool rotates.** With four banks and a fixed anchor, the pool three rungs
after the paired rung holds only the anchor (original build) and third-build checkpoints. From that rung on
the long-run pair must be dropped from the declaration.

## 7. Rig runbook

Not run. Everything below is for the owner to run. Paths are the rig's.

```
C=/home/rache/bloodbowl-rl-longrun-20261002     # the long-run checkout
K=/home/rache/m1-20261005                       # scratch for this runbook
LOCK=/home/rache/kt-e2e/kt-gpu.lock
```

Digests that appear below, in full:

| build | env source | patch bundle | module |
|---|---|---|---|
| original | `3ed6899e121bbc084568d03687be79b8ce1bb0f375c5f9cdbcdc074b0eb0a68b` | `de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad` | `d63498f6e49f1c0713cd55390e3df54e3ba43c7d11b6d8c2d1dfc081c75eee69` |
| long-run | `2ed3ffc2dcc33df0a2262cbe1f86b4742ece0983ee31d41a3b0e2cc462a01dc4` | `c1174af6b4a6c6a6b91df353678c69846b5c66a2f08997d18a141a5062a60bda` | `3d8e5f72b8e27f3e92755383a33d626e76de6ae6827b5b810554d30e0c68cbc3` |
| this branch | new, printed in step 2 | `c1174af6...` if rebuilt in place (see step 2) | new |

Pool `cc9b201e...` holds bank 0 (anchor) and bank 1 (chain 36) from the original build and banks 2 and 3
(chains 40 and 41) from the long-run build. Chain 41 is the warm start.

### 7.0 Before touching the checkout

- D407 freezes the long-run build ("no edit under `puffer/bloodbowl` ... nobody runs
  `install_puffer_env.sh` or `build.sh` in the long-run checkout"). Rebuilding it in place lifts that
  freeze for every later stage of the campaign, chains 50 to 53 of D414 included. That needs a
  `DECISIONS.md` entry first. Section 9 gives the alternative that leaves the campaign alone.
- After the rebuild every stage on this checkout needs the two-pair declaration of step 5, because its warm
  start and pool hold long-run-build checkpoints that are no longer "this build". `~/longrun/common_env.sh`
  declares one pair today.

### 7.1 Pause after the running stage

```
systemctl --user disable --now chain-supervisor@longrun-20261002.timer
# wait until the running stage has registered its verdict and nothing is left:
pgrep -af '[p]uffer_cuda_runtime.py train|[p]uffer train|[c]hain_stage.sh|[l]adder_stage.sh|[r]un_reward_screen.sh|[e]val_vs_contact_bot.sh'
```

`disable`, not `stop` (`docs/chain-supervisor-2026-10-02.md`). Do not rebuild while anything imports `_C`.

### 7.2 Keep the old build, move, rebuild in place

```
mkdir -p $K && cd $C
git status --short | head; git rev-parse HEAD | tee $K/old_head.txt
cat vendor/PufferLib/ocean/bloodbowl/.content_hash; echo        # 2ed3ffc2...
sha256sum vendor/PufferLib/pufferlib/_C*.so                     # 3d8e5f72...
cp -a vendor/PufferLib/pufferlib/_C.cpython-311-x86_64-linux-gnu.so $K/_C.longrun-3d8e5f72.so
cp -a vendor/PufferLib/ocean/bloodbowl $K/ocean-bloodbowl.longrun
cp -a vendor/PufferLib/config/bloodbowl.ini $K/bloodbowl.ini.longrun

# flag-off legal digests on the OLD tree, with this branch's tool (CPU only)
git fetch origin
git show origin/feat/no-early-end-turn-20261005:tools/bb_legal_digest.c > $K/bb_legal_digest.c
cc -std=c11 -O2 -DBB_DIGEST_PRE_FLAG_TREE -Iengine/include -Iengine/tests -Ipuffer/bloodbowl \
   -Wno-unused-function $K/bb_legal_digest.c -o $K/digest_old -lm
for s in 1 42 777; do $K/digest_old --seed $s --mixed-rosters > $K/digest_old_s$s.txt; done

git checkout feat/no-early-end-turn-20261005 && git log --oneline -1
export PATH=$C/vendor/PufferLib/.venv/bin:$PATH CUDA_VISIBLE_DEVICES=0
export PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1
bash tools/install_puffer_env.sh > $K/install.log 2>&1; echo "install rc=$?"
( cd vendor/PufferLib && rm -rf build && nice -n 5 ./build.sh bloodbowl --float > $K/build.log 2>&1 ); echo "build rc=$?"
bash tools/install_puffer_env.sh --check 2>&1 | tail -3
cat vendor/PufferLib/ocean/bloodbowl/.content_hash; echo        # the NEW source digest: write it down
sha256sum vendor/PufferLib/pufferlib/_C*.so                     # the NEW module digest

make -j8 test 2>&1 | grep -E 'tests, [0-9]+ failures|smoke OK'
make legal-digest
for s in 1 42 777; do ./build/bb_legal_digest --seed $s --mixed-rosters > $K/digest_new_s$s.txt
  cmp $K/digest_old_s$s.txt $K/digest_new_s$s.txt && echo "seed $s IDENTICAL"; done
```

Both install flags must stay exported for every later `install_puffer_env.sh` call on this checkout, the
`--check` in the stage scripts included (`common_env.sh` exports them). The patch-bundle digest hashes the
patch files under their absolute paths, so an in-place rebuild keeps `c1174af6...`; the third build then
differs from the long-run build in source and module only.

To go back: `git checkout $(cat $K/old_head.txt)`, install and rebuild the same way, and require
`.content_hash` = `2ed3ffc2...`. The rebuilt module will not be byte-equal to the kept one; the kept copy is
the reference for a `checkpoint_lineage.py rehost` if one is ever needed.

### 7.3 Identity check, flag OFF

The rebuilt checkout must reproduce chain 42's own stored checkpoints from chain 42's exact trainer
arguments, chain 41 as the warm start and a copy of pool `cc9b201e...` as the league preseed. This is
`/home/rache/bbopt-20261001/replicate_c36.sh` for chain 42. About 12 minutes of GPU. Save as
`$K/replicate_c42.sh`:

```bash
#!/usr/bin/env bash
# Replicate the first 382 epochs (50,069,504 steps) of chain 42 on the rebuilt checkout, flag OFF:
# chain 42's exact trainer arguments, chain 41 warm, a copy of pool cc9b201e as the league preseed.
# The saved weights must equal chain 42's own checkpoints at 131,072 and 50,069,504 steps.
set -uo pipefail
K=/home/rache/m1-20261005
C=/home/rache/bloodbowl-rl-longrun-20261002
PY=$C/vendor/PufferLib/.venv/bin/python
export CUDA_VISIBLE_DEVICES=0 PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1
RUN=$C/runs/ladder-d0-r0chain42-cont41-rr1-20261003
MANIFEST=$RUN/screen-attempt1/ladder-d0-s42-r0chain42-cont41-rr1-20261003-r0_poss_half-s42.log.manifest.json
WARM=$C/vendor/PufferLib/checkpoints/bloodbowl/1791097707780/0000002999975936.bin
REF=$C/vendor/PufferLib/checkpoints/bloodbowl/1791129357655
POOL=$K/pool-cc9b201e
LOCK=/home/rache/kt-e2e/kt-gpu.lock
cd $K
[ -d "$POOL" ] || cp -a "$RUN/pool" "$POOL"
"$PY" - "$MANIFEST" > "$K/chain42-full.args" <<"PY"
import json, sys
m = json.load(open(sys.argv[1]))
argv = m["command"][m["command"].index("bloodbowl") + 1:]
drop = {"--tag", "--eval-episodes", "--checkpoint-interval", "--selfplay.league-preseed", "--load-model-path"}
pairs = [argv[i:i + 2] for i in range(0, len(argv), 2)]
assert all(p[0].startswith("--") and len(p) == 2 for p in pairs)
assert not any(p[0] == "--env.no-early-end-turn" for p in pairs)
for flag, value in pairs:
    if flag not in drop:
        print(flag); print(value)
PY
mapfile -t A < "$K/chain42-full.args"
sha256sum "$WARM" "$POOL"/*.bin | cut -c1-110
exec 9>>"$LOCK"
until flock -w 600 9; do echo "$(date -u +%FT%TZ) waiting on gpu lock"; done
echo "$(date -u +%FT%TZ) $$ acquired(lock=$LOCK) bloodbowl-rl:m1-replicate-c42-flag-off (12 min)" >> "$LOCK.log"
"$PY" "$C/tools/probe_train_identity.py" run --puffer-root "$C/vendor/PufferLib" --output "$K/replicate-c42.json" --weights-dir "$K/replicate-c42-w" --epochs 382 --save-at 1,382 -- "${A[@]}" --load-model-path "$WARM" --selfplay.league-preseed "$POOL" --checkpoint-dir "$K/ckpt-rep" > replicate-c42.out 2>&1
rc=$?
echo "$(date -u +%FT%TZ) $$ released(exit $rc) bloodbowl-rl:m1-replicate-c42-flag-off" >> "$LOCK.log"
echo "probe rc=$rc"
echo "chain 42 reference:"; sha256sum "$REF/0000000000131072.bin" "$REF/0000000050069504.bin" | cut -c1-64
echo "rebuilt checkout, flag off:"; sha256sum "$K/replicate-c42-w/epoch-0001.bin" "$K/replicate-c42-w/epoch-0382.bin" | cut -c1-64
if cmp -s "$REF/0000000000131072.bin" "$K/replicate-c42-w/epoch-0001.bin"; then echo "EPOCH 1 IDENTICAL"; else echo "EPOCH 1 DIFFERENT"; fi
if cmp -s "$REF/0000000050069504.bin" "$K/replicate-c42-w/epoch-0382.bin"; then echo "EPOCH 382 IDENTICAL"; else echo "EPOCH 382 DIFFERENT"; fi
echo REPLICATE_DONE
```

Pass: `probe rc=0`, both lines IDENTICAL, reference digests
`a9efe0acbaa4794b7e830cef0e73a0bdc3af953d97caa39c129efd73d9b4ca73` (131,072 steps) and
`6c079cdc60799cf176c040e344e8a899db8af563b21850c3303486076a72313f` (50,069,504 steps), and
`hard_integrity.zero` true in `replicate-c42.json`. The warm start must hash to `b1830e23...`. If either
epoch differs, stop: the build is not the control's build with the flag off, and nothing below is a paired
rung. This check covers the first 1.7% of a rung, as D407's did.

### 7.4 Smoke, flag ON

Two short runs with the flag, both judged by the env's own `end_turn_removed`, so neither can pass with
the flag ignored. Full games, not the 48-decision probe layout: an opening cut at 48 decisions may never
reach a team turn. About 3 minutes of GPU. Save as `$K/smoke_flag_on.sh`:

```bash
#!/usr/bin/env bash
# Flag-ON smoke on the rebuilt checkout: (a) a rollout trace, (b) 24 epochs of rollout + PPO.
# Needs $K/chain42-full.args and $K/pool-cc9b201e from replicate_c42.sh.
set -uo pipefail
K=/home/rache/m1-20261005
C=/home/rache/bloodbowl-rl-longrun-20261002
PY=$C/vendor/PufferLib/.venv/bin/python
export CUDA_VISIBLE_DEVICES=0 PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1
WARM=$C/vendor/PufferLib/checkpoints/bloodbowl/1791097707780/0000002999975936.bin
POOL=$K/pool-cc9b201e
LOCK=/home/rache/kt-e2e/kt-gpu.lock
cd $K
[ -s "$K/chain42-full.args" ] && [ -d "$POOL" ] || { echo "run replicate_c42.sh first"; exit 2; }
mapfile -t A < "$K/chain42-full.args"
# 512 agents and 32 rollouts of 64 steps: about 2,000 decisions an env, so whole games complete.
TRACE=(--vec.total-agents 512 --vec.num-threads 8 --train.horizon 64 --train.minibatch-size 4096)
exec 9>>"$LOCK"
until flock -w 600 9; do echo "$(date -u +%FT%TZ) waiting on gpu lock"; done
echo "$(date -u +%FT%TZ) $$ acquired(lock=$LOCK) bloodbowl-rl:m1-smoke-flag-on (3 min)" >> "$LOCK.log"
timeout 900 "$PY" "$C/tools/probe_scripted_bank_skip.py" trace --puffer-root "$C/vendor/PufferLib" --output "$K/trace-flag-on.json" --rollouts 32 -- "${A[@]}" "${TRACE[@]}" --env.no-early-end-turn 1 --load-model-path "$WARM" --checkpoint-dir "$K/ckpt-rep" > trace-flag-on.out 2>&1; echo "trace rc=$?"
timeout 900 "$PY" "$C/tools/probe_train_identity.py" run --puffer-root "$C/vendor/PufferLib" --output "$K/smoke-flag-on.json" --weights-dir "$K/smoke-flag-on-w" --epochs 24 --save-at 24 -- "${A[@]}" --env.no-early-end-turn 1 --load-model-path "$WARM" --selfplay.league-preseed "$POOL" --checkpoint-dir "$K/ckpt-rep" > smoke-flag-on.out 2>&1; echo "ppo rc=$?"
echo "$(date -u +%FT%TZ) $$ released(exit 0) bloodbowl-rl:m1-smoke-flag-on" >> "$LOCK.log"
flock -u 9
grep -c "outside exact joint support" trace-flag-on.out smoke-flag-on.out
"$PY" - <<"PY"
import json
for name in ("trace-flag-on", "smoke-flag-on"):
    t = json.load(open(f"/home/rache/m1-20261005/{name}.json"))
    env = t["env"]
    print(name, "skip", t["skip"], "integrity_zero", t["hard_integrity"].get("zero"),
          "no_early_end_turn", t["config"]["env"].get("no_early_end_turn"),
          "episodes", env.get("n"), "end_turn_removed", env.get("end_turn_removed"),
          "truncated_episodes", env.get("truncated_episodes"))
PY
echo SMOKE_DONE
```

Pass, for both lines: `rc=0`; `skip` shows `bank: 4` and `routed: True` (the scripted-bank forward skip is
still routed with the flag on); `integrity_zero` True; `no_early_end_turn` 1; `episodes` above zero;
`end_turn_removed` well above zero (expect on the order of a hundred an episode);
`truncated_episodes` 0; and both `grep -c` counts 0. If `end_turn_removed` is 0 or missing, the env did
not apply the rule: stop. The weights are thrown away.

### 7.5 The paired rung

Control: chain 42. Same warm start (chain 41), seed 42, pool `cc9b201e...` and recipe. Declared differences:
the rule, the build (argued inert by 7.3), and the exam rule (below). The wrapper is `~/longrun/s06_chain42.sh`
with a new stamp, the pool pinned, the knob, the two-build graft and `EXAM_RULE=none`. Save as
`~/longrun/s14_chain54_m1.sh` (chain 54 is the next free number):

```bash
#!/usr/bin/env bash
# Chain 54: chain 42's rung trained under no_early_end_turn (docs/no-early-end-turn-2026-10-05.md).
# Control: chain 42 (warm chain 41, seed 42, pool cc9b201e). Not generated by make_plan.py.
set -uo pipefail
source /home/rache/longrun/common_env.sh
export SEED=42 STAMP=r0chain54-noearlyend-from41-s42-20261006
export PREV_COMPLETE=/home/rache/bloodbowl-rl-longrun-20261002/runs/ladder-d0-r0chain41-cont40-rr1-20261003/LADDER_RUNG_COMPLETE.json
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
export EXPECTED_POOL_HASH=cc9b201e619aab3dedb2577eeac273a3b70a346a5e87d30fa9ab432c068d3be6
export LADDER_NO_EARLY_END_TURN=1
# Two old builds, read pairwise: the original build (anchor, chain 36) and the long-run build (chains 40, 41).
export GRAFT_FROM_SOURCE_SHA256=3ed6899e121bbc084568d03687be79b8ce1bb0f375c5f9cdbcdc074b0eb0a68b,2ed3ffc2dcc33df0a2262cbe1f86b4742ece0983ee31d41a3b0e2cc462a01dc4
export GRAFT_FROM_PATCH_BUNDLE_SHA256=de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad,c1174af6b4a6c6a6b91df353678c69846b5c66a2f08997d18a141a5062a60bda
export GRAFT_REASON="no_early_end_turn build over the original and long-run builds"
# A paired arm never stops itself. Chain 42's drift-guard floor (0.536) was registered on exams without the rule.
export EXAM_RULE=none
exec bash "$C/tools/chain_stage.sh"
```

Put the DECISIONS entry number in `GRAFT_REASON` once it exists.

**A disposable canary first. This is required, not optional.** `AGENTS.md` asks for provenance, the CUDA
graph and zero-update checks, deterministic full games and a disposable 50M-step canary before a long
budget on a changed runtime. 7.2 to 7.4 are the provenance, identity and full-game evidence; they were
driven by probes, not by the launcher. The canary is the first time the knob, the two-pair graft,
acceptance, the six exam cells under the rule and the verdict run together on a real build, as D407's
canary was for the long-run build. If the owner's practice for a rebuilt module includes
`tools/qualify_recurrent_cuda.py`, run it before the canary. Copy the wrapper to
`~/longrun/s14_canary54_m1.sh`, replace its `SEED`/`STAMP` line and add the `STEPS` line, and change
nothing else:

```bash
export SEED=42 STAMP=canary54-noearlyend-from41-s42-20261006
export STEPS=50000000     # after `source common_env.sh`, which sets 3000000000
```

Run it to the end (`bash ~/longrun/s14_canary54_m1.sh`, about 10 minutes of training and 9 of exam). Pass:
exit 0; `EXAM_VERDICT_PASS.json` with `no_early_end_turn: 1` and six cells each carrying
`end_turn_removed` above zero; the arm's `.result.json` has `acceptance_pass: true` with
`train_metrics.end_turn_removed` and `eval_metrics.end_turn_removed` above zero, `truncated_episodes` 0 and
`illegal_frac` 0 in both; `LADDER_RUNG_COMPLETE.json` has `no_early_end_turn: 1`; and the checkpoint's
`.lineage.json` has `ancestry.grafted_from` (the original build) and one entry in
`ancestry.grafted_from_also` (the long-run build). The canary's checkpoint is never a warm start, a pool
member or a result.

**The D244 regression gate can refuse a rule rung.** `launch_ladder_rung.sh` publishes no marker when the
rung's eval `tds` is below `LADDER_REGRESSION_FLOOR` (default 0.5) times the warm rung's, and chain 41's
was 1.738 without the rule. Touchdowns per game under the rule are not that number: in the harness the
masked copy and its plain opponent scored 0.68 and 0.61 a game against 0.75 each in plain self-play. The
canary runs the same gate from the same warm start, so it shows where the rule puts `eval_tds`
(`regression_gate` in the canary's marker). If it lands near or under 0.87, the rung needs
`export LADDER_REGRESSION_FLOOR=0` in its wrapper, declared in the DECISIONS entry as a third difference
from chain 42; otherwise 3B steps can end with no marker.

Then the plan-only pass of the real rung:

```
PLAN_ONLY=1 bash ~/longrun/s14_chain54_m1.sh 2>&1 | tee ~/longrun/preflight_s14_chain54_m1.log
```

Pass: `plan-only pass verified`, `pool identity matches EXPECTED_POOL_HASH (cc9b201e...)`, and in
`$C/runs/ladder-d0-r0chain54-noearlyend-from41-s42-20261006/screen-attempt1/SCREEN_MANIFEST.json`:
`contract.ladder.no_early_end_turn` 1, `contract.graft.from_module_sha256` equal to
`d63498f6...,3d8e5f72...`, the warm sha `b1830e23...`, learning rate 0.00028 and entropy 0.009. Launch with
the supervisor timer still disabled, so the next campaign stage does not start beside it:

```
setsid nohup bash ~/longrun/s14_chain54_m1.sh > ~/longrun/s14_chain54_m1.log 2>&1 < /dev/null &
```

While it trains, on the machine panel: `end_turn_removed` above zero (expect on the order of a hundred per
episode), `truncated_episodes` 0, `illegal_frac` 0, `episode_length` well above chain 42's, and
`blocks_thrown` and turnovers up as in the harness. After it: `EXAM_VERDICT_PASS.json` with
`no_early_end_turn: 1`. Re-enable the timer when the campaign may continue:
`systemctl --user enable --now chain-supervisor@longrun-20261002.timer`, after `common_env.sh` carries the
two-pair declaration for the stages that follow on this checkout.

### 7.6 Exam and tournament consequences

Masked actions get no gradient, so a checkpoint trained under the rule is only meaningful when played under
it. On the harness side that is `--mask chain54=m1`.

- **Rig exam.** Chain 54's six cells run under the rule; chain 42's and chain 41's stored exams did not.
  For a like-for-like exam read, re-run the controls' six cells under the rule (about 90 seconds a
  cell), with the supervisor paused and under the GPU lock. For chain 42, and the same for chain 41 with
  its checkpoint (`.../1791097707780/0000002999975936.bin`) and its own output directory:

  ```bash
  CKPT=$C/vendor/PufferLib/checkpoints/bloodbowl/1791129357655/0000002999975936.bin   # chain 42
  OUT=$K/exam-under-rule-chain42; mkdir -p $OUT
  exec 9>>"$LOCK"; flock 9
  for seed in 42 43; do for spec in "contact_away 0 1" "contact_home 0 0" "offense_away 1 1"; do
    read -r cell bot_type bot_team <<<"$spec"; mkdir -p $OUT/s$seed
    env -u OMP_NUM_THREADS PATH="$C/vendor/PufferLib/.venv/bin:$PATH" NATIVE=1 RIG_ALLOW_FLOAT=1 \
        CUDA_VISIBLE_DEVICES=0 PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1 \
        SEED=$seed BOT_TYPE=$bot_type BOT_TEAM=$bot_team EVAL_EPISODES=2000 LADDER_NO_EARLY_END_TURN=1 \
        bash $C/tools/eval_vs_contact_bot.sh "$CKPT" 12000000 $OUT/s$seed/$cell.log \
        > $OUT/s$seed/$cell.out 2>&1 || echo "FAILED s$seed $cell"
  done; done; flock -u 9
  python3 $C/tools/chain_exam_verdict.py --exam-dir $OUT --seeds 42 43 --rule none \
    --no-early-end-turn 1 --output-dir $OUT
  ```

  The verdict tool is used here only as a reader: it refuses unless every cell's panel shows
  `end_turn_removed` above zero, and prints the six cells.
- **Tournament.** The harness already showed that m1 at play time is worth +32.5 Elo to chain 41 with no
  training. Chain 54 under m1 against plain chain 42 would therefore credit training with what the mask
  gives for free. The pairs that answer "did training under the rule add anything": chain 54 (m1) against
  chain 42 (m1), against chain 41 (m1), and against plain chain 42 and chain 41 for the scoreboard. Also
  chain 54 unmasked against chain 54 (m1), together with its unmasked share of team turns ended by choice
  with a player left, which measures how much of the early stopping is still in the weights.
- **Not comparable with chain 42:** in-run bank scores (the opponents are restricted too), `episode_length`,
  and per-game counts taken from the training panel.
- **A checkpoint trained under the rule and one trained without it are different action contracts.** Any
  result must say which rule each side played under. The lineage sidecar does not record the rule; the run
  manifest it hashes does.

## 8. What would make the rule removable

The rule does not remove itself: under it nothing trains the early END_TURN away (section 3, point 2), so
removal is a separate, registered step. These are the conditions under which it would be worth trying and
would count as done.

1. A rung trained under the rule beats its control with the mask held equal on both sides (section 7.6).
   Without that there is nothing to keep.
2. A continuation rung from it with the rule **off** keeps the behaviour: activations per team turn stay
   near the rule-trained parent's, and the share of team turns ended by choice with a player left stays
   low, on the style panel.
3. That rule-off checkpoint, played plain, is non-inferior to itself under m1 by the harness's registered
   margin (lower end of the interval above -20 Elo), and passes the normal gate with no loss.

If 2 fails the habit comes back as soon as the option does, and the choice is between keeping the
restriction (a constrained agent, to be described as one) and a mechanism that keeps the gradient: a
penalty or prior on END_TURN at those decisions that is annealed to zero.

## 9. Where the design is wrong, what it missed, and what I would do instead

1. **"END_TURN stays when no ACTIVATE is legal" describes a case that does not occur.** The engine ends the
   turn itself. The rule is "a policy seat has no END_TURN in a team turn". Section 3, point 1.
2. **The comparison needs the mask held equal.** As designed (rule rung against chain 42) it confounds
   training with the +32.5 the mask gives at play time. Section 7.6.
3. **Restricting the frozen-bank seats is a second factor.** The contract asks for one declared factor. With
   the bank policies restricted too, the learner's opponents change. A learner-only restriction (every seat
   except the bank's seat in a tagged env) would leave the pool as chain 42 met it. I built what was
   specified; a learner-only value is a few lines if wanted.
4. **The bot-seat exemption protects almost nothing in practice.** The contact bot never ends a turn early
   and the offense bot does 0.03% of the time. The exemption is still right, and tested.
5. **Rebuilding the long-run checkout in place collides with D407 and D414.** Chains 50 to 53 would run on
   a third build with a changed graft declaration. Preferred: a separate checkout made the way
   `/home/rache/bbopt-20261001/make_longrun_checkout.sh` made the long-run one (clone, copy the venv,
   repoint the editable finder, install with both flags, build), which leaves the campaign's build frozen
   and needs no pause beyond the GPU lock. It is not a change of one variable. What differs from section 7:
   - the new checkout's path replaces `C` in 7.2 (no old module to keep, no checkout to move), in the
     `C=` and `--puffer-root` of `replicate_c42.sh` and `smoke_flag_on.sh`, and in the two tool paths
     those scripts call;
   - `RUN`, `MANIFEST`, `WARM` and `REF` in `replicate_c42.sh`, `WARM` in the smoke script and
     `PREV_COMPLETE` in the wrapper keep pointing at the long-run checkout, where chain 41's and chain
     42's files live;
   - the wrapper must not source `~/longrun/common_env.sh`, which sets `C` to the long-run checkout: use a
     copy of that file with `C` changed, and source the copy;
   - the patch-bundle digest of the new checkout differs from `c1174af6...` because it hashes absolute
     paths; the two declared pairs are the same;
   - the rung's checkpoints and run directory land under the new checkout, so the tournament and any later
     rung read them from there.
6. **The stage wrapper should not inherit chain 42's drift guard.** Its floor was registered on exams
   without the rule, and the masked copy scored fewer touchdowns in the harness. `EXAM_RULE=none`.
7. **The cheapest way to satisfy the rule is the empty activation,** and nothing in the reward pays for
   using a player while blocks and rushes are charged. The harness copy already ended 44% of its
   activations at once. A trained policy may learn to do that for every extra player, in which case the
   rung buys longer games and forced trait rolls and no play. Read "activations ended at once" first.
8. **If the rule is the wrong mechanism:** keep END_TURN legal and put the pressure where it can be
   annealed. A bias on the END_TURN logit at decisions where an ACTIVATE is legal, part of the policy in
   both rollout and update and decayed to zero over the rung, keeps the gradient on END_TURN, changes no
   legality, needs no special exam and no lineage note, and is removable by construction. It costs a
   trainer change, which the hard rule does not. The hard rule is the right first experiment because it is
   exactly what the harness tested; it is the wrong thing to keep.

## 10. Not verified, because it needs the rig

- That the CUDA trainer builds and runs on this branch at all. Only the C test binaries and the Python
  suites ran. `binding.c` was not compiled here (it needs `vecenv.h` and the Puffer build).
- Flag-off training identity against chain 42 (7.3) and the Linux digest comparison (7.2).
- That `--env.no-early-end-turn 1` is accepted by the trainer's config parser and reaches the env (7.4).
- The scripted-bank forward skip with the flag on (7.4), and throughput under the rule.
- `my_pack_joint_actions` with the flag on: it reads the same list the tests check tuple by tuple, but the
  function itself only runs inside the trainer.
- The whole launch path with the knob and a two-pair graft on a real build. The tests cover the screen plan
  on the stand-in build, the per-arm launcher's lineage block with real sidecars, and the stage script with
  stubbed children. A 50M-step canary of the wrapper in 7.5 (`STEPS=50000000`, a throwaway stamp) would
  cover the rest, as D407's canary did, and is never a warm start.
- Whether the play harness accepts a sidecar with `grafted_from_also`. The pristine validator does.

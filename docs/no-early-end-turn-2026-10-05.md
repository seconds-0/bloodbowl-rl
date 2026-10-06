# no_early_end_turn: a training restriction, its launcher knob, and the rig runbook (2026-10-05)

**Status: built and tested off the rig. Nothing was trained. Default off. No default was changed.**
Branch `feat/no-early-end-turn-20261005`, on top of `origin/opt/long-run-20261001` (`adebf3d`).

This is not a Blood Bowl rule. The rulebook lets a coach end the team turn whenever they like, and the
engine still offers it. `no_early_end_turn` is a restriction the training environment places on the
learner's seats, for one experiment. `AGENTS.md` says every rulebook "may" is policy surface; this flag takes one
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

At a decision of a learner seat, if the engine's legal list holds an END_TURN and at least one ACTIVATE,
END_TURN is removed from the list. Nothing else changes. An activated player may still end its
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
        bbe_seat_is_learner(env, env->match.decision_team)) {
        bbe_restrict_end_turn(env);
    }
}

static bool bbe_seat_is_frozen_bank(const Bloodbowl* env, int agent) {
    return env->tag > 0 && agent == BB_AWAY;
}

static bool bbe_seat_is_learner(const Bloodbowl* env, int agent) {
    return !bbe_seat_is_scripted(env, agent) &&
           !bbe_seat_is_frozen_bank(env, agent);
}
```

- **It is the harness's m1.** m1 removes END_TURN from a seat's exact joint support when an ACTIVATE is in
  it, by action type, and never removes the last legal action. This is the same test on the same types. A
  list that holds an ACTIVATE is never emptied by taking END_TURN out.
- **One list.** `env->legal` is what the marginal masks (`bbe_fill_mask`), the packed joint support
  (`binding.c`, `my_pack_joint_actions`), the reference sampler and `bbe_decode` all read, so they shrink
  together. A policy tuple for the removed END_TURN is outside support and takes the existing abort path.
- **The engine is untouched.** No file under `engine/` changed; `bb_legal_actions` still returns END_TURN.
- **Seats: the learner's only.** Both seats of a mirror env, the learner's seat of an env whose opponent
  is a frozen bank, the champion's seat in a scripted exam. A frozen-bank seat and a scripted-bot seat keep
  the engine's list. The env reads this from state it already has. A bot seat is the predicate `c_step`
  uses to route a seat to the bot (`bbe_seat_is_scripted`). A frozen-bank seat is `env->tag > 0` and the
  AWAY slot: `selfplay.py` (`build_perm_tags`) tags an env `b+1` exactly when it routes slot 1 to frozen
  bank `b`'s row slice and slot 0 to a learner row, and tag 0 when both slots are learner rows; the
  forward-skip patch validates the same layout (`scripted_bank_skip_validate`: a bank's rows are the AWAY
  seats of the envs tagged for it). No new field was needed.
- **Two places the env cannot know better.** `puffer match` routes slot 1 to the enemy's frozen bank
  through the perm alone and sets no tags, so with the flag on it restricts both players; tournaments run
  in the play harness, where the mask is per player. And selfplay tags are assigned after the first reset,
  so a list built before them is a learner's list: a bot seat gets the engine's list back before it picks
  (`bbe_unrestrict_legal`), and a frozen-bank seat in that position has already sampled and plays that one
  decision restricted. That needs a banked start that opens on the AWAY team's turn; a kick-off start opens
  in the pre-game sequence (200 seeds checked) and the long run uses kick-off starts only.
- **Two windows.** The engine offers END_TURN beside ACTIVATE in a team turn and in the Charge! kickoff
  result. The rule applies in both, as m1 does.
- **Observation.** Unchanged, byte for byte. No observation byte says whether the flag is on, and the
  policy's forward pass does not see masks: they are applied when the action is sampled. The policy can
  therefore not tell at any one decision. What it can see is the consequence: boards on which more of its
  players have been used.
- **Flag off** is today's env in trajectories, masks and observations (section 4).
- **Panel.** `end_turn_removed` is the number of decisions per episode that a policy took from a list the
  rule had shortened, that is the learner seats' removals. It is exactly 0 with the flag off and above zero with it on. `truncated_episodes` counts
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
   closed for a learner seat and the "activate the carrier and do not score" route is the one left.
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
6. **The opponents are the control's opponents.** The frozen-bank policies play unrestricted, as they
   were trained, and the scripted bot is never restricted (the contact bot never ends a turn with a player
   left, 0 of 40,493 such decisions in 300 bot games, and the offense bot does so rarely, 19 of 63,508;
   both keep the option). So the arm meets the same pool, playing the same way, as chain 42 did, and
   differs from it in one thing: what the learner may do. The mirror envs, where the learner plays itself,
   are restricted on both seats because both seats are the learner.

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

**Which seats** (`test_contact_bot.c`). In a bank env (tag 2, no bot) the bank's seat had the engine's
list at each of its 1,015 decisions, 224 of them with END_TURN beside an ACTIVATE, while the learner's seat
lost END_TURN 1,044 times; the panel counter equals the learner's count. A mirror env restricts both seats.
In the env of a scripted bank the bot's seat is untouched and the learner's is restricted. In the exam
layout the champion is restricted on whichever seat it sits and the bot is untouched (600 and 728 bot lists
kept END_TURN beside an ACTIVATE while the champion lost it 1,506 and 1,476 times). Bot against bot is
identical with the flag on and off in observations, masks, actions, rewards and terminals. The offense bot,
on both seats with the rule on, ended a turn early 7 times in 60 games, in the same games as with the rule
off. With the flag off the env tag changes nothing. A seat tagged as a bot after its list was shortened
gets the engine's list back.

`make test` and `make asan` pass (459 engine tests, 34 observation tests, 14 contact-bot tests).

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
both read the env's own `end_turn_removed`, which now counts the learner seats' removals:

- screen acceptance, for the train phase and the eval phase separately: with the rule declared the phase's
  `end_turn_removed` must be present, finite and above zero; without it, zero or absent. Otherwise the arm
  fails acceptance (`no_early_end_turn_evidence`) and publishes no lineage.
- exam verdict, for each of the six cells: the same two conditions against the cell's manifest, which must
  itself agree with `--no-early-end-turn`. Otherwise no verdict is registered.

In a rung the learner is on at least one seat of every env and in an exam cell the champion is on one, so
"above zero" still holds under the learner-only rule; only the size of the number changed. That closes the
case of an env module compiled before the flag existed, which would take the kwarg and ignore it.

A stage that trains under the rule examines under it: `chain_stage.sh` passes the knob to the six exam
cells itself, the champion's seat is restricted and the bot's is not, and the verdict says so. The exam
script refuses to run under the rule when the venv's `puffer` entrypoint runs in another checkout's venv
(section 7.1 says why that happens). Which exam
to run is decided by the rung marker, and a launch whose variable disagrees with the marker or with a
registered verdict exits 7, including a relaunch of a finished stage and a plan-only pass.

**Knob unset, before and after.** The existing launcher suites pass unchanged. The pristine tree's scripts
and this branch's, given the same inputs:

| output | result |
|---|---|
| trainer argv, chain 42's recipe (111 words) | identical; with the knob, the same plus `--env.no-early-end-turn 1` |
| run-manifest pairs (88 keys) | identical; with the knob, the same plus `no_early_end_turn 1` |
| `SCREEN_MANIFEST` contract, rung plan on the tests' stand-in build (78 fields) | identical except `implementation.screen_script_sha256`, `implementation.checkpoint_lineage_sha256` and `implementation.game_stats_sha256`; with the knob, plus `ladder.no_early_end_turn` |
| same, graft plan with one declared old build (83 fields) | the same three fields differ; `contract.graft` identical |
| `LADDER_RUNG_COMPLETE.json` | identical bytes |
| `EXAM_VERDICT.json` (time masked) | identical bytes |
| exam cell argv and `BB_EVAL_MANIFEST` line | identical |

The three differing contract fields are recorded hashes of tool files this branch edits. On the rig the
per-arm launcher's own hash is recorded too (the stand-in stubs that script) and changes for the same
reason. So a contract written by this branch never has the same sha256 as one written before it, with or
without the knob; nothing else in it moves.

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

## 7. Rig runbook: a second checkout under the campaign's one supervisor

Not run. Everything below is for the owner to run. The arm runs from its own checkout,
`/home/rache/bloodbowl-rl-b3-20261006`, and the long-run checkout is only read. The scripts are in
`training/campaigns/longrun-20261002/b3/` with a README.

Digests that appear below, in full:

| build | env source | patch bundle | module |
|---|---|---|---|
| original | `3ed6899e121bbc084568d03687be79b8ce1bb0f375c5f9cdbcdc074b0eb0a68b` | `de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad` | `d63498f6e49f1c0713cd55390e3df54e3ba43c7d11b6d8c2d1dfc081c75eee69` |
| long-run | `2ed3ffc2dcc33df0a2262cbe1f86b4742ece0983ee31d41a3b0e2cc462a01dc4` | `c1174af6b4a6c6a6b91df353678c69846b5c66a2f08997d18a141a5062a60bda` | `3d8e5f72b8e27f3e92755383a33d626e76de6ae6827b5b810554d30e0c68cbc3` |
| b3 | new, printed by `make_b3_checkout.sh` | new | new |

Pool `cc9b201e...` holds bank 0 (anchor) and bank 1 (chain 36) from the original build and banks 2 and 3
(chains 40 and 41) from the long-run build. Chain 41 (`b1830e23...`) is the warm start.

### 7.0 What one supervisor needs to drive a second checkout

Read from `tools/campaign_supervisor.py` (the long-run checkout runs the same file):

- **Absolute `success` and `progress` paths are accepted.** `stage_is_complete` (line 187) and
  `stage_progress_age` (line 178) join a path to the plan root only when it is not absolute. A stage's
  artifacts can therefore live under the b3 checkout's `runs/`.
- **The attempt logs stay with the plan root:** `runs/campaign-logs/<stage>-attempt<N>.log` under the
  long-run checkout (line 257), unless the plan sets `log_dir`. That is the only thing a b3 stage writes
  there.
- **The launch cwd is the plan root** (line 243). The b3 stages do not depend on it: each finds its env
  file from its own location and `chain_stage.sh` changes into `$C`.
- **Liveness is one host-wide `pgrep -f` of the plan's `trainer_pgrep`** (lines 157 to 172). A stage in
  another checkout counts, if the pattern names it. `chain_stage.sh` is named. `b3_identity.sh` is not:
  add `|[b]3_identity.sh` to the plan's pattern, or the supervisor sees nothing alive while that stage
  waits for the GPU lock or runs its probes, relaunches it each tick and halts the campaign at the attempt
  cap.
- **A halt is campaign-wide and sticky.** A b3 stage that exhausts its attempts stops the long-run stages
  queued behind it. Put the b3 stages after the last stage that must run regardless.

The launch path has no checkout that `C` does not override. `chain_stage.sh` refuses to start without `C`
(line 92) and changes into it (line 188). `ladder_stage.sh:61` and `launch_ladder_rung.sh:78` default `C` to
the original checkout only when it is unset, and the wrappers export it. `run_reward_screen.sh:25`,
`run_reward_ablation.sh:67` and `eval_vs_contact_bot.sh:69` take their checkout from their own location and
are always invoked through `$C`. What is shared across checkouts is two locks, which is what is wanted:
the GPU lock (`chain_stage.sh:168`) and the one-trainer host lock (`run_reward_ablation.sh:532`). An
accepted checkpoint must come out of the checkout that ran the screen (`run_reward_screen.sh:1372`), so
chain 54's checkpoints land under the b3 checkout. No change to any of these scripts was needed;
`tools/test_b3_stage_scripts.py` pins it.

### 7.1 Create the checkout

```
cp -a <this branch>/training/campaigns/longrun-20261002/b3 /home/rache/longrun/b3
bash /home/rache/longrun/b3/make_b3_checkout.sh 2>&1 | tee /home/rache/longrun/b3/make_b3_checkout.log
```

It is `/home/rache/bbopt-20261001/make_longrun_checkout.sh` with the target and ref changed: clone the
original checkout, set the remote, check out `origin/feat/no-early-end-turn-20261005`; rsync
`vendor/PufferLib` without `build`, `.venv`, `checkpoints`, `logs`, `experiments`; `cp -a` the venv (7 GB);
repoint the editable finder `__editable___pufferlib_4_0_0_finder.py`; install with
`PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1`; `./build.sh bloodbowl --float`;
`install_puffer_env.sh --check`; import check from `/`. It refuses an existing target and writes only under
the new path. It is CPU work, at `nice 5`, plus one module import at the end, and can run while the campaign
trains.

**One addition, and a finding about the long-run checkout.** `cp -a` copies the venv's entrypoint scripts
with the shebang of the venv they came from. The long-run checkout's
`vendor/PufferLib/.venv/bin/puffer` starts with
`#!/home/rache/bloodbowl-rl-qualification-candidate-10619e2/vendor/PufferLib/.venv/bin/python`, and that
venv's editable finder points at the original checkout. The trainer does not go through that entrypoint
(it runs `python tools/puffer_cuda_runtime.py`), but `eval_vs_contact_bot.sh` does. So the exam cells of
the long-run campaign appear to have run the original checkout's `pufferlib` and compiled module, while
each cell's manifest records the long-run module (`3d8e5f72...`), which it takes from the checkout's file
and not from the import. Chain 42's training log has the long-run build's deciding-row telemetry 69,030
times; its exam cell logs have it zero times. D407's identity evidence says the two builds play the same
with the flag-free env, so the exam numbers are probably unaffected; the provenance is wrong. This was
read from files on the rig, not reproduced by running anything.

For b3 the same thing would run the exam on a module that does not know the flag. So
`make_b3_checkout.sh` repoints the shebangs as well and checks the import through both doors (the venv's
python and the interpreter the entrypoint names), `b3_identity.sh` refuses a foreign entrypoint, and
`eval_vs_contact_bot.sh` refuses one under the rule. Without the rule it prints a warning and runs as
before.

Expected at the end: `install rc=0`, `build rc=0`, `drift check: OK`, the two import blocks both naming
`/home/rache/bloodbowl-rl-b3-20261006/vendor/PufferLib/pufferlib/` with one module sha256 and
`compiled == installed`, then `B3_CHECKOUT_DONE`. Write down the source digest and the module sha256.

**The patch-bundle digest of this build is not `c1174af6...`.** Both launchers hash each patch file
together with its absolute path, so the same patch files under a different checkout root give a different
bundle digest. The b3 build therefore differs from the long-run build in source, bundle and module.

### 7.2 The graft declaration

The rung's warm start (chain 41) and banks 2 and 3 bind the long-run build; banks 0 and 1 bind the original
build; nothing binds the b3 build yet. So there are exactly two old builds, declared pairwise, in
`b3_common_env.sh`:

```
export LADDER_PROFILE=graft
export GRAFT_FROM_SOURCE_SHA256=3ed6899e121bbc084568d03687be79b8ce1bb0f375c5f9cdbcdc074b0eb0a68b,2ed3ffc2dcc33df0a2262cbe1f86b4742ece0983ee31d41a3b0e2cc462a01dc4
export GRAFT_FROM_PATCH_BUNDLE_SHA256=de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad,c1174af6b4a6c6a6b91df353678c69846b5c66a2f08997d18a141a5062a60bda
```

Two pairs, not three. The path change makes the b3 build's bundle digest new, and that digest belongs to
"this build", which is never declared; it does not split the long-run build into two. A third pair would
be declared and absent, and is refused. The recorded modules will be
`d63498f6...,3d8e5f72...`, and the published sidecar carries the original build in `ancestry.grafted_from`
and the long-run build in `ancestry.grafted_from_also`.

### 7.3 The three stages

Add them to `CAMPAIGN_PLAN.json` as the README gives them (absolute `success` and `progress`, and
`|[b]3_identity.sh` appended to `trainer_pgrep`), or run them by hand in order with the supervisor paused
(`systemctl --user disable --now chain-supervisor@longrun-20261002.timer`).

1. **`b3_identity.sh`**, about 20 minutes of GPU under the shared lock. It is `replicate_c36.sh` for chain
   42 on the b3 build, plus the flag-on smoke:
   - flag off: chain 42's exact trainer arguments (its run manifest minus tag, eval episodes, checkpoint
     interval, preseed and warm path), chain 41 as the warm start, a private copy of pool `cc9b201e...` as
     the league preseed, 382 epochs through `tools/probe_train_identity.py`. The saved weights must be
     byte-equal to chain 42's own checkpoints at 131,072 steps
     (`a9efe0acbaa4794b7e830cef0e73a0bdc3af953d97caa39c129efd73d9b4ca73`) and 50,069,504 steps
     (`6c079cdc60799cf176c040e344e8a899db8af563b21850c3303486076a72313f`), and the env panel must show
     `end_turn_removed` exactly 0.
   - flag on: a rollout trace of whole games (512 agents, 32 rollouts of 64 steps) and 24 epochs of rollout
     plus PPO at the full layout with the real pool. Both must show `end_turn_removed` above zero, the
     forward skip routed to bank 4, zero hard-integrity counters, no truncated episode and no
     out-of-support abort.
   - every probe must have imported the b3 checkout's module, the drift check must pass, and the warm
     start, the two reference checkpoints and the pool copy must have their pinned sha256.
   It writes `runs/b3-identity-20261006/B3_IDENTITY_PASS.json` only if all of that held, exits non-zero
   otherwise, and each launch works in a new `attemptN` directory. This covers the first 1.7% of a rung, as
   D407's check did. If either epoch differs, stop: the build is not the control's build with the flag off.
2. **`b3_canary54.sh`**, a disposable 50M-step run of the rung's exact launch path
   (`canary54-noearlyend-from41-s42-20261006`), about 10 minutes of training and 9 of exam. It is the first
   time the knob, the two-pair graft, acceptance, the six exam cells under the rule and the verdict run
   together on a real build. Pass: `EXAM_VERDICT_PASS.json` with `no_early_end_turn: 1` and six cells each
   carrying `end_turn_removed` above zero; the arm's `.result.json` with `acceptance_pass: true`,
   `end_turn_removed` above zero and `truncated_episodes` 0 in both phases; `LADDER_RUNG_COMPLETE.json` with
   `no_early_end_turn: 1`; a sidecar with `grafted_from` and one `grafted_from_also` entry. Never a warm
   start, a pool member or a result. If the owner's practice for a new module includes
   `tools/qualify_recurrent_cuda.py`, run it before this.
3. **`b3_chain54.sh`**, the paired rung `r0chain54-noearlyend-from41-s42-20261006`: warm chain 41, seed 42,
   pool `cc9b201e...`, bot on tag 4, the standard recipe, `LADDER_NO_EARLY_END_TURN=1`, `EXAM_RULE=none`.
   Control: chain 42. `PLAN_ONLY=1 bash b3_chain54.sh` first: `plan-only pass verified`, `pool identity
   matches EXPECTED_POOL_HASH (cc9b201e...)`, and in the run's `screen-attempt1/SCREEN_MANIFEST.json`
   `contract.ladder.no_early_end_turn` 1, `contract.graft.from_module_sha256` equal to
   `d63498f6...,3d8e5f72...`, the warm sha `b1830e23...`, learning rate 0.00028 and entropy 0.009.

The canary refuses to train without the identity marker, and the rung without the identity marker and the
canary's passing verdict. Put the DECISIONS entry number into `GRAFT_REASON` in `b3_common_env.sh` once it
exists.

**The D244 regression gate can refuse the rung.** `launch_ladder_rung.sh` publishes no marker when the
rung's eval `tds` is below `LADDER_REGRESSION_FLOOR` (default 0.5) times the warm rung's, and chain 41's was
1.738 without the rule. The canary runs the same gate from the same warm start, so its marker shows where
the rule puts `eval_tds` (`regression_gate`). If it lands near or under 0.87, the rung needs
`export LADDER_REGRESSION_FLOOR=0`, declared as a difference from chain 42; otherwise 3B steps can end with
no marker.

**What differs from chain 42, to be written into the DECISIONS entry:** the rule on the learner's seats;
the build (argued inert by the identity stage, for 1.7% of a rung); `EXAM_RULE=none` in place of the
drift guard, whose floor was registered on exams without the rule; the exam itself, which runs under the
rule.

While it trains, on the machine panel: `end_turn_removed` above zero, `truncated_episodes` 0,
`illegal_frac` 0, `episode_length` above chain 42's.

### 7.4 Exam and tournament consequences

Nothing trains the early END_TURN away (section 3, point 2), so a checkpoint trained under the rule is to
be played under it. On the harness side that is `--mask chain54=m1`.

- **Rig exam.** Chain 54's six cells run under the rule; chain 42's and chain 41's stored exams did not.
  For a like-for-like read, re-run the controls' six cells under the rule from the b3 checkout (about 90
  seconds a cell), with the supervisor paused and under the GPU lock. For chain 42, and the same for chain
  41 with its checkpoint (`.../1791097707780/0000002999975936.bin`) and its own output directory:

  ```bash
  C=/home/rache/bloodbowl-rl-b3-20261006; L=/home/rache/bloodbowl-rl-longrun-20261002
  CKPT=$L/vendor/PufferLib/checkpoints/bloodbowl/1791129357655/0000002999975936.bin   # chain 42
  OUT=$C/runs/exam-under-rule-chain42; mkdir -p $OUT
  exec 9>>/home/rache/kt-e2e/kt-gpu.lock; flock 9
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
- **Tournament.** The harness showed that m1 at play time is worth +32.5 Elo to chain 41 with no training
  (the free tournament of chains 41 and 42 under m1 is being run separately). Chain 54 under m1 against
  plain chain 42 would credit training with what the mask gives for free. The pairs that answer "did
  training under the rule add anything": chain 54 (m1) against chain 42 (m1), against chain 41 (m1), and
  against plain chain 42 and chain 41 for the scoreboard. Also chain 54 unmasked against chain 54 (m1),
  with its unmasked share of team turns ended by choice with a player left, which measures how much of the
  early stopping is still in the weights.
- **Comparable with chain 42 now:** the opponents. The pool plays as it did for chain 42, so the in-run
  bank scores are scores against the same opponents. **Still not comparable:** `episode_length` and
  per-game counts from the training panel, and the mirror envs, where the learner's own play changed.
- **A checkpoint trained under the rule and one trained without it are different action contracts.** Any
  result must say which rule each side played under. The lineage sidecar does not record the rule; the run
  manifest it hashes does. `puffer match` cannot apply the rule to one side only (section 2).

### 7.5 The in-place route, not taken

Rebuilding the long-run checkout in place would keep its patch-bundle digest (same paths), need the same
two pairs, lift D407's build freeze for chains 50 to 53, and make every later stage of the campaign need
the two-pair declaration. It also inherits the entrypoint shebang problem of 7.1 unchanged. Nothing in the
tooling prevents it; this document no longer describes it.

## 8. What would make the rule removable

The rule does not remove itself: under it nothing trains the early END_TURN away (section 3, point 2), so
removal is a separate, registered step. These are the conditions under which it would be worth trying and
would count as done.

1. A rung trained under the rule beats its control with the mask held equal on both sides (section 7.4).
   Without that there is nothing to keep.
2. A continuation rung from it with the rule **off** keeps the behaviour: activations per team turn stay
   near the rule-trained parent's, and the share of team turns ended by choice with a player left stays
   low, on the style panel.
3. That rule-off checkpoint, played plain, is non-inferior to itself under m1 by the harness's registered
   margin (lower end of the interval above -20 Elo), and passes the normal gate with no loss.

If 2 fails the habit comes back as soon as the option does, and the choice is between keeping the
restriction (a constrained agent, to be described as one) and the removable alternative below.

**Parked: an annealed END_TURN bias.** Keep END_TURN legal and subtract a bias from its logit at decisions
where an ACTIVATE is legal, as part of the policy in both rollout and update, decayed to zero over the
rung. It keeps the gradient on END_TURN, changes no legality, needs no special exam and no lineage note,
and is removable by construction: at zero bias the policy is an ordinary one. It costs a trainer change
(the sampling kernels and the PPO recompute), which the hard rule does not. Not built. It is the mechanism
to reach for if the hard rule shows a gain worth keeping.

## 9. What changed from the first design, and what is still open

Accepted and done: the rule restricts learner seats only, so the arm's opponents are the control's; the arm
runs from its own checkout; the tournament holds the mask equal. Still open:

1. **"END_TURN stays when no ACTIVATE is legal" describes a case that does not occur.** The engine ends the
   turn itself. The rule is "a learner seat has no END_TURN in a team turn". Section 3, point 1.
2. **The cheapest way to satisfy the rule is the empty activation,** and nothing in the reward pays for
   using a player while blocks and rushes are charged. The harness copy already ended 44% of its
   activations at once. A trained policy may learn to do that for every extra player, in which case the
   rung buys longer games and forced trait rolls and no play. Read "activations ended at once" first.
3. **The long-run campaign's exam cells appear to have run the original checkout's module** (section 7.1).
   That is a provenance defect in chains 37 to 49's exam records whether or not b3 runs, and it wants its
   own entry and a decision on whether to fix that venv's shebangs between stages.
4. **One supervisor means one halt.** A b3 stage that fails its attempts halts the long-run stages behind
   it. A second supervisor unit with its own plan and state would isolate them, at the cost of a second
   thing to watch; the GPU lock already serialises the two.
5. **The regression gate and the drift guard were registered on numbers without the rule** (section 7.3).
6. **Mirror envs still change on both seats.** That is the learner playing itself, so it is the declared
   factor and not a second one, but it means part of the arm's experience is against a restricted opponent
   and part against unrestricted ones.

## 10. Not verified, because it needs the rig

- That the CUDA trainer builds and runs on this branch at all. Only the C test binaries and the Python
  suites ran. `binding.c` was not compiled here (it needs `vecenv.h` and the Puffer build).
- `make_b3_checkout.sh`: written from the long-run script and read, never run. In particular the shebang
  rewrite and the two-door import check.
- Flag-off training identity against chain 42 and the flag-on smoke: `b3_identity.sh` was run only against
  stand-in probes.
- That `--env.no-early-end-turn 1` is accepted by the trainer's config parser and reaches the env.
- That selfplay tags are what the env reads them as on the real layout (the env tests set the tag by hand;
  the layout is read from `selfplay.py` and the forward-skip patch). The trace in `b3_identity.sh` exercises
  it; a direct check would be the trace's per-bank action masks.
- `my_pack_joint_actions` with the flag on: it reads the same list the tests check tuple by tuple, but the
  function itself only runs inside the trainer.
- The whole launch path with the knob and a two-pair graft on a real build: the canary is that check.
- The supervisor driving a stage in another checkout: read from the code and tested with the supervisor's
  own functions, not run under systemd.
- That the long-run exam cells ran the original module: inferred from the shebang, the finder and the
  missing telemetry in the exam logs.
- Whether the play harness accepts a sidecar with `grafted_from_also`. The pristine validator does.

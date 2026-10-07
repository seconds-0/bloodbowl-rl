# Search probe: design study (2026-10-07)

**Status: a design study, written by an agent on the session model and read by the operator, who checked its main code citations against the source. Nothing here is registered until a DECISIONS.md entry says so. No code was written, nothing was built, no game was played. Codex reviewed it on 2026-10-07 (`.codex-reviews/search-probe-design-review.md`); section 8 lists what that review changes. Where section 8 and the text above it disagree, section 8 holds.**

How to read the labels. Every claim carries one of these:
- **[code]** verified by reading the source, with file and line. Paths under `play_harness/`, `puffer/` and `engine/` are in `/Users/alexanderhuth/Code/bb-harness-masks` at commit `7d0d547` (the mask branch), unless another path is given.
- **[ledger]** read from `DECISIONS.md` or a doc in one of the two repos, with the entry or file. This is the repo's own record, not something I re-measured.
- **[given]** a fact supplied with the task and not re-derived.
- **[lit]** from a published source, listed in section 6.
- **[estimate]** arithmetic on labelled inputs. Read every estimate as plus or minus a factor of two until the pilot measures it.
- **[hypothesis]** my judgment, not verified.

## Recommendation

Build the narrowest version and test it, because it is cheap in dollars and the engine was built for it: a root-only rollout search for one seat, at the three decisions that open an activation (which player, which action, and the first choice after the declaration), with about 4 candidates and 8 to 16 rollouts each to the end of the seat's own team turn, scored by the reward the checkpoint was trained on plus the value head at the turn boundary, deviating from the policy's own sampled action only when a candidate is better by a margin and by two standard errors. Play it as chain 55 + m1 + search against chain 55 + m1, with the two held-out opponents on shared seeds. A pilot of about 600 searched games and 1,000 offline states (about $1 to $2) decides whether the gate is worth playing. The gate is about $10 to $35 of droplets and 60 to 200 droplet-hours [estimate].

Three things in the plan as it stands are wrong and one is missing. They are the first four items of the next section.

## Where the plan is wrong, and what was missed

1. **"Score with the value head" is wrong for this reward.** The value head predicts the discounted sum of the *shaped* training reward, not the chance of winning. `r0_poss_half` pays 0.4 per touchdown, 0.6 for the win, 0.05 for gaining the ball, 0.04 per square the carrier advances, 0.02 per square toward a loose ball, a block's expected value at declaration, 0.015 possession annuity at own turn end, and charges 0.015 per rush [code: `/Users/alexanderhuth/Code/bb-opt-build/puffer/config/rewards/r0_poss_half.json:6-39`]. Reward already collected inside a rollout is not in the value at the end of it. A rollout that scores a touchdown has banked 0.4 that the end-state value does not contain, so a value-only score would rank scoring below not scoring. The score must be the n-step return: discounted reward collected in the rollout plus the discounted value at the stop.
2. **The harness cannot compute that return today.** The shim creates its env with every shaping coefficient zero, on purpose: "Reward fields keep the objective defaults and zero shaping" [code: `play_harness/native/bbplay.c:121-128`]. The search needs the training reward manifest switched on in the env it rolls out, pinned by hash, with gamma 0.999 [given].
3. **Variant (b) as described is not a valid search.** "Sample k whole-turn continuations, keep the best by value" takes a maximum over single dice samples. It prefers whichever first action happened to roll well, which is noise at best and risk-seeking at worst (a risky dodge looks best in the one sample where it worked). Only the first action can be committed, so samples must be grouped by first action and averaged. Once that is done it is variant (a) restricted to turn-level decisions, with a worse way of choosing candidates. Section 2.
4. **The control must be the same checkpoint under m1, not the plain checkpoint.** m1 alone is worth +32 to +43 [given; ledger: `docs/play-harness/masked-copy-baselines-2026-10-05.md:107-109`]. The roadmap's exit bar ("more than +50 decisive-Elo over the raw network" [ledger: `docs/plans/superhuman-roadmap-2026-10-03.md:51`]) would be mostly met by the mask. Search has to beat chain 55 + m1.
5. **Missed: nobody has measured the free sharpening baseline for one checkpoint.** A few-rollout search partly works by avoiding low-probability actions that T=1 sampling picks. Lower temperature does that at zero cost. The ledger used argmax and T=0.75 as controls between different checkpoints (D400), and I found no run of one checkpoint at T below 1 against itself at T=1 [not found; see section 7]. The pilot adds that pair. If T=0.5 is worth +30 on its own, the search result has to be read against it.
6. **Missed: the search optimizes the shaped proxy harder, not winning.** The policy is already the trained response to that reward. A search that maximizes the same n-step shaped return can over-collect shaping (for example run the carrier forward for the immediate 0.04 a square). Whether that raises win rate is the empirical question, and it is why the gate is decisive-Elo against held-out opponents and not the search's own predicted gain. A small outcome head (win probability or touchdown difference, fitted offline on harness games) would remove the proxy. It is parked on the ladder, not in the probe.
7. **Missed: what search cannot fix.** A rollout to the end of the own turn scored by this value head can only find what the short-horizon reward or the value head already prices. If the value head does not price marking and screening, the search will not either. I expect the gain to come from three places: empty activations where a paid block, pickup or advance was available; the order of safe and risky activations; and last-turn scoring attempts. [hypothesis]
8. **Missed: dollars are not the constraint.** At $0.167 an hour a 100-fold slowdown still costs a few dollars per 3,200-game pair [estimate, section 2]. Wall-clock and droplet slots are the constraint (the account limit is 10, shared with other projects [ledger: `docs/play-harness/droplet-tournaments-2026-09-17.md`, "Size and price"]). So "the cheapest search" should not be chosen for cost alone. It should be chosen for signal against noise.
9. **Missed: at human time scales this search is nearly free.** One searched decision is about 1,150 forward rows [estimate], well under a second on the Mac. A human-facing agent in the browser harness can afford ten times the rollouts of the tournament arm. If the probe is positive, the M4 human series should use the larger budget.
10. **A wording trap in the roadmap.** It says "under shared dice" [ledger: `superhuman-roadmap-2026-10-03.md:34`]. Shared dice across candidates is fine as a variance reduction, and only if the dice are the search's own streams. The existing scratch-copy function copies the real dice stream with the session. Section 1.2.

## 1. Feasibility in this codebase

### 1.1 Clone and restore

- The match state is one fixed-size struct with no pointers, designed as a forward-model snapshot: "Fixed size, no pointers, memcpy-able. Copying a bb_match IS a forward model snapshot (search, undo, golden traces)" [code: `engine/include/bb/bb_match.h:3-5`; struct at `:76-140`]. It is 2,240 bytes [estimate from the ctypes mirror `play_harness/engine.py:126-150`, which the loader checks against the C layout at `:260-265`].
- The env wraps it with its own bookkeeping: the dice stream, counters, reward state, the legal list and its projections [code: `puffer/bloodbowl/bloodbowl.h:686-852`]. The shim's session adds the observation, mask, action and reward buffers [code: `bbplay.c:35-57`].
- A whole-session copy already exists and is tested. `bbp_peek_legal` does `malloc`, `memcpy(c, s, sizeof(bbp_session))`, re-points the buffer pointers with `bbp_wire`, steps the copy with the real `bbp_step`, frees it, and re-attaches the stalling sink [code: `bbplay.c:360-372`, `bbp_wire` at `:94-109`]. `test_peek_legal_matches_real_activation_and_leaves_state_untouched` checks the real session's digest is unchanged [code: `play_harness/tests/test_engine.py:74-96`].
- `bbp_run_c_step` also keeps a pre-step copy of the match and of the dice stream to rebuild the final state [code: `bbplay.c:259-297`], so both halves of a snapshot are already handled by value.
- A session is at least about 42 KB (the legal list is 4,096 four-byte actions, plus projections, two observations and two matches) [estimate; `sizeof(bbp_session)` not measured because nothing was built]. A copy is a few microseconds. Cloning is not a cost that matters.
- Global state that a clone could disturb:
  - The stalling tally pointer is thread-local and `c_step` re-points it at its own env on every call [code: `engine/src/proc_turn.c:10`, `bloodbowl.h:3448`, rationale `engine/include/bb/bb_stall.h:20-31`]. After stepping clones the real session must be re-attached, as `bbp_peek_legal` does at `bbplay.c:370`. No rule reads the tally.
  - `bb_casualty_hook` is process-global and only the renderer sets it [code: `puffer/bloodbowl/bbe_render.h:305`]. `bbe_feed_hook` defaults to null [code: `bloodbowl.h:2146-2149`]. The state bank statics load only when `demo_reset_pct > 0`, and the shim sets 0 [code: `bloodbowl.h:2166-2168`, `:2493-2494`, `bbplay.c:140`]. The macro-move debug counters are behind `macro_moves`, which the shim sets 0 [code: `bloodbowl.h:1759`, `bbplay.c:137`].
  - I found no call to `rand`, `time` or any other entropy source in `engine/src` or the env header [code: search of those files].
- `c_step` resets the env to a fresh match at the terminal step [code: `bloodbowl.h:4046-4065`]. The shim already marks a session terminal and refuses further steps [code: `bbplay.c:292-294`, `:303`]. A rollout that reaches the end of the match stops there and takes the terminal reward with no value bootstrap.

**Verdict: clone and restore is cheap and mostly exists. What is missing is a clone entry point for search that does not carry the real dice.**

### 1.2 Dice, and the guarantee that search never sees the real game's future

- The match holds no dice: "the state itself holds no RNG, so the same state can be advanced under PRNG or under a replay dice script" [code: `bb_match.h:11-13`]. Every die goes through the `bb_rng` passed to `bb_apply` and `bb_advance` [code: `engine/src/bb_match.c:422-446`, `:478-496`; `engine/src/bb_rng.c:46-70`].
- The real stream lives in the env, not the match: `bb_rng rng; // in-match dice` [code: `bloodbowl.h:687`]. It is seeded at reset as PCG32 `(seed + episode * 7919, stream 1)` [code: `bloodbowl.h:2631`; `bb_rng.c:12-24`]. `c_step` applies the action with `&env->rng` [code: `bloodbowl.h:3655`].
- Dice for an action are drawn when the action is applied, during the advance to the next decision [code: `bb_match.c:478-496`]. At a decision point the future dice exist only as the stream's state.
- **So a `memcpy` of the session copies the real stream state, and stepping that copy rolls the real game's next dice.** `bbp_peek_legal` does exactly this. It is harmless there because it only returns the legal list after a dice-free ACTIVATE, but the same call pattern in a search would be the peeking bug.
- Design:
  1. One exported clone function for search, `bbp_clone_for_search(s, seed, stream)`, which copies the session and then always calls `bb_rng_seed(&clone->env.rng, seed, stream)`. It refuses `stream == 1`, the real stream's id. There is no exported way to clone with the dice intact, except one test hook with `test` in its name that `search.py` never references (a unit test greps for that).
  2. Rollout seeds are a hash of public values only: the seat's sampling seed, the engine step index, and the rollout index. The same rollout index uses the same seed for every candidate (common random numbers across candidates).
  3. Rollout action sampling uses its own generators, never the seat's real generator.
- Tests that prove it (section 5): the search's outputs are bit-identical when the root's real stream state is scrambled; the real session's digest, which covers the match bytes and the dice stream bytes [code: `bbplay.c:417-430`], is unchanged by a search; and a deliberate peeking variant, used only as a positive control, is caught by a statistical canary in the pilot.

### 1.3 Hidden information

- Blood Bowl as implemented here is perfect information apart from dice. Both observations are functions of the same match [code: `bloodbowl.h:2280-2286`]. The only things the search must not know are future dice and the opponent's future choices.
- Opponent choices inside a rollout come from a model: the searching seat's own network, read on the opponent's observation row, sampled with search generators. The real opponent seat's policy, recurrent state and generator are never touched. Test: run a search with the opponent seat replaced by an object that raises on any access.
- With rollouts that stop at the end of the searcher's own turn, the opponent only makes reactive choices (block die when the defender chooses, skill and re-roll prompts, apothecary). The opponent model therefore matters little in the probe, and matters a great deal if the depth is ever extended through the opponent's turn. [hypothesis]

### 1.4 The recurrent state

- The policy is stepped on every engine step, deciding or waiting, and its state is zeroed once per match [code: `play_harness/policy.py:286-335`; contract in the module docstring `:18-22`]. The tournament aborts unless each seat made exactly one forward per engine step [code: `play_harness/tournament.py:22-24`, `:293-295`].
- Skipping waiting steps changes the decision logits [code: `play_harness/tests/test_recurrence.py:57-73`], so a rollout must forward the searcher's network on every rollout step, including the steps where the opponent decides.
- When `decide()` is called the seat's state is already the state after the forward on the root observation, in both the unbatched and the batched path [code: `policy.py:312-317`, `:453-475`; `tournament.py:574`, `:589`]. A rollout starts from a copy of that state (3 x 1 x 512 floats), applies the candidate, and forwards on each new observation with the copy. The real state is never written.
- The opponent model needs its own recurrent stream. Exact version: the search seat keeps a shadow state by forwarding its own network on the opponent's row once per real step (one extra row per real step), and each rollout carries a copy forward. That makes a rollout step two forward rows, one per view.
- Test that the carry is right (the important one): an oracle rollout, in a test only, is given the real dice stream and the real generators and must reproduce what the real game then does under plain play, step for step. If the state carry, the mask, or the reward accounting were wrong it would diverge.

### 1.5 What the harness lacks today

1. A dice-free clone entry point (1.2).
2. The training reward in the env. The shim mirrors only `reward_td`, `reward_win`, `reward_draw` [code: `bbplay.c:125-128`; drift guard `play_harness/tests/test_native_config.py:14-30`]. All rewards go through one seam, `bbe_reward_add`, into `reward_ptr` [code: `bloodbowl.h:1005-1011`], and the shim already exposes the last step's rewards [code: `bbplay.c:410-413`]. Switching the manifest on at session creation gives training semantics from step 0, including the potentials that reset primes as inactive [code: `bloodbowl.h:2733-2737`]. Switching it on only in a clone would lose the first step's distance reward, because the legacy distance form emits nothing while the previous potential is unset [code: `bloodbowl.h:4010-4028`]. So the real session of any game with a search seat is created with the manifest. I read `c_step` and found reward code writing only reward and telemetry fields, never the match or the dice [code: `bloodbowl.h:3443-4066`]; a test must prove games are identical with and without the manifest.
3. The value. `PolicySeat.step` returns it but `batched_forward` discards it [code: `policy.py:316`, `:472`]. The search runs its own forwards and keeps it.
4. An engine handle on the seat. `decide(logits, support, deciding)` has no access to the engine [code: `tournament.py:589`]. The search seat is bound to its match's engine after construction [code: seats built at `tournament.py:254`, engine at `:259`].

## 2. The narrowest search worth testing

### Cost model

Inputs:
- A game under m1 is about 1,258 engine steps for both sides; chain 55 + m1 makes 643.8 own decisions, 6.78 activations and 0.42 turnovers per team turn [ledger: D421 diagnostics table].
- 7.8 games a second on an 8-vCPU droplet at 32 games per worker [given]. From the ledger's cost lines the plain gates ran at about 7.7 to 8.7 games a second net of start-up and the m1 gate at about 5 [estimate from D419, D421, D424 cost lines and 5 minutes of overhead per droplet]. I use 5 to 7.8.
- At 32 per worker a forward row costs about 0.2 ms in the matrix products and the sampler is about a third of the time [ledger: `docs/play-harness/batched-tournaments-2026-09-17.md:193-200`].
- A team turn is about 36 to 39 engine steps, so the mean distance from an activation boundary to the end of the own turn is about 18 steps (L = 18, range 12 to 25) [estimate].
- A rollout step is two forward rows, one sampled selection and one engine step. In a Python implementation that reuses `select_joint` I price it at one plain engine step (r = 1). A C rollout kernel would be about half (r = 0.5). [hypothesis; the pilot measures it]

Slowdown of a game with one searching seat: `1 + D * k * n * L * r / 1258`, where D is searched decisions per game, k candidates, n rollouts per candidate.

| Scope | D per game | k x n | Rollout steps per game | Slowdown (r = 1) | Slowdown (r = 0.5) |
|---|---|---|---|---|---|
| Turn-level only (which player) | about 108 | 4 x 8 | 69,000 (L = 20) | 56 | 28 |
| Activation boundary (pick) | about 300 | 3 x 4 | 65,000 | 52 | 27 |
| Activation boundary (pick) | about 300 | 4 x 8 | 173,000 | 138 | 70 |
| Activation boundary (pick) | about 300 | 4 x 16 | 346,000 | 276 | 138 |
| Every own in-turn decision | about 520 | 4 x 8 | 266,000 (L = 16) | 213 | 107 |

All [estimate]. Per searched decision at 4 x 8: 576 engine steps and 1,152 forward rows, in 18 batched calls of 64 rows. A plain decision is one engine step and two rows.

In dollars, at 5 to 7.8 plain games a second and a slowdown of 138: 130 to 200 games per droplet-hour, so a 3,200-game pair is 16 to 25 droplet-hours, $2.60 to $4.10 [estimate].

### Variant (a): root-only rollouts at every own decision inside the own team turn

- Algorithm. At each such decision with two or more legal actions: take the top k joint actions by policy probability; for each, run n rollouts (clone, reseed, apply the action, then both sides play from the policy under m1 until the searcher's `turns_completed` counter rises or the match ends); score each rollout by its n-step return; play the action with the best mean.
- The stop signal is the engine's own monotonic counter, bumped at exactly the two places a team turn ends, including a touchdown that unwinds the turn [code: `engine/src/proc_turn.c:84-85`, `engine/src/proc_match.c:954`; `bb_match.h:130-139`].
- Knobs: k, n.
- Cost: slowdown about 107 to 213 at 4 x 8.
- Weakness: most of the extra decisions are single STEPs with many near-equal squares. The gaps there are far below what 8 or 16 rollouts can resolve, so the argmax is noise there and the cost is wasted or harmful.

### Variant (b): turn level

- As written in the brief ("sample k whole-turn continuations, keep the best by value") it is invalid: a maximum over single dice samples (item 3 above).
- The valid form: at each turn-level decision sample k x n whole-turn continuations from the policy, group them by first action, average within groups, play the best group's first action. That is variant (a) at turn-level decisions only, with candidates chosen by sampling, which spends most rollouts on the policy's favourite and leaves alternatives with one or two samples.
- With top-k candidates in place of sampled ones it is the first row of the table: the cheapest scope, slowdown 28 to 56.
- Weakness: it can only reorder activations. The measured deficits are not in the order. Under m1, 2.5 of chain 55's 6.8 activations per team turn are empty (the first choice after the declaration is END_ACTIVATION), and it picks 0.62 block targets per team turn against a human 2.5 [ledger: D421 diagnostics; human figure given]. Those are decided at DECLARE and at the first choice after it, which this scope never searches.

### Variant (c), the pick: activation-boundary rollouts with a deviation test

Scope, fixed by design and not a knob: own decisions inside the own team turn that are one of
1. the turn-level choice (an ACTIVATE is legal),
2. the DECLARE choice,
3. the first own decision after the own DECLARE (the harness already tracks this flag for mask m2 [code: `policy.py:415`, `:449`]).

Algorithm at such a decision, for the seat's policy under m1:
1. Draw `a0` from the policy exactly as plain play does, with the seat's own generator [code: `policy.py:224-271`, `:444-450`]. This is the action plain play would take.
2. Candidates: `a0` plus the k - 1 other legal joint actions with the highest policy probability. If there is one legal action, play it and stop.
3. For each candidate and each rollout index j in 1..n: clone with rollout dice seed j, apply the candidate, then roll forward. The searcher's side samples from its policy at T=1 under m1 with search generator j. Opponent decisions come from the opponent model. Both views are forwarded every step. Stop when the searcher's turn counter rises, at the end of the match, or after 200 steps.
4. Rollout return: `G = sum of gamma^t * r_t + gamma^T * V(s_T)`, with r the searcher's training reward, gamma 0.999, V the searcher's value output on the first observation after the stop, and no bootstrap at the end of the match.
5. For each other candidate, the paired difference `d_j = G_j(a) - G_j(a0)` over the n shared rollout indices, its mean and standard error.
6. Deviate to the candidate with the largest mean difference only if that mean exceeds delta and exceeds two standard errors. Otherwise play `a0`.

Knobs, three: k (4), n (8, 16 or 32, set by the pilot), delta (0.02 in reward units; a touchdown is 0.4).

Why this one:
- It searches where the measured deficits are decided (empties, blocks, order) and nowhere else.
- "When in doubt, play the policy" makes spurious deviations rare, which is what a noisy 8-rollout estimate needs. The best published precedent for a rollout search on top of an RL policy does the same (SPARTA, section 6).
- With delta set to infinity the seat computes everything and never deviates, so its games must be the plain m1 games action for action. That is an end-to-end identity test of the plumbing that no other variant offers: recurrent state untouched, real dice untouched, generator consumed as before.
- It is the same machinery as (a) and (b). Widening or narrowing the scope later is a constant, not a rewrite.

### Variant (d), a free rider measured in the pilot: one-step value lookahead with no rollouts

- At dice-free decisions (ACTIVATE and DECLARE usually are; a negative trait can roll) apply each candidate on a clone, forward once, and compare `r + gamma * V(s')`.
- Cost: k forward rows per searched decision, a slowdown near 1.2.
- It leans entirely on the value head separating near-identical states. Its errors are correlated across sibling states, so differences may be better than the absolute fit suggests, or it may be noise. [hypothesis]
- The pilot scores it offline against the high-rollout truth. If it agrees, it is a nearly free play-time option of the m1 kind.

### Not in the probe

Deeper trees with chance nodes, sequential halving, candidates stratified by action type, rollouts through the opponent's turn, a C rollout kernel, an outcome head. All are on the ladder in section 5.

## 3. Known ways this goes wrong

Each with whether it is cheap to test before a gate.

| # | Failure | Mechanism | Guard in the design | Cheap test |
|---|---|---|---|---|
| 1 | Wrong score | Value-only scoring drops reward banked inside the rollout | n-step return with the pinned training manifest | Unit test on a scripted touchdown rollout: return rises by 0.4 x gamma^t. Yes |
| 2 | Value error at turn boundaries | V was trained on-policy (explained variance 0.92 on chain 37's first panels [ledger: `DECISIONS.md:1763`]; not measured for chain 55 or on boundary rows). After searched play the states drift, and the value loss weights waiting rows in a way I did not verify | Rollouts stop where the policy's own play would also be: the candidates are the policy's top k | Pilot D3: compare V at the stop with a 64-rollout estimate that continues to the end of the next own turn. Yes |
| 3 | Optimism from a maximum over noisy means | Best of k means is biased up by about one standard error at k = 4 | Paired test against `a0`, margin delta, two standard errors | Pilot D2: re-estimate every n = 8 deviation with 256 fresh rollouts; count deviations whose true gain is zero or less. Yes |
| 4 | Risk mispricing | A maximum over single dice samples is risk-seeking | Each candidate is a mean over n independent dice streams; nothing is ever chosen from one sample | By construction; D2 also shows it |
| 5 | Peeking at real dice | A session copy carries the real stream | Clone entry point always reseeds and refuses stream 1 | Unit tests T2, T2b; pilot canary D5 with a positive control. Yes |
| 6 | END_TURN habit inside rollouts | Without m1 the rollout policy ends the turn after about 3 activations [given], so a rollout models a turn the masked seat will not play | m1 on the searcher's side inside rollouts, same as at the root | Oracle test T6 would diverge without it. Yes |
| 7 | Cost blow-up | D x k x n x L | Narrow scope; skip single-action decisions | Pilot measures the slowdown before the gate. Yes |
| 8 | Proxy over-collection | Search maximizes shaped return harder than the policy | None in the probe; the gate is the judge | Pilot behaviour table: turnovers, rushes and carrier advance per turn against the control. Partly |
| 9 | Opponent model mismatch | Held-out opponents are other networks; the bot is not a network | Rollouts stop at own turn end, so only reactive choices are modelled | The bot pair is descriptive. Not cheap to isolate |
| 10 | Common random numbers buy little | Different first actions consume dice in a different order, so shared seeds decouple quickly | None needed; pairing is free | Pilot D4: paired against unpaired variance. Yes |
| 11 | Candidate set misses the fix | Top k by joint probability can be four squares of one action type | k = 4 includes END_ACTIVATION and the top alternatives in the empties case | Pilot D1 by decision class. Yes |
| 12 | Reward config changes the game | Switching the manifest on in the real session | Reward code writes only reward and telemetry fields (read, section 1.5) | Test: same seed and actions with and without the manifest give the same digest trail. Yes |
| 13 | Shallow gain | Fixes only what the reward or V already prices (item 7 of the first section) | None | Only the gate's held-out contrasts answer it |

## 4. A first experiment that can be pre-registered

### Players

- **C** = chain 55 (`f6ba3b44...` [ledger: D419]) + m1. The usual control, already measured under m1 against chain 37 (+215.5), chain 46 (+202.9) and the offense bot (+110.7) [ledger: D421 pairs 3, 6, 11].
- **S** = chain 55 + m1 + search, variant (c), k = 4, delta = 0.02, n fixed by the pilot rule below, reward manifest `r0_poss_half` by file hash, gamma 0.999, opponent model = own network under m1.
- Held-out: chain 37 (`268f1db0...`) and chain 46 (`8eee9ac1...`) [ledger: D420], played plain.

Why chain 55 and not chain 49 or 57: it is the control of every open gate, it has the most m1 reference pairs, and a search result on it can be set beside what one more 3B rung bought on the same parent.

### Pilot (before any gate plan is hashed)

Seed block 25000000 (free by my reading of the ledger, which uses 22000000 to 22800000, and of the mask docs, which use 23000000 to 24900000; confirm at registration). 32 games per worker, T=1, kick-off starts, both legs. One droplet, plus the Mac at low load for step 1.

1. **Identity.** S with delta = infinity against chain 37, and C against chain 37, same seeds.
   - Mac, 1 game per worker, 10 seeds: 20 of 20 games with identical action trails. Required.
   - Droplet, 100 seeds: at least 199 of 200 identical action trails and identical W/D/L (batched forwards flip about one knife-edge game in 1,200 [ledger: `batched-tournaments-2026-09-17.md:13-22`]). Required.
2. **Cost and sanity.** S against C (S with sampling offset 1), 200 seeds, 400 games, k = 4, n = 8.
   - Required: every game natural, every integrity counter zero, real forwards equal to engine steps for both seats.
   - Measured: wall slowdown, rollout steps and forward rows per searched decision, deviation rate by decision class, and the D421 behaviour table (activations, empty activations, block targets, turnovers per team turn, touchdowns per game) for both sides. Decisive-Elo is printed and gates nothing (the interval is about plus or minus 55 at 400 games [estimate]).
3. **Temperature baseline.** Chain 55 + m1 at T = 0.5 (offset 1) against C, 3,200 games. Plain speed, a few cents. Descriptive: it says how much of any search gain is sharpening.
4. **Offline diagnostics** on 1,000 root states drawn from C's side of step 2's games (every k-th in-scope decision, all three classes, plus a sample of STEP, CHOOSE_DIE and re-roll decisions for the map only):
   - **D1 headroom.** With n = 256 for each of the top 4: the share of states where some candidate beats `a0` by more than delta and two standard errors, by decision class.
   - **D2 rule quality.** Apply the deviation rule at n = 8, 16 and 32 on resampled rollouts; judge each deviation by the n = 256 truth. False-deviation rate and mean true gain per searched decision.
   - **D3 boundary value.** V at the stop against a 64-rollout continuation to the end of the next own turn: mean difference and correlation.
   - **D4** paired against unpaired variance of the differences.
   - **D5 no-peek canary.** For the first dodge, rush or pickup roll after an action S chose in step 2, realized success against the pre-roll probability from the shim's own helper [code: `bbplay.c:465-478`]. The same statistic for a deliberately peeking test seat on 50 games, never used elsewhere, must fail it.
   - **D6** variant (d)'s ranking against the n = 256 truth on dice-free decisions.
   - **D7** depth: stop at end of activation against end of turn, each judged by D3's deeper estimate.

Go rules, fixed now:
- Identity required as stated. A miss is a bug; nothing else is read until it is fixed.
- D5: realized minus nominal within three standard errors for S, and outside for the positive control.
- D1: headroom in at least 2% of in-scope states. Below that the search has nothing to find under this evaluator and the gate is not played.
- n is the smallest of 8, 16, 32 with a false-deviation rate of 25% or less and a positive mean true gain whose interval excludes zero. If none qualifies the gate is not played.
- D3: if the mean difference exceeds 0.02 in absolute value or the correlation is under 0.8, the gate is not played at this depth; a new entry decides.
- Cost: go if one 3,200-game search pair is at most 48 droplet-hours.

Pilot cost: about 600 searched games (3 to 5 droplet-hours), the diagnostics (1,000 states x 4 x 256 rollouts x 18 steps is 18 million rollout steps, about 1 droplet-hour), and one plain pair: $1 to $2 [estimate].

### Gate

Statistic and acceptance as in D418: decisive-Elo with 95% seed-cluster intervals; paired contrasts by `paired_contrasts.py` (sha256 `722ece95...`, 2,000 replicates, generator seed 0); kick-off starts, both legs, 3,200 naturally completed games per pair, 32 per worker, T=1; plan file hashed, committed and pushed before any shard is launched; scored only after acceptance against that plan with every integrity counter zero [ledger: D418, D419 process change]. Acceptance also checks each player's mask and search settings in the manifest and on its side of every game, as D420 item 1 did for masks. `tools/gate_acceptance.py` requires sample mode at temperature 1 for every checkpoint player [code: `tools/gate_acceptance.py:53-57`, `:84-89`]; the search seat keeps both, because its `a0` is a T=1 sample.

Seed block 25100000. Pairs:

| # | Pair | Role |
|---|---|---|
| 1 | S (offset 1) against C | label |
| 2 | S against chain 37 | label contrast |
| 3 | C against chain 37 | label contrast |
| 4 | S against chain 46 | label contrast |
| 5 | C against chain 46 | label contrast |
| 6 | S against the offense bot | descriptive |
| 7 | C against the offense bot | descriptive |

Contrasts: S minus C against chain 37 and against chain 46 (label); against the offense bot (descriptive, since the bot is not what the opponent model assumes).

Labels, applied in this order to accepted evidence only:
- **Negative:** pair 1's interval entirely below zero.
- **Positive:** pair 1's point estimate above +40 with its interval entirely above zero, and both held-out contrasts with intervals entirely above zero.
- **Flat:** pair 1 within plus or minus 40 inclusive.
- **Inconclusive:** anything else.
- Unread: missing, unaccepted or integrity-invalid evidence; a shard aborted on the 4,096-decision cap (D420).

Consequences:
- Positive: this search setting becomes a play-time option like m1, and the measured slowdown is recorded with it. A second entry designs its use as a teacher and the C kernel. Adoption as the evaluation agent needs a second Positive on another checkpoint (chain 49).
- Flat or Negative: one escalation is allowed, registered before it is played: same scope, n times 4. If that is also Flat or Negative, rollout search on this evaluator is closed until the evaluator changes (an outcome head).
- Inconclusive: the contrasts and the behaviour table are reported; no escalation without a new entry.

Registered diagnostics, not gates: the D421 behaviour table for S and C in pairs 1 to 5; deviation rate by decision class; mean predicted gain at deviations; wall slowdown.

Written down so it cannot be adjusted later: my point guess for pair 1 is about +30, with +10 to +60 plausible, so the single most likely label is Flat, then Inconclusive. I expect the held-out contrasts to carry over better than a training rung's do, because the search is not trained against any opponent. [hypothesis]

Power: a 3,200-game pair has an interval half-width of about 14 Elo and a contrast about 21 to 23 [ledger: D421 tables]. A true transfer gain under about +25 will not clear both contrasts.

Cost [estimate]: four search pairs (1, 2, 4, 6) at 16 to 25 droplet-hours each for n = 8 is 64 to 100 droplet-hours, $11 to $17; double for n = 16, four times for n = 32. Three plain pairs add about ten cents. On six droplets that is 11 to 17 hours of wall-clock at n = 8. Dropping the bot pairs saves a quarter. If the wall-clock is the problem, play pairs 1 to 5 at 1,600 games first as a registered screen with no label, then complete to 3,200; I would rather wait and keep one size.

## 5. Implementation plan, as a milestone ladder

Branch from `feat/play-masks-20261005` (`7d0d547`), because the search needs m1 and the activation log. Its own worktree, removed when the branch is pushed. The main checkout at `b0099fb` is not touched.

**M1. Native surface (about 120 lines of C, 50 of Python, 200 of tests).**
- `play_harness/native/bbplay.c`: `bbp_clone_for_search(s, seed, stream)` (the first lines of `bbp_peek_legal`, then `bb_rng_seed`, refusing stream 1); `bbp_copy_into(dst, src, seed, stream)` to reuse an allocated clone; `bbp_free_clone`; a create variant that takes the full reward coefficient table and runs `bbe_validate_reward_config`; `bbp_test_copy_dice(dst, src)` for tests only. ABI version 4 to 5 [code: `bbplay.c:19`, `play_harness/engine.py:22`].
- `play_harness/engine.py`: signatures and `Engine.clone_for_search`, `Engine.rewards`.
- `play_harness/tests/test_native_config.py`: the reward mirror now covers every coefficient.
- Tests:
  - T1 clone fidelity: a clone given the same dice (test hook) and the same actions matches the source's digest, observations, masks and legal list for 2,000 steps over 20 seeds; nothing done to a clone changes the source's digest.
  - T2 no real dice: two roots that differ only in the real stream state (scrambled through the test hook) give bit-identical rollout returns.
  - T2b the clone's stream bytes differ from the source's after cloning; stream 1 is refused.
  - T8 a rollout across the end of the match returns the terminal reward and no bootstrap, and a terminal clone refuses further steps.
  - T9 the real session's stalling counts are the same with and without clone stepping.
  - T12 reward independence: same seed and actions with and without the manifest give the same digest at every step.

**M2. Rollout core (about 250 lines, 200 of tests).**
- `play_harness/search.py`: `Rollouts`: a batch of clones with their two recurrent states each; one batched forward of both views per step; m1 through the existing `restrict_support` [code: `policy.py:357-392`]; selection through the existing `select_joint`; reward accumulation; the stop rule; joint action probabilities for candidate ranking.
- Tests:
  - T6 oracle: given the real dice and generators through the test hooks, one rollout reproduces the next real steps of a plain m1 game exactly, to the end of the turn, on 20 roots.
  - T3 the seat's recurrent state tensor and generator state are equal before and after a search.
  - T1r the scripted-touchdown return test of section 3 row 1.
  - T13 the opponent seat replaced by a raising object: the search still runs.

**M3. Seat and tournament wiring (about 250 lines, 150 of tests).**
- `play_harness/search.py`: `SearchSeat(MaskedPolicySeat)`: the shadow opponent-view state, the scope test, the deviation rule, per-game search statistics.
- `play_harness/tournament.py`: a `search` entry in the player spec and `--search NAME=k:n:delta`; seat construction in `Match` [code: `tournament.py:230-249`]; engine created with the reward manifest when a seat searches [code: `:259`]; manifest and record fields; the resume check refuses a changed setting [code: `:1118-1122`]. Real forwards stay one per engine step per seat; search forwards are counted separately.
- `tools/droplet_tournament.py` passes extra tournament arguments through already [code: `tools/droplet_tournament.py:172-188`]; add the flag to its checks and tests (about 30 lines).
- Acceptance: the plan-level check of search settings beside the mask check.
- Tests:
  - T4 identity: delta = infinity gives the plain m1 game's action trail, digest and log-probability sum on 10 seeds, unbatched.
  - T5 determinism: the same seed and settings give the same record, search statistics included, on two runs and at two worker counts.
  - The batched path gives the same games as the unbatched one. The mask branch has a test of that name for masked games [code: `play_harness/tests/test_masks.py:219`, name only; body not read], and the batching doc describes the row-wise test policy that removes float rounding [ledger: `docs/play-harness/batched-tournaments-2026-09-17.md:281-289`].

**M4. Pilot (a diagnostics tool of about 300 lines, then the runs of section 4).** `tools/search_probe_diag.py`: D1 to D7. The peeking positive control lives under `play_harness/tests/`, not in the package.

**M5. Gate.** Plan, hash, ledger entry, shards, acceptance, contrasts.

Total before the gate: about 950 lines of code and 550 of tests [estimate]. For an agent this is one working session for M1 and M2, one for M3, one for M4, with the oracle test (T6) the likeliest place to lose time.

**Parked, in order of what I would do next if the gate is not Negative:**
1. A C rollout kernel: batch stepping, exact joint sampling in C checked against `select_joint` (there is a C sampler reference at `play_harness/tests/native_sampler_ref.c`), observation batches written in place. Halves the cost or better. [hypothesis]
2. Racing: stop rollouts for candidates more than two standard errors behind (SPARTA reports a tenfold saving [lit]), or sequential halving (Gumbel [lit]).
3. Wider scope by the pilot's map (re-roll and block-die choices first).
4. Depth through the opponent's turn, which needs a real opponent model.
5. An outcome head as evaluator.
6. Search as a teacher. The torch trainer already has an imitation-regularized path [code: file `training/torch_pufferl_bcreg.patch` exists; not read]. A million searched decisions is about 3,000 games, a few dollars. [estimate]
7. The larger-budget agent for human games.

## 6. Literature, kept to what changes the design

- **Tesauro and Galperin, "On-line Policy Improvement using Monte-Carlo Search" (NeurIPS 1996).** Root-only rollouts with the base policy in backgammon, the direct ancestor of variant (a). Error rates fell by a factor of 5 or more for base players up to TD-Gammon. Truncated rollouts (a few steps, then the network's value) gave an order of magnitude speed-up. They estimate about 10,000 trials per candidate to resolve differences of 0.01, cut to tens of thousands per move by statistical pruning. *Design effect:* truncate at the turn boundary with the value head; expect 8 to 32 rollouts to fix only large errors; add pruning later. https://arxiv.org/abs/2501.05407 (reissue of the 1996 paper)
- **Lerer, Hu, Foerster and Brown, "Improving Policies via Search in Cooperative Partially Observable Games" (AAAI 2020), SPARTA.** Rollout search on top of an RL policy. At least 100 rollouts per action; rollouts for an action stop once it is more than two standard deviations behind the best, a tenfold saving; the agent deviates from the blueprint only if the gain exceeds a threshold (0.05 of 25 points). Hanabi self-play 24.08 to 24.61. The summary I read does not say how they handle the blueprint's recurrent state. *Design effect:* the deviation rule in variant (c). https://arxiv.org/abs/1912.02318
- **Gray, Lerer, Bakhtin and Brown, "Human-Level Performance in No-Press Diplomacy via Equilibrium Search" (ICLR 2021).** Candidates are the policy's top actions; each is scored by rolling the policy out 2 or 3 phases and then reading the value network; no gain from rolling out further than 3 or 4 phases; 20.2% to 52.7% against blueprint agents; minutes per turn. *Design effect:* candidates from the prior, short rollouts, value at the cut. https://arxiv.org/abs/2010.02923
- **Danihelka, Guez, Schrittwieser and Silver, "Policy improvement by planning with Gumbel" (ICLR 2022).** AlphaZero's root selection can fail to improve the policy with few simulations; sampling candidates without replacement and sequential halving fixes that. *Design effect:* the parked allocation rule. https://iclr.cc/virtual/2022/poster/6418
- **Antonoglou et al., "Planning in Stochastic Environments with a Learned Model" (ICLR 2022), Stochastic MuZero.** Deep trees in stochastic games need chance nodes and afterstates. *Design effect:* none for a root-only search, where averaging rollouts is the chance node; it is why a deeper tree is not in the probe. https://iclr.cc/virtual/2022/poster/6832
- **Justesen et al., "Blood Bowl: A New Board Game Challenge and Competition for AI" (CoG 2019).** Turn-wise branching factor about 10^50. In their Python engine the game state was "slow to clone" and "tree search is possible, but not very feasible". *Design effect:* that obstacle is gone here (a 2,240-byte copy). https://njustesen.github.io/njustesen/publications/justesen2019blood.pdf
- **Bot Bowl II results page.** Sapling, an MCTS bot with a scripted heuristic, finished 1 win, 20 draws, 39 losses with one touchdown. Gotebot, a learned bot, carried two scripted rules, one of them "never end the turn with unused players left", which is m1. https://njustesen.github.io/botbowl/bot-bowl-ii.html
- **botbowl MCTS tutorial.** With random rollouts, "MCTS is better when we don't do rollouts" on medium and large boards, because random actions fail dodges. *Design effect:* rollouts must use the trained policy, and the evaluator must be learned. https://njustesen.github.io/botbowl/mcts.html
- **Pezzotti, "MimicBot" (2021), Bot Bowl III winner.** Imitation then RL, no search; block-die and re-roll choices are scripted. Notes that the game's randomness "act[s] as a confounder for Monte-Carlo based methods". https://arxiv.org/abs/2108.09478
- I found no published Blood Bowl agent that searches with a trained policy and value. AlphaZero-style search is not directly usable: dice at every action, and about 10^50 turn-level actions.

## 7. Not verified

- `sizeof(bbp_session)` and every timing. Nothing was built or run.
- The rollout step cost, L, D and so every slowdown and dollar figure in sections 2 and 4.
- The per-droplet rate of m1 games (derived from three cost lines in the ledger and an assumed 5 minutes of overhead).
- That the value loss covers waiting rows. The telemetry patch says the loss averages include waiting rows [code: `/Users/alexanderhuth/Code/bb-opt-build/training/puffer_deciding_row_telemetry.patch:55-56`]; I did not read the trainer.
- That chain 55 was trained on `r0_poss_half` at gamma 0.999. The ledger says so for the rung family (D422) and the brief gives gamma; the lineage sidecar carries only hashes.
- That the reward configuration cannot change a game. Read, not tested (test T12).
- The value head's fit for chain 55 and at turn boundaries. The 0.92 is chain 37's first panels.
- Whether one checkpoint at T below 1 has been played against itself at T=1. I searched `DECISIONS.md` and the play-harness docs and did not find it.
- That seed blocks 25000000 and 25100000 are free.
- How many droplet slots other projects hold today.
- Which decisions roll dice at ACTIVATE or DECLARE (negative traits), which matters for variant (d) only.
- The Bot Bowl 2022 result (a scripted winner) is from a search summary of a secondary page, so it is not cited above. SPARTA's numbers are from a machine summary of the ar5iv text, not my own reading of the PDF.
- The line numbers are from the mask worktree at `7d0d547`. The same files in the training worktree and on the rig's build may be offset by a few lines.

## 8. Changes after the Codex review (2026-10-07)

The review found the clone design sound and said milestones M1 to M3 can be built with the safeguards below. It found the pilot's statistical go rules too weak to register as written. Nothing in this section has been tested.

**Deviation rule and pilot rule D2 (blocking for registration, not for the build).**
- "Two standard errors" does not make deviations rare at 8 rollouts. With Gaussian differences a one-sided test at 7 degrees of freedom passes about 4.3% of the time per alternative, about 12% across three. With skewed returns it can be far worse: a zero-mean difference of +0.04 nine times in ten and -0.36 once has all eight samples positive 43% of the time, and then the sample standard error is zero. That example is an illustration, not an estimate of this policy's rate.
- So the rule's standard error gets a floor from the pooled per-rollout variance of all candidates at that decision, n = 8 is dropped as a setting unless the pilot shows it safe, and D2 is judged with fresh, independent reference rollouts, an upper confidence bound on the false-deviation rate of 10% or less (not a 25% point estimate), a lower bound above zero on the mean gain, intervals clustered by game, and a held-out split of states after n is chosen. The n = 256 estimate is a reference with its own error, not the truth.

**The value target (blocking for reading the pilot).** The study's citation for "the value loss covers waiting rows" is a telemetry comment about entropy, KL and clip fraction, not the value loss. Before the pilot is interpreted, the pinned trainer's reward storage, GAE and value target, row routing and recurrent resets are read from the trainer source (`/Users/alexanderhuth/Code/pufferlib-pr` and the rig's `vendor/PufferLib`), and gamma's application per engine step is confirmed there.

**The value target, read from the trainer (2026-10-07 02:55 PDT).** This closes the "blocking for reading the pilot" item above. A read-only agent read a local PufferLib 4.0 tree with the project's patch files, and the operator then read the same kernel in the source that ran chain 55, on the rig (`vendor/PufferLib/src/pufferlib.cu` in the b3 checkout).
- The advantage is GAE(gamma, lambda) with V-trace clips at 1.0, per agent row over consecutive buffer steps: `delta = rho * (r[t+1] + gamma * V[t+1] * nonterminal - V[t])` (rig source line 1533), and the value target is the stored value plus that advantage (line 1632). Chain 55's stage manifest records gamma 0.999 and 4-byte precision.
- One buffer step is one env step, which is one applied decision by either side with all dice up to the next decision. Both teams' rows get a reward and a value on every step, waiting rows are in the value loss, and nothing is skipped for the waiting team. So gamma steps once per env step for the searching seat, on its own decisions and the opponent's alike, as the study assumed.
- The value output is one linear column in raw shaped-reward units. There is no return normalisation, symlog or two-hot transform to invert. Rewards are hard-clamped before the target, and the project's integrity rule requires that clamp to change nothing.
- The reward that arrives with the first step after the root is undiscounted, which is the study's `t = 0` term.
- At the end of a match the env rebuilds the terminal reward (touchdown objective, result bonus, potential payback, with incidental shaping on that step suppressed) and the target has no bootstrap. A match cut at the decision cap takes the same path. A rollout must therefore take the env's own emitted reward on the final step and add no value.
- Only learner rows train the value head, each from its own team's observation and reward.
- Two limits on the value as a leaf score: it estimates the learner's on-policy return against its training opponent mix, not a minimax value; and in training the recurrent state is zeroed at the start of every 64-step segment, while at play time it persists for the whole match, as it already does for plain play in the harness.
- Not read: the Torch backend, which the native trainer does not use.

**Build safeguards (M1 to M3).**
- The match struct holds already-realized dice results; "dice-free" means it holds no future dice stream. `bb_rng_seed` clears the script and sink pointers, so a reseeded clone has no route back to the real stream.
- Save and restore the thread-local stalling attachment on every exit path of every clone call, failures included.
- A clone that reaches the end of the match stops and is never bootstrapped from the reset observation (the terminal reset reseeds from the copied seed).
- The rollout return is the searching seat's own reward read on every engine step, opponent decisions included, indexed by physical team. The shaped reward is not zero-sum (distance terms are paid independently), so the opponent's reward is never negated or summed in.
- Test T12 also compares observations, legal support, cache validity and bookkeeping with and without the reward manifest, not only the match and dice digest.
- Test T6 (the oracle rollout) is specified on a same-network game with matching opponent-view history, masks and generators; it cannot reproduce a different network's choices.
- Identity can still differ through batch-size rounding, batch membership, tensor aliasing, mask bookkeeping or reward initialisation. Bitwise equality across worker counts is claimed for the row-wise test policy only.
- A rollout that hits the 200-step cutoff is bootstrapped and counted; engine errors and decision-cap endings are rejected, not treated as natural ends.

**Gate design, for the registration entry.**
- Acceptance must check, per game, the reward manifest hash, gamma, scope, candidate construction, opponent model, sampling offsets and rollout integrity, beside masks.
- A T = 0.5 control goes inside the gate, with direct and held-out pairs, if the claim is that search adds value beyond sharpening. The likeliest misleading Positive is reduced sampling noise read as tactics.
- The +40 Positive threshold is the training gates' convention and is not required for a play-time option. The entry sets a minimum worthwhile gain tied to the measured slowdown.
- The one allowed escalation (n times 4) gets its own seed block, acceptance, labels and cost ceiling fixed in advance. Two failures close this setting, not all rollout search on this evaluator.
- D3 compares the value at the stop with discounted rewards through the deeper horizon plus that horizon's bootstrap, with uncertainty, and is not a veto on correlation alone. The likeliest misleading Negative is a noisy D3 veto.
- D5 measures the first raw roll, with no re-roll substitution and no selection on survival. Offline roots store the full env, both recurrent histories, the root logits and `a0`.

**Cost, restated.** At n = 8 the four searched pairs are 63 to 98 droplet-hours, $10.5 to $16.4. At n = 32 they are 251 to 393 droplet-hours, $42 to $66. The pilot's diagnostics cost more than the 18 million rollout steps counted in section 4.

**Corrections from the operator.** The droplet limit on the account is 15, with 5 held by other projects on 2026-10-07. Chain 55's stage manifest on the rig confirms `r0_poss_half`'s coefficients and gamma 0.999 on the trainer's command line. Seed blocks 25000000 and 25100000 appear nowhere else in the ledger, the plans or the play-harness docs.

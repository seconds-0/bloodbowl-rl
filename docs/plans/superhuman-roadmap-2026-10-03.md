# Toward a superhuman Blood Bowl bot: where we are and the next three steps (2026-10-03)

**Status: proposal for the owner. Nothing here is registered until a DECISIONS.md entry says so.**

The owner's goal, 2026-10-03: "do the stuff for more human looking play. ultimately i want a super human bloodbowl bot". This page turns that into a milestone ladder. It rests on four research threads run the same morning (human replay inventory, trainer design for a human-prior term, literature and prior art, a matched style panel). Their reports are summarized here; the style panel is in `docs/style-panel-2026-10-03/` and `tools/style_panel.py`.

## Where the policy is, measured

Per game, one team. Human numbers are the BB2025 replay subset (11,580 games). Policy numbers are the policy's own side.

| | Humans | Chain 9 | Chain 30 | Chain 36 | Chain 37 |
|---|---|---|---|---|---|
| Touchdowns, against frozen ancestors (estimated) | 1.10 | 1.04 | 1.29 | 1.48 | 1.51 |
| Touchdowns, against the scripted bots | | 0.53 | 0.56 | 0.55 | 0.56 |
| Resolved blocks, against the scripted bots | 40.1 | 6.0 | 4.6 | 5.9 | 6.3 |
| Passes plus hand-offs | 1.59 | 0.001 | 0.008 | 0.004 | 0.004 |
| Possession (both teams pooled) | 0.475 | 0.361 | | | 0.367 |

- **Style has not moved since chain 1.** Blocks have wandered between 4.6 and 8.2 a game with no direction; passing has never been above 0.008.
- **Strength against its own family keeps rising** (chain 34 +53 and chain 36 +77 decisive-Elo over their parents), and against the two scripted bots it has been flat for the whole lineage (0.53 to 0.56 touchdowns a game).
- **There is no measurement against a human at all.**
- Counting caveats are in the panel's own header: red-dice blocks are booked to the defender's side (about 0.5 a game), and most counters other than touchdowns and blocks are logged for both teams together.

## What the research changed

1. **A human prior is not the first move.** Three independent reads say so.
   - The usable human data covers only the opening. The replay-to-engine alignment stops at the first divergence, so every record is in half one and 83% are from turns 0 to 2. A prior trained on that is extrapolating for the rest of a match.
   - The data does not exist in today's format, and the alignment tool has not been updated since June.
   - The ledger has two negative results: an imitation anchor at full strength took offense to zero (D176, which also recorded "do NOT build KL-to-frozen"), and the best imitation net wins no decisive games against any RL checkpoint (D98).
   - Humans attempt about one pass per team per game. A human prior cannot create a passing game; it could pull early-turn play toward blocking.
   - In two-player zero-sum games human data is not required for superhuman play. It helps where exploration is hard (AlphaStar's ablation: 1,020 to 1,400 Elo from a KL-to-human term), and it is the standard fix for an agent stuck in a basin.
2. **Low blocking is a symptom to test, not a style to copy.** Nothing the policy trains against punishes a team for not blocking. The cheap test is an exploiter and a stronger opponent mix, not imitation.
3. **The opponent pool has a known defect that costs nothing to fix.** The newest checkpoint never plays as a frozen opponent, because the scripted bot takes its seat, and a quarter of frozen games go to an anchor the learner beats nine times in ten. A plan-only preflight on the rig shows the bot can take the anchor's seat instead with no code change and the same pool files.
4. **Search is the usual route past the policy's own strength**, and the cheapest version needs no training: at each decision, roll the policy forward to the end of the turn for the top few candidate actions under shared dice, score with the value head, keep the best. Its cost is network inference, not engine speed.
5. **Nobody has a human-level Blood Bowl bot.** Bot Bowl ran 2016 rules with one roster; scripted bots won four of five editions. There is no bar to copy and no ladder that accepts a bot today.
6. **Compute is the biggest risk.** Every superhuman result the literature thread found used far more than one GPU.

## The ladder

Each milestone names what it must show before the next one starts. Rig rungs are about 8.7 hours.

**M1. Yardsticks and the free fix (now, mostly off the rig).**
- The style panel next to every gate result (done: `tools/style_panel.py`).
- One paired rung on the rig: the scripted bot takes the anchor's seat, so chains 30, 34 and 36 are all active opponents. Control: chain 40 (same warm start, seed and pool files). Normal gate plus the style panel.
- An exploiter probe: a fresh rung trained only against frozen chain 36, to learn how beatable it is. One rung, scheduled after the paired rung.
- You play five games against the current best in the browser harness. That is the first human data point and costs no compute.
- *Exit:* the pool arm has read; the exploiter's win rate is known; you have an opinion on what feels wrong.

**M2. Search probe (off the rig, droplets).**
- Root-only search in the play harness for one side, about 8 candidates and 64 leaves per decision, against the raw network on paired dice.
- *Exit:* more than +50 decisive-Elo over the raw network at a cost we can afford per game. If yes, search becomes both the evaluation-time agent and a teacher for training. If no, we know search is not cheap for this game and say so.

**M3. Human data, done properly (CPU first, rig later).**
- Deepen the replay alignment so replays cover whole halves, not openings. Each divergence class fixed lengthens thousands of replays. This is also what makes a human-imitation agent usable as a fixed anchor in the ladder.
- Offline check before any trainer work: on chain 36's own game states, does the human-imitation net put clearly more weight on blocks and blitzes than chain 36 does? If not, stop.
- Only then the trainer term: a small penalty toward the human net, in the direction that punishes missing human behaviours, decayed to zero, in the loss and not the reward. Paired against a plain control. About 6% throughput and under 0.5 GB of GPU memory by estimate.
- *Exit:* blocks move toward human in the style panel with no loss in the gate.

**M4. Humans.**
- A pre-registered series in the browser harness against rated coaches: about 200 decisive games detect a 60% win rate. Whether to ask FUMBBL about a bot account is the owner's call.

## What I am doing now, and what needs your word

Running without waiting:
- Chain 38 finishes, then chain 40 (the registered continuation from chain 36) starts on its own.
- A three-minute GPU check, queued behind chain 38, that the bot-in-anchor-seat layout routes correctly on the long-run build.
- A first run of the replay alignment on the 400 BB2025 replays already on the Mac, to see whether the human-data pipeline still works at all and how deep it gets today.

Needs a yes or no from you:
1. **Order.** I recommend M1 then M2, with M3's alignment work running on CPU alongside, instead of going straight to the human-prior rung you approved. Say so if you want the human prior first anyway.
2. **The stage after chain 40.** I plan to register the pool arm there, in place of another plain continuation.
3. **Five games.** `cd ~/Code/bb-play-harness && play_harness/run.sh`, then open `http://127.0.0.1:8790/`.

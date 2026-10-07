# The policy is almost deterministic at most decisions (2026-10-07, exploratory)

**Status: an observation from a few games on the Mac. No plan was committed before it, nothing is registered, Codex has not reviewed it, and it changes nothing on the rig. It is written down because it bears on what the next training lever should be.**

## How it was found

The search gate's smoke (D430) produced one record whose log-probability sum was minus infinity. The search had deviated to a legal action whose probability under chain 55 underflows to zero in a double.

## What was measured

`candidate_logprob_probe.py`: three plain games of chain 55 + m1 against chain 37 (seeds 29920000 to 29920002), at every decision the search would search. Of 1,506 alternative candidates (the three most probable actions other than the sampled one), 92.7% have log-probability below -7, 49.7% below -50, 20.9% below -100 and 0.7% underflow. The logits seen run from -1,207 to +927. Typical cases: after a BLOCK declaration the policy gives END_ACTIVATION log-probability 0 and every BLOCK_TARGET below -680.

`logit_scale_probe.py`: six plain self-play games per checkpoint (seeds 29930000 to 29930005), every own decision of one side with two or more legal joint actions.

| Checkpoint | Decisions | Largest logit magnitude, median (90th percentile, maximum) | Top action above 0.99 | Top action above 0.999999 | Mean entropy, nats | Second action's log-probability, median |
|---|---|---|---|---|---|---|
| chain 25 | 2,066 | 300 (689, 2,126) | 77% | 57% | 0.180 | -20 |
| chain 30 | 2,071 | 265 (549, 2,505) | 78% | 58% | 0.156 | -20 |
| chain 37 | 2,134 | 266 (504, 2,246) | 79% | 61% | 0.175 | -21 |
| chain 46 | 2,003 | 315 (607, 1,640) | 84% | 70% | 0.137 | -33 |
| chain 49 | 2,273 | 291 (591, 2,343) | 87% | 73% | 0.106 | -36 |
| chain 55 | 2,449 | 263 (533, 2,241) | 85% | 69% | 0.112 | -31 |
| chain 58 | 2,465 | 238 (516, 2,458) | 88% | 72% | 0.091 | -32 |

## What it suggests, not established

- At roughly seven decisions in ten the policy never samples anything but its first choice. Training only learns about actions it samples, so at those decisions it cannot find out that another action is better. That would fit three things in the ledger: the plateau near three activations a team turn, exams and gates that barely move from rung to rung, and a search that gains by trying actions the policy all but rules out (D426, and the deviation types of D426: a block in place of ending the activation, another player activated).
- The sharpness is not new. Chain 25 already has it, and it grows slowly along the ladder.
- A lower sampling temperature cannot produce the search's deviations; it makes them rarer.

## What it does not show

- That the saturated first choices are wrong. Many decisions have one sensible action. The share of saturated decisions where an alternative is better is what the search measures: about 1.5% of searched decisions have a large gain.
- That more exploration in training would help. That needs a design and a registered rung: for example a small uniform mix over legal actions in the behaviour policy (the trainer's V-trace clips already correct for off-policy sampling), an entropy floor at decisions with several legal actions, or training on the search's deviations.
- Anything about cause. Six games a checkpoint, one side, self-play, no intervals.

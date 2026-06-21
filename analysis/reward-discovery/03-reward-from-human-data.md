# Agent 3 — Learning a Reward FROM the Human Corpus (IRL / preference / offline inference)

**Bottom line:** For our situation — non-stationary self-play, ~450-way factored discrete actions, a hard "decision-time EV (pre-dice)" constraint, and a goal of *reproducing aggregate human behavior* not copying actions — full adversarial IRL (GAIL/AIRL) is the **wrong tool** (variance-laundering risk + self-play instability). The two that fit: **(a) distribution/moment-matching reward inference (f-IRL-style) to *calibrate* hand-shaped knobs, and (b) a KL-to-human-anchor regularizer (AlphaStar/piKL-style)** — the cheapest, most battle-tested "learned-from-humans during RL" signal, already half-present in our BC warm-start.

## Target 1 — Modern inverse RL
| Method | 1-line | Ref | Tractable for us? |
|---|---|---|---|
| MaxEnt IRL | match feature expectations under max-entropy | Ziebart 2008 | tabular roots |
| AIRL | adversarial IRL; disentangled transferable reward g(s)+γh(s')−h(s) | 1710.11248 | on-policy+adversarial → unstable in self-play; per-step not pre-dice |
| **IQ-Learn** | inverse soft-Q: one Q implicitly encodes reward+policy, no discriminator, no min-max | NeurIPS 2021, 2106.12142 | **most promising IRL family** — stable, offline; r=Q−γ𝔼V |
| ValueDICE | off-policy DICE imitation | Kostrikov 2020 | off-policy plus; DICE finicky |
| **CSIL** | invert the BC policy into a shaped reward+critic prior, refine with RL — bridges BC↔IRL | NeurIPS 2023 spotlight | **best architectural fit** — consumes the BC policy we already have |
| Scalable IRL = TD-reg MLE | inverse-soft-Q as MLE+TD-reg; IRL>BC for retaining diversity while matching the demo distribution, no online data | DeepMind 2024, 2409.01369 | strong evidence IRL>BC for dist-matching; offline sidesteps self-play |
| Pessimistic/offline IRL | conservatism so inferred reward doesn't over-extrapolate off-support | 2024, 2402.02616 | guardrail for fitting to a fixed corpus |

**Self-play tractability:** non-stationarity is a known hard IRL pain point. A 2024 paper handles IRL-from-non-stationary-learning-agents (2410.14135) but is research-grade. **The clean escape all strong 2024 work uses: do reward inference OFFLINE on the fixed corpus (a stationary expert), then bring the *frozen* reward into self-play as an auxiliary term.** 450-way factored actions + 4M-param policy are fine for value/density-based methods.

## Target 2 — Discriminator/GAIL-AIRL as a learned per-step aux reward
**Practicality: low, and it fights our constraint.**
- Failure #1 — decision-time-EV: a GAIL/AIRL discriminator scores *realized* (s,a)/(s,s') transitions → rewards trajectories that *landed* in human-looking states, including via lucky dice = the **post-dice realized-outcome reward we've banned**.
- Failure #2 — adversarial + self-play = two stacked non-stationarities.
- Failure #3 — reward hacking once the policy finds discriminator blind spots.
- **If forced:** only a **frozen, pre-trained, state-only (state-marginal) discriminator** trained offline on FUMBBL states vs bot states, as a small shaping term. Never adversarial online.

## Target 3 — Preference-based reward learning (RLHF-for-agents)
Learn reward from pairwise trajectory-segment comparisons (Bradley-Terry), then RL. Mature (RLHF backbone). Reward model trained offline/async → non-stationarity not the blocker. **The blocker: where do preferences come from?** We have implicit signals: outcome-derived (winning team segment ≻ losing; high-division ≻ low-division — FUMBBL exposes rating/division), human-vs-bot (human segment ≻ bot segment same board). 2025 caveat: "Policy-labeled Preference Learning" (2505.06273) — naive PbRL is biased when segments come from different-quality policies; needs their correction. EV-compatible if scored on pre-dice features. Heavier build than Targets 4/5 for uncertain payoff (you're *manufacturing* labels).

## Target 4 — Offline distributional reward inference matching AGGREGATE stats ★ (closest fit)
| Method | 1-line | Ref | Fit |
|---|---|---|---|
| **f-IRL** | analytic gradient of any f-divergence between agent & expert *state-marginal* density w.r.t. reward params → recovers a *stationary* reward by gradient descent | CoRL 2020/21, 2011.04709 | **single best conceptual match** — state-marginal (not action-copying), stationary reward (survives self-play), few demos |
| SMM | match expert state-visitation distribution via divergence | Lee 2019 | f-IRL is its reward-recovering successor |
| GMMIL / moment-matching | non-parametric MMD between human & agent feature moments — no discriminator, no min-max | 1911.02256 | turns "match these aggregate stats" into a reward; stable |

**Why right for us:** we don't want action-copying (many equivalent moves); we want to reproduce human *aggregate* behavior (block rates, dodge frequencies, ball-handling distributions, screens) — **occupancy/moment matching by definition.** f-IRL outputs a **stationary reward function** → carries into non-stationary self-play (reward independent of current opponent).

**Concrete application:** (1) feature vector φ(s) = the aggregate stats we already validate against; (2) human moment vector 𝔼_human[φ] from the 2.1M pairs; (3) fit reward params θ on a **linear-in-φ reward** r_θ(s)=θ·φ(s) (f-IRL gradient or plain MMD) so a policy optimizing it reproduces 𝔼_human[φ]; (4) because φ is hand-chosen over **pre-dice EV features**, the learned reward is *automatically* decision-time-EV-priced + interpretable — **it doesn't replace the 8 knobs, it *automatically calibrates their weights* to match humans.** Highest-value lowest-risk "learn the reward." (5) Run offline on the frozen corpus, freeze θ, anneal in.

## Target 5 — Game-AI precedents (AlphaStar middle ground)
| Precedent | 1-line | Ref | Relevance |
|---|---|---|---|
| **AlphaStar KL-to-human** | self-play RL from a supervised human-replay policy + a **KL penalty to that policy** held throughout RL | Vinyals 2019 | canonical lightweight human signal during RL; we already have the BC policy — KL-to-BC is a ~1-day change |
| **piKL** | regularize policy/search *toward a human BC policy* (KL) → strong yet human-like; BC-alone can't model strong humans, BC+KL-reg RL can | ICML 2022, 2112.07544 | most transferable precedent for a board-game action space; an anchor, not a learned reward — cheapest path |
| IRL for soccer agents | IRL on relative positional features | 2024 | confirms moment/positional-feature IRL is the live sports-sim approach (= Target 4) |
| Controllable/diverse behaviors | reproduce a *distribution* of human play styles | 2512.10835, 2504.18160 | for style-conditioned bots later (bashy vs agile coaches) |

## Effort vs payoff hierarchy
1. **KL-to-BC anchor (AlphaStar/piKL)** — cheapest, most proven, self-play-safe, no new reward model. Add a decaying KL(π_RL‖π_BC) to the existing BC warm-start. The "lighter-weight middle ground"; **does NOT touch the decision-time-EV reward** (policy regularizer, no laundering risk). **First experiment.**
2. **f-IRL / moment-matching to auto-calibrate the 8 knobs** — medium effort, high payoff, keeps interpretability + EV invariant, offline on frozen corpus. Replaces hand-tuning of weights, not structure.
3. **CSIL / IQ-Learn offline reward recovery** — if you want a genuinely learned (non-linear) reward beyond φ. CSIL most stable, lowest-tuning, consumes the BC policy. Train offline, freeze, anneal in.
4. **GAIL/AIRL online: don't.**
5. **Preference RM: only if** mining implicit win/division/human-vs-bot preferences.

## Genuinely intractable under self-play (be honest)
- Online adversarial IRL in the self-play loop — stationarity violated twice over (policy moves AND opponent moves). MA-AIRL (1907.13220), non-stationary IRL (2410.14135) are research-grade.
- Recovering a *unique* reward in 2-player zero-sum — provably under-determined ("On Feasible Rewards in MA-IRL," 2411.15046). Expect a *behavior-matching* reward (Target 4), not a "true human reward."
- Per-step realized-transition discriminators — incompatible with decision-time-EV unless restricted to pre-dice features (which guts them).

**The unifying move:** infer the reward OFFLINE on the frozen 12.7k-game corpus (stationary expert), constrain to pre-dice EV features, freeze, anneal into self-play — never run reward inference *inside* the self-play loop.

## Sources
IQ-Learn 2106.12142; AIRL 1710.11248; CSIL joemwatson.github.io/csil (NeurIPS 2023); scalable-IRL 2409.01369; pessimism-in-IRL 2402.02616; non-stationary IRL 2410.14135; f-IRL 2011.04709; GMMIL/divergence-min 1911.02256; AIL-via-boosting (ICLR 2024); DRLHP 1706.03741; residual reward models 2507.00611; policy-labeled pref 2505.06273; best-policy-from-pref 2501.18873; piKL 2112.07544; MA-AIRL 1907.13220; feasible-rewards MA-IRL 2411.15046; controllable behaviors 2512.10835 / 2504.18160; self-play survey 2408.01072.

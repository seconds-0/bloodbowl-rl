# Key paper extracts (abstracts/method claims, fetched 2026-06-20)

> Full PDFs not pulled verbatim (arxiv abs pages); these are the load-bearing claims for integration
> decisions. The 01–04 syntheses carry the detailed applicability. Web-fetch the arXiv IDs for depth.

## EA-SEED — Self-Correcting Reward Shaping via LMs (2506.23626)
- Closed loop: an LM proposes **updated reward weights each iteration** from (a) a user-defined
  natural-language behavioral goal + (b) a **summary of performance statistics from prior training
  rounds**. Self-corrects without manual reward engineering. Output = updated weights (NOT code).
- Results (racing task): one iteration 9%→74% success; final LM-tuned 80% / 855 steps vs expert
  94% / 850 steps. Single-agent, not self-play.
- → This is our D113-A statmatch loop formalized; weights = our 8 EV knobs; stat-summary = our
  human-vs-observed metric report.

## GERS — Evolutionary Bilevel Reward Shaping (2606.16236)
- **Lower level:** RL agent guided by an upper-level-shaped reward learns a policy on limited training
  envs. **Upper level:** **CMA-ES optimizes the reward-shaping parameters to maximize the cumulative
  UNSHAPED reward on separate VALIDATION envs.** Scalar feedback only (no trajectory access needed).
- → Swap "validation envs"→"human-replay stat aggregate", "unshaped reward"→"−stat-distance" and this
  is our harness; CMA-ES is the named outer optimizer over the knobs; our warm-start probe = inner solve.

## f-IRL — IRL via State-Marginal Matching (2011.04709)
- Main result: **analytic gradient of any f-divergence between agent & expert STATE-MARGINAL
  distribution w.r.t. reward parameters** → recovers a **STATIONARY reward** by gradient descent that
  makes the policy match the expert state density. Not adversarial. More sample-efficient than GAIL,
  fewer expert trajectories. Recovered reward transfers across dynamics.
- → Fit a linear-in-φ reward over our existing human-stat features so a policy optimizing it reproduces
  human aggregate state statistics; stationary ⇒ carries into self-play; φ over pre-dice EV features ⇒
  auto-respects decision-time-EV + interpretable = **auto-calibrates our 8 knob weights**.

## EvalStop — world-feedback early stop for reward overoptimization (2606.04145)
- Scheduler primitive: **terminate jobs on k consecutive eval-score declines**, release GPUs, preserve
  best checkpoint, delegate to any base scheduler. Frames early-stop as a DETECTION problem on held-out
  eval-score trajectories (training loss "drops monotonically through hacking" → useless).
- Numbers: 98% precision, 99% recall, 1.5% FP; ≥91% precision at noise σ≤0.05; ≥89% across hacking base
  rates 20–80%. 22% wasted-compute reduction.
- → Add to our fleet monitor: stop+keep-best on k=2 consecutive Elo-vs-frozen-anchor drops even while
  shaped reward keeps climbing.

## Potential-based shaping (Ng-Harada-Russell 1999; Wiewiora 2003; Devlin-Kudenko 1401.3907)
- `F(s,s')=γΦ(s')−Φ(s)` leaves the optimal policy set EXACTLY unchanged for any Φ (necessary &
  sufficient among Markovian state shapings); ≡ Q-value init (only changes learning speed). Multi-agent:
  Nash equilibria unchanged under per-player PBRS.
- → Knobs of this form are hack-immune by construction. Audit our 8 knobs: telescoping (possession
  annuity, dist-endzone) = safe; raw event bonuses (k_kd/k_value/k_ball, k_turnover) = optimum-movers =
  the risk surface.

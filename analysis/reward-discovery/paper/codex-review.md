# Codex review of bloodbowl-reward-discovery.md

Reviewer: Codex (GPT-5.5, high reasoning effort), 2026-06-20. Reviewed against DECISIONS.md.
All 10 major findings + related-work gaps + clarity edits were incorporated; see Appendix B of the paper for the point-by-point resolutions.

---

**Bottom Line**

The draft is already unusually honest about the big two constraints: no from-scratch validation and no tournament-confirmed strength result. That part is good and should stay loud. The main fixes are narrower but important: the current text sometimes turns a single-lineage behavioral read into a “clean demonstration,” hides one active cardinal-rule violator (`ball_gain`) that was present in the violence/netblock configs, overstates PBRS guarantees, and slightly garbles the native-CUDA NaN story. I would revise before circulating.

**Major Findings**

1. **The paper says the experimental economy is cardinal-rule clean, but D156/D159 show `ball_gain 0.05` was still active.**

In §5.2 the draft says the “settled economy” is a weighted sum of decision-time-legitimate terms and omits `ball_gain` entirely ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:302)). §6 then says all experiment arms share that settled economy except named knobs ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:354)). But D147 explicitly classifies `ball_gain/ball_loss` as outcome-based shaping violators ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:722)), and D156 says the violence arm kept `ball_gain 0.05` ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:764)). Netblock inherited that economy unless changed, and D159 only zeroed `k_seq`, not `ball_gain` ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:781)).

Concrete fix: disclose this directly in §5.2 and §6. Something like:

> The block-reward terms tested in §6 are cardinal-rule clean, but the arms still inherited `reward_ball_gain=0.05`, which D147 classifies as an outcome-based shaping term. Because `ball_gain` was held fixed across violence, violence2, and netblock, it is unlikely to explain the block-dice-mix deltas, but the experiments are not a fully cardinal-rule-clean economy. A fully clean replication should set `ball_gain=0` or replace it with declaration-time pickup/pass EV.

Without that sentence, the “cardinal-rule clean” framing is overstated.

2. **The abstract has a factual overcompression: “doubling” did not raise block volume 5→21.**

The abstract says “doubling the aggression knobs raised block volume 5→21 per episode” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:30)). D156/D157 show the first violence change raised volume 5→15.7 with `k_kd 0.03→0.10`, `k_value 0.25→0.50` ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:767)). D158 shows the actual doubling from violence to violence2 raised 15.7→21.1 ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:774)).

Concrete fix:

> raising and then doubling the aggression knobs increased block volume 5→15.7→21.1 per episode, while the unfavorable “2-dice-red” fraction remained high or worsened, 0.10→0.11→0.13.

That is both more accurate and more persuasive.

3. **“Clean, controlled demonstration” and “generalizes beyond Blood Bowl” are too strong for one lineage.**

The draft repeatedly uses high-confidence language: “clean, controlled demonstration” in the contributions ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:98)), “The headline lesson generalizes beyond Blood Bowl” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:420)), and “general to reward shaping” in the conclusion ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:546)). D157-D160 support a strong mechanistic hypothesis, but the empirical base is one warm-started lineage, with no seed replicates, no from-scratch reproduction, no cross-ancestor warm-start, and no strength gate.

Concrete fix: use “mechanistically interpretable single-lineage evidence” instead of “clean demonstration,” and “suggests a general design principle” instead of “generalizes beyond Blood Bowl.” For example:

> In one single-seed warm-started lineage, the result is consistent with a general design principle: linear upside scaling changes action volume more readily than action selectivity, while an asymmetric downside term can reweight the mix.

That still lets the analytic argument breathe without overstating the experiment.

4. **The “bad blocks” language ignores the D157 caveat about carrier pressure.**

§6.1 says cranking the proxy “eventually buys only more bad blocks” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:392)). D157 explicitly cautions that 2d-red is not always bad, especially against the carrier ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:770)), and D160 says carrier telemetry existed but was not yet evaluated enough to distinguish smart residual pressure from sloppiness ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:787)).

Concrete fix: change “bad blocks” to “unfavorable-dice blocks, many of which may be bad absent carrier/high-value context.” In §6.2, keep the self-sorting point, but explicitly say the aggregate 2d-red fraction is an imperfect proxy until stratified by target value/carrier status.

5. **The PBRS/hack-immunity discussion overclaims, especially around possession.**

The table correctly classifies possession as a zero-sum turn-boundary objective-like term ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:308)), but the next paragraph says “the telescoping terms (possession, dist_ball, dist_endzone) carry the Ng–Harada–Russell optimum-invariance guarantee for free” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:326)). Possession annuity is not written as `γΦ(s') − Φ(s)` in the draft, and D43 framed it as an annuity, not PBRS. Also, the repo’s own RL notes warn that reward clamping can break PBRS telescoping invariance when rewards saturate ([docs/rl-best-practices.md](/Users/alexanderhuth/Code/bloodbowl-rl/docs/rl-best-practices.md:11)).

Concrete fix: remove possession from the PBRS guarantee sentence. Weaken “hack-immune by construction” to:

> The distance terms are intended as potential-like shaping terms; the formal PBRS invariance guarantee applies only where the implementation exactly matches `γΦ(s')−Φ(s)` and is not altered by reward clipping or interaction with non-potential raw bonuses. The possession annuity and block EV terms remain objective/shaping choices that can change the learned equilibrium.

This is a scientific-rigor fix, not just wording.

6. **The NaN section incorrectly says the violence arms repeatedly died before the fix.**

§6.3 says “The threat-annuity and violence arms repeatedly died” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:431)). The decision log supports threat/control failures before the CUDA fix, then violence/violence2/netblock running clean after D154. D157 says violence was the first 28B clean native run after the fix ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:766)); D158 and D160 also say clean.

Concrete fix:

> The threat-annuity arm and a matched no-threat control exposed the bug; the later violence, violence2, and netblock arms are evidence that the native-CUDA fix held.

Also revise “four consecutive full 28B/14B runs” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:441)) unless you list the actual runs and budgets. D154 validated only to 181.9M at first ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:755)); D156 later says threat ran clean to 4B; D157 28B; D158 12B; D160 ~14B. Say exactly that.

7. **The system-validation language is stronger than the decision log supports.**

§4.1 says the engine implements the BB2025 ruleset, 30 teams, skill/trait catalogue, May-2026 FAQ/errata ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:208)). §4.4 says correctness is “gated” by replay-differential validation ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:256)). But D146 documents a BB2025 Blitz legality bug that validation missed ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:710)), and early decisions document deferred or approximated kickoff/pass/skill windows. Unless there is a current validation report not cited in DECISIONS.md, “gated” and “implements the ruleset” read too final.

Concrete fix:

> The engine is a substantial C11 implementation of BB2025 with injectable dice and a replay-differential validation layer under active use; remaining rule-window approximations and recently found legality bugs are tracked in the decision log.

Add a small validation-status table: layer, number of tests/cases, pass/fail status, known gaps. That would turn a trust-me claim into evidence.

8. **The statistics need denominators, uncertainty, and run provenance.**

The §6 table has point estimates only ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:367)). For a paper, that is the biggest scientific weakness after single-lineage. Even if this is a preprint, add:

- run ID/checkpoint/warm start for each row;
- seed;
- step budget and final window used;
- number of episodes or block decisions in the measurement window;
- denominator for `block_2dred_frac`;
- mean ± bootstrap CI or at least across-dashboard-window min/max;
- whether the metric is training-dashboard, full-game eval, or replay corpus.

Concrete fix: replace the current table with two tables. Table 1: run provenance. Table 2: behavioral metrics with uncertainty. Keep human rates separate or visually mark them “not same unit” for absolute rates.

9. **The table still invites invalid agent-vs-human comparisons despite the caveat.**

§4.4 correctly warns that curriculum-dashboard rates are not comparable to from-kickoff human numbers ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:261)), but §6.1 puts `blocks/ep`, `tds/ep`, and human `~89/game`, `2.22/game` in the same table ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:367)). D61 explicitly says full-game-from-kickoff is the only human-comparable mode for per-game rates ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:83)).

Concrete fix: split rate and fraction metrics. Put human only beside fraction metrics in the main evidence table. Put absolute human per-game rates in a separate “orientation only” row or footnote until full-game eval exists for the arms.

10. **“Human play is plausibly-near-optimal” needs qualification.**

The draft says human play is “plausibly-near-optimal” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:71), [bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:134)). D61 supports “human is a reference, not a ceiling” ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:83)), but not “near-optimal,” especially if the corpus is not skill-filtered.

Concrete fix:

> Human FUMBBL play is a large, strategically meaningful behavioral reference, not an optimality certificate.

If you have division/rating filters, cite them. Otherwise do not use “near-optimal” as a premise.

**Related Work Gaps**

Add **Abbeel & Ng apprenticeship learning / feature expectation matching**. Your objective is aggregate-stat matching, so this is more central than f-IRL alone. It gives the classic “match expert feature expectations without copying actions” framing.

Add the actual **GAIL** and **AIRL** citations if you reject adversarial IRL in §3 ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:179)). Right now the paper names them but does not cite them.

Consider adding **IQ-Learn / ValueDICE / CSIL / SMM / GMMIL** in one compact sentence, because the repo’s own reward-from-human-data notes identify these as relevant alternatives. You do not need a long survey, but readers will expect them around f-IRL.

Add **multi-agent PBRS** explicitly if you invoke Nash-equilibrium preservation in §3 ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:191)). Devlin & Kudenko should be in the references.

Add **demonstration-augmented RL / anchoring** beyond AlphaStar/piKL if you discuss BC warm-start erosion: DQfD, Kickstarting, QDagger, and perhaps AlphaStar Unplugged-style human-stat pseudo-rewards. This would make the “BC warm-start is the cheap half” sentence more rigorous.

Add **self-play evaluation / non-transitivity** if you keep saying tournament confirmation is missing. DECISIONS.md has a lot of evidence that Elo/BT and mirror evals can decouple. A brief related-work nod to evaluation in non-transitive games would justify why “no tournament strength claim” matters.

**Clarity Edits**

Define “curriculum episode” before Table §6.1. Right now `blocks/ep` looks too much like `blocks/game`.

Define “2d-red” once in §2 and then use one notation consistently. You currently alternate “2-dice against / red,” “2-dice-red,” and “2d-red.”

In §5.1, replace “teaches dice-superstition” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:283)) with a less anthropomorphic scientific claim:

> assigns credit to uncontrollable outcome variance and can favor high-variance actions for the wrong reason.

In §5.1, the sentence “A subsequent audit found five terms…” lists only four categories and omits `statmatch_scale` ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:294)); D147 lists `statmatch_scale` as a qualified fifth ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:723)). Fix to “four hard violators plus one qualified episode-end regularizer.”

In §6.2, “leaves a 2-dice-red against the ball carrier or a star +EV” ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:409)) is analytically plausible and echoed by D158, but not empirically shown yet because residual carrier-targeting was not read. Say “can leave” rather than “leaves.”

In §6.4, “behavioral deltas are strong enough to motivate the next arm” is fine ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:452)), but do not let it read as validation. Add “not to conclude improved play.”

**Claims I Would Keep**

Keep the no-strength-claim language in the abstract and limitations. It is exactly right ([bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:37), [bloodbowl-reward-discovery.md](/Users/alexanderhuth/Code/bloodbowl-rl/analysis/reward-discovery/paper/bloodbowl-reward-discovery.md:479)).

Keep the central D156-D160 story, but recast it as “single-lineage evidence plus analytic mechanism.” DECISIONS.md supports: violence increased blocks/tds/fwd_adv but not mix ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:766)); violence2 increased volume and worsened mix ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:774)); netblock halved 2d-red while tds/fwd_adv held ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:787)).

Keep the native-CUDA lesson, but make the chronology exact: D151/D152 were wrong-path diagnoses; D153 identified the native backend; D154 fixed `pufferlib.cu`/`muon.cu` ([DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:748), [DECISIONS.md](/Users/alexanderhuth/Code/bloodbowl-rl/DECISIONS.md:750)).

**Suggested Minimal Patch Plan**

1. Patch abstract wording: fix the “doubling 5→21” error and replace “controlled demonstration/generalizable lesson” with “single-lineage evidence for a mechanistic design principle.”
2. Add a one-paragraph “Known active confound” in §6: `ball_gain=0.05` remained active and is a D147 cardinal-rule violator held constant across arms.
3. Split §6.1 table into provenance and metrics; add denominators/step budgets if available.
4. Fix §6.3 chronology: threat/control exposed the NaN; violence/netblock validated the fix.
5. Remove possession from the PBRS guarantee and weaken “hack-immune” language.
6. Add missing related-work citations around feature expectation matching, GAIL/AIRL, multi-agent PBRS, and demonstration-anchored RL.
7. Add an appendix table mapping each key claim to D147-D160 evidence. That would make the draft much harder to accidentally overclaim.

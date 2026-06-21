# Agent 1 — LLM-Driven / Automated Reward Function Design (2024–2026)

**Bottom line up front:** What we're doing by hand — propose reward term → train a probe arm → compare behavioral stats (block dice-mix, ball advancement, TDs) to a human corpus → revise — is *exactly* the loop the 2024–2026 literature is now automating. The single closest published match is **EA SEED's "Self-Correcting Reward Shaping" (June 2025)**: it tunes reward *weights* (not code) from a natural-language behavioral goal plus a *summary of training statistics*, in PPO, on a game. The rest splits into "LLM writes reward **code** + reflects on training metrics" (Eureka lineage) and a cheaper branch that **avoids per-iteration RL** via trajectory-preference proxies (CARD). Almost none target competitive self-play or fast simulators specifically — a genuine gap we're positioned to exploit, because 860K-SPS makes the expensive branch (full RL per candidate) affordable.

## Tier 1 — Adoptable in the next few weeks

### 1. EA SEED — Self-Correcting Reward Shaping via Language Models (closest analog)
- **What:** An LM proposes updated reward *weights* each iteration from (a) a natural-language behavioral goal and (b) a summary of performance statistics from prior training rounds; closed-loop self-correction, no code generation. PPO, car-racing game.
- **Paper:** arXiv 2506.23626, Afonso et al. (EA SEED + KTH), June 2025.
- **Maturity:** Real game agents, production-motivated ("game mechanics changed, re-tune the weights"). Single-agent, not self-play. Modest scale (9%→74% success in one iteration; reached 80% vs expert 94%).
- **How WE use it:** This is essentially **our D113-A statmatch arm formalized.** Our 8 EV knobs = its "weights"; our human-corpus aggregate stats (block dice-mix, ball advancement/possession, TD rate) = its "performance statistics summary"; our goal = "match the human distribution." Drop-in: wrap the probe-arm launcher so an LLM reads a DECISIONS-style metric report (observed vs human ref per stat), emits a new knob vector as JSON, launch the warm-started arm, feed results back. Lowest-risk highest-fit start. **Adopt first.**

### 2. CARD — LLM Reward Design via Dynamic Feedback (the cost-saver)
- **What:** Coder writes/verifies reward **code**; Evaluator gives dynamic feedback via **Trajectory Preference Evaluation (TPE)** — ranks trajectories to score a reward function *without* running full RL every iteration.
- **Paper:** arXiv 2410.14660 (KBS 2025). **Code: github.com/ShengjieSun419/CARD.** Meta-World + ManiSkill2; beats/matches expert rewards on 10/12 tasks.
- **How WE use it:** TPE is the transferable idea. Pre-screen 5–10 LLM-proposed knob vectors by ranking each candidate reward against a fixed bank of cached self-play trajectories (we keep selfplay banks); only train the top 1–2 as full probe arms. Direct multiplier on iteration throughput.

### 3. PROF — LLM Reward-Code Preference Optimization for (offline) Imitation
- **What:** LLM generates executable reward **code**, optimized by preferences, explicitly for imitation / distribution-matching against expert data.
- **Paper:** arXiv 2511.13765 (late 2025). Research-grade, offline-IL.
- **How WE use it:** Conceptually most aligned with our actual objective (play like the 12,722-game corpus, not "win"). Reframes the problem as adversarial/distribution-matching imitation with an LLM-authored reward — justifies treating "block-dice-mix divergence from human" as a first-class reward signal, not just a diagnostic.

## Tier 2 — Research-grade, harvest ideas not code

### 4. Eureka (progenitor — still the reference design)
- GPT-4 writes reward **code** from raw env source, evolutionary search over reward programs, **reward reflection** on training telemetry, RL fitness as selection. Beats human experts on 83% of 29 tasks. arXiv 2310.12931 (NVIDIA, ICLR 2024). Code: github.com/eureka-research/Eureka.
- **Critical fit note:** Eureka's premise is "GPU-accelerated sim lets you evaluate a large batch of reward candidates in parallel" — we have the same 860K-SPS superpower almost no game-RL group has. Port the **reward-reflection** step: instrument each of the 8 knobs to log its per-decision contribution, hand that table to the LLM with the human-stat deltas. Strictly richer feedback than we give ourselves by hand.

### 5. HROSE — Heuristic Reward Observation-Space Evolution
- Evolves the **Reward Observation Space** (which features + operations) with a persistent **State Execution Table** (memory of which features helped — breaks the one-shot-context limit). arXiv 2504.07596 (2025). Beats Eureka 9/20.
- **How WE use it:** The persistent memory maps onto our DECISIONS.md ledger — give the LLM a structured table: knob → past values tried → resulting stat-deltas. Disentanglement ("first pick which behavioral target, then tune magnitude") matches "fix advancement first, then dice-mix."

### 6. RF-Agent — reward design via Language-Agent Tree Search (MCTS over reward code)
- Tree search over reward-function candidates; training feedback prunes/expands. arXiv 2602.23876 (2026). Code: github.com/deng-ai-lab/RF-Agent. Defer until the basic loop is automated.

### 7. LaRes — Evolutionary RL with LLM rewards + shared replay/Thompson sampling
- "Don't throw away probe-arm experience between candidates" — share trajectories across candidate rewards. OpenReview 2025.

## Skip
- **Text2Reward** (2309.11489, ICLR 2024) — other progenitor; superseded for our purposes.
- **Reward-Policy Co-Evolution / ChatPCG** (2024) — tangential.
- **RLVR / GRPO** (DeepSeek R1, 2025) — for binary-verifiable LLM reasoning, NOT our rich-telemetry game. Don't be pulled toward it.

## The gap / opportunity
2024-2026 closed-loop LLM-reward work is overwhelmingly single-agent robotics; the only game entries (EA SEED racing, ChatPCG) are single-agent; NONE target competitive self-play leagues. The technique was born from fast GPU sims (Eureka/Isaac), precisely our 860K-SPS regime that game-RL rarely has. "LLM-driven reward design for *competitive self-play* against *human behavioral-distribution targets* in a fast simulator" with a 12,722-game corpus is, per this search, **unpublished.**

## Concrete first step
Generalize D113-A into an LLM-in-the-loop controller: (1) behavioral target = human-corpus stat vector; (2) after each probe cap, emit {per-stat observed, human-ref, delta} + {per-knob mean contribution}; (3) LLM returns next knob vector as JSON + rationale logged to DECISIONS.md; (4) gate each suggestion through a TPE-style trajectory-rank pre-filter so only promising vectors get a full arm. EA-SEED = method template, CARD/TPE = cost control, Eureka reflection = feedback enrichment.

## Sources
- EA SEED: https://arxiv.org/abs/2506.23626
- CARD: https://arxiv.org/abs/2410.14660 · https://github.com/ShengjieSun419/CARD
- PROF: https://arxiv.org/pdf/2511.13765
- Eureka: https://arxiv.org/abs/2310.12931 · https://eureka-research.github.io/
- HROSE: https://arxiv.org/html/2504.07596v2
- RF-Agent: https://arxiv.org/pdf/2602.23876 · https://github.com/deng-ai-lab/RF-Agent
- Text2Reward: https://arxiv.org/abs/2309.11489
- Survey (LLM/VLM-integrated RL): https://arxiv.org/pdf/2502.15214

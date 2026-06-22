# Blood Bowl Defense — Collected Research (2026-06-22)

Motivation: the agents' biggest weakness is DEFENSE — a competent human beats them ~3-0 to 6-0 (Alex,
watching BBTV), worst when the opponent is fast (6-0): the agent doesn't screen, wall lanes, keep a deep
safety, or pressure the ball. Self-play from a weak prior plateaus at a mutually-incompetent equilibrium
(neither side learns to screen because neither can punish a bad screen). Below: 4 web-research syntheses +
pointer to the existing AndyDavo guide. NEXT: Codex synthesizes → proposed RL paths forward.

Existing in-repo: `docs/vendor/andydavo/07-Defensive_Setup_Guide.md` (LoS protection, 2nd-rank assist
denial, kick-and-rush sideline channeling, Boat/Rule-of-5, agility-vs-bash philosophies, chevron/column
pitfalls, cage-breaking, clock management, + draft reward mappings). Also #06 (WoodElf screening/cage-
breaking/drive-control), #09 (chain-push/crowd-surf), #16/#31 (control-drive replays).

## THE CONVERGENT CORE (all 4 agents + AndyDavo agree)
1. **"Force the dodge — more dice = more failure" is the master principle.** Defense = maximize the
   NUMBER and DIFFICULTY of dice rolls the opponent must make between the ball and your endzone. (1 dodge
   ~67% success, 2 ~44%, 3 ~30%; a forced −2 dodge ~11% AG3 / ~25% AG4.) You win by occupying space so
   they must roll, then collect the turnovers the dice give you.
2. **Screen, don't blitz** (until you can kill the carrier). Stand players ONE square off the runner so
   tackle zones overlap into a wall — do NOT rush into base contact (it removes your TZ web, lets one
   dodge find open field, gives up the counter). Overcommitting into contact is the #1 defensive mistake.
3. **Two-deep columns at 2-square spacing (the "Elf Screen").** Atomic screen unit = 2 defenders with a
   2-square gap (the middle square is in both their TZs → can't pass without a dodge; one body can't fit).
   Stack columns 2 deep so a single knockdown/blitz does NOT open a lane (the 2nd rank re-covers). 5
   such columns span the pitch and "stymie double their number." Even/aligned ranks (staggered leaks
   diagonal paths).
4. **Keep a DEEP SAFETY (non-negotiable).** ≥1 fast player held back, goal-side of the ball, behind
   everything — so one broken screen ≠ uncontested walk-in. THIS IS THE AGENT'S 6-0 FAILURE MODE: with no
   safety, one knockdown → carrier sprints to an undefended endzone. Never draw the safety up.
5. **Mark the carrier from the endzone-side square + spend the ONE blitz/turn on the best target**
   (carrier, cage corner, or a crowd-surf), never on a no-progress block. Marking forces him to
   blitz-the-marker / pass / dodge — all spend resources or roll dice.
6. **Lane coverage** = count opponent-traversable squares on the carrier→endzone path that are in ZERO
   friendly tackle zones; every such square is a free lane. The operational objective.

## KICKOFF / SETUP (Agent 1)
- Legal: exactly 3 on the LoS (center 12-wide stripe); ≤2 per wide zone. Put EXPENDABLE/armored bodies on
  the LoS (they eat the blitz + line blocks), never a fragile playmaker.
- **Don't give >4 blocks on turn 1** (3 LoS + 1 blitz). Pull edge/wide players ~2 squares back from the
  line so a Quick Snap can't shove them into free blocks.
- Three setup goals simultaneously: (a) COVERAGE (no clear lane, overlapping TZs), (b) BLOCK-MITIGATION
  (≤4 first-turn blocks), (c) PLAY-TO-STRENGTH (fast→load wide zones to threaten a defensive blitz;
  slow→funnel to center where your mass stays relevant).
- Formation archetypes: spread/flat 3-4-4 (vs bash, default); wide two-deep column screen / 3-5-2 (vs
  fast teams — the one the agent most needs); 5-5-1 (dense intersecting zones vs agility); compact "Boat"
  3-x-x (slow team funneling center, concedes flanks); asymmetric/offset (proactive trap when you have
  time). The "named formations are a lie" thesis: train the PRINCIPLES (coverage, block-mitigation,
  safety), not fixed templates.
- React to the kickoff event before acting (Quick Snap → wide 2-back; Blitz → fast team pressures the ball
  before the receiver sets up). Screens start near midfield and RETREAT one square per turn (delay; push
  the score attempt to a later, riskier turn).

## IN-DRIVE / SCREENING / CAGE (Agent 2)
- Screen integrity invariant: every lateral gap between adjacent screeners ≤2 empty squares AND the gap
  square is in ≥1 TZ. Diagonal coverage is weaker than orthogonal → diagonal screens need tighter packing.
- Cage = carrier + 4 diagonal corners ("5 on a die"); blitzer must dodge into 3 TZs to reach him.
  Defense: DON'T blitz into the cage — put a loose screen between cage and your endzone (convert a fast
  carrier to a slow one), and MARK A CAGE CORNER (exploits "no corner may end in an enemy TZ" → he must
  spend his blitz removing your marker instead of progressing). Best anti-cage = prevent the cage forming
  (pressure the carrier before the 4 corners lock).
- Contain vs pressure: default CONTAIN (screen+funnel, force dice/passes/stalls); switch to PRESSURE
  (commit to strip) only when behind on the clock OR the carrier is soft (no Block/Dodge, low AV) AND you
  hold a reroll. Commit-discipline: don't blitz a Block/Dodge carrier with no banked reroll.
- Turnover mechanisms (preference order): force dodges by position → mark carrier from endzone-side →
  the one good blitz (carrier/corner) → SURF (crowd-push carrier out: funnel to sideline, push out; Frenzy
  surfs from 1-2 squares off) → pin against sideline (touchline = free defender, sets up the surf).
- Per-turn defensive sequence: (1) re-seal the wall / reform 2-deep columns, close any 1-sq lane; (2)
  hold/restore the deep safety; (3) mark carrier + key receivers with disposable linemen; (4) take the
  one good blitz (carrier/corner/surf); (5) funnel + retreat one square toward the sideline.

## ROSTER-CONDITIONED (Agent 3) — the mark-vs-screen switch the agent is missing
- **Bash (Orc/Chaos/Dwarf):** defend as a connected block, 2-deep columns, concentrate center / deny
  wings flat, GRIND — do NOT charge the backfield (agile teams bait bashers into open field). Mark weak
  pieces with AV9 bodies.
- **Agility/elf (WoodElf/Skaven/DarkElf):** PRESSURE the ball early (separate the handler before the cage
  forms) — "defend by attacking the ball"; threaten both flanks; L-trap to the sideline (a sideline
  screen needs ~6 elves vs ~8 central); ACCEPT fragility (don't eat blocks — screen-distance, not mark).
  High AG can leave the line to hunt and re-screen next activation.
- **Hybrid (Human/Norse):** READ the opponent and switch modes — stand OFF sticky/strong teams (limit
  blocks), get IN THE FACE of faster teams (break armour). Carry a deep safety ONLY vs faster foes.
- **Stunty (Goblin/Halfling):** anchor big guys on LoS, outnumber, slow-roll the cage one square,
  disengage (Dodge out) rather than trade.
- **Down players:** tighten into front-facing columns (all defenders in front of the ball), refuse cheap
  blocks (disadvantage compounds exponentially), be score/clock-aware (sometimes concede a fast TD to get
  the ball back).
- **Skill-conditioned mark/screen flip:** Tackle/Diving Tackle (−2 dodge) → MARK aggressively; Shadowing
  → passive-mark fast players (denies their Guard/PtB); Stand Firm → un-removable mark; Guard → enables
  the defensive 2-die blitz; absence of Tackle vs agile → SCREEN don't mark. "More dice = more failure"
  (P16) is the master rule; skills set the mark-vs-screen choice.

## CANONICAL SOURCES (Agent 4 — ranked, for deeper mining)
- **grumbbl.co.uk** — "To Base or Not to Base (Defending pt1)" + "A Lean Mean Screening Machine" (the two
  best modern long-forms; marking heuristics + screen geometry).
- **bbtactics.com** wiki — Marking Players, Cage Basics, Cage Breaking, Tackle, Blocking Odds Tables;
  forum "Let's talk screen defense".
- **thetacklezone.net** — "Tackle Zones Pt2: Screening" (the most rigorous screen-integrity math).
- **bloodbowlstrategies.com** — "How to Stop an Offense" (cleanest complete defense guide, by archetype).
- **Goonhammer** — "Why everything about kick-off setups was a lie", "Combine: Kick-off Formations",
  "Hammer of Math: Risk Management", "Art of Game Management" (analytical/data-driven).
- **NAF Playbooks** (plasmoid, LRB6-era — concepts transfer, numbers don't).
- **Dave's Action Calculator** (bloodbowldave.com — BB2025 odds ground-truth) + bbtactics blocking odds.
- Video: **Bonehead Podcast** "Defensive Set-Up Formations (BB2020)" + Theory Thursday (the higher-value
  NEW video source beyond AndyDavo).

## ENGINE-FEASIBILITY NOTES (what we can already compute → candidate signals)
- Tackle zones per square: `tz_scratch` / the obs TZ planes already exist.
- Reachability (Dijkstra dodge/GFI cost to every square): `bb_reach_field_compute` (used by R6/R12) →
  can compute the carrier's min-cost path to our endzone and count zero-TZ lane squares + forced dodges.
- `bb_block_ev`, `bb_count_assists` — block/assist EV for the one-blitz-on-carrier decision.
- R12 `reward_defensive_threat` ALREADY EXISTS (off): per unmitigated opponent that can reach OUR endzone
  in ≤1 / ≤2 of its own turns — a coarse version of "deny the scoring lane / keep them marked." A natural
  starting point to revisit/extend.
- DOCTRINE to respect (from DECISIONS): decision-time-EV pricing (D147); D46 ground inhuman behavior in
  WINS not aesthetics; the threat-annuity over-engineering scar (D150, 8x SPS — keep any board-eval
  BOUNDED); the assist-potential optimum-invariance lesson (D165 — a telescoping PBRS potential can't
  create behavior the base reward doesn't already favor; to CHANGE behavior toward human you may need a
  non-PBRS push / BC-toward-human); win-rate-vs-frozen-anchors is the only ground truth (self-play metrics
  are inflated — both sides equally weak).

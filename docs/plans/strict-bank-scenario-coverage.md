# Strict-bank S1–S6 scenario coverage

## Objective and boundary

Measure which tactical opportunity structures exist in the provenance-bound
strict-BB2025 state bank. This tranche classifies and reports coverage only. It
does not choose actions, use replay outcomes as labels, assign curriculum
weights, install a bank, launch training, select a checkpoint, or change the
active vacation queues.

Canonical inputs are the D191 subset bank (15,348 records / 5,328 replay IDs,
SHA-256 `bcd9daf55ac5d177f48160092f17a9b4978da877455b830ba33a9c1b5ba84d22`)
and its deterministic filtering manifest. Every record is the first
`BB_STATUS_DECISION` of a fresh team turn, staged only after the next replay
operation also applied cleanly. The literal legal actions are therefore
`ACTIVATE` plus `END_TURN`; all deeper action-family claims are explicitly
derived, pre-negatrait opportunity predicates.

## Architecture

1. `tools/bank_scenario_predicates.{h,c}` contains pure, RNG-free predicates
   over one `bb_match`. It reuses engine reachability, tackle-zone, assist,
   carrier-threat, and defensive-horizon queries.
2. `tools/bank_scenario_scan.c` validates the BBS1 ABI/fingerprint and emits one
   deterministic JSON record per input record in source order. It never
   advances or mutates the source state.
3. `tools/report_scenario_coverage.py` requires exact bank, D191-manifest,
   scanner-source, and scanner-binary hashes; invokes the scanner; re-hashes the
   input afterward; verifies the canonical count/turn histogram; aggregates
   record, replay, and capped-per-replay denominators; and publishes a
   deterministic report plus provenance manifest with the manifest last.

Bucket flags overlap. No primary-bucket assignment or sampling policy belongs
in this tranche.

## Operational predicates

### S1 — ball recovery opportunity

Loose on-pitch ball and at least one truly activatable, standing, non-rooted,
non-`NO BALL` active-team player whose engine reach field reaches the ball
square. Report cheapest path dodge/GFI counts, recoverer count, AG/Sure Hands,
ball-square tackle zones, and weather. This is derived opportunity, not
guaranteed pickup legality or success; reachability
does not include Jump/Leap-class paths and pickup target-number calculation is
out of v1.

### S2 — loose-ball contest geometry

S1 plus at least one standing opponent that can reach the ball square under a
fresh-next-turn static-board clone. Before opponent reachability, reset only
that team's `moved` and `rushes` counters; otherwise the snapshot retains its
prior-turn expenditures and systematically undercounts the next turn. Preserve
stance, location, Rooted, and board geometry. Report the S1 active-side costs
plus the S2 opponent-side cheapest costs and contester counts. Structurally
assert `S2 ⊆ S1`. This is static
contest geometry; the active team moves first and can change the position.

### S3 — ordering-pressure opportunity

At least four exact `ACTIVATE` options, at least two standing eligible players
with a nonempty zero-dodge/zero-GFI movement path that does not traverse the
loose-ball square, and at least one derived risky candidate: any S1 pickup,
direct Block declaration, or marked-player movement. Report opportunity-family
and count bands. Never call this ordering quality, regret, or stranded value:
the bank contains no chosen continuation or outcome.

### S4 — own-carrier sack-access geometry

Active team holds the ball and a fresh-next-turn opponent clone has either
current adjacency/free access or exactly one dodge/GFI of access to a square
adjacent to the carrier. Marked/free access is `full`; one-roll-only access is
`soft`. Report the existing R6v1 exposure and threat queries separately under
their own names because R6v1 includes an endzone-dash reward exemption and uses
the snapshot's current movement counters; it is diagnostic comparison, not the
primary S4 flag. This is static sack-access geometry, not sack probability.

### S5 — defensive red-zone geometry

Opponent holds the ball, the active team defends, and
`bb_def_threat_turns(carrier)` is one or two. Report horizon, marked/open,
active-team access around the carrier, and team-level one/two-turn threat
counts. Horizons are straight-line `MA + max rushes` geometry: they ignore
tackle zones, path availability, and the defender's intervening action.

### S6 — direct-block and one-move assist structure

Part A reports the set of fixed direct-Block pool classes available at the
boundary. It uses exact `bb_count_assists`, player strength, and the current
Cheering Fans latch. Dauntless attackers are reported as dynamic and excluded
from fixed-class span claims; blitz/Horns, block preambles, Frenzy follow-up
geometry, and target value are outside v1. `S6A` fires when the global direct
Block alternatives span at least two fixed classes.

Part B exhaustively considers each eligible standing mover and each
zero-dodge/zero-GFI reachable final square whose selected path does not traverse
the loose ball. On a memcpy clone, move with the engine placement helper and
recompute fixed pool classes for direct blocks by other active-team players.
`S6B` fires only if a class changes. This is a one-move, zero-roll reachability
counterfactual; it excludes dodge-assisted, multi-move, blitz, and alternate
equal-cost paths not selected by the engine reach field. No heuristic
"adjacent square probably assists" substitute is allowed.

## Denominators, overlap, and provenance

For every bucket, sub-bucket, turn band (`1–2`, `3–4`, `5–8`), and pairwise
overlap, publish:

- raw records out of 15,348;
- distinct replay IDs out of 5,328; and
- record count capped at three contributions per replay.

Also publish deterministic replay-ID-disjoint 70/15/15 hash splits as
descriptive composition only. Without a separately pinned metadata join, v1 is
not stratified by coach, TV, outcome, or replay chronology. Team IDs permit
race-pair composition, but replay outcomes remain forbidden as action-quality
labels.

The provenance manifest binds the bank and D191 manifest, BBS header and local
ABI/fingerprint, source/binary hashes, engine git tree, compiler/flags, full
command, all thresholds, output hashes, count/histogram invariants, overlap
relations, anomaly counters, and the approximation register. Canonical bytes
contain no timestamps.

## Test-first acceptance

Before the scanner/report implementation, add fixtures that distinguish each
positive predicate from a near-identical negative state, including:

- S1 reach, `NO BALL`, and held-ball exclusions;
- S2 opponent prior-turn movement counters that must be normalized;
- S3 eligible/safe/risky count boundaries;
- S4 raw full/soft access even when R6v1's scoring exemption fires;
- S5 one/two/beyond-two geometric horizons;
- S6 fixed pool span, Dauntless exclusion, a real one-move class change, and a
  marked non-Guard mover that cannot assist versus the same mover with Guard;
- grid/player consistency after the cloned move;
- wrong BBS magic/version/size/fingerprint, partial records, metadata mismatch,
  hash drift, input mutation, existing outputs, and handled publish failure;
- deterministic scanner, report, split, caps, and overlap bytes; and
- failing containment checks for synthetic `S2 !⊆ S1` and `S4 ∩ S5` input.

Canonical acceptance requires 15,348 records, 5,328 replay IDs, half 1 only,
turn counts `8026/3975/1798/857/395/185/87/25`, zero unexplained invariants,
byte-identical double runs, and exact reconciliation of loose-ball primitives
against the independent pickup probe.

## Approximation register

- `derived-pre-negatrait`: sub-activation actions are opportunity predicates,
  not literal boundary actions or execution guarantees.
- `reach-no-jump`: engine Dijkstra excludes Jump/Leap-class paths.
- `contest-static-next-turn`: S2/S4 normalize opponent movement counters but
  do not model the active team's intervening actions.
- `pickup-components-not-target-number`: v1 reports AG/TZ/weather facts without
  reimplementing edition-sensitive pickup modifier logic.
- `s3-opportunity-only`: no ordering-quality conclusion is possible or made.
- `geometric-score-horizon`: S5 ignores tackle zones and path feasibility.
- `s6-fixed-direct-blocks`: Dauntless/blitz/preambles/Frenzy/value are outside
  fixed pool-span semantics.
- `s6-one-move-zero-roll-only`: no multi-move, dodge-assisted, or alternate
  equal-cost assist construction is claimed.
- `opening-censored`: every record is half one; 12,001/15,348 are turns 1–2
  and only 25 are turn 8.

The measured holes size a future authored-fixture plan. They do not authorize
training or a curriculum distribution.

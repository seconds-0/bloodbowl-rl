# Architecture spec (for review): R6v1 — carrier-exposure reward term

**Status:** ARCHITECTURE-FOR-REVIEW, not an implementation-ready brief. To be reviewed
by Opus + Codex + Alex and refined before anyone builds it. No code is changed by this
document.

Repo: `/Users/alexanderhuth/Code/bloodbowl-rl`. Decisions context: D119 (formation
problem), D120 (4-way pressure-test consensus — R6 #1), D121 (AndyDavo corpus
corroboration), D123 / D123-A (R6 staged v1/v1.5/v2; v1's dual dodge/GFI-counter
correction; v2 "fragility" reframe). Design memo: `docs/reward-design-coaching-wisdom.md`
(search "R6"). This spec covers **R6v1 ONLY**, designed so v1.5 and v2a/v2b are natural
in-place extensions rather than rewrites.

---

## 0. What R6v1 must do (corrected per D123-A)

At each **settled own-turn-end** (the team whose turn just ended = `t`), if team `t` has a
**standing ball carrier**, evaluate the carrier's exposure to team `1-t`'s standing players
and charge a **one-sided penalty to team `t`** (never positive, never credited to `1-t`):

- **Full penalty** (`reward_carrier_exposure`, e.g. −0.05) if **either**:
  - the carrier is currently **marked** (an opponent already adjacent — `bb_is_marked`), OR
  - **some** standing opponent can reach a square adjacent to the carrier with
    `min_dodges == 0 AND min_gfis == 0` (a totally free walk-up / walk-up-and-blitz).
- **Reduced penalty** (optional second tier, `reward_carrier_exposure_soft`, e.g. −0.02) if
  the best opponent path needs **exactly one** risky roll — i.e. `min_dodges + min_gfis == 1`
  for the cheapest-access opponent — and the full tier did not already fire.
- **Zero** otherwise.
- **Exempt entirely** (charge nothing) if the carrier is within **MA of the opposing
  endzone** — i.e. the carrier could itself score next turn with a pure run; scoring dashes
  are deliberately exposed and must not be taxed.

The penalty prices a **positional mistake the turn it is made**, a full turn before the
−0.5 sack it predicts. It is formation-agnostic by construction (tight cage, loose cage,
screen wall, sideline bunker all score by the same access-cost metric).

---

## 1. The reachability computation

### 1.1 Where it lives

**New translation unit: `engine/src/bb_reachability.c` + `engine/include/bb/bb_reachability.h`.**
Rationale:
- It is pure engine logic (operates on `const bb_match*`, no env/PufferLib types), so it
  belongs in `engine/`, not in `puffer/bloodbowl/bloodbowl.h`. This keeps it unit-testable
  by the existing `engine/tests/` harness (same as `bb_blockev.c` → `test_blockev.c`) and
  reusable by the obs layer later (D119(3)/N2 want a per-acting-player "min-opponent-reach"
  obs plane — same routine).
- It reuses the **modifier law** already centralized in `proc_move.c::bb_step_success_p255`
  (`engine/src/proc_move.c:984`), but needs the underlying **dice-count booleans** (is this
  step a dodge? a rush/GFI?) not the conflated probability. v1 does NOT call
  `bb_step_success_p255`; it walks the SAME predicates (is the FROM-square in an opposing TZ
  → dodge on exit; has the mover spent its MA → this step is a rush) to accumulate counts.
  v1.5 will switch to probabilities and at that point can share more with `p255` (see §1.6).

### 1.2 Core data structure (richer-intermediate, forward-compatible)

The key forward-compat decision (per task item 1): compute a **per-opponent cost field over
the whole board**, not just a single aggregate number. The marginal cost is trivial (the BFS
already visits every square; we just keep the per-square label instead of discarding it), and
it makes v1.5 (probabilities) and v2 (fragility edge-costs) drop-in changes to the *edge
relaxation rule* rather than a re-architecture.

```c
// engine/include/bb/bb_reachability.h
#include "bb/bb_match.h"

// Lexicographic movement cost to reach a square: minimize dodges first, then
// GFIs (a path needing 0 dodges + 2 GFIs is "cheaper" / more dangerous than
// one needing 1 dodge + 0 GFIs, per Alex's "make them dodge OR GFI" framing —
// both count, dodges are the harder bar). UNREACHABLE = sentinel.
typedef struct {
    uint8_t dodges;   // 0xFF = unreachable
    uint8_t gfis;
} bb_reach_cost;

#define BB_REACH_UNREACHABLE 0xFF

// Per-square reachability cost field for ONE mover, filled by Dijkstra over the
// 26x15 grid. cost[x][y] = cheapest (dodges,gfis) for `mover` to STAND on (x,y)
// — including the blitz step (a blitzer's final move-into-block square is just
// another reachable square; the block itself rolls no movement dice).
typedef struct {
    bb_reach_cost cost[BB_PITCH_LEN][BB_PITCH_WID];
} bb_reach_field;

// Fill `out` for `mover` (assumed standing, on-pitch). `is_blitz` extends the
// budget by the implicit blitz step's reach (see §1.4). Pure, no RNG.
void bb_reach_field_compute(const bb_match* m, int mover, int is_blitz,
                            bb_reach_field* out);

// Aggregate query: cheapest (dodges,gfis) for ANY standing player of `team` to
// end ADJACENT to (tx,ty) — i.e. min over opponents, min over the 8 squares
// around the target, of that opponent's reach cost. `team` is the REACHING
// team (the carrier's opponents). Returns the lexicographic-min cost; .dodges
// == 0xFF if no one can reach. Also reports whether the target is already
// marked via the caller (bb_is_marked) — not folded in here.
bb_reach_cost bb_min_access_cost(const bb_match* m, int team, int tx, int ty);
```

**Why a cost field per opponent and not one global multi-source field:** see §1.5 — a single
multi-source BFS would conflate which opponent owns which square and would not let v2 attach
per-screener fragility. The per-opponent field is the structure v1.5/v2 need. But §1.5 also
gives a cheaper aggregate-only formulation that v1 could ship if the per-opponent cost proves
too heavy; flagged as an open question for review.

### 1.3 The BFS/Dijkstra algorithm (per opponent)

Movement in BB is 8-connected (orthogonal + diagonal, all cost-1 in *squares*). The cost we
minimize is not squares but **(dodges, gfis)** lexicographically. This is a shortest-path
problem with non-negative integer edge weights → **0-1-BFS / Dijkstra with a tiny bucket
queue** (costs are small: dodges ≤ ~3, gfis ≤ 2 for any realistic path within MA+blitz).

For mover `p` of team `mt = BB_TEAM_OF(mover)`:

1. **Budget.** `budget = p->ma - p->moved` squares of normal movement (almost always
   `p->ma` at settled-turn-end, since opponents have not activated — but compute from the
   fields to be correct). Plus up to **2 rush/GFI** squares (BB2025: 2 GFI by default;
   confirm Sprint/Sure Feet interactions are out-of-scope for v1, see Open Questions). If
   `is_blitz`, the blitzer's reach is "MA squares of movement, the last of which can be the
   move-into-contact step" — the blitz block consumes one square (`proc_move.c:818`,
   `:949`), so reach-adjacency is already covered by ordinary reach to an adjacent square
   within the same budget. **Net: blitz does not add movement budget; it adds nothing to the
   distance field beyond ordinary reach.** (This is important — see Open Question Q1: the
   real benefit of the team-blitz is the *block*, but for "can an opponent end ADJACENT to
   the carrier" the blitz step is just a normal move to an adjacent square. So `is_blitz` may
   be a no-op for v1's adjacency query and could be dropped; flagged.)

2. **Edge cost (relaxation), moving FROM square `s` TO neighbor `n`:**
   - `step_dodges = 1` if `s` is in an **opposing TZ for the mover**
     (`bb_tackle_zones(m, mt, s.x, s.y) > 0`) — BB2025: the dodge is rolled when **leaving**
     a square you are marked in, regardless of where you go. Confirmed against
     `bb_step_success_p255` (`proc_move.c:996`: dodge test gates on
     `bb_tackle_zones(m, team, p->x, p->y) > 0`, i.e. the FROM square). Else 0.
   - `step_gfis = 1` if reaching `n` would exceed `budget` normal squares (i.e. the running
     square-count along this path is `> budget`). Else 0. Cap total GFIs at 2 — a path that
     would need a 3rd GFI is treated as not traversable (BB2025 max 2 GFI without
     Sprint).
   - New tentative cost = lexicographic add: `(cost[s].dodges + step_dodges,
     cost[s].gfis + step_gfis)`, with the square-count tracked alongside to know when GFIs
     start. **Tie-break / ordering: minimize dodges first, then gfis, then square-count.**
     Because the GFI boundary depends on *square-count along the path*, the state is really
     (square, squares_used); a clean implementation does Dijkstra over `(x, y,
     squares_used)` with `squares_used ∈ [0, budget+2]`, OR — simpler and sufficient —
     two-phase: BFS the free-movement region (≤ budget squares, dodges-as-weight) then expand
     1–2 GFI rings. Recommend the explicit `(x,y,squares_used)` Dijkstra for correctness
     (the two-phase version mishandles paths that trade a dodge for a longer GFI-free route);
     the state space is 26·15·(budget+3) ≈ ~4k nodes, trivial.

3. **Blocked squares.** A square occupied by ANY player (`m->grid[x][y] != 0`) is not
   standable → not a node you can settle on, and not traversable (BB has no move-through).
   **Exception the design must get right:** the mover's OWN current square is the source.
   Friendly pieces and enemy pieces are both hard obstacles in v1 (v2 makes *some friendly*
   screeners soft — see §1.7). The carrier's square itself is occupied (by the carrier) so
   opponents settle on the 8 neighbors, which is exactly what we want for "end adjacent."

4. **Output.** Fill `out->cost[x][y]` for every reachable square with the lexicographic-min
   `(dodges, gfis)`; unreachable squares stay `{0xFF, 0xFF}`.

### 1.4 Adjacency aggregation (`bb_min_access_cost`)

For the carrier at `(tx,ty)`, opponents of the carrier = team `1 - BB_TEAM_OF(carrier)`.
For each standing on-pitch opponent, compute its `bb_reach_field`, then take the min over the
(up to 8) on-pitch squares adjacent to `(tx,ty)` of that opponent's `cost`. Lexicographic-min
across all opponents → the team aggregate. Diagonal cage-corners: the memo says **never count
diagonal cage-corners** as protection — but for the *access* query we DO consider all 8
adjacency squares as valid "blitz-adjacent" end squares (an opponent diagonally adjacent to
the carrier can blitz it). The "don't count diagonal corners" rule is about FRIENDLY
screen geometry, not about which squares an attacker may stand in. **Flagged Q4** — confirm
this reading; it affects whether diagonal adjacency counts as "marked"/"reachable".

### 1.5 Performance & the single-BFS question (task item 2)

**Frequency.** The hook fires once per turn-flip (`m->active_team` change). `m->turn[t]`
runs 1..8 per half (`bb_match.h:84`), so ≤ 8 own-turn-ends per team per half → **≤ 32
firings per full game** (2 halves × 2 teams × 8), and only those where team `t` ends holding
a standing carrier actually run the BFS (a minority — most turns the ball is loose, in the
air, or the holder is down). Realistically ~5–15 BFS-bearing firings/game. Negligible vs the
~hundreds of `bb_advance`/decision steps per game.

**Worst-case cost.** Up to 11 standing opponents × Dijkstra over ~4k `(x,y,squares)` nodes
each = ~45k relaxations, a handful of times per game. This is **cheap** — comparable to a
single `bb_blockev` sweep, far under existing per-step env costs (the env does TZ counts and
reach checks every decision). No optimization needed for v1.

**The O(board) reformulation (genuinely better, recommended to evaluate):** instead of one
BFS *per opponent*, run a **single multi-source Dijkstra seeded from ALL standing opponents
simultaneously** (each opponent's source square initialized to cost `{0,0}`), producing one
field `min_cost[x][y]` = cheapest access cost for the cheapest opponent to stand on `(x,y)`.
Then `bb_min_access_cost` is just the min over the carrier's 8 neighbors of that single field.
This is **O(board) total**, not O(opponents × board), and is the natural v1 implementation if
v1 only needs the aggregate.

**BUT** — and this is the load-bearing forward-compat tension — a multi-source field
**loses the identity of which opponent reaches each square**, which **v2 needs**: v2's
fragility model asks "if I knock down / push this *specific* screener, does *this specific*
opponent's access cost to the carrier drop?" That requires per-opponent fields (or at least
re-running the relevant opponent's BFS with one screener softened). 

**Proposed resolution (the design choice for reviewers):** ship v1 with the **multi-source
single field** (cheapest, O(board)) for the aggregate penalty, AND structure
`bb_reach_field_compute` as a standalone per-mover routine that the multi-source version
calls in a loop OR that v2 can call individually. I.e. expose BOTH:
- `bb_min_access_cost(...)` — v1's fast aggregate (internally may use multi-source).
- `bb_reach_field_compute(m, mover, ...)` — per-opponent, used by v1.5/v2 and the future obs
  plane.

That keeps v1 cheap and correct while not painting v2 into a corner. **This is the single
biggest architecture decision in the spec — see Open Question Q2.**

### 1.6 Forward-compat: v1.5 (probabilities)

v1.5 replaces the lexicographic `(dodges, gfis)` edge cost with a **probability product**
edge cost: each edge multiplies a survival probability `P(make this dodge/GFI)` computed from
the SAME `bb_test_target` math `bb_step_success_p255` already uses (AG-based dodge target with
`-TZ(dest)` modifier and hook mods; rush 2+ with blizzard/hook mods). The "cost" of a square
becomes `1 - Π P(rolls)` = P(opponent reaches this square at all this turn). The field type
generalizes from `bb_reach_cost{dodges,gfis}` to a `float p_reach[x][y]`. Because v1 already
computes a *field* and already isolates the edge-relaxation rule, v1.5 is a change to (a) the
field's value type and (b) the relax function — same Dijkstra skeleton (now max-product
instead of lexicographic-min; equivalently min over `-log p`). **v1 should keep the
edge-relaxation logic in one small static function so v1.5 swaps exactly that.**

### 1.7 Forward-compat: v2 (fragility edge costs)

v2a makes a *friendly* screener square soft: instead of "occupied = hard obstacle", a
screener with high **fragility** `f` (probability it stops projecting its TZ this turn, via
knockdown-in-place or being pushed off, vs its best current adjacent threat — computed by
EXISTING `bb_block_ev`) contributes a *reduced* dodge cost on the edges that leave its TZ
(in the limit `f → 1`, the screener's TZ contributes ~0 dodge cost; `f → 0`, full cost).
This is again **only an edge-cost modification** on the per-opponent field — which is exactly
why §1.5/§1.2 keep the relaxation rule isolated and keep per-opponent fields available. v2
needs `bb_block_ev` (`engine/include/bb/bb_blockev.h:62`) and the per-opponent field; both
are reachable from this v1 structure with no rework. (v2b — blitz-angle + Frenzy-chain — is
explicitly research, via sampling, out of scope here.)

---

## 2. The reward field, kwarg, ini default

### 2.1 Struct field (`puffer/bloodbowl/bloodbowl.h`, in the reward block ~line 297)

```c
// Carrier-exposure penalty (R6v1, D120/D123-A; docs/reward-design-coaching-wisdom.md).
// One-sided penalty to the team whose OWN turn just ended holding a standing
// carrier, charged at the settled-turn-end hook (same hook as reward_possession).
// Fires if the carrier is MARKED or some standing opponent has a free walk-up
// (min_dodges==0 && min_gfis==0) to a blitz-adjacent square. NEVER positive,
// never credited to the opponent (it prices YOUR positional mistake, not a
// zero-sum transfer). Exempt when the carrier is within MA of the opposing
// endzone (scoring dashes are deliberately exposed). 0 = off (default).
float reward_carrier_exposure;
// Optional softer tier: charged INSTEAD of the full penalty when the cheapest
// opponent access needs exactly one risky roll (min_dodges+min_gfis==1). Also
// one-sided, also negative-only. 0 = off (default); set ~0.4x the full value.
float reward_carrier_exposure_soft;
```

Naming: matches the `reward_<concept>` convention (`reward_rush_cost`,
`reward_statmatch_scale`, `reward_possession`). `reward_carrier_exposure` reads cleanly and is
distinct from the `reward_k_*` block-EV family. The soft tier as a separate field (rather than
a hardcoded ratio) matches how the economy keeps every coefficient externally tunable.

### 2.2 kwarg (`puffer/bloodbowl/binding.c`, with the other reward kws ~line 85)

```c
env->reward_carrier_exposure = (float)kw(kwargs, "reward_carrier_exposure", 0.0);
env->reward_carrier_exposure_soft = (float)kw(kwargs, "reward_carrier_exposure_soft", 0.0);
```

### 2.3 ini default (`puffer/config/bloodbowl.ini`, near `reward_rush_cost`)

```ini
reward_carrier_exposure = 0.0
reward_carrier_exposure_soft = 0.0
```

Default 0.0 = OFF, matching `reward_statmatch_scale` / `reward_surf_*` / `reward_rush_cost`
precedent. (Note D120's config-hygiene finding: the ini is NOT the live v4 economy; these
defaults exist for documentation/safety, and R6 is enabled via launch-script trailing args
like every other settled knob.)

---

## 3. Sign / symmetry (task item 4)

**One-sided penalty to the exposed team only. No opponent-side credit.** This matches the
table-row ("never a positive for safe") and the `reward_rush_cost` precedent exactly:
`reward_rush_cost` (`bloodbowl.h:1608`) charges only the acting team
(`reward_ptr[rt][0] -= ...`) with no mirror credit — a declaration-time cost for a risky
choice, not a zero-sum transfer. R6 is the same shape: it prices a positional mistake the
exposed coach made, and crediting the opponent would (a) double-count against the −0.5 sack
they already get if they convert, and (b) make it a transfer the opponent could "farm" by
just standing near carriers.

Contrast with the genuinely zero-sum terms (`reward_possession`, `reward_k_kd/value/ball`,
`reward_td`, injury) which all do `reward_ptr[t] += x; reward_ptr[1-t] -= x`. R6 deliberately
does **only** `reward_ptr[t][0] -= penalty`. Apply at the **settled-turn-end hook**
(mid-episode, per-step reward stream — NOT `bbe_finish_episode`), exactly like the possession
annuity it sits beside, so credit lands on the turn the mistake was made.

---

## 4. Hook integration (concrete)

Inside the existing `if ((int)m->active_team != env->prev_active_team)` block in
`puffer/bloodbowl/bloodbowl.h` (~line 1894, where the possession annuity fires), AFTER the
possession-metric/annuity logic, add (sketch):

```c
if (env->reward_carrier_exposure != 0.0f || env->reward_carrier_exposure_soft != 0.0f) {
    // Only if team t ended its turn with a STANDING carrier it owns.
    if (m->ball.state == BB_BALL_HELD && m->ball.carrier != BB_NO_PLAYER) {
        int c = m->ball.carrier;
        const bb_player* cp = &m->players[c];
        if (BB_TEAM_OF(c) == t && cp->stance == BB_STANCE_STANDING
            && cp->location == BB_LOC_ON_PITCH) {
            // Endzone-MA exemption: carrier could itself score next turn.
            int own_ez_x = (t == BB_HOME) ? (BB_PITCH_LEN - 1) : 0; // attack target col
            int dist_ez = (t == BB_HOME) ? (own_ez_x - cp->x) : (cp->x - own_ez_x);
            // dist_ez = squares from the carrier's CURRENT x to the line it must
            // cross to score (the opposing endzone column). Chebyshev not needed:
            // scoring only needs to reach the endzone COLUMN (y is free). Exempt
            // if reachable by a pure run incl. up to 2 GFI: dist_ez <= cp->ma + 2.
            // (Open Q3: include GFI in the exemption, or only cp->ma?)
            int exempt = (dist_ez <= cp->ma + 2);
            if (!exempt) {
                int opp = 1 - t;
                int full = bb_is_marked(m, c);
                bb_reach_cost ac = {BB_REACH_UNREACHABLE, BB_REACH_UNREACHABLE};
                if (!full) ac = bb_min_access_cost(m, opp, cp->x, cp->y);
                if (full || (ac.dodges == 0 && ac.gfis == 0)) {
                    env->reward_ptr[t][0] -= env->reward_carrier_exposure;
                    env->ep_return[t] -= env->reward_carrier_exposure;
                    // (optional telemetry: env->ep_carrier_exposed_full++;)
                } else if (env->reward_carrier_exposure_soft != 0.0f
                           && ac.dodges != BB_REACH_UNREACHABLE
                           && (ac.dodges + ac.gfis) == 1) {
                    env->reward_ptr[t][0] -= env->reward_carrier_exposure_soft;
                    env->ep_return[t] -= env->reward_carrier_exposure_soft;
                    // (optional telemetry: env->ep_carrier_exposed_soft++;)
                }
            }
        }
    }
}
```

Notes:
- Uses `bb_is_marked(m, c)` (`bb_match.h:195`) for the marked check — already exactly
  "standing player in an opposing TZ", the predicate the spec wants. Do **not** re-derive it
  from `bb_tackle_zones`.
- `BB_TEAM_OF(c) == t` guards that the carrier belongs to the team whose turn ended (the
  whole point — we never penalize the team that DIDN'T just move).
- Endzone column: Home attacks toward `x == BB_PITCH_LEN-1 == 25`, Away toward `x == 0`
  (`bb_types.h:11-12`). The exemption uses x-distance to that column (scoring needs only to
  reach the endzone column; `y` is unconstrained), NOT Euclidean distance to a specific
  square.
- Telemetry counters (`ep_carrier_exposed_*`) are optional but recommended so the canaries in
  §6 are directly observable on the training dashboard; they follow the existing `ep_*`
  counter pattern (`ep_turns`, `ep_gfi_attempts`, etc.). Adding them touches the `Env`
  struct + the per-episode log aggregation (mind the dict-capacity footgun: capacity is 64,
  abort-on-overflow — adding 2 keys is fine, but count the total).

---

## 5. Endzone-MA exemption & marked-carrier predicates (task item 5)

- **Marked carrier:** `bb_is_marked(m, carrier_slot)` → true if a standing carrier is in an
  opposing TZ. Charges full penalty immediately (no BFS needed — short-circuit).
- **Free walk-up:** `bb_min_access_cost(m, opponent_team, carrier_x, carrier_y)` returns
  `{0,0}` → full penalty.
- **One-risky-roll:** `bb_min_access_cost(...)` returns cost with `dodges+gfis == 1` → soft
  penalty (if enabled and full didn't fire).
- **Endzone-MA exemption:** `dist_to_opposing_endzone_column(carrier) <= carrier.ma (+ GFI?)`
  → charge nothing. (Open Q3: whether to add the 2 GFI to the exemption budget. Including GFI
  is more generous — exempts more dashes; excluding GFI taxes a carrier that needs to rush to
  score. Leaning: include GFI, since a carrier one-GFI-from-scoring SHOULD be exposed/charging
  forward. Flagged for review.)

---

## 6. Validation / self-test plan (task item 6)

Follow the **`engine/tests/test_blockev.c` pattern** exactly: a `BB_TEST(name)` per case,
fixtures from `engine/tests/bb_fixtures.h` (`fx_match_midturn`, `fx_lineman`, `fx_give_skill`,
place players at explicit `(x,y)`), registered in the test main. Add
`engine/tests/test_reachability.c`. These test the PURE engine routine (`bb_reach_field_compute`
/ `bb_min_access_cost`), which is why it lives in `engine/` — the env hook is then a thin
wrapper that needs only a couple of integration smoke checks.

Hand-constructed boards (each asserts the returned `bb_reach_cost`, NOT the reward — reward
wiring is a separate integration check):

1. **Open-field exposed.** Carrier alone at (13,7); one standing opponent at (13,3) with
   MA 6, no TZs anywhere on the path. Assert `bb_min_access_cost` = `{0,0}` (free walk-up to
   an adjacent square). → full penalty.
2. **Tight cage.** Carrier at (13,7); friendly pieces on all 8 diagonals+orthogonals forming
   a cage; nearest opponent outside, must dodge to enter any adjacent square. Assert
   `min.dodges >= 1`. → not full. (And assert NOT marked.)
3. **Marked.** Carrier at (13,7); opponent standing at (13,8) (adjacent). Assert
   `bb_is_marked == true`. → full penalty via short-circuit (BFS not even required).
4. **One-dodge buffer.** Carrier at (13,7) with a single friendly screener at (12,5) such
   that the only opponent must make exactly one dodge (leave one TZ square) to reach an
   adjacent square, no GFI. Assert `min == {1,0}` → soft tier.
5. **GFI-gated.** Carrier at (13,7); opponent far enough that reaching any adjacent square
   needs 1 GFI but 0 dodges. Assert `min == {0,1}` → soft tier (per D123-A correction: GFI
   counts; this is NOT a free walk-up; v1's earlier-sketch bug would have scored this `{0,0}`
   full — the regression test that locks the correction).
6. **Unreachable.** Carrier at (13,7); the only opponent stunned/prone or so far it cannot
   reach even with 2 GFI. Assert `min.dodges == 0xFF` → no penalty.
7. **Endzone exemption (integration).** Carrier at (24,7), Home, MA 6 → `dist_ez =
   25-24 = 1 <= ma` → exempt; assert the env charges nothing even though an opponent is
   adjacent/free. (This one needs the env hook, so it's an env-level test or a direct call to
   the exemption predicate.)
8. **Prone/stunned opponents ignored.** Same as case 1 but the opponent is PRONE — assert
   `unreachable` (only STANDING opponents project threats / can move).
9. **Diagonal-adjacency-as-marked (covers Q4).** Opponent diagonally adjacent at (14,8) to
   carrier (13,7): assert whatever the reviewers decide (currently: counts as marked/reach,
   since a diagonal opponent can blitz). Lock the decision with this test.

Also: `make goldens` is unaffected (no rules change). The new reward term is default-OFF so
existing training/eval behavior is byte-identical unless the knob is set — verify with a quick
A=B tournament at `reward_carrier_exposure 0`.

---

## 7. Open questions / risks for review (Opus + Codex + Alex)

**Q1 — Is `is_blitz` a no-op for the adjacency query?** For "can an opponent end ADJACENT to
the carrier," the team-blitz adds no movement budget (the blitz block consumes a move square,
`proc_move.c:818/949`); the relevant reach is just "stand on an adjacent square within MA(+GFI)."
So `is_blitz` may add nothing in v1 and could be dropped from the v1 signature (kept in the
header for v1.5/v2 where the block itself matters). Recommend dropping it from v1's compute
but is it ever load-bearing (e.g. a player who is ALREADY adjacent but needs the blitz to
*reach through* — no, that's a block not a move)? Confirm.

**Q2 — Per-opponent fields vs single multi-source field (the big one).** §1.5: v1 only needs
the aggregate, for which a single multi-source Dijkstra is O(board) and strictly cheaper. But
v2 needs per-opponent identity (to test softening one screener). Proposed: expose both
(`bb_min_access_cost` fast-path possibly multi-source; `bb_reach_field_compute` per-mover for
v1.5/v2/obs). Is the extra surface worth it now, or should v1 ship per-opponent-in-a-loop
(slightly slower, still trivial cost) to keep ONE code path until v2 actually lands? I lean
**per-opponent-in-a-loop for v1** (one code path, cost is negligible at ≤15 firings/game) and
add the multi-source fast-path only if profiling ever shows it matters — simpler is better and
the perf headroom is enormous. Flagging because the task explicitly asked about the O(board)
reformulation; my recommendation is to NOT do it for v1.

**Q3 — Does the endzone exemption budget include the 2 GFI** (`ma + 2`) or just `ma`?
Including GFI exempts more carriers (any carrier that could rush in to score); excluding it
taxes a carrier that must GFI to score. Leaning include (`ma + 2`), matching the BFS's own
GFI allowance, but it's a policy call.

**Q4 — Diagonal adjacency.** The memo says "never count diagonal cage-corners" for FRIENDLY
screen geometry. For the ATTACKER's access query, does a diagonally-adjacent opponent count
as "blitz-adjacent / marking"? `bb_is_marked`/`bb_tackle_zones` use the standard 8-square TZ
(diagonals included), so a diagonal opponent already counts as marking under the engine's own
definition. Recommend: yes, all 8 adjacency squares are valid attacker end-squares and
diagonal = marked, consistent with the engine. Confirm this isn't double-counting the memo's
"don't reward diagonal corners" intent (that intent is about not REWARDING shape, which R6
doesn't do anyway — it only penalizes).

**Q5 — GFI count = 2 fixed, or skill-aware (Sprint, Sure Feet, Two Heads, Break Tackle,
Stunty/Titchy dodge mods)?** v1 as specced uses a flat 2-GFI cap and counts raw dodge/GFI
*occurrences*, ignoring skills that change the *probability* (Dodge, Tackle) — which is fine
because v1 thresholds on COUNTS, not probabilities (a Dodge-skill player still needs "1 dodge"
to leave a TZ; it's just more likely to succeed). Sprint (3 GFI) and movement-extending skills
DO change reachable squares, so v1 arguably should honor Sprint's +1 GFI. Recommend: honor
**Sprint** (budget) since it changes reachability counts; defer **probability**-altering
skills (Dodge/Tackle/Break Tackle) to v1.5 where they belong. Is even Sprint worth it for v1,
or accept a small under-count? Flagging.

**Q6 — Soft-tier semantics: `dodges+gfis==1` vs the memo's "exactly one of {1 dodge, 1
GFI}".** The spec uses `dodges+gfis==1` (so {1,0} or {0,1}). A path needing {1,1} (one dodge
AND one GFI) falls through to "safe / no penalty" — is that right, or should {1,1} also be
soft? Two compounding rolls is genuinely safer than one, so dropping to no-penalty seems
defensible, but it's a boundary worth a conscious decision. (v1.5's continuous probability
dissolves this question entirely.)

**Q7 — Interaction with the −0.3/turn positional-charge cap (memo §5).** R6 is meant to live
under a combined R6+R7+R8 cap of ≈−0.3/turn. R7/R8 aren't built yet, so v1 ships alone, but
the magnitude (−0.05 full / −0.02 soft) should be chosen with that future cap in mind and
kept well under one TD per incident (−0.05 + later −0.5 sack ≪ +1 TD). No code coupling
needed for v1; just don't let the default magnitude creep.

**Q8 — Does the carrier's own MA reflect Take Root / Distracted / negatraits at turn-end?**
The exemption reads `cp->ma`. If the carrier is Rooted (`BB_PF_ROOTED`) it can't move at all
→ should NOT be exempt regardless of distance. Recommend: gate the exemption on "carrier can
actually move" (not Rooted, standing). Minor but correct-by-construction.

**Q9 — Telemetry counters.** Recommend adding `ep_carrier_exposed_full/soft` (and maybe a
per-episode "turns ended with exposed carrier" rate) so the §6 canaries (sack-rate-against,
stall length) can be correlated on-dashboard. Costs 2 dict keys (capacity 64, watch the
overflow-abort footgun). Worth it? I think yes — R6's whole value is credit-assignment
legibility and we'll want to see it firing.

---

## 8. REVISION APPENDIX (post-review, D126) — these OVERRIDE §1-7 where they conflict

Three independent reviews (Opus, Codex, lead) found this spec sound with NO blocker —
the §7 priority item (`moved`-reset timing) is CLEARED (3-way confirmed; see D126 for the
precise causal trace). The fixes below are small and targeted; implement against §1-7
PLUS these overrides, not a rewrite.

### 8.1 File references (doc fix only)
`bb_state.h` does not exist in this checkout. The relevant structs/constants live in
`engine/include/bb/bb_types.h` (`bb_player`, `BB_PITCH_LEN`/`BB_PITCH_WID`, `BB_TEAM_OF`,
`BB_PF_ROOTED`, endzone constants) and `engine/include/bb/bb_match.h` (`bb_match`, `m->grid`,
`bb_is_marked`, `bb_tackle_zones`). Wherever §1-7 says "bb_state.h", read these two files.

### 8.2 SIGN CONVENTION FIX (real bug, codex catch)
§2.1/§4's `-0.05`/`-0.02` example values, combined with the `-=` charge in §4's sketch,
double-negate — net effect REWARDS exposure. Fix, matching `reward_rush_cost`
(`bloodbowl.h:1608-1611`) exactly:

```c
// ini / kwarg defaults: POSITIVE magnitudes (0 = off)
env->reward_carrier_exposure = (float)kw(kwargs, "reward_carrier_exposure", 0.0);      // e.g. 0.05
env->reward_carrier_exposure_soft = (float)kw(kwargs, "reward_carrier_exposure_soft", 0.0); // e.g. 0.02

// at the hook, charge via subtraction of a POSITIVE value:
env->reward_ptr[t][0] -= env->reward_carrier_exposure;       // full tier
env->ep_return[t]     -= env->reward_carrier_exposure;
// (soft tier: -= reward_carrier_exposure_soft, same pattern)
```

Struct field comments (§2.1) should say "positive magnitude, charged via subtraction" —
update the doc-comment, not just the launch examples.

### 8.3 AGGREGATION FIX (real bug, codex catch) — replaces §1.4's lex-min-then-threshold

§1.4 as written: take the lexicographic-min `(dodges,gfis)` ACROSS opponents, then
threshold that single result. **Bug**: lexicographic ordering compares `dodges` first, so
an opponent with `{0,2}` (0 dodges, 2 GFIs — a real but GFI-gated path) lex-sorts BEFORE
an opponent with `{1,0}` (1 dodge, 0 GFIs — a one-roll soft-tier path), even though `{1,0}`
is the one that should trigger the soft tier and `{0,2}` (sum=2) should not trigger anything.
Picking only the lex-min `{0,2}` and thresholding it would report "no penalty" while a
DIFFERENT opponent's `{1,0}` should have scored "soft penalty".

**Fix**: `bb_min_access_cost` (or its caller) computes TWO BOOLEANS by OR-ing across all
standing, non-rooted opponents of `team` and their up-to-8 adjacent-to-target squares:

```c
// Pseudocode for bb_min_access_cost's new contract (or a wrapper around it):
bool any_free = false;     // some opponent: dodges==0 && gfis==0
bool any_one_roll = false; // some opponent: dodges+gfis==1
for each standing, non-ROOTED opponent o of `team`:
    field = bb_reach_field_compute(m, o, ...);
    for each of the (up to 8) on-pitch squares adjacent to (tx,ty):
        c = field.cost[sq.x][sq.y];
        if (c.dodges != BB_REACH_UNREACHABLE) {
            if (c.dodges == 0 && c.gfis == 0) any_free = true;
            if (c.dodges + c.gfis == 1) any_one_roll = true;
        }
// caller:
full = bb_is_marked(m, carrier) || any_free;
soft = !full && any_one_roll && reward_carrier_exposure_soft != 0.0f;
```

This changes `bb_min_access_cost`'s RETURN TYPE/contract from "a single `bb_reach_cost`"
to either two bools, or a small struct `{bool any_free; bool any_one_roll;}` — adjust
§1.2's header sketch accordingly. The per-opponent `bb_reach_field_compute` (§1.2) is
UNCHANGED; only the aggregation step changes.

### 8.4 Rooted OPPONENTS excluded from BFS movers (Q8 extended, codex)
`can_step` already rejects `BB_PF_ROOTED` (`proc_move.c:45`) — a rooted player cannot
move to a NEW square this turn. So: when enumerating "standing opponents" to BFS from
(§1.4), EXCLUDE opponents with `BB_PF_ROOTED` set — they cannot contribute new reach.
A rooted opponent that is ALREADY adjacent still marks the carrier via the unchanged
`bb_is_marked` short-circuit (§5) — no change needed there, `bb_is_marked` doesn't care
about rootedness, correctly.

### 8.5 Engine amalgamation wiring (codex catch, missing from §1.1)
`puffer/bloodbowl/bloodbowl.h:61` directly `#include`s engine `.c` files (single
translation-unit amalgamation). The new `engine/src/bb_reachability.c` MUST be added to
that include list, or it will never be compiled into the env. Add the include alongside
the existing engine `.c` includes at that location. (Header `engine/include/bb/bb_reachability.h`
is included normally wherever needed, same as other engine headers.)

### 8.6 2D Dijkstra, not 3D (Opus finding — `bbe_macro_reach` precedent)
§1.3 step 2's proposed `(x,y,squares_used)` 3D state space is unnecessary. `bbe_macro_reach`
(`bloodbowl.h:794-867`) already solves the equivalent problem with a 2D `(x,y)` Dijkstra
where the GFI boundary falls out of `reach_len`/path-length tracked per node under the
lexicographic `(dodges,gfis)` cost order — shorter-and-safer paths win naturally. Adapt
that approach: `bb_reach_field_compute` is a 2D Dijkstra over `(x,y)`, cost = `(dodges,gfis)`
lex-order, `reach_len` (squares used so far) tracked per node to determine when a step
becomes a GFI (`reach_len >= budget`). Use `bbe_macro_reach` as the reference
implementation for the traversal/obstacle/edge-cost mechanics; `bb_reach_field_compute`
is its generalization to "fill the whole field" rather than "find one target."

### 8.7 Carrier's endzone-exemption budget (Q3, both reviewers converged)
§4/§5's exemption: `dist_ez <= cp->ma + 2` → **`dist_ez <= cp->ma + bb_max_rushes(m, carrier)`**
(Sprint-aware: `bb_max_rushes` returns 3 for Sprint, 2 otherwise, `bb_skills.c:11-13`),
**AND** `!(cp->flags & BB_PF_ROOTED)` (Q8's original finding — a Rooted carrier is never
exempt regardless of distance, since it cannot move at all).

### 8.8 `is_blitz` / naming (Q1 — doc clarification, no logic change)
Keep `is_blitz` dropped from v1's `bb_reach_field_compute`/`bb_min_access_cost` calls
(per Opus: §0's literal goal is "can reach a square ADJACENT to the carrier," which is
blitz-independent). But in code comments and the `reward_carrier_exposure` doc-comment
(§2.1), call the metric **"free adjacent access"**, not "sack threat" / "blitz threat" —
avoids implying the richer "can successfully Block the carrier" semantics that v2's
fragility model (not v1) actually addresses.

### 8.9 Additional test cases (§6)
- **Downed/prone carrier** (symmetric to test 8's prone-opponent case): carrier at (13,7)
  with `stance != STANDING` — assert the hook charges NOTHING (the `stance==STANDING`
  guard in §4 short-circuits before any BFS). Closes the guard with a test.
- **Fix test 2 ("tight cage")**: as written, "all 8 adjacent squares occupied" makes the
  target UNREACHABLE (matches test 6's semantics, not "must dodge"). Rewrite: leave 1-2
  adjacent squares OPEN but place them inside a screener's TZ (so reaching them costs a
  dodge) — assert `any_free==false`, `any_one_roll` per the screener configuration.
- **Rooted opponent, adjacent**: opponent at (13,8) adjacent to carrier (13,7), `BB_PF_ROOTED`
  set — assert `bb_is_marked==true` still fires (full penalty via short-circuit), confirming
  8.4 doesn't accidentally suppress the marked check for rooted-but-adjacent opponents.
- **Rooted opponent, non-adjacent**: same opponent moved 2 squares away, still ROOTED —
  assert it does NOT contribute to `any_free`/`any_one_roll` (excluded per 8.4).

### 8.10 Telemetry (Q9, unanimous)
Add `ep_carrier_exposed_full` and `ep_carrier_exposed_soft` counters (increment on each
firing), following the existing `ep_*` pattern (e.g. `ep_turns`, `ep_gfi_attempts`).
Current dashboard dict usage is ~36-37/64 keys (per D113-A's `create_dict(64)` patch
context) — 2 more keys is safe headroom. Surface both in the per-episode log aggregation
the same way other `ep_*` counters are surfaced.

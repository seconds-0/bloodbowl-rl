# Strict BB2025 replay-state bank

## Objective and boundary

Produce a provenance-bound exact-BB2025 subset of the historical BBS1 state
bank before replay-derived scenario classification or curriculum work. This is
data hygiene, not a curriculum, policy evaluation, or reward experiment. It
must not modify the active RTX 2070 checkout, queue, module, plan, pins, state,
trainer, BBTV, or production defaults.

The canonical mixed bank has 15,471 records from 5,370 replay IDs. The strict
9,118-ID nonempty BB2025 allowlist selects 15,348 records from 5,328 IDs and
excludes 123 records from 42 IDs. A polite independent replay fetch confirmed
all 42 excluded IDs embed `rulesVersion=BB2020`; there are no unexplained
exclusions.

## Test-first contract

`tools/filter_state_bank.py` must:

1. require lowercase SHA-256 pins for both the source BBS and allowlist before
   creating any output;
2. validate BBS1 magic/version, bounded nonzero match size, nonzero engine
   fingerprint, exact record divisibility, replay IDs, zero metadata padding,
   and authoritative half/turn ranges;
3. parse a canonical, unique, positive-u32 replay-ID allowlist while accepting
   UTF-8 BOM, CRLF, surrounding whitespace, and blank lines;
4. stream records with bounded memory, preserve the 16-byte header and every
   selected record byte-for-byte in original order, and detect source mutation
   between initial hashing and the copy pass;
5. refuse aliased or existing paths and require output, selected-ID list, and
   manifest in one directory;
6. fsync same-directory temporary files, publish them through exclusive hard
   links that cannot overwrite a racing writer, publish the manifest last as
   the transaction commit marker, fsync the directory, and remove only
   inode-owned outputs if a handled publish step fails;
7. write a sorted selected-ID artifact and deterministic manifest binding tool
   hash, full command, exact input/output/allowlist identities, BBS header,
   record/replay counts, input/output half and turn histograms, and the complete
   excluded replay-ID list; and
8. say explicitly that edition comes from the external ID join, replay outcomes
   are not action-quality labels, the subset remains half-one/opening-censored,
   and an allowlist-at-build-time source rebuild should eventually supersede it.

Focused tests must prove byte/order preservation through the existing
`validation.build_state_bank.read_shard` reader, double-run byte determinism,
hash-pin failure, malformed header/record/metadata failure, allowlist failure,
no-overlap failure, alias/existing-output refusal, concurrent source-mutation
detection, and cleanup after an injected mid-publish failure.
The publish test must also simulate a destination appearing during publication
and prove that the racing writer's bytes survive ownership-safe cleanup.

## Canonical acceptance

Run twice at identical paths with exact count flags. Require byte-identical BBS,
selected-ID, and manifest outputs across runs. Independently require:

- output header equals input header;
- output body equals the ordered concatenation of selected source records;
- the existing state-bank reader sees exactly 15,348 records;
- first and last selected records match their input records;
- output histogram is half 1 only, with turns 1–8 equal to
  `8026/3975/1798/857/395/185/87/25`; and
- all 42 excluded replay IDs independently report embedded BB2020 rules.

Keep the generated 33 MiB bank and its two sidecars gitignored. Record content
hashes and limitations in D191. Do not stage the subset into a training build
until a separately reviewed future experiment actually needs it.

## Next tranche

Classify strict-bank scenario coverage and counts only—no training wiring—using
the audit's S1–S6 taxonomy and replay-disjoint strata. Use measured empty/thin
buckets to size separately authored pass, handoff, second-half, score/clock,
Stalling, and contextual-reroll fixtures. Do not oversample the 25 turn-8 states
and call that late-game coverage.

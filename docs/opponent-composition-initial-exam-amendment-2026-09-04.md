# Initial 100M opponent-composition exam amendment

Status: prospective execution and evaluation amendment. No comparison result
exists. This does not modify or replace the frozen pool plan with SHA-256
`99a60ca75a66b771587e020e3d886cc1ade56c69f4db2bbef08dcc0b1de27977`.

The initial diagnostic remains four 100M-step models: control and candidate at
training seeds 42 and 44, ordered seed-42 control then candidate and seed-44
candidate then control. Retain a 50M checkpoint if the runner already emits it,
but do not evaluate it in this initial diagnostic. Evaluate only each final
100M checkpoint.

Each model receives eight scripted cells: contact and cage/offense script,
learner HOME and learner AWAY, at fresh evaluation seeds 6001 and 6002. Require
exactly 32 completed full games per cell. This is 256 games per model and 1,024
games for the four trained models, approximately 34 minutes if run serially at
the measured two seconds per game. All cells use kickoff starts with
`demo_reset_pct=0`; record W/D/L, match score, TD for/against, completed games,
side, script type, evaluation seed, checkpoint hash, and full integrity
counters.

The shared chain-9 reference may be evaluated once through the identical eight
cells, adding 256 games, only when a same-build calibration is needed. Keep it
outside the four-model paired total and label it `reference`, never a fifth
training arm. The existing 64-game functional bridge remains an execution and
compatibility check; it is not a strength baseline and must not be pooled with
this exam.

This sample can detect large failures, strong side/style asymmetry, and
descriptive composition differences. A null result cannot reject a long-horizon
benefit. A positive result cannot select or promote the candidate. No arm may
be promoted, extended, or rejected for strength from this diagnostic alone.
A 128-games-per-cell confirmation, learned-opponent grid, roster-stratified
exam, or longer training run requires a later separately reviewed and frozen
plan written after this diagnostic completes.

Acceptance still requires the final cumulative evaluation reprint, every
declared cell at its exact completed-game floor, and zero clip, non-finite,
engine-error, demo, fallback, exact-action, and recurrent-integrity counters.
Reject an execution-integrity failure; do not reinterpret it as a strength
result.

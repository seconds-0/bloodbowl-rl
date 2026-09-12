# Observation ABI v7

Obs-v7 is a semantic and physical ABI revision. It has 2,851 unsigned-byte
inputs and retains the `exact-joint-v1` action ABI with heads `{30,33,391}`.

Bytes 0..2781 retain the obs-v6 layout except for the two bytes obs-v6 proved
were always zero:

* scalar 30, absolute byte 814: drive-scoped bonus rerolls owned by the viewing
  coach;
* scalar 31, absolute byte 815: drive-scoped bonus rerolls owned by the other
  coach.

The new typed player parameters follow the old final probability plane:

* bytes 2782..2813: `p_loner` for egocentric player rows 0..31;
* bytes 2814..2845: `p_bloodlust` for egocentric player rows 0..31;
* byte 2846: targeted-action variant (`x+1`, zero off-wrapper);
* byte 2847: targeted-action context flags;
* byte 2848: projected targeted-action choice state;
* byte 2849: nearest targeted-action wrapper actor row + 1 (egocentric, zero if none);
* byte 2850: nearest targeted-action wrapper target row + 1 (egocentric, zero if none).

The public targeted state bits are: bit 0 Dump-off declined, bit 1 Dump-off
used, bit 2 Dump-off pass in flight, bit 3 Trickster declined, bit 4 Trickster
used, bit 5 Trickster pickup declined, bit 6 Trickster pickup in flight, and
bit 7 action dispatched/child pending. The encoder finds the nearest targeted
wrapper through a child TEST and projects these meanings; it never exposes raw
overloaded frame data. The ordinary context player slots continue to describe the actual top frame. The appended actor and target bytes preserve the nearest wrapper identity while a child TEST is on top.

Each byte reports effective behavior. Loner is zero without the skill and uses
the engine's established 4+ fallback when the skill is present but raw
`p_loner` is zero. Bloodlust is zero unless both the trait and a positive raw
parameter are present. The underlying fields are signed bytes, so every
positive target fits losslessly in the observation byte. The encoder adds no
new validation or termination rule. Ordinary skill tokens and cached skill
rows are unchanged.

BBP v5 is the replay-pair encoding for obs-v7. BBP v4 is exact-action obs-v6
and remains readable only under the explicit historical-reproduction flag. A
v4 record cannot be relabelled or zero-padded because it lacks bonus composition
and both X+ values. Re-extract raw replay command streams through the v7 engine
to create v5 pairs.

An obs-v6 native checkpoint may be migrated only through the explicit
`training/convert_checkpoint.py --migrate-v6-to-v7` path. It copies occupied
old encoder weights and all later tensors bit-for-bit, zeros old columns
814/815, and zero-initializes the appended 69 columns. The required manifest
records both semantic identities and hashes. This preserves the old algebraic
function on valid v6 inputs; numerical forward agreement must be measured
because a changed matrix shape may select a different GEMM kernel.

Obs-v7 does not authorize a default, checkpoint, reward, or production
promotion. Historical obs-v6 manifests and artifacts remain immutable.

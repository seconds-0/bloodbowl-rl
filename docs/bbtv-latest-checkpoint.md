# BBTV latest-checkpoint follower

BBTV is an external progress view for the current reward-screen experiment. It
continuously plays the newest completed training checkpoint against that run's
frozen warm-start policy. This pairing makes cumulative behavior change easier
to see than latest-vs-latest self-play while still showing the freshest policy.

The public page remains <https://bbtv.seconds0.com>. The WebSocket remains at
`/ws`; no frontend or protocol change is required.

## Safety contract

`stream_backend/follow_latest.py`:

- considers only checkpoint directories with `RUN_MANIFEST.json` and mode
  `native_static_pool_reward_ablation`;
- requires the manifest's schema, frozen-warm byte count, and frozen-warm
  SHA-256 to match the live baseline before and after conversion;
- ignores bootstrap checkpoints and files whose byte size differs from the
  manifest's expected checkpoint size;
- requires size and timestamps to remain stable before reading a checkpoint;
- hashes the source before conversion and confirms it did not change during
  conversion;
- writes converted Torch policies and metadata atomically under
  `runs/bbtv-follow`, never in the trainer's checkpoint tree;
- selects the greatest checkpoint step from the greatest numeric run ID, so
  touching or restoring an older checkpoint cannot roll the stream backward;
- fingerprints the converter and environment config in every cache entry and
  rebuilds when either changes;
- uses a separate, float-built Puffer environment at
  `/home/rache/bloodbowl-rl-bbtv/vendor/PufferLib`, so it cannot rebuild or
  replace the native module imported by the live trainer;
- falls back to the prior league9-vs-league8 stream if discovery or conversion
  fails; and
- runs at nice level 19 and idle I/O priority.

A new pairing becomes “last successful” only after the server completes its
bounded match cycle. A load/runtime failure quarantines that exact converted
pair and restores the previous successful pairing (or the static fallback).
Conversion and match cycles also have finite timeouts, so a wedged child cannot
leave the follower alive but permanently stalled.

The follower rechecks after every two streamed games. Home and away are swapped
between those games by the existing match runner. A just-finished checkpoint can
therefore take up to one two-game cycle to appear.

The checked-in launcher samples legal actions from each policy by default
(`BBTV_SAMPLE=1`). This matches the action-selection mode used by training and
evaluation more closely than greedy argmax and makes the public stream a more
representative qualitative view of learned behavior. BBTV games remain
observational: their small, unpaired sample must not be used for reward tuning,
promotion, or regression gates. The exact child command, including `--sample`,
is recorded in `server_status.json`.

## RTX 2070 service

The repository launcher is `stream_backend/run_follow_latest.sh`. Production is
enabled with a reversible systemd user-service override:

The checked-in override template is
`stream_backend/bbstream-follow-latest.conf`; install it as
`~/.config/systemd/user/bbstream.service.d/follow-latest.conf`.

Apply or inspect it with:

```bash
systemctl --user daemon-reload
systemctl --user restart bbstream.service
systemctl --user status bbstream.service
cat /home/rache/bloodbowl-rl-audit/runs/bbtv-follow/selection.json
cat /home/rache/bloodbowl-rl-audit/runs/bbtv-follow/server_status.json
```

To compare with or immediately roll back to deterministic greedy viewing, set
`BBTV_SAMPLE=0` in the service environment and restart only
`bbstream.service`. Removing that override restores sampled viewing.

Rollback preserves the original static launcher:

```bash
rm ~/.config/systemd/user/bbstream.service.d/follow-latest.conf
systemctl --user daemon-reload
systemctl --user restart bbstream.service
```

Do not delete or rewrite the audit checkpoint tree to repair BBTV. If no valid
checkpoint is discoverable, inspect `server_status.json`, the conversion
metadata, and `journalctl --user -u bbstream.service`; the designed recovery path
is the static-policy fallback.

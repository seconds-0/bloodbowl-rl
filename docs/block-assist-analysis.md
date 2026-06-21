# Block Assist Analysis

Matched per-game means use the same shape as the env `Log`: each game contributes `carrier_count[tier] / max(1, tier_count)` and `offassist_sum[tier] / max(1, tier_count)`, then games are averaged. Human tiers are binned by the reconstructed engine tier from snapshot strength plus `bb_count_assists`; recorded FUMBBL tier mismatches are kept as an audit count. The human tool also records block-weighted counts in the JSON artifact.

| tier | agent: frac-vs-carrier | agent: mean off-assists | human: frac-vs-carrier | human: mean off-assists |
| --- | ---: | ---: | ---: | ---: |
| 1d | 0.168 | 0.283 | 0.071 | 0.554 |
| 2d | 0.080 | 0.523 | 0.017 | 0.936 |
| 2d-red | 0.259 | 0.090 | 0.111 | 0.167 |

Verdict: H1 is only a partial explanation. The agent's 2d-red blocks are more carrier-concentrated than human 2d-red blocks, 0.259 vs 0.111, so some red dice are pressure attempts. But about 74% of the agent's 2d-red blocks are still not against the carrier, so carrier pressure cannot explain most of the residual red-dice behavior. H2 is supported: the agent brings fewer offensive assists than humans on every matched tier, with the largest practical gap on favorable 2d blocks, 0.523 vs 0.935, and a smaller but still present gap on 2d-red blocks, 0.090 vs 0.167 per-game mean. Human block-weighted 2d-red off-assists are 0.292, so the conclusion is not an artifact of one weighting.

Run notes: the agent side used `training/netblock_cap.bin` for both coaches in a finite native PufferLib eval-log rollout with frozen-bank slots disabled, producing 513 completed games. The policy's 2d-red rate in that run was 0.069. The human side parsed all 401 normalized FUMBBL games, measuring 32,483 blocks, skipping 17 malformed block events, and seeing 459 mismatches, 1.4%, between reconstructed snapshot strength/assist tier and recorded FUMBBL dice metadata. Snapshot caveat: the parser reconstructs positions, stance, skills, touchbacks, and held-ball state needed for this measurement, but it does not fully mirror every transient no-tackle-zone, Distracted, or Eye Gouge flag; those residuals are part of the 1.4% tier-mismatch audit risk.

Build verification: the GPU rebuild completed after `bash tools/install_puffer_env.sh`, `bash tools/install_puffer_env.sh --check`, and `cd vendor/PufferLib && rm -rf build && ./build.sh bloodbowl`. The rebuilt module reports `precision_bytes == 2`, and `vendor/PufferLib/src/pufferlib.cu` still contains `raw_logratio`.

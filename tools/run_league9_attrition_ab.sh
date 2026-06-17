#!/usr/bin/env bash
# D141 attrition-restore A/B for league9, PREP ONLY.
#
# Warm-starts from training/league9_latest.bin and keeps the live league9 resume
# recipe unchanged except for the settled attrition/contact economy knobs and
# tag. Launch only after the current league9 run caps.
#
# Watch condition: SCORING RETENTION. TDs must not collapse back into the
# D34/D39 contact-vs-scoring failure mode while block volume and foul rate climb
# toward the human reference.
set -u
cd /root/bloodbowl-rl
. tools/cpu_cap.sh 2>/dev/null || true
POOL=/root/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/league7-20260615-191058/pool
/opt/conda/bin/puffer train bloodbowl --tag league9-attrition-ab \
  --load-model-path training/league9_latest.bin \
  --selfplay.league-preseed "$POOL" \
  --vec.num-frozen-banks 8 --vec.frozen-bank-pct 0.06 --selfplay.swap-winrate 0.55 \
  --selfplay.snapshot-interval 2000000000 --train.total-timesteps 28000000000 \
  --train.learning-rate 0.00028 --train.ent-coef 0.009 \
  --env.reward-draw 0 --env.reward-setup-done 0 --env.reward-setup-autofix 0 \
  --env.reward-injury-inflicted 0.15 --env.reward-injury-taken -0.15 --env.reward-injury-value-scaled 1 \
  --env.reward-send-off -0.15 \
  --env.reward-surf-taken 0 --env.reward-surf-inflicted 0 \
  --env.reward-possession 0.03 --env.reward-ball-gain 0.05 --env.reward-ball-loss 0 \
  --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.reward-k-kd 0.06 --env.reward-k-value 0.5 --env.reward-k-ball 0.15 --env.reward-k-seq 0.01 \
  --env.reward-rush-cost 0.015 \
  --env.reward-carrier-exposure 0.05 --env.reward-carrier-exposure-soft 0.02 \
  --env.demo-reset-pct 0 --env.demo-endzone-maxdist 0 --env.demo-pickup-maxdist 0 --env.demo-postkick-maxturn 0 \
  > /tmp/league9.log 2>&1
echo "LEAGUE9_EXIT $?" >> /tmp/league9.log

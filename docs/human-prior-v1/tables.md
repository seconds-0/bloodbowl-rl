### Training subset against held-out subset (60 replays never trained on)

| trained on | train records (prefix + re-seated) | held-out prefix: exact / NLL | held-out prefix + closed-equal | held-out everything |
|---|---|---|---|---|
| prefix only | 98,211 + 0 | 46.6% / 1.641 | 46.9% / 1.553 | 46.6% / 1.580 |
| prefix + closed-equal (default) | 98,211 + 269,906 | 50.7% / 1.385 | 51.3% / 1.283 | 51.2% / 1.297 |
| everything (stamps 0-4) | 98,211 + 380,371 | 51.3% / 1.347 | 52.5% / 1.241 | 52.5% / 1.252 |

Held-out records in the default subset: 67,989 (20,267 prefix + 47,722 re-seated). Exact 51.3% [50.1%, 52.6%] (replay-clustered).

### Default prior, by head (held-out, default subset)

| head | accuracy, all rows | rows with a choice | accuracy there | mean p(human) there | mean top probability there |
|---|---|---|---|---|---|
| type | 94.1% | 45,977 | 91.3% | 0.869 | 0.920 |
| arg | 84.6% | 25,311 | 58.7% | 0.513 | 0.601 |
| square | 70.9% | 27,914 | 29.2% | 0.233 | 0.371 |

All three heads right: 51.3%. Mean probability on the human's joint action: 0.455. NLL 1.283 nats. Type-head ECE 0.007.

### Default prior, by action family (held-out, default subset)

|  | n | exact | type | arg | square | mean p(human) | NLL |
|---|---|---|---|---|---|---|---|
| setup | 2,826 | 19.9% | 98.4% | 80.4% | 23.5% | 0.142 | 3.77 |
| activate | 9,050 | 28.4% | 100.0% | 28.4% | 100.0% | 0.251 | 1.67 |
| end_turn | 296 | 0.0% | 0.0% | 100.0% | 100.0% | 0.079 | 2.81 |
| declare_move | 5,652 | 93.5% | 100.0% | 93.5% | 100.0% | 0.803 | 0.27 |
| declare_block | 2,192 | 94.8% | 100.0% | 94.8% | 100.0% | 0.708 | 0.37 |
| declare_blitz | 1,053 | 3.7% | 100.0% | 3.7% | 100.0% | 0.249 | 1.53 |
| pass | 49 | 0.0% | 71.4% | 38.8% | 61.2% | 0.006 | 6.26 |
| handoff | 47 | 23.4% | 85.1% | 46.8% | 89.4% | 0.223 | 3.46 |
| foul | 100 | 31.0% | 85.0% | 49.0% | 97.0% | 0.272 | 2.10 |
| declare_other | 42 | 0.0% | 100.0% | 0.0% | 100.0% | 0.077 | 2.73 |
| move | 31,932 | 42.2% | 89.9% | 100.0% | 50.5% | 0.368 | 1.52 |
| block_target | 3,134 | 85.7% | 98.6% | 100.0% | 86.9% | 0.820 | 0.30 |
| block_die | 3,252 | 78.1% | 100.0% | 78.1% | 100.0% | 0.691 | 0.46 |
| push_follow | 4,854 | 53.5% | 100.0% | 81.4% | 72.1% | 0.503 | 0.80 |
| reroll_skill | 3,245 | 89.1% | 89.3% | 99.8% | 100.0% | 0.831 | 0.31 |
| other | 265 | 47.9% | 99.2% | 49.4% | 98.9% | 0.475 | 0.88 |

### Default prior, by half (held-out, default subset)

|  | n | exact | type | arg | square | mean p(human) | NLL |
|---|---|---|---|---|---|---|---|
| 1 | 38,046 | 51.1% | 94.3% | 84.2% | 70.7% | 0.454 | 1.31 |
| 2 | 29,943 | 51.6% | 93.9% | 85.1% | 71.3% | 0.456 | 1.25 |

### Default prior, by team-turn band (held-out, default subset)

|  | n | exact | type | arg | square | mean p(human) | NLL |
|---|---|---|---|---|---|---|---|
| 0 (set-up, kick-off) | 2,177 | 25.0% | 98.6% | 78.7% | 30.8% | 0.189 | 3.40 |
| 1-2 | 21,609 | 52.4% | 93.7% | 85.2% | 72.5% | 0.466 | 1.19 |
| 3-4 | 17,830 | 53.9% | 94.1% | 84.7% | 74.0% | 0.482 | 1.15 |
| 5-8 | 26,373 | 50.9% | 94.1% | 84.6% | 70.9% | 0.450 | 1.27 |

### Default prior, by provenance (held-out, default subset)

|  | n | exact | type | arg | square | mean p(human) | NLL |
|---|---|---|---|---|---|---|---|
| prefix | 20,267 | 50.7% | 94.3% | 84.1% | 69.6% | 0.447 | 1.38 |
| reseat | 47,722 | 51.6% | 94.0% | 84.9% | 71.5% | 0.458 | 1.24 |
| reseat_stamp_1 | 47,722 | 51.6% | 94.0% | 84.9% | 71.5% | 0.458 | 1.24 |

Same prior on every held-out re-seated record, by span stamp: stamp 0: n 13,400, exact 51.4%, NLL 1.35; stamp 1: n 47,722, exact 51.6%, NLL 1.24; stamp 2: n 3,301, exact 49.4%, NLL 1.28; stamp 4: n 1,761, exact 50.3%, NLL 1.45.

### Learning curve (default subset, held-out default subset)

| training replays | training records | exact | NLL | mean p(human) |
|---|---|---|---|---|
| 100 | 107,448 | 48.0% | 1.425 | 0.416 |
| 200 | 218,604 | 49.7% | 1.339 | 0.438 |
| 339 | 368,117 | 51.3% | 1.283 | 0.455 |

With biases (not convertible): exact 51.6%, NLL 1.283, against bias-free 51.3%, NLL 1.283.

Sequences of 16 with carried state: exact 55.7% [54.7%, 56.9%], NLL 1.160; by position in the window {'0': 0.46212285652268287, '1-3': 0.5757259865971706, '4+': 0.5610786354900704}; the same net at zero state: exact 49.5%, NLL 1.322.

Human states: prefix records + re-seated records in spans that closed equal to the replay (span stamp 1); {'prefix': 20267, 'reseat': 47722} records from 60 held-out replays.

### A1. P(net picks the human's action), by family (zero state, human masks)

| family | n | prior: mean p / argmax match | chain41: mean p / argmax match | chain36: mean p / argmax match | chain9: mean p / argmax match | U1: log p prior - chain 41 | U2: prior - uniform | usable target |
|---|---|---|---|---|---|---|---|---|
| setup | 2,826 | 0.142 / 20% | 0.076 / 8% | 0.088 / 9% | 0.094 / 10% | 97.56 [87.15, 110.96] | 2.63 | yes |
| activate | 9,050 | 0.251 / 28% | 0.080 / 8% | 0.084 / 8% | 0.104 / 10% | 112.24 [107.42, 117.19] | 0.61 | yes |
| end_turn | 296 | 0.079 / 0% | 0.870 / 87% | 0.829 / 83% | 0.772 / 77% | 1.76 [-0.16, 3.82] | -2.11 | no |
| declare_move | 5,652 | 0.803 / 93% | 0.506 / 51% | 0.312 / 31% | 0.531 / 53% | 11.08 [9.85, 12.45] | 1.07 | yes |
| declare_block | 2,192 | 0.708 / 95% | 0.932 / 93% | 0.913 / 91% | 0.934 / 94% | 0.89 [0.53, 1.32] | 1.21 | yes |
| declare_blitz | 1,053 | 0.249 / 4% | 0.481 / 48% | 0.216 / 22% | 0.220 / 22% | 19.32 [17.23, 21.44] | -0.06 | no |
| pass | 49 | 0.006 / 0% | 0.122 / 12% | 0.345 / 35% | 0.191 / 18% | 171.09 [88.86, 253.70] | -2.80 | no |
| handoff | 47 | 0.223 / 23% | 0.133 / 11% | 0.007 / 0% | 0.034 / 4% | 103.43 [59.87, 157.31] | -2.16 | no |
| foul | 100 | 0.272 / 31% | 0.033 / 3% | 0.036 / 2% | 0.005 / 0% | 125.99 [67.99, 197.48] | -0.61 | no |
| declare_other | 42 | 0.077 / 0% | 0.349 / 36% | 0.072 / 7% | 0.024 / 2% | 45.49 [24.58, 70.97] | -1.21 | no |
| move | 31,932 | 0.368 / 42% | 0.330 / 33% | 0.318 / 32% | 0.331 / 33% | 78.92 [70.92, 86.55] | 0.53 | yes |
| block_target | 3,134 | 0.820 / 86% | 0.655 / 65% | 0.653 / 65% | 0.646 / 65% | 55.79 [51.24, 60.33] | 0.79 | yes |
| block_die | 3,252 | 0.691 / 78% | 0.532 / 53% | 0.531 / 53% | 0.532 / 53% | 59.63 [55.33, 64.33] | 0.18 | no |
| push_follow | 4,854 | 0.503 / 53% | 0.432 / 43% | 0.429 / 43% | 0.434 / 43% | 68.09 [63.79, 72.61] | -0.03 | no |
| reroll_skill | 3,245 | 0.831 / 89% | 0.815 / 81% | 0.816 / 82% | 0.809 / 81% | 26.08 [23.14, 28.99] | 0.40 | no |
| other | 265 | 0.475 / 48% | 0.580 / 58% | 0.435 / 44% | 0.356 / 35% | 21.98 [16.40, 28.54] | -0.09 | no |
| ALL | 67,989 | 0.455 / 51% | 0.380 / 38% | 0.354 / 35% | 0.381 / 38% | 69.34 [65.11, 73.54] | 0.61 | yes |

### A2. Marginal family rates on human states, per 1,000 decisions

| family | human | prior | chain41 | chain36 | chain9 |
|---|---|---|---|---|---|
| setup | 41.6 | 41.6 | 41.6 | 41.6 | 41.6 |
| activate | 133.1 | 132.0 | 50.9 | 52.3 | 60.0 |
| end_turn | 4.4 | 5.5 | 86.6 | 85.2 | 77.4 |
| declare_move | 83.1 | 84.8 | 49.6 | 32.5 | 54.6 |
| declare_block | 32.2 | 27.7 | 37.2 | 36.5 | 37.5 |
| declare_blitz | 15.5 | 14.7 | 26.4 | 11.0 | 13.8 |
| pass | 0.7 | 1.9 | 9.8 | 50.2 | 18.8 |
| handoff | 0.7 | 2.1 | 5.9 | 2.5 | 8.3 |
| foul | 1.5 | 2.1 | 0.2 | 0.2 | 0.2 |
| declare_other | 0.6 | 1.0 | 4.2 | 0.5 | 0.1 |
| move | 469.7 | 469.9 | 480.8 | 480.9 | 481.6 |
| block_target | 46.1 | 45.8 | 35.9 | 36.0 | 35.3 |
| block_die | 47.8 | 47.8 | 47.8 | 47.8 | 47.8 |
| push_follow | 71.4 | 71.4 | 71.4 | 71.4 | 71.4 |
| reroll_skill | 47.7 | 47.7 | 47.7 | 47.7 | 47.7 |
| other | 3.9 | 3.9 | 3.9 | 3.9 | 3.9 |

### A3. Declarations where the kind is legal (human states)

| kind | n legal | human rate | prior: T=1 / argmax | chain41: T=1 / argmax | chain36: T=1 / argmax | chain9: T=1 / argmax | human / chain 41 | prior / human |
|---|---|---|---|---|---|---|---|---|
| Block | 2,728 | 0.804 [0.775, 0.831] | 0.692 / 0.929 | 0.928 / 0.927 | 0.909 / 0.911 | 0.934 / 0.937 | 0.87 [0.83, 0.90] | 0.86 [0.83, 0.90] |
| Blitz | 5,702 | 0.185 [0.176, 0.193] | 0.176 / 0.017 | 0.315 / 0.316 | 0.131 / 0.131 | 0.164 / 0.168 | 0.59 [0.54, 0.64] | 0.95 [0.90, 1.00] |
| Pass | 8,885 | 0.003 [0.002, 0.005] | 0.013 / 0.000 | 0.074 / 0.074 | 0.384 / 0.385 | 0.143 / 0.141 | 0.05 [0.03, 0.07] | 3.82 [2.61, 6.48] |
| Handoff | 8,970 | 0.003 [0.002, 0.004] | 0.013 / 0.000 | 0.044 / 0.043 | 0.018 / 0.018 | 0.062 / 0.061 | 0.06 [0.04, 0.09] | 4.58 [3.21, 7.26] |
| Foul | 1,561 | 0.033 [0.023, 0.044] | 0.059 / 0.000 | 0.003 / 0.003 | 0.001 / 0.001 | 0.005 / 0.005 | 11.14 [5.17, 42.73] | 1.80 [1.33, 2.61] |

### A4. Ending the turn while a player could still be activated (human states)

| n | human rate | prior: T=1 / argmax | chain41: T=1 / argmax | chain36: T=1 / argmax | chain9: T=1 / argmax |
|---|---|---|---|---|---|
| 9,346 | 0.032 [0.028, 0.036] | 0.040 / 0.000 | 0.630 / 0.629 | 0.620 / 0.619 | 0.563 / 0.564 |

### B1 and C. Declarations where the kind is legal (chain 41's own states)

208,428 decisions, 300 self-play games, 28,430 declarations.

| kind | n legal | chain 41 sampled | chain 41 T=1 | prior | prior / chain 41 | chain 9 | chain 9 / chain 41 | chain 36 | chain 41 at zero state |
|---|---|---|---|---|---|---|---|---|---|
| Block | 7,371 | 0.825 | 0.825 | 0.589 | 0.71 [0.70, 0.73] | 0.718 | 0.87 [0.86, 0.88] | 0.783 | 0.872 |
| Blitz | 19,584 | 0.140 | 0.140 | 0.237 | 1.69 [1.61, 1.77] | 0.213 | 1.52 [1.43, 1.62] | 0.103 | 0.147 |
| Pass | 25,079 | 0.072 | 0.072 | 0.028 | 0.38 [0.36, 0.41] | 0.149 | 2.08 [1.91, 2.24] | 0.337 | 0.072 |
| Handoff | 27,499 | 0.025 | 0.025 | 0.026 | 1.04 [0.95, 1.16] | 0.041 | 1.66 [1.44, 1.90] | 0.021 | 0.019 |
| Foul | 2,855 | 0.004 | 0.003 | 0.087 | 27.06 [13.85, 75.25] | 0.001 | 0.26 [0.04, 0.99] | 0.002 | 0.003 |

### B2. Ending the turn while a player could still be activated (chain 41's states)

| n | chain 41 sampled | chain 41 | prior | chain 9 | chain 36 |
|---|---|---|---|---|---|
| 34,312 | 0.171 | 0.172 | 0.013 | 0.414 | 0.221 |

### B3. Family rates on chain 41's states, per 1,000 decisions

| family | chain 41 did | prior wants | chain 9 wants | chain 36 wants |
|---|---|---|---|---|
| setup | 125.4 | 125.4 | 125.4 | 125.4 |
| activate | 136.4 | 162.5 | 96.4 | 128.3 |
| end_turn | 28.2 | 2.1 | 68.2 | 36.4 |
| declare_move | 81.9 | 83.4 | 67.6 | 55.5 |
| declare_block | 29.2 | 20.8 | 25.4 | 27.7 |
| declare_blitz | 13.1 | 22.2 | 20.0 | 9.7 |
| pass | 8.6 | 11.9 | 17.9 | 40.6 |
| handoff | 3.3 | 3.5 | 5.4 | 2.8 |
| foul | 0.0 | 1.2 | 0.0 | 0.0 |
| declare_other | 0.2 | 2.0 | 0.0 | 0.1 |
| move | 466.8 | 446.0 | 468.2 | 466.2 |
| block_target | 20.6 | 32.7 | 19.4 | 21.3 |
| block_die | 21.5 | 21.5 | 21.5 | 21.5 |
| push_follow | 25.8 | 25.8 | 25.8 | 25.8 |
| reroll_skill | 33.8 | 33.8 | 33.8 | 33.8 |
| other | 5.0 | 5.0 | 4.9 | 5.0 |

### B4 and C. Mean KL by decision context (chain 41's states, nats)

| context (legal types) | n | share | KL(prior || c41) | KL(c41 || prior) | KL(c9 || c41) | KL(c41 || c9) | KL(c36 || c41) | KL(c41 zero || c41) | KL(prior || c41) >= 0.10 |
|---|---|---|---|---|---|---|---|---|---|
| STEP|END_ACTIVATION | 73,287 | 35.2% | 91.64 | 2.43 | 40.05 | 29.98 | 11.84 | 22.04 | yes |
| ACTIVATE|END_TURN | 34,312 | 16.5% | 87.13 | 2.43 | 14.60 | 10.83 | 4.83 | 1.95 | yes |
| SETUP_PLACE | 21,577 | 10.4% | 78.16 | 11.73 | 23.49 | 17.92 | 8.06 | 0.15 | yes |
| STEP|PASS_TARGET|END_ACTIVATION | 5,588 | 2.7% | 244.03 | 1.97 | 65.23 | 50.95 | 9.54 | 1.54 | yes |
| STEP|JUMP|END_ACTIVATION | 8,839 | 4.2% | 80.75 | 2.21 | 23.64 | 19.88 | 11.99 | 23.86 | yes |
| BLOCK_TARGET|END_ACTIVATION | 5,929 | 2.8% | 115.95 | 2.17 | 24.98 | 25.66 | 6.35 | 1.00 | yes |
| DECLARE | 28,430 | 13.6% | 19.87 | 0.89 | 11.91 | 10.47 | 8.51 | 0.96 | yes |
| KICK_TARGET | 995 | 0.5% | 274.09 | 6.79 | 38.21 | 6.23 | 4.63 | 0.00 | yes |
| CHOOSE_DIE | 4,490 | 2.2% | 50.93 | 0.67 | 0.10 | 0.15 | 0.11 | 0.01 | yes |
| USE_REROLL|DECLINE_REROLL | 6,918 | 3.3% | 31.88 | 0.17 | 0.05 | 0.20 | 0.03 | 0.03 | yes |
| FOLLOW_UP | 2,353 | 1.1% | 91.50 | 0.72 | 0.02 | 0.01 | 0.00 | 0.00 | yes |
| PUSH_SQUARE | 3,017 | 1.4% | 66.96 | 1.06 | 27.05 | 22.32 | 8.05 | 0.08 | yes |
| PASS_TARGET|END_ACTIVATION | 485 | 0.2% | 225.46 | 1.27 | 0.00 | 0.00 | 0.00 | -0.00 | yes |
| TOUCHBACK | 647 | 0.3% | 131.98 | 1.97 | 177.15 | 85.72 | 2.70 | 0.10 | yes |
| ALL | 208,428 | 100% | 78.73 [77.61, 79.76] | 2.94 [2.89, 2.99] | 25.71 [25.33, 26.09] | 19.68 [19.41, 19.97] | 8.26 [8.11, 8.41] | 9.36 [9.14, 9.58] |  |

Mean log-probability of the action chain 41 took: chain41 -0.11, prior -3.05, chain9 -19.81, chain36 -7.19, chain41_zero_state -13.81.

### Opportunity per team turn

|  | team turns | declarations per turn | Block: legal / declared per turn | Blitz: legal / declared per turn | Pass: legal / declared per turn | Hand-off: legal / declared per turn | Foul: legal / declared per turn |
|---|---|---|---|---|---|---|---|
| humans (held-out, default subset) | 1,206 | 7.48 | 2.26 / 1.82 | 4.72 / 0.87 | 7.37 / 0.02 | 7.44 / 0.02 | 1.29 / 0.04 |
| chain 41 self-play | 9,170 | 3.07 | 0.80 / 0.66 | 2.13 / 0.29 | 2.73 / 0.20 | 3.00 / 0.07 | 0.31 / 0.00 |

### D. Added after the first read of the gate (not pre-registered)

D1. Decisions whose legal types are exactly BLOCK_TARGET and END_ACTIVATION and whose declared kind (observation byte 807) is Block: the activation was ended without a block.

|  | decisions in the context | of which declared Block | ended without blocking |
|---|---|---|---|
| humans (held-out, default subset) | 2,163 | 2,163 | 0.009 [0.003, 0.015] |
| chain 41 self-play | 5,929 | 5,929 | 0.391 [0.368, 0.414] |

Each net's mean probability of ending the activation on those human decisions: prior 0.011, chain41 0.195, chain9 0.232, chain36 0.219.

Each net's mean probability of ending the activation on those chain 41's decisions: chain41 0.392, prior 0.009, chain9 0.422, chain36 0.367, chain41_zero_state 0.385.

D2. The decision after a declaration is END_ACTIVATION by the same coach (only declarations whose next decision is verified to be the next one in the game):

| declared | humans: declarations | with a verified next decision | ended at once | chain 41: declarations | with a verified next decision | ended at once |
|---|---|---|---|---|---|---|
| Move | 5,652 | 5,642 | 0.002 [0.001, 0.005] | 17,078 | 17,078 | 0.178 [0.168, 0.188] |
| Block | 2,192 | 2,189 | 0.009 [0.003, 0.015] | 6,083 | 6,083 | 0.383 [0.360, 0.405] |
| Blitz | 1,053 | 1,052 | 0.005 [0.001, 0.010] | 2,732 | 2,732 | 0.149 [0.132, 0.165] |
| Pass | 30 | 29 | 0.000 [0.000, 0.000] | 1,797 | 1,797 | 0.198 [0.176, 0.219] |

D3. Per team turn. Turns are counted from turn-level decisions, so a turn with no declaration counts.

| per team turn | humans, whole turns (re-seated, closed equal) | humans, prefix records (last turn can be cut) | chain 41 self-play |
|---|---|---|---|
| team turns | 899 | 323 | 9,491 |
| declarations (activations) | 7.16 | 7.99 | 2.97 |
| ended by choice with a player left | 0.239 | 0.248 | 0.619 |
| Block-legal declarations | 2.18 | 2.38 | 0.78 |
| Block declared | 1.72 | 1.99 | 0.64 |
| block targets chosen, Block action | 1.68 | 1.95 | 0.38 |
| Blitz declared | 0.86 | 0.85 | 0.28 |
| block targets chosen, Blitz action | 0.81 | 0.79 | 0.07 |
| Pass declared | 0.024 | 0.025 | 0.189 |
| pass targets chosen | 0.017 | 0.012 | 0.000 |
| Foul declared | 0.048 | 0.025 | 0.001 |
| foul targets chosen | 0.046 | 0.025 | 0.000 |

D5. Ending the turn by how many players were already activated in it (whole turns; decisions where both ACTIVATE and END_TURN are legal).

| players already activated | human states: n | humans ended | chain 41 (zero state) would end | prior would end | chain 41's states: n | chain 41 ended | prior would end |
|---|---|---|---|---|---|---|---|
| 0 | 899 | 0.012 | 0.341 | 0.024 | 9,491 | 0.034 | 0.010 |
| 1 | 858 | 0.003 | 0.395 | 0.027 | 7,133 | 0.147 | 0.012 |
| 2 | 832 | 0.006 | 0.492 | 0.031 | 5,383 | 0.228 | 0.013 |
| 3 | 787 | 0.004 | 0.598 | 0.036 | 3,843 | 0.223 | 0.014 |
| 4-5 | 1,408 | 0.016 | 0.726 | 0.045 | 4,940 | 0.253 | 0.015 |
| 6-7 | 1,130 | 0.050 | 0.853 | 0.057 | 2,345 | 0.368 | 0.017 |
| 8+ | 741 | 0.155 | 0.917 | 0.063 | 900 | 0.349 | 0.023 |

D4. Mean probability each net gives the action chain 41 took (chain 41's states):

| context | n | chain 41 (as played) | chain 41 at zero state | chain 36 | chain 9 | prior |
|---|---|---|---|---|---|---|
| ALL | 208,428 | 0.94 | 0.77 | 0.69 | 0.51 | 0.29 |
| STEP|END_ACTIVATION | 73,287 | 0.98 | 0.61 | 0.69 | 0.42 | 0.17 |
| ACTIVATE|END_TURN | 34,312 | 0.95 | 0.90 | 0.69 | 0.49 | 0.12 |
| DECLARE | 28,430 | 0.98 | 0.93 | 0.64 | 0.60 | 0.60 |
| SETUP_PLACE | 21,577 | 0.65 | 0.64 | 0.30 | 0.15 | 0.01 |
| STEP|JUMP|END_ACTIVATION | 8,839 | 0.97 | 0.55 | 0.68 | 0.54 | 0.20 |
| USE_REROLL|DECLINE_REROLL | 6,918 | 1.00 | 1.00 | 1.00 | 1.00 | 0.87 |
| BLOCK_TARGET|END_ACTIVATION | 5,929 | 1.00 | 0.96 | 0.90 | 0.78 | 0.48 |
| STEP|PASS_TARGET|END_ACTIVATION | 5,588 | 0.99 | 0.94 | 0.87 | 0.48 | 0.22 |
| CHOOSE_DIE | 4,490 | 1.00 | 1.00 | 1.00 | 0.99 | 0.61 |
| END_ACTIVATION | 3,712 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| PUSH_SQUARE | 3,017 | 0.99 | 0.98 | 0.84 | 0.62 | 0.42 |
| STAND_UP|END_ACTIVATION | 2,502 | 0.99 | 0.97 | 0.90 | 0.68 | 0.73 |
| FOLLOW_UP | 2,353 | 1.00 | 1.00 | 1.00 | 1.00 | 0.51 |

### The five examples

1. **STEP|END_ACTIVATION** (game 179, step 111, symmetric KL 171.61). Half 1, turn 3 (opponent 2), score 0-0, ball held by opp Beastman Lineman at (6,2). Acting player: own Stilty Runna at (18,4). Chain 41 did: **end activation** (its p 1.00; prior's p 0.00). Chain 41's top: end activation 1.00; step (17,3) 0.00; step (19,5) 0.00. Prior's top: step (18,3) 0.35; step (19,3) 0.21; step (17,4) 0.18.
2. **ACTIVATE|END_TURN** (game 184, step 803, symmetric KL 144.54). Half 2, turn 8 (opponent 8), score 0-3, ball held by own Hobgoblin Lineman at (9,5). Acting player: None. Chain 41 did: **activate own Hobgoblin Lineman at (9,5)** (its p 1.00; prior's p 0.07). Chain 41's top: activate own Hobgoblin Lineman at (9,5) 1.00; activate own Bull Centaur at (11,5) 0.00; activate own Chaos Dwarf Blocker at (11,6) 0.00. Prior's top: activate own Bull Centaur at (12,4) 0.15; activate own Bull Centaur at (11,5) 0.14; activate own Chaos Dwarf Blocker at (9,6) 0.13.
3. **STEP|PASS_TARGET|END_ACTIVATION** (game 86, step 369, symmetric KL 518.21). Half 2, turn 2 (opponent 1), score 0-0, ball held by own Skink Lineman at (24,0). Acting player: own Skink Lineman at (24,0). Chain 41 did: **step (25,1)** (its p 1.00; prior's p 0.04). Chain 41's top: step (25,1) 1.00; end activation 0.00; pass target (25,1) 0.00. Prior's top: step (25,0) 0.73; end activation 0.15; step (25,1) 0.04.
4. **STEP|JUMP|END_ACTIVATION** (game 266, step 65, symmetric KL 159.86). Half 1, turn 2 (opponent 1), score 0-0, ball held by own Fun-hoppa at (18,3). Acting player: own Fun-hoppa at (18,3). Chain 41 did: **step (19,2)** (its p 1.00; prior's p 0.12). Chain 41's top: step (19,2) 1.00; end activation 0.00; step (19,3) 0.00. Prior's top: step (19,3) 0.45; end activation 0.34; step (19,2) 0.12.
5. **BLOCK_TARGET|END_ACTIVATION** (game 27, step 440, symmetric KL 344.49). Half 2, turn 1 (opponent 0), score 0-2, ball held by own Bretonnian Squire at (14,1). Acting player: own Bretonnian Squire at (12,4). Chain 41 did: **end activation** (its p 1.00; prior's p 0.01). Chain 41's top: end activation 1.00; block target (13,4) (opp Jaguar Warrior at (13,4)) 0.00; block target (13,5) (opp Eagle Warrior at (13,5)) 0.00. Prior's top: block target (13,5) (opp Eagle Warrior at (13,5)) 0.66; block target (13,4) (opp Jaguar Warrior at (13,4)) 0.34; end activation 0.01.

### Verdict (computed by the registered rule)

```json
{
 "thresholds": {
  "ratio_min": 1.5,
  "gap_min": 0.05,
  "faithful": [
   0.8,
   1.25
  ],
  "u1_min": 0.2,
  "u2_min": 0.5,
  "act_kl_min": 0.1
 },
 "BLOCK": {
  "gate_B": false,
  "gate_B_ratio": {
   "value": 0.7139011989916128,
   "lo": 0.6982709369551583,
   "hi": 0.7301431869056776,
   "resamples_with_zero_denominator": 0
  },
  "gate_B_gap": -0.23599221897158862,
  "gate_A": false,
  "gate_A_ratio": {
   "value": 0.8656212784510012,
   "lo": 0.8344854153424157,
   "hi": 0.8965592038440652,
   "resamples_with_zero_denominator": 0
  },
  "gate_A_gap": -0.12473799677044839,
  "prior_over_human": 0.8606586987764513,
  "prior_faithful": true,
  "proceed": false
 },
 "BLITZ": {
  "gate_B": true,
  "gate_B_ratio": {
   "value": 1.6904231848667248,
   "lo": 1.6138928654407703,
   "hi": 1.7743281072713153,
   "resamples_with_zero_denominator": 0
  },
  "gate_B_gap": 0.09662637077163194,
  "gate_A": false,
  "gate_A_ratio": {
   "value": 0.585562435398493,
   "lo": 0.5399384274591493,
   "hi": 0.6388719671273297,
   "resamples_with_zero_denominator": 0
  },
  "gate_A_gap": -0.13070345348367954,
  "prior_over_human": 0.9516263083333251,
  "prior_faithful": true,
  "proceed": false
 },
 "verdict": "STOP (gate B passes but gate A or prior fidelity does not)",
 "anchor_C_declarations": {
  "kl_prior__chain41": 19.868773938726996,
  "kl_chain41__prior": 0.887109476743084,
  "kl_chain9__chain41": 11.910939856524074,
  "kl_chain41__chain9": 10.467837437229356
 },
 "anchor_C_prior_gap_is_larger_than_lineage_drift": false
}
```

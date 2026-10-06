## Transfer of m1

| opponent | pair | W/D/L | decisive share | decisive-Elo [95%] | TD for | TD against | blocks per game |
|---|---|---|---|---|---|---|---|
| offense | chain41m1 | 951/1725/524 | 0.645 | 103.5 [86.6, 120.8] | 0.411 | 0.275 | 11.4 |
| offense | chain41 | 1024/1658/518 | 0.664 | 118.4 [100.6, 137.1] | 0.430 | 0.279 | 7.4 |
| contact | chain41m1 | 1118/1448/634 | 0.638 | 98.5 [82.6, 115.6] | 0.560 | 0.376 | 8.1 |
| contact | chain41 | 1102/1393/705 | 0.610 | 77.6 [61.5, 94.0] | 0.542 | 0.402 | 5.4 |
| chain27 | chain41m1 | 1651/1089/460 | 0.782 | 222.0 [204.5, 239.1] | 1.128 | 0.538 | 11.7 |
| chain27 | chain41 | 1635/1007/558 | 0.746 | 186.8 [171.3, 202.9] | 1.190 | 0.630 | 7.9 |
| chain36 | chain41m1 | 1492/1143/565 | 0.725 | 168.7 [153.7, 185.1] | 1.108 | 0.668 | 10.8 |
| chain36 | chain41 | 1398/1144/658 | 0.680 | 130.9 [117.1, 144.8] | 1.172 | 0.794 | 7.6 |
| chain47 | chain41m1 | 872/1403/925 | 0.485 | -10.3 [-24.5, 4.4] | 0.680 | 0.725 | 9.4 |
| chain47 | chain41 | 822/1263/1115 | 0.424 | -53.0 [-67.7, -38.6] | 0.709 | 0.860 | 6.9 |

| opponent | m1 minus plain, decisive-Elo [95%] | verdict | score-rate contrast [95%] |
|---|---|---|---|
| offense | -14.8 [-35.9, 4.6] | inconclusive | -0.012 [-0.025, -0.001] |
| contact | 20.9 [2.0, 39.5] | better, non-inferior | 0.014 [-0.001, 0.027] |
| chain27 | 35.2 [15.1, 56.0] | better, non-inferior | 0.018 [0.003, 0.033] |
| chain36 | 37.8 [18.9, 57.0] | better, non-inferior | 0.029 [0.014, 0.044] |
| chain47 | 42.7 [23.5, 60.6] | better, non-inferior | 0.037 [0.022, 0.052] |

## m1 + m2 against plain chain 41

W/D/L 979/1398/823; decisive share 0.543; decisive-Elo 30.2 [15.7, 44.7]; verdict: better, non-inferior; draw rate 0.437; 987 engine steps a game

| metric | A | B | A - B [95%] |
|---|---|---|---|
| activations per team turn | 5.952 | 3.103 | 2.849 [2.807, 2.889] |
| turns ended by choice with a player left, per team turn | 0.000 | 0.622 | -0.622 [-0.627, -0.617] |
| block targets chosen per game | 15.323 | 6.646 | 8.677 [8.519, 8.831] |
| block targets inside a Blitz per game | 1.347 | 1.333 | 0.015 [-0.034, 0.063] |
| block targets inside a Block per game | 13.976 | 5.313 | 8.663 [8.508, 8.811] |
| turnovers per team turn | 0.558 | 0.309 | 0.250 [0.244, 0.256] |
| touchdowns per game | 0.766 | 0.689 | 0.077 [0.044, 0.108] |
| possession (turns ended holding the ball) | 0.403 | 0.397 | 0.006 [-0.001, 0.013] |
| activations ended at once, per activation | 0.002 | 0.209 | -0.208 [-0.211, -0.204] |
| activations ended with a block target on offer (Block or Blitz), per game | 0.585 | 3.373 | -2.788 [-2.881, -2.702] |
| Block declared per team turn | 0.906 | 0.527 | 0.379 [0.370, 0.389] |
| Blitz declared per team turn | 0.365 | 0.312 | 0.053 [0.047, 0.059] |
| Pass declared per team turn | 0.241 | 0.182 | 0.058 [0.054, 0.063] |
| pass targets chosen per game | 0.001 | 0.000 | 0.001 [0.000, 0.002] |
| foul targets chosen per game | 0.003 | 0.001 | 0.002 [-0.000, 0.004] |
| team turns per game | 15.843 | 15.838 | 0.006 [0.001, 0.012] |
| engine steps per game (both sides) | 987.350 | 987.350 | 0.000 [0.000, 0.000] |

## Null control: plain against plain, shifted sampling seeds

W/D/L 880/1382/938; decisive share 0.484; decisive-Elo -11.1 [-25.4, 2.8]; draw rate 0.432; 695 engine steps a game

| metric | A | B | A - B [95%] |
|---|---|---|---|
| activations per team turn | 2.984 | 2.968 | 0.016 [-0.013, 0.046] |
| turns ended by choice with a player left, per team turn | 0.617 | 0.615 | 0.002 [-0.003, 0.008] |
| block targets chosen per game | 7.332 | 7.322 | 0.010 [-0.107, 0.136] |
| block targets inside a Blitz per game | 1.190 | 1.182 | 0.008 [-0.038, 0.055] |
| block targets inside a Block per game | 6.142 | 6.140 | 0.002 [-0.109, 0.112] |
| turnovers per team turn | 0.317 | 0.318 | -0.001 [-0.007, 0.005] |
| touchdowns per game | 0.730 | 0.754 | -0.024 [-0.057, 0.007] |
| possession (turns ended holding the ball) | 0.411 | 0.419 | -0.009 [-0.016, -0.001] |
| activations ended at once, per activation | 0.218 | 0.220 | -0.001 [-0.006, 0.003] |
| activations ended with a block target on offer (Block or Blitz), per game | 4.241 | 4.223 | 0.018 [-0.105, 0.138] |
| Block declared per team turn | 0.644 | 0.645 | -0.001 [-0.011, 0.009] |
| Blitz declared per team turn | 0.288 | 0.281 | 0.007 [0.002, 0.012] |
| Pass declared per team turn | 0.187 | 0.185 | 0.002 [-0.002, 0.007] |
| pass targets chosen per game | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| foul targets chosen per game | 0.000 | 0.000 | -0.000 [-0.001, 0.000] |
| team turns per game | 15.832 | 15.829 | 0.003 [-0.004, 0.010] |
| engine steps per game (both sides) | 694.977 | 694.977 | 0.000 [0.000, 0.000] |

## Both sides under m1

W/D/L 836/1561/803; decisive share 0.510; decisive-Elo 7.0 [-7.7, 21.0]; draw rate 0.488; 1202 engine steps a game

| metric | A | B | A - B [95%] |
|---|---|---|---|
| activations per team turn | 6.858 | 6.874 | -0.016 [-0.064, 0.031] |
| turns ended by choice with a player left, per team turn | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| block targets chosen per game | 10.628 | 10.582 | 0.045 [-0.119, 0.208] |
| block targets inside a Blitz per game | 1.305 | 1.251 | 0.055 [0.006, 0.109] |
| block targets inside a Block per game | 9.322 | 9.332 | -0.009 [-0.169, 0.148] |
| turnovers per team turn | 0.422 | 0.418 | 0.004 [-0.002, 0.009] |
| touchdowns per game | 0.585 | 0.577 | 0.008 [-0.020, 0.037] |
| possession (turns ended holding the ball) | 0.394 | 0.399 | -0.005 [-0.012, 0.002] |
| activations ended at once, per activation | 0.423 | 0.425 | -0.002 [-0.006, 0.003] |
| activations ended with a block target on offer (Block or Blitz), per game | 7.537 | 7.610 | -0.072 [-0.228, 0.074] |
| Block declared per team turn | 1.051 | 1.057 | -0.006 [-0.017, 0.005] |
| Blitz declared per team turn | 0.414 | 0.412 | 0.002 [-0.004, 0.008] |
| Pass declared per team turn | 0.270 | 0.271 | -0.002 [-0.007, 0.003] |
| pass targets chosen per game | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| foul targets chosen per game | 0.002 | 0.000 | 0.002 [0.001, 0.003] |
| team turns per game | 15.850 | 15.852 | -0.002 [-0.007, 0.002] |
| engine steps per game (both sides) | 1202.217 | 1202.217 | 0.000 [0.000, 0.000] |

## What an activation did, per team turn

| | chain 41 + m1 (five transfer runs) | plain chain 41 (same runs) | chain 41 + m1 v chain 47 | plain chain 41 v chain 47 | m1 + m2 v plain | both under m1 | plain v plain (null) |
|---|---|---|---|---|---|---|---|
| activations | 7.178 | 2.963 | 6.904 | 3.016 | 5.952 | 6.858 | 2.984 |
| empty | 3.182 | 0.735 | 3.003 | 0.650 | 0.010 | 2.903 | 0.651 |
| moved | 3.278 | 1.738 | 3.243 | 1.891 | 4.910 | 3.215 | 1.829 |
| block | 0.574 | 0.374 | 0.521 | 0.362 | 0.882 | 0.588 | 0.388 |
| blitz | 0.073 | 0.071 | 0.072 | 0.073 | 0.085 | 0.082 | 0.075 |
| foul | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| pass_handoff | 0.002 | 0.001 | 0.003 | 0.001 | 0.003 | 0.003 | 0.001 |
| no_decision | 0.037 | 0.020 | 0.036 | 0.020 | 0.035 | 0.037 | 0.019 |
| other | 0.032 | 0.025 | 0.027 | 0.020 | 0.026 | 0.028 | 0.020 |
| moved: mean net displacement in squares | 2.464 | 2.979 | 2.669 | 3.147 | 2.103 | 2.568 | 3.074 |
| moved: mean change in distance to the ball | -0.389 | -0.571 | -0.265 | -0.333 | -0.269 | -0.265 | -0.320 |
| moved: mean change in distance from own end zone | 0.061 | 0.127 | 0.035 | 0.061 | 0.110 | -0.016 | 0.119 |
| activations that ended the turn in a turnover | 0.371 | 0.274 | 0.409 | 0.315 | 0.558 | 0.422 | 0.317 |

| negative-trait activations | chain 41 + m1 (five transfer runs) | plain chain 41 (same runs) | chain 41 + m1 v chain 47 | plain chain 41 v chain 47 | m1 + m2 v plain | both under m1 | plain v plain (null) |
|---|---|---|---|---|---|---|---|
| activations per game | 8.241 | 6.100 | 7.727 | 5.855 | 7.618 | 7.857 | 6.030 |
| came out distracted or rooted | 0.084 | 0.076 | 0.085 | 0.073 | 0.084 | 0.085 | 0.073 |
| ended at once | 0.238 | 0.174 | 0.223 | 0.142 | 0.019 | 0.219 | 0.146 |
| engine ended it | 0.067 | 0.049 | 0.068 | 0.050 | 0.067 | 0.067 | 0.047 |
| blocked or blitzed | 0.305 | 0.387 | 0.333 | 0.433 | 0.379 | 0.331 | 0.429 |
| turn ended in turnover there | 0.128 | 0.158 | 0.146 | 0.180 | 0.165 | 0.140 | 0.180 |
| failures per game | 0.695 | 0.466 | 0.661 | 0.430 | 0.642 | 0.669 | 0.438 |
| turnovers there per game | 1.054 | 0.962 | 1.130 | 1.055 | 1.260 | 1.097 | 1.085 |


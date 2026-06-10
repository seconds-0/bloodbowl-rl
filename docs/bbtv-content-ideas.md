# BBTV content idea bank — mined from FFB client source (2026-06-10)

*Source: vendor/ffb (FUMBBL production client). Every string verbatim from
source. This is the content/alert/layout reference for BBTV v3+. (BB3 by
Cyanide is proprietary — no source; its Cabalvision broadcast FRAMING is the
tonal reference: casters, replays, crowd shots.)*

## 1. Play-by-play templates (ReportMessage* classes)
Verb-first, name-driven, colon before dice:
- "{Player} blocks {Opponent}:" / "{Player} blitzes {Opponent}:"
- "Block Roll [ SKULL | BOTH DOWN | PUSHBACK | POW/PUSH | POW ]"
- "Dodge Roll [ {n} ]" → "{Player} dodges successfully." / "{Player} trips while dodging."
- "{Thrower} passes the ball to {Catcher}:" / "...to an empty field:" / "{Thrower} fumbles the ball." / "{Thrower} holds on to the ball."
- "{Player} tries to catch the ball:" → "catches" / "fails the catch."
- "{Player} tries to intercept the ball:" → "intercepts" / "fails to intercept."
- "{Attacker} fouls {Defender}:" · "{Player} uses {Skill}."
- "{Player} scores a touchdown."
- "Knocked Out Recovery Roll [ {n} ]" → "is regaining consciousness." / "stays unconscious."
- "Succeeded on a roll of {min}+" / "Roll a {min}+ to succeed"
- Apothecary: "The apothecary patches {Player} up so {pronoun} is able to play again."

CASUALTY TABLE (red text, with stat loss):
Seriously Hurt (Miss next game) · Serious Injury (Niggling) · Head Injury (-1 AV)
· Smashed Knee (-1 MA) · Broken Arm (-1 PA) · Neck Injury (-1 AG)
· Dislocated Shoulder (-1 ST) · **Dead (RIP)**
Log form: "{Player} suffered a smashed knee (-1 MA)" / "{Player} is dead"

Crowd/FAME: "{N} fans have come to support {Team}." · "Team {T} have the whole
audience with them (FAME +2)!" · Vampire flavor: "heads off to the spectator
ranks to bite some beautiful maiden."

## 2. Sound-event taxonomy (SoundId.java, 37 sounds) = alert checklist
Action: BLOCK DODGE CATCH PICKUP THROW KICK · Failure: BLUNDER DUH
Physics: BOUNCE FALL STEP · Event: INJURY KO RIP STAB FOUL METAL(chainsaw)
EXPLODE VOMIT NOMNOM SLURP TRAPDOOR YOINK · Magic: LIGHTNING ZAP FIREBALL HYPNO
Game: WHISTLE (turn end!) · UI: DING CLICK
CROWD (the emotional layer): SPEC_AAH SPEC_BOO SPEC_CHEER SPEC_CLAP
SPEC_CRICKETS SPEC_HURT SPEC_LAUGH SPEC_OOH SPEC_SHOCK SPEC_STOMP ROAR
WOOOAAAH PUMP_CROWD
→ BBTV mapping: every feed kind gets a sound class; crowd reacts to TD
(SPEC_CHEER+ROAR), cas (SPEC_SHOCK→SPEC_HURT), failed gfi (SPEC_LAUGH),
boring turns (SPEC_CRICKETS). WHISTLE on turnover/turn end.

## 3. Alert modality (DialogId.java, 36 dialogs)
MODAL in FFB (for BBTV = banner/slam treatment since no input): TD, game end
(GAME_STATISTICS), KICK_OFF_RESULT announcements, APOTHECARY_CHOICE moments.
Log-line only: routine rolls, skill uses. BBTV: banners = TD / turnover /
first blood / kickoff event / MVP+final; everything else → action log.

## 4. Layout (FFB UserInterface)
Score bar top (score | turn/half | weather icon | spectator count); home/away
SIDEBARS flanking the pitch each with: PlayerDetail card (name/number/position,
MA ST AG PA AV, SPP, skills list, injuries), Resource grid (rerolls,
apothecaries, kegs, cards), TurnDiceStatus (whose turn + status line); dugout
box (KO/reserves/cas). Log+chat strip below pitch.
→ BBTV v3: hover/click a player = PlayerDetail card; reroll/apo counters per
side; 8 turn pips per half (already in v2 spec).

## 5. Kickoff events + weather (announce as centered banner + description)
BB2025 kickoff table: Get the Ref (free bribes) · Time-out · Solid Defence
(reorganize D3+3) · High Kick · Cheering Fans (Prayer) · Weather Change ·
Brilliant Coaching (reroll) · Quick Snap · Blitz! (defence free turn) ·
Officious Ref · Pitch Invasion · Charge · Dodgy Snack.
Format: "Kick-off Event Roll [ d ][ d ]" → "Kick-off event is {Name}" → desc.
Weather: Sweltering Heat / Very Sunny / Nice / Pouring Rain / Blizzard.

## 6. Game-end flavor
"Most Valuable Players" jury lines · "{Team} win the game." (team color) ·
"The game ends in a tie." · concession lines. BBTV: MVP card + final-score
plate between matches (we already have next_match_in_s dead air to fill).

## Implementation queue (BBTV v3 backlog, in value order)
1. Play-by-play GENERATOR server-side: feed templates above + player position
   names → richer feed[] lines (needs only existing delta data + tag_positions).
2. Kickoff-event + weather detection → banner messages (weather byte is in obs
   scalars; kickoff events need a C-side feed export — same export as dice).
3. Sound layer (web audio, files or synth blips keyed to feed kinds + crowd).
4. PlayerDetail hover card (data already in snapshot players[]).
5. MVP/final plate between matches.
6. C-side feed/dice export → literal Block Roll [POW] strings + casualty names.

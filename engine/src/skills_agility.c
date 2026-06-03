// skills_agility.c — Agility-category skill implementations (hook registrations).
//
// Each entry quotes the BB2025 reference (docs/vendor/bloodbowlbase mirror,
// core_rules/skills_and_traits) it implements. Of the twelve Agility skills,
// Catch, Dodge, Sidestep, Sprint and Sure Feet are already registered in
// skills_core.c / bb_skills.c. Every remaining Agility skill changes a
// procedure (decision windows, movement legality, ball placement, assist
// cancellation) and is NOT expressible through the bb_hooks registration
// classes, so nothing registers here yet. The audit below records the
// blocking effect for each so that, when the procedure work lands, any
// hook-expressible residue is registered in this file.
//
// DIVING CATCH: "may attempt to Catch the ball if it lands in a square in
// their Tackle Zone as a result of a Pass, Throw-in or Kick-off" (not a
// Bounce), and "+1 modifier ... when attempting to Catch the ball as part of
// a Pass Action if they are in the target square." Blocked: CATCH frames
// carry only a base modifier (proc_ball.c), so the catch ctx cannot
// distinguish a pass-target catch from a hand-off or bounce; even the +1
// needs a catch-source tag, and the adjacent-square attempt needs a landing
// decision window.
//
// DIVING TACKLE: "When an opposition player attempts to leave this player's
// Tackle Zone as a result of a Dodge, Leap or Jump, and an Agility test has
// been rolled and any modifiers and re-rolls have been applied, this player
// may use this Skill. Immediately apply a -2 modifier ... and place this
// player Prone in the square the opposition player vacated." Blocked:
// post-re-roll optional interrupt, not a pre-roll aura (May 2026 FAQ: the
// user occupies the vacated square, pre-empting Shadowing).
//
// DEFENSIVE: "During your opponent's Turns, opposition players Marked by
// this player cannot use the Guard or Put the Boot In Skills." Blocked: no
// skill-cancellation hook class; Guard eligibility is a direct check in
// bb_can_assist (bb_skills.c).
//
// HIT AND RUN: "When a player with this Skill performs a Block Action or a
// Stab Special Action, after fully resolving the Action, they may
// immediately move one free square ignoring Tackle Zones, so long as they
// are still Standing." Blocked: post-action free-move decision window (May
// 2026 FAQ: granted even when Stab-in-a-Blitz ends the activation).
//
// JUMP UP: "A Prone player with this Skill can stand up for free without
// having to spend 3 squares of movement", and may "declare a Block Action
// whilst Prone" passing an Agility Test at +1. Blocked: stand-up cost and
// prone Block declaration are movement/activation legality in
// proc_move/proc_turn.
//
// LEAP: "can attempt to Leap over a single adjacent square regardless of
// what is in the square", reducing Jump negative modifiers "by 1, to a
// minimum of -1." Blocked: jump-target legality and the modifier floor live
// in proc_move.
//
// SAFE PAIR OF HANDS: "If this player would be Knocked Down, Fall Over or be
// Placed Prone whilst in possession of the ball then, before they become
// Prone, they may place the ball in any adjacent unoccupied square ...
// instead of Bouncing the ball as normal." Blocked: replaces the bounce in
// the ball-drop path with a coach placement choice.
#include "bb/bb_hooks.h"

// DIVING CATCH (partial): "+1 modifier to their Agility Test when attempting
// to Catch the ball as part of a Pass Action if they are in the target
// square." (The land-in-TZ diving attempt window remains in the
// needs-proc-integration audit above.)
BB_SKILL_MOD(DIVING_CATCH) {
    (void)m;
    return (c->kind == BB_TEST_CATCH && c->range_band == 1) ? 1 : 0;
}

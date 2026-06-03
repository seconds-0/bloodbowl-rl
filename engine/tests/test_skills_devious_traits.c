// test_skills_devious_traits.c — BB2025 RULEBOOK tests for the Devious-skill /
// Trait batch (skills_devious_traits.c): Titchy, Drunkard, Insignificant.
//
// Authoritative source, under docs/vendor/bloodbowlbase/bloodbowlbase.ru/
// bb2025/core_rules/:
//   SK  = skills_and_traits/index.html (TITCHY, DRUNKARD, INSIGNIFICANT)
//
// Scripted dice (bb_rng_script) choose every die face.
#include "bb/bb_hooks.h"
#include "bb/bb_match.h"
#include "bb/bb_skills.h"
#include "bb_fixtures.h"
#include "bb_test.h"

static bb_action act(int type, int arg, int x, int y) {
    bb_action a = {(uint8_t)type, (uint8_t)arg, (uint8_t)x, (uint8_t)y};
    return a;
}

// Drive the fixture to the mover's movement decision point:
// run -> ACTIVATE slot -> DECLARE Move.
static bb_status begin_move(bb_match* m, bb_rng* rng, int slot) {
    bb_status st = fx_run(m, rng);
    if (st != BB_STATUS_DECISION) return st;
    st = fx_apply(m, act(BB_A_ACTIVATE, slot, 0, 0), rng);
    if (st != BB_STATUS_DECISION) return st;
    return fx_apply(m, act(BB_A_DECLARE, BB_ACT_MOVE, 0, 0), rng);
}

// =============================================================================
// Titchy
// =============================================================================

// SK "TITCHY* (Passive)": "A player with this Trait may apply a +1 modifier
// to the Agility Test when attempting to Dodge." AG 3+ dodging into an
// unmarked square needs only a 2 with Titchy; without it, the 2 fails.
BB_TEST(skdt_titchy_dodge_plus1) {
    { // With Titchy: a natural 2 passes (3+ improved to 2+).
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+
        fx_give_skill(&m, mover, BB_SK_TITCHY);
        fx_lineman(&m, 1, 0, 10, 8); // marks origin (10,7) only
        static const uint8_t dice[] = {2};
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);

        bb_status st = begin_move(&m, &rng, mover);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].y, 6);
        BB_CHECK_EQ(m.active_team, BB_HOME);
    }
    { // Control, no Titchy: the same natural 2 fails the bare 3+.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        fx_lineman(&m, 1, 0, 10, 8);
        static const uint8_t dice[] = {2, 3, 3}; // dodge fails; armour holds
        bb_rng rng;
        bb_rng_script(&rng, dice, 3);

        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
        BB_CHECK_EQ(m.active_team, BB_AWAY); // turnover
    }
}

// SK "TITCHY* (Passive)": "when an opposition player attempts to Dodge into
// a square within this player's Tackle Zone, this player will not apply a -1
// modifier to the opposition player's Agility Test for Marking the
// opposition player." A destination Marked only by a Titchy player is dodged
// into at an unmodified AG 3+; a second (non-Titchy) marker still applies
// its own -1.
BB_TEST(skdt_titchy_aura_cancels_own_destination_minus1) {
    { // Destination marked by the Titchy player only: bare 3+ (3 passes).
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+, no skills
        fx_lineman(&m, 1, 0, 10, 8);             // marks origin (10,7) only
        int titchy = fx_lineman(&m, 1, 1, 9, 5); // marks dest (10,6) only
        fx_give_skill(&m, titchy, BB_SK_TITCHY);
        static const uint8_t dice[] = {3};
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);

        bb_status st = begin_move(&m, &rng, mover);
        BB_CHECK_EQ(bb_tackle_zones(&m, BB_HOME, 10, 6), 1); // Titchy marks dest
        st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].y, 6);
        BB_CHECK_EQ(m.active_team, BB_HOME);
    }
    { // Titchy + a normal marker on the destination: net -1, a 4 passes.
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        fx_lineman(&m, 1, 0, 10, 8);              // marks origin only
        int titchy = fx_lineman(&m, 1, 1, 9, 5);  // marks dest (10,6)
        fx_give_skill(&m, titchy, BB_SK_TITCHY);
        fx_lineman(&m, 1, 2, 11, 5);              // normal, marks dest (10,6)
        static const uint8_t dice[] = {4};
        bb_rng rng;
        bb_rng_script(&rng, dice, 1);

        bb_status st = begin_move(&m, &rng, mover);
        BB_CHECK_EQ(bb_tackle_zones(&m, BB_HOME, 10, 6), 2);
        st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
        BB_CHECK_EQ(m.players[mover].y, 6);
    }
    { // Same two markers: a 3 fails (proving the non-Titchy -1 survived).
        bb_match m;
        fx_match_midturn(&m, BB_HOME, 0);
        int mover = fx_lineman(&m, 0, 0, 10, 7);
        fx_lineman(&m, 1, 0, 10, 8);
        int titchy = fx_lineman(&m, 1, 1, 9, 5);
        fx_give_skill(&m, titchy, BB_SK_TITCHY);
        fx_lineman(&m, 1, 2, 11, 5);
        static const uint8_t dice[] = {3, 3, 3}; // dodge fails; armour holds
        bb_rng rng;
        bb_rng_script(&rng, dice, 3);

        bb_status st = begin_move(&m, &rng, mover);
        st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
        BB_CHECK_EQ(st, BB_STATUS_DECISION);
        BB_CHECK(!bb_rng_error(&rng));
        BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
        BB_CHECK_EQ(m.active_team, BB_AWAY);
    }
}

// SK "TITCHY* (Passive)" + RR "Prone and Stunned Players": a Prone Titchy
// player exerts no Tackle Zone, so it is not Marking the destination — there
// is no -1 to cancel and the aura must NOT fire. The dodge stays a bare AG
// 3+, so a natural 2 fails (were the aura wrongly applied, the target would
// improve to 2+ and the 2 would pass).
BB_TEST(skdt_titchy_prone_no_aura) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7);
    fx_lineman(&m, 1, 0, 10, 8);              // marks origin only
    int titchy = fx_lineman(&m, 1, 1, 9, 5);  // adjacent to dest (10,6)
    fx_give_skill(&m, titchy, BB_SK_TITCHY);
    m.players[titchy].stance = BB_STANCE_PRONE; // no TZ: not Marking
    static const uint8_t dice[] = {2, 3, 3}; // dodge 2 fails 3+; armour holds
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);

    bb_status st = begin_move(&m, &rng, mover);
    BB_CHECK_EQ(bb_tackle_zones(&m, BB_HOME, 10, 6), 0);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.active_team, BB_AWAY);
}

// =============================================================================
// Drunkard
// =============================================================================

// SK "DRUNKARD* (Passive)": "This player applies a -1 modifier to test
// whenever they attempt to Rush." The hook table must yield -1 for a
// BB_TEST_RUSH context and 0 for every other test kind. (proc_move.c still
// computes the Rush target inline without consulting bb_hook_mods — the
// in-game wiring is tracked as a proc-integration item, so this asserts the
// registered modifier directly.)
BB_TEST(skdt_drunkard_rush_mod_registered) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int p = fx_lineman(&m, 0, 0, 5, 7);
    fx_give_skill(&m, p, BB_SK_DRUNKARD);
    fx_lineman(&m, 1, 9, 24, 1);

    bb_ctx rush = {BB_TEST_RUSH, (uint8_t)p, BB_NO_PLAYER, (uint8_t)p, 5, 7, 6, 7, -1, 0};
    BB_CHECK_EQ(bb_hook_mods(&m, &rush), -1);
    bb_ctx dodge = {BB_TEST_DODGE, (uint8_t)p, BB_NO_PLAYER, (uint8_t)p, 5, 7, 6, 7, -1, 0};
    BB_CHECK_EQ(bb_hook_mods(&m, &dodge), 0);
    bb_ctx pickup = {BB_TEST_PICKUP, (uint8_t)p, BB_NO_PLAYER, (uint8_t)p, 5, 7, 6, 7, -1, 0};
    BB_CHECK_EQ(bb_hook_mods(&m, &pickup), 0);
}

// =============================================================================
// Insignificant
// =============================================================================

// SK "INSIGNIFICANT* (Passive)": "When creating a Team Draft List, you may
// not include more players with this Trait than players without this Trait."
// A pure team-draft constraint: the trait registers NO match-time hooks, and
// an Insignificant player plays out a test (here a Dodge at bare AG 3+)
// exactly as if the trait were absent.
BB_TEST(skdt_insignificant_no_match_time_effect) {
    // No hook of any class is registered for the trait.
    BB_CHECK(bb_hooks[BB_SK_INSIGNIFICANT].mod == 0);
    BB_CHECK(bb_hooks[BB_SK_INSIGNIFICANT].aura == 0);
    BB_CHECK(bb_hooks[BB_SK_INSIGNIFICANT].armour_mod == 0);
    BB_CHECK(bb_hooks[BB_SK_INSIGNIFICANT].injury_mod == 0);
    BB_CHECK_EQ(bb_hooks[BB_SK_INSIGNIFICANT].reroll_kinds, 0);
    BB_CHECK_EQ(bb_hooks[BB_SK_INSIGNIFICANT].activate_gate, 0);
    BB_CHECK_EQ(bb_hooks[BB_SK_INSIGNIFICANT].push_flags, 0);
    BB_CHECK_EQ(bb_hooks[BB_SK_INSIGNIFICANT].st_mod_blitz, 0);

    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int mover = fx_lineman(&m, 0, 0, 10, 7); // AG 3+
    fx_give_skill(&m, mover, BB_SK_INSIGNIFICANT);
    fx_lineman(&m, 1, 0, 10, 8); // marks origin only
    static const uint8_t dice[] = {3}; // bare 3+ still needed, and passes
    bb_rng rng;
    bb_rng_script(&rng, dice, 1);

    bb_status st = begin_move(&m, &rng, mover);
    st = fx_apply(&m, act(BB_A_STEP, 0, 10, 6), &rng);
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK(!bb_rng_error(&rng));
    BB_CHECK_EQ(m.players[mover].stance, BB_STANCE_STANDING);
    BB_CHECK_EQ(m.players[mover].y, 6);
    BB_CHECK_EQ(m.active_team, BB_HOME);
}

// Regression (adversarial review H2a): the Animal Savagery lash-out knocks
// the team-mate down IMMEDIATELY — before the declared action resolves — so
// the "downed" mate can't keep exerting TZ/assists or receive a hand-off
// through the whole action. The deferred push also let TDs delete the
// pending knockdown entirely.
BB_TEST(skdt_animal_savagery_lashout_resolves_before_action) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int savage = fx_lineman(&m, 0, 0, 10, 7);
    fx_give_skill(&m, savage, BB_SK_ANIMAL_SAVAGERY);
    int mate = fx_lineman(&m, 0, 1, 10, 8); // adjacent standing team-mate

    // Dice: AS d6 = 1 (lash out; MOVE has no +2); knockdown armour 2D6 = 2,2
    // (no break on AV 9+). The mate holds no ball -> no turnover.
    static const uint8_t dice[] = {1, 2, 2};
    bb_rng rng;
    bb_rng_script(&rng, dice, 3);
    bb_status st = begin_move(&m, &rng, savage);
    // First decision INSIDE the activation: the mate is already down.
    BB_CHECK_EQ(st, BB_STATUS_DECISION);
    BB_CHECK_EQ(m.players[mate].stance, BB_STANCE_PRONE);
    BB_CHECK_EQ(m.turnover, 0);
    BB_CHECK_EQ(m.active_team, BB_HOME);
    BB_CHECK(!bb_rng_error(&rng));
}

// Regression (adversarial review H2b): a KNOCKDOWN queued for a player who
// left the pitch before it resolved (chain-push into the crowd mid-action)
// must be a no-op — it used to set PRONE on off-pitch players, roll
// armour/injury, overwrite a CAS location with KO, and let drive-end KO
// recovery resurrect a casualty.
BB_TEST(skdt_knockdown_offpitch_is_noop) {
    bb_match m;
    fx_match_midturn(&m, BB_HOME, 0);
    int p = fx_lineman(&m, 1, 0, 10, 7);
    bb_remove_from_pitch(&m, p, BB_LOC_CAS);
    bb_push(&m, BB_PROC_KNOCKDOWN, (uint8_t)p, BB_KD_OTHER, 0, 0);
    bb_rng rng;
    bb_rng_script(&rng, 0, 0); // any die roll would trip the script error
    bb_advance(&m, &rng);
    BB_CHECK_EQ(m.players[p].location, BB_LOC_CAS);
    BB_CHECK_EQ(m.players[p].stance, BB_STANCE_STANDING);
    BB_CHECK(!bb_rng_error(&rng)); // zero dice consumed
}

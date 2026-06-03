// proc_ttm.c — Throw Team-mate / Kick Team-mate (BB_PROC_TTM).
//
// GAME/PERFORMING A THROW TEAM-MATE ACTION: one per turn (TTM trait); the
// thrower may move first; picks up an adjacent team-mate with Right Stuff
// (even Prone); target within Quick (no mod) or Short (-1) throw range; -1
// per opponent marking the thrower (+1 Strong Arm). Superb (pass / nat 6):
// the thrown player Scatters (3) from the target. Subpar (fail): Scatter (3),
// -1 to land. Fumbled (nat 1 / modified <= 1): the player Bounces from the
// thrower's square, -1 to land. Off-pitch: Injury by the Crowd + Turnover
// (+ Throw-in if the ball was held). Landing in an occupied square: the
// occupant is automatically Knocked Down (even if already down) and the
// thrown player Bounces and will Fall Over; repeat while occupied. Landing
// (unoccupied): AG test (-1 subpar, -1 fumbled, -1 per marker on the landing
// square); auto-fail if the thrown player was Prone/Stunned/Distracted.
// A failed landing Falls Over but causes a Turnover ONLY if the thrown player
// held the ball. KICK TEAM-MATE: same, separate budget; a Fumbled kick makes
// an immediate Injury Roll on the team-mate with Stunned treated as KO.
// ALWAYS HUNGRY (thrower): D6 before the PA test: on 1, roll again — 2+ the
// team-mate squirms free (auto-Fumble); 1 the team-mate is EATEN (removed,
// no apothecary/regeneration; held ball bounces; Turnover).
//
// Frame: a = team-mate, b = thrower, x,y = target. data: bit0 kick,
// bit1 subpar, bit2 fumble, bit3 auto-fail landing.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"
#include "bb/gen_tables.h"

static const int8_t DIR8[8][2] = {
    {-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1},
};

static void ttm_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int mate = f.a, thrower = f.b;
    bb_player* tp = &m->players[thrower];
    bb_player* mp = &m->players[mate];
    bool kick = (f.data & 1) != 0;

    // ALWAYS HUNGRY gate.
    bool forced_fumble = false;
    if (bb_has_skill(&tp->skills, BB_SK_ALWAYS_HUNGRY) && bb_d6(rng) == 1) {
        if (bb_d6(rng) == 1) {
            // Eaten. Removed for good; held ball bounces; turnover.
            bb_cover(BB_SK_ALWAYS_HUNGRY);
            bool had_ball = (mp->flags & BB_PF_HAS_BALL) != 0;
            int bx = mp->x, by = mp->y;
            if (had_ball) bb_drop_ball(m);
            bb_remove_from_pitch(m, mate, BB_LOC_CAS);
            mp->spp_game = BB_CAS_DEAD; // eaten: out of the league entirely
            bb_turnover(m);
            if (had_ball) bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
            return;
        }
        forced_fumble = true; // squirms free
    }

    // PA test: Quick 0 / Short -1; -1 per marker; Strong Arm +1; then the
    // skill/trait hooks via a BB_TEST_TTM ctx — the BB2025 Disturbing
    // Presence text explicitly names the "Throw Team-mate Action", so
    // opposing DP auras within 3 squares of the thrower apply their -1 here
    // (adversarial review M12).
    int dx = f.x - tp->x, dy = f.y - tp->y;
    bool quick = dx * dx + dy * dy <= 12;
    int mod = quick ? 0 : -1;
    mod -= bb_tackle_zones(m, BB_TEAM_OF(thrower), tp->x, tp->y);
    if (bb_has_skill(&tp->skills, BB_SK_STRONG_ARM)) {
        mod += 1;
        bb_cover(BB_SK_STRONG_ARM);
    }
    bb_ctx c = {BB_TEST_TTM, (uint8_t)thrower, BB_NO_PLAYER, (uint8_t)thrower,
                (int8_t)tp->x, (int8_t)tp->y, (int8_t)f.x, (int8_t)f.y,
                (int8_t)(quick ? 0 : 1), 0};
    mod += bb_hook_mods(m, &c);
    bool fumble = forced_fumble;
    bool subpar = false;
    if (!forced_fumble) {
        int die = bb_d6(rng);
        if (tp->pa <= 0) fumble = true;
        else if (die == 1 || die + mod <= 1) fumble = true;
        else if (die == 6 || die >= bb_test_target(tp->pa, mod)) subpar = false;
        else subpar = true;
    }

    // Auto-fail landing for players thrown while not standing-and-attentive.
    bool autofail = mp->stance != BB_STANCE_STANDING ||
                    (mp->flags & BB_PF_DISTRACTED) != 0;

    // Lift the team-mate into flight (ball travels with a carrier).
    bool has_ball = (mp->flags & BB_PF_HAS_BALL) != 0;
    int ox = mp->x, oy = mp->y;
    m->grid[ox][oy] = 0;

    // Flight path.
    int x, y;
    if (fumble) {
        x = tp->x;
        y = tp->y;
        int d = bb_roll(rng, 8) - 1; // bounce from the thrower's square
        x += DIR8[d][0];
        y += DIR8[d][1];
    } else {
        x = f.x;
        y = f.y;
        for (int i = 0; i < 3; i++) { // Scatter (3)
            int d = bb_roll(rng, 8) - 1;
            x += DIR8[d][0];
            y += DIR8[d][1];
        }
    }

    // KTM fumble: immediate Injury Roll, Stunned treated as KO (the kick goes
    // straight into the team-mate; they end prone next to the kicker).
    if (kick && fumble) {
        // Land them in the bounce square if free, else their origin square.
        int lx = (bb_on_pitch_xy(x, y) && !m->grid[x][y]) ? x : ox;
        int ly = (bb_on_pitch_xy(x, y) && !m->grid[x][y]) ? y : oy;
        bb_place(m, mate, lx, ly);
        mp->stance = BB_STANCE_PRONE;
        if (has_ball) {
            if (BB_TEAM_OF(mate) == m->active_team) bb_turnover(m);
            bb_drop_ball(m);
            bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)lx, (uint8_t)ly);
        }
        // Injury with Stunned -> KO: roll 2D6 manually.
        int t = bb_d6(rng) + bb_d6(rng);
        bool stunty = bb_is_stunty(m, mate);
        int ko_max = stunty ? BB_INJ_STUNTY_KO_MAX : BB_INJ_KO_MAX;
        if (t <= ko_max) {
            bb_remove_from_pitch(m, mate, BB_LOC_KO); // stun band promoted to KO
        } else {
            bb_push(m, BB_PROC_CASUALTY, mate, 0, 0, 0);
        }
        return;
    }

    // Landing loop: crash-land through occupied squares.
    bool forced_fall = false;
    for (;;) {
        if (!bb_on_pitch_xy(x, y)) {
            // Off the pitch: Injury by the Crowd; Turnover always.
            bb_turnover(m);
            if (has_ball) {
                mp->flags &= (uint16_t)~BB_PF_HAS_BALL;
                m->ball.carrier = BB_NO_PLAYER;
                m->ball.state = BB_BALL_OFF_PITCH; // until the throw-in lands
                int ex = x < 0 ? 0 : (x >= BB_PITCH_LEN ? BB_PITCH_LEN - 1 : x);
                int ey = y < 0 ? 0 : (y >= BB_PITCH_WID ? BB_PITCH_WID - 1 : y);
                bb_push(m, BB_PROC_THROW_IN, 0, 0, (uint8_t)ex, (uint8_t)ey);
            }
            mp->location = BB_LOC_RESERVES; // crowd injury relocates from here
            bb_push(m, BB_PROC_INJURY, mate, 1 /* crowd */, 0, 0);
            return;
        }
        int occ = bb_slot_at(m, x, y);
        if (occ < 0) break;
        // Crash landing: the occupant is Knocked Down even if already down.
        bb_knockdown2(m, occ, BB_KD_OTHER, 0, mate);
        forced_fall = true;
        int d = bb_roll(rng, 8) - 1;
        x += DIR8[d][0];
        y += DIR8[d][1];
    }

    bb_place(m, mate, x, y);
    mp->stance = BB_STANCE_STANDING;
    if (has_ball) {
        m->ball.x = (uint8_t)x;
        m->ball.y = (uint8_t)y;
    }

    if (forced_fall || autofail) {
        // Falls Over; the TTM-landing cause makes KNOCKDOWN latch a turnover
        // only when the thrown player held the ball.
        bb_knockdown(m, mate, BB_KD_TTM_LANDING, 0);
        return;
    }

    // Attempt to land on their feet: AG test.
    int lmod = (subpar ? -1 : 0) + (fumble ? -1 : 0);
    lmod -= bb_tackle_zones(m, BB_TEAM_OF(mate), x, y);
    int die = bb_d6(rng);
    bool ok = die != 1 && (die == 6 || die >= bb_test_target(mp->ag, lmod));
    if (ok) {
        if (has_ball) bb_check_td(m);
        return; // lands standing; may still activate later
    }
    bb_knockdown(m, mate, BB_KD_TTM_LANDING, 0);
}

const bb_proc_vtable bb_proc_ttm_vtable = {ttm_advance, 0, 0};

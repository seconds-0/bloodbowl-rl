// proc_block.c — BLOCK, PUSH (incl. chains & crowd), KNOCKDOWN, ARMOUR,
// INJURY, CASUALTY, FOUL.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/bb_hooks.h"
#include "bb/gen_tables.h"

// --- assists -----------------------------------------------------------------
static int count_assists_ex(const bb_match* m, int for_slot, int against_slot, bool is_foul) {
    int n = 0;
    const bb_player* target = &m->players[against_slot];
    int team = BB_TEAM_OF(for_slot);
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (s == for_slot) continue;
        if (m->players[s].location != BB_LOC_ON_PITCH) continue;
        if (!bb_adjacent(m->players[s].x, m->players[s].y, target->x, target->y)) continue;
        if (m->players[s].flags & BB_PF_EYE_GOUGED) continue; // cannot assist
        if (bb_can_assist(m, s, against_slot)) {
            n++;
            continue;
        }
        // PUT THE BOOT IN: may give OFFENSIVE assists on a team-mate's Foul
        // regardless of being Marked (DEFENSIVE on a marker cancels it during
        // the opponent's turn, like Guard).
        if (is_foul && BB_TEAM_OF(for_slot) == m->active_team &&
            m->players[s].stance == BB_STANCE_STANDING &&
            !(m->players[s].flags & BB_PF_DISTRACTED) &&
            bb_has_skill(&m->players[s].skills, BB_SK_PUT_THE_BOOT_IN)) {
            n++;
        }
    }
    return n;
}

int bb_count_assists(const bb_match* m, int for_slot, int against_slot) {
    return count_assists_ex(m, for_slot, against_slot, false);
}

static int count_assists(const bb_match* m, int for_slot, int against_slot) {
    return bb_count_assists(m, for_slot, against_slot);
}

enum { PSH_POW = 1 << 0, PSH_CHAIN = 1 << 1, PSH_MOVED = 1 << 2, PSH_FUP = 1 << 3,
       PSH_CROWD = 1 << 4, PSH_FROM_BLITZ = 1 << 5, PSH_STOOD_FIRM = 1 << 6,
       // This push came from the Frenzy SECOND block: never a third (M6).
       PSH_FRENZY_DONE = 1 << 7,
       // The pushee's coach declined Stand Firm for THIS push (window done).
       PSH_SF_DECLINED = 1 << 8 };

// ===== BLOCK ==================================================================
// a = attacker, b = defender.
// data: bits 0-2 die0, 3-5 die1, 6-8 die2, 9-10 ndice-1, bit11 chooser-is-defender,
//       bit12 reroll used.
// phase 0: compute pool, roll; 1: reroll window; 2: choose die;
// phase 4: Both Down — ATTACKER's Wrestle window (USE_SKILL/DECLINE_SKILL);
// phase 5: Both Down — DEFENDER's Wrestle window (FFB asks attacker first).

enum { BLK_RR_USED = 1 << 12, BLK_DEF_CHOOSES = 1 << 11, BLK_IS_BLITZ = 1 << 13,
       BLK_DAUNTLESS_OK = 1 << 14, BLK_FRENZY_2ND = 1 << 15 };

static int blk_die(const bb_frame* f, int i) { return (f->data >> (3 * i)) & 7; }
static int blk_ndice(const bb_frame* f) { return ((f->data >> 9) & 3) + 1; }

static void blk_roll_pool(bb_frame* f, bb_rng* rng) {
    int nd = blk_ndice(f);
    uint16_t keep = f->data & (uint16_t)~0x1FF; // clear dice bits
    for (int i = 0; i < nd; i++) {
        keep |= (uint16_t)(bb_roll_block_die(rng) << (3 * i));
    }
    f->data = keep;
}

static void resolve_face(bb_match* m, bb_frame* f, int face);

static void block_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int att = f->a, def = f->b;
    if (f->phase == 0) {
        // FOUL APPEARANCE: "roll a D6 before any other dice ... On a 1, the
        // Block Action is immediately cancelled and the opposition player's
        // activation immediately ends." (No turnover.)
        // TRICKSTER: before dice are determined, the defender may relocate
        // to any unoccupied adjacent square (auto-policy: fewest markers;
        // ties -> first). The block then proceeds against the new square.
        if (bb_has_skill(&m->players[def].skills, BB_SK_TRICKSTER) &&
            !(m->players[def].flags & BB_PF_DISTRACTED)) {
            bb_player* dp2 = &m->players[def];
            int bestx = -1, besty = -1, best_tz = 99;
            for (int dx = -1; dx <= 1; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int nx = dp2->x + dx, ny = dp2->y + dy;
                    if (!bb_on_pitch_xy(nx, ny) || m->grid[nx][ny]) continue;
                    int tz = bb_tackle_zones(m, BB_TEAM_OF(def), nx, ny);
                    if (tz < best_tz) {
                        best_tz = tz;
                        bestx = nx;
                        besty = ny;
                    }
                }
            }
            // Only worth it if it escapes adjacency to the attacker entirely
            // (cancels the block) or reduces markers.
            if (bestx >= 0 && !bb_adjacent(bestx, besty,
                                           m->players[att].x, m->players[att].y)) {
                bb_cover(BB_SK_TRICKSTER);
                bb_place(m, def, bestx, besty);
                if (dp2->flags & BB_PF_HAS_BALL) {
                    m->ball.x = dp2->x;
                    m->ball.y = dp2->y;
                }
                bb_pop(m); // target out of reach: the block fizzles
                return;
            }
        }
        // DUMP-OFF: a carrying defender may make an interruption Quick Pass
        // that cannot cause a turnover (auto-policy: throw to the adjacent
        // team-mate with the fewest markers, if any).
        if ((m->players[def].flags & BB_PF_HAS_BALL) &&
            bb_has_skill(&m->players[def].skills, BB_SK_DUMP_OFF) &&
            !(m->players[def].flags & BB_PF_DISTRACTED) &&
            m->players[def].pa > 0 && !(f->data & BLK_RR_USED /*once*/)) {
            // Find a quick-range team-mate (d^2 <= 12), fewest markers.
            bb_player* dp2 = &m->players[def];
            int best = -1, best_tz = 99;
            int dteam = BB_TEAM_OF(def);
            for (int s2 = dteam * BB_TEAM_SLOTS; s2 < (dteam + 1) * BB_TEAM_SLOTS; s2++) {
                if (s2 == def) continue;
                const bb_player* q = &m->players[s2];
                if (q->location != BB_LOC_ON_PITCH) continue;
                if (!bb_can_catch(m, s2)) continue;
                int ddx = q->x - dp2->x, ddy = q->y - dp2->y;
                if (ddx * ddx + ddy * ddy > 12) continue;
                int tz = bb_tackle_zones(m, dteam, q->x, q->y);
                if (tz < best_tz) {
                    best_tz = tz;
                    best = s2;
                }
            }
            if (best >= 0) {
                bb_cover(BB_SK_DUMP_OFF);
                // Resolve a simplified turnover-免 quick pass inline: PA test;
                // accurate -> catch test by the receiver; any failure just
                // drops the ball (bounce) with no turnover.
                bb_player* rp = &m->players[best];
                int pmod = -bb_tackle_zones(m, dteam, dp2->x, dp2->y);
                int die = bb_d6(rng);
                bool acc = die != 1 && (die == 6 || die >= bb_test_target(dp2->pa, pmod));
                bb_drop_ball(m);
                if (acc) {
                    int cmod = -bb_tackle_zones(m, dteam, rp->x, rp->y);
                    int cdie = bb_d6(rng);
                    if (cdie != 1 && (cdie == 6 || cdie >= bb_test_target(rp->ag, cmod))) {
                        bb_give_ball(m, best);
                    } else {
                        bb_ball_to(m, rp->x, rp->y);
                        bb_push(m, BB_PROC_SCATTER, 0, 1, rp->x, rp->y);
                    }
                } else {
                    bb_ball_to(m, dp2->x, dp2->y);
                    bb_push(m, BB_PROC_SCATTER, 0, 1, dp2->x, dp2->y);
                }
                // No turnover from any of this. Return so the pass/scatter
                // chain resolves; BLOCK re-enters phase 0 with the preamble
                // latch set and proceeds to the dice.
                return;
            }
        }
    }
    if (f->phase == 0) {
        // DAUNTLESS: against a higher unmodified ST, roll D6 + own ST; beat
        // the target's unmodified ST to match it for this block.
        int base_a = m->players[att].st;
        int base_d = m->players[def].st;
        if (bb_has_skill(&m->players[att].skills, BB_SK_DAUNTLESS) &&
            base_d > base_a && !(f->data & BLK_DAUNTLESS_OK)) {
            int roll = bb_d6(rng) + base_a;
            if (roll > base_d) f->data |= BLK_DAUNTLESS_OK;
        }
        int st_a = ((f->data & BLK_DAUNTLESS_OK) ? base_d : base_a) +
                   count_assists(m, att, def);
        // CHEERING FANS: the first Block of this team's turn gets an extra
        // offensive assist.
        if (m->cheer_assist[BB_TEAM_OF(att)] && BB_TEAM_OF(att) == m->active_team) {
            m->cheer_assist[BB_TEAM_OF(att)] = 0;
            st_a += 1;
        }
        int st_d = base_d + count_assists(m, def, att);
        if (f->data & BLK_IS_BLITZ) st_a += bb_hook_st_mod_blitz(m, att); // Horns
        int nd = 1;
        bool def_chooses = false;
        if (st_a > st_d) nd = st_a > 2 * st_d ? 3 : 2;
        else if (st_d > st_a) {
            nd = st_d > 2 * st_a ? 3 : 2;
            def_chooses = true;
        }
        // Keep BLK_FRENZY_2ND across the rebuild: resolve_face propagates it
        // into the resulting PUSH (PSH_FRENZY_DONE) so the mandatory Frenzy
        // second block can never spawn a third (review M6).
        f->data = (uint16_t)((f->data & (BLK_IS_BLITZ | BLK_FRENZY_2ND)) |
                             ((nd - 1) << 9) | (def_chooses ? BLK_DEF_CHOOSES : 0));
        blk_roll_pool(f, rng);
        // BRAWLER: "may re-roll a single Both Down result" (without a team
        // re-roll). Auto-policy: reroll the first Both Down when the pool has
        // no plainly better face for the attacker.
        if (bb_has_skill(&m->players[att].skills, BB_SK_BRAWLER)) {
            bool better = false;
            int bd_idx = -1;
            for (int i = 0; i < blk_ndice(f); i++) {
                int face = blk_die(f, i);
                if (face == BB_BD_POW || face == BB_BD_STUMBLE ||
                    face == BB_BD_PUSH_1 || face == BB_BD_PUSH_2) {
                    better = true;
                }
                if (face == BB_BD_BOTH_DOWN && bd_idx < 0) bd_idx = i;
            }
            if (bd_idx >= 0 && !better) {
                int nd = bb_roll_block_die(rng);
                uint16_t mask = (uint16_t)~(7u << (3 * bd_idx));
                f->data = (uint16_t)((f->data & mask) | ((uint16_t)nd << (3 * bd_idx)));
            }
        }
        // Reroll window for the attacking coach (team reroll only, own turn).
        int team = BB_TEAM_OF(att);
        if (m->rerolls[team] > 0 && m->active_team == team && !(f->data & BLK_RR_USED)) {
            f->phase = 1;
            bb_need_decision(m, team);
            return;
        }
        f->phase = 2;
        bb_need_decision(m, (f->data & BLK_DEF_CHOOSES) ? BB_TEAM_OF(def) : BB_TEAM_OF(att));
        return;
    }
    if (f->phase == 2) {
        bb_need_decision(m, (f->data & BLK_DEF_CHOOSES) ? BB_TEAM_OF(def) : BB_TEAM_OF(att));
        return;
    }
    if (f->phase == 4) { // Both Down: attacker's Wrestle window
        bb_need_decision(m, BB_TEAM_OF(att));
        return;
    }
    if (f->phase == 5) { // Both Down: defender's Wrestle window
        bb_need_decision(m, BB_TEAM_OF(def));
        return;
    }
    m->status = BB_STATUS_ERROR;
}

// May this player offer the optional Wrestle choice on a Both Down?
// "Whilst a player is Distracted, they cannot use Active Skills" (mirror
// PLAYER STATUS); Wrestle is ACTIVE.
static bool wrestle_eligible(const bb_match* m, int slot) {
    return bb_has_wrestle(m, slot) && !(m->players[slot].flags & BB_PF_DISTRACTED);
}

// WRESTLE used: "both players in the Block Action are Placed Prone,
// regardless of any other Skills they may possess" — no armour rolls, no
// knockdown turnover. A carrier placed prone drops the ball; an ACTIVE
// carrier placed prone is a turnover.
static void both_down_wrestle(bb_match* m, bb_frame* f) {
    int att = f->a, def = f->b;
    bb_cover(BB_SK_WRESTLE);
    bb_pop(m);
    int both[2] = {def, att};
    for (int i = 0; i < 2; i++) {
        bb_player* p = &m->players[both[i]];
        p->stance = BB_STANCE_PRONE;
        p->flags &= (uint16_t)~BB_PF_ROOTED; // placed prone un-roots
        if (p->flags & BB_PF_HAS_BALL) {
            int bx = p->x, by = p->y;
            if (BB_TEAM_OF(both[i]) == m->active_team) bb_turnover(m);
            bb_drop_ball(m);
            bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
        }
    }
}

// Plain Both Down (no Wrestle, or every Wrestle owner declined): a player
// with Block (not Distracted) stays up; everyone else is Knocked Down
// (armour rolls; attacker down = turnover for the active team).
static void both_down_plain(bb_match* m, bb_frame* f) {
    int att = f->a, def = f->b;
    bool att_down = !(bb_has_block(m, att) && !(m->players[att].flags & BB_PF_DISTRACTED));
    bool def_down = !(bb_has_block(m, def) && !(m->players[def].flags & BB_PF_DISTRACTED));
    bb_pop(m);
    // Defender resolves first, attacker's knockdown (turnover) after.
    if (att_down) bb_knockdown2(m, att, BB_KD_BLOCK, 0, def);
    if (def_down) bb_knockdown2(m, def, BB_KD_BLOCK, 0, att);
}

static int block_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int n = 0;
    if (f->phase == 1) {
        out[n++] = (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0};
        out[n++] = (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0};
        return n;
    }
    if (f->phase == 4 || f->phase == 5) { // Wrestle window (owner's coach)
        out[n++] = (bb_action){BB_A_USE_SKILL, BB_SK_WRESTLE, 0, 0};
        out[n++] = (bb_action){BB_A_DECLINE_SKILL, BB_SK_WRESTLE, 0, 0};
        return n;
    }
    // phase 2: choose one of the rolled dice.
    for (int i = 0; i < blk_ndice(f); i++) {
        out[n++] = (bb_action){BB_A_CHOOSE_DIE, (uint8_t)i, 0, 0};
    }
    return n;
}

static void block_apply(bb_match* m, bb_action a, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int att = f->a;
    if (f->phase == 1) {
        if (a.type == BB_A_USE_REROLL) {
            int team = BB_TEAM_OF(att);
            m->rerolls[team]--;
            // Drive-scoped bonuses (Brilliant Coaching) are spent first —
            // they expire soonest (END_DRIVE); see proc_test.c.
            if (m->bonus_rerolls[team]) m->bonus_rerolls[team]--;
            f->data |= BLK_RR_USED;
            int loner = bb_loner_value(m, att);
            if (!(loner > 0 && bb_roll(rng, 6) < loner)) {
                blk_roll_pool(f, rng);
            }
        }
        f->phase = 2;
        return;
    }
    if (f->phase == 4) { // attacker's Wrestle window
        if (a.type == BB_A_USE_SKILL) {
            both_down_wrestle(m, f);
        } else if (wrestle_eligible(m, f->b)) {
            f->phase = 5; // attacker declined: defender's window
        } else {
            both_down_plain(m, f);
        }
        return;
    }
    if (f->phase == 5) { // defender's Wrestle window
        if (a.type == BB_A_USE_SKILL) both_down_wrestle(m, f);
        else both_down_plain(m, f);
        return;
    }
    // phase 2: die chosen.
    resolve_face(m, f, blk_die(f, a.arg));
}

static void resolve_face(bb_match* m, bb_frame* f, int face) {
    int att = f->a, def = f->b;
    int ax = m->players[att].x, ay = m->players[att].y;
    switch (face) {
        case BB_BD_ATTACKER_DOWN:
            bb_pop(m);
            bb_knockdown2(m, att, BB_KD_BLOCK, 0, def);
            return;
        case BB_BD_BOTH_DOWN: {
            // Juggernaut (attacker, blitz): Both Down becomes a Push (also
            // cancelling the defender's Wrestle for this block).
            if ((f->data & BLK_IS_BLITZ) &&
                bb_has_skill(&m->players[att].skills, BB_SK_JUGGERNAUT)) {
                // Snapshot before pop: bb_push reuses the popped slot, so f
                // would alias the new frame (Codex finding).
                uint16_t f2 = f->data & BLK_FRENZY_2ND;
                bb_pop(m);
                bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
                bb_top(m)->data |= PSH_FROM_BLITZ;
                if (f2) bb_top(m)->data |= PSH_FRENZY_DONE;
                return;
            }
            // Wrestle (either player): the OWNER may choose that both players
            // are Placed Prone instead (D29: a real USE_SKILL/DECLINE_SKILL
            // window — declining is correct play for a Wrestle defender vs a
            // Block-less attacker, forcing the knockdown turnover). FFB asks
            // the attacker first, then the defender (StepWrestle).
            if (wrestle_eligible(m, att)) {
                f->phase = 4;
                bb_need_decision(m, BB_TEAM_OF(att));
                return;
            }
            if (wrestle_eligible(m, def)) {
                f->phase = 5;
                bb_need_decision(m, BB_TEAM_OF(def));
                return;
            }
            both_down_plain(m, f);
            return;
        }
        case BB_BD_PUSH_1:
        case BB_BD_PUSH_2: {
            uint16_t blitz = f->data & BLK_IS_BLITZ;
            uint16_t f2 = f->data & BLK_FRENZY_2ND;
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            if (blitz) bb_top(m)->data |= PSH_FROM_BLITZ;
            if (f2) bb_top(m)->data |= PSH_FRENZY_DONE;
            return;
        }
        case BB_BD_STUMBLE: {
            bool dodge = bb_has_dodge_skill(m, def) &&
                         !(m->players[def].flags & BB_PF_DISTRACTED) &&
                         !bb_has_skill(&m->players[att].skills, BB_SK_TACKLE);
            uint16_t blitz = f->data & BLK_IS_BLITZ;
            uint16_t f2 = f->data & BLK_FRENZY_2ND;
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            if (!dodge) bb_top(m)->data |= 1; // pow flag
            if (blitz) bb_top(m)->data |= PSH_FROM_BLITZ;
            if (f2) bb_top(m)->data |= PSH_FRENZY_DONE;
            return;
        }
        case BB_BD_POW: {
            uint16_t blitz = f->data & BLK_IS_BLITZ;
            uint16_t f2 = f->data & BLK_FRENZY_2ND;
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            bb_top(m)->data |= 1; // pow flag
            if (blitz) bb_top(m)->data |= PSH_FROM_BLITZ;
            if (f2) bb_top(m)->data |= PSH_FRENZY_DONE;
            return;
        }
    }
    m->status = BB_STATUS_ERROR;
}

// ===== PUSH ===================================================================
// a = pusher (direction origin), b = pushee. x,y = origin square of the push
// (the pusher's square, or the previous pushee for chains).
// data: bit0 pow, bit1 is-chain, bit2 moved (pushee relocated), bit3 follow-up
//       pending, bits 4-9: pushee's original square (x:3? not enough) ->
//       store original square in f->x/f->y after computing candidates? x,y are
//       the origin; we need pushee original too — keep origin in (x,y) until
//       relocation, then overwrite with pushee's old square for follow-up.


// SIDESTEP: usable only when an adjacent unoccupied square exists ("If there
// are no adjacent unoccupied squares, then this Skill cannot be used").
// Decision OWNERSHIP and the legal set must apply the same predicate: skill
// possession alone handed the attacker's chain/crowd choice to the defending
// coach when no free square existed (review M8).
static bool side_step_active(const bb_match* m, const bb_frame* f) {
    if (!(bb_hook_push_flags(m, f->b) & BB_PUSHF_SIDE_STEP)) return false;
    if ((f->data & PSH_FROM_BLITZ) &&
        bb_has_skill(&m->players[f->a].skills, BB_SK_JUGGERNAUT)) {
        return false;
    }
    if (bb_has_skill(&m->players[f->a].skills, BB_SK_GRAB)) return false;
    const bb_player* dp = &m->players[f->b];
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int x = dp->x + dx, y = dp->y + dy;
            if (bb_on_pitch_xy(x, y) && !m->grid[x][y]) return true;
        }
    }
    return false;
}

static int push_candidates(const bb_match* m, const bb_frame* f, int cand[3][2]) {
    // Three squares "behind" the pushee relative to the push origin.
    int px = m->players[f->b].x, py = m->players[f->b].y;
    int dx = px - f->x, dy = py - f->y;
    int n = 0;
    // Primary: continue in (dx,dy). Secondaries: the two neighbours of that
    // direction (45 degrees off).
    static const int8_t dirs[8][2] = {
        {-1, -1}, {0, -1}, {1, -1}, {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0},
    };
    int main_dir = 0;
    for (int i = 0; i < 8; i++) {
        if (dirs[i][0] == dx && dirs[i][1] == dy) {
            main_dir = i;
            break;
        }
    }
    int order[3] = {(main_dir + 7) & 7, main_dir, (main_dir + 1) & 7};
    for (int i = 0; i < 3; i++) {
        cand[n][0] = px + dirs[order[i]][0];
        cand[n][1] = py + dirs[order[i]][1];
        n++;
    }
    return n;
}

static void push_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (f->phase == 0) {
        int def_flags = bb_hook_push_flags(m, f->b);
        bool jugg = (f->data & PSH_FROM_BLITZ) &&
                    bb_has_skill(&m->players[f->a].skills, BB_SK_JUGGERNAUT);
        if (m->players[f->b].flags & BB_PF_ROOTED) {
            // Rooted: "cannot be Pushed Back" — mandatory, no window, not
            // cancelled by Juggernaut (it is not the Stand Firm Skill).
            f->data |= PSH_STOOD_FIRM;
            f->phase = 5;
            return;
        }
        if ((def_flags & BB_PUSHF_STAND_FIRM) && !jugg &&
            !(f->data & PSH_SF_DECLINED) &&
            !(m->players[f->b].flags & BB_PF_DISTRACTED)) {
            // STAND FIRM: "they can CHOOSE to not be Pushed Back" — a real
            // USE_SKILL/DECLINE_SKILL window for the pushee's coach,
            // including during chain pushes (mirror SK#STAND FIRM); FFB
            // allows the decline (v0 lockstep finding). Distracted players
            // cannot use Active Skills (mirror PLAYER STATUS).
            f->phase = 4;
            bb_need_decision(m, BB_TEAM_OF(f->b));
            return;
        }
        // Side Step: the DEFENDER's coach chooses the square (any adjacent
        // free square, not just the usual three) — handled in legal/apply via
        // the decision owner. With no free adjacent square the skill cannot
        // be used and the normal candidates (incl. chain/crowd) belong to the
        // attacking coach (review M8).
        bb_need_decision(m, side_step_active(m, f) ? BB_TEAM_OF(f->b)
                                                   : m->active_team);
        return;
    }
    if (f->phase == 4) { // Stand Firm window: re-issue on re-entry
        bb_need_decision(m, BB_TEAM_OF(f->b));
        return;
    }
    if (f->phase == 1) {
        // Chain child finished; destination square is normally now free.
        // If the chained occupant STOOD FIRM the square is still occupied:
        // this pushee is not moved either (the push is absorbed in place; a
        // POW still knocks them down where they stand).
        if (m->grid[f->x][f->y]) {
            f->data |= PSH_STOOD_FIRM;
            f->phase = 5;
            return;
        }
        f->phase = 2;
        return;
    }
    if (f->phase == 2) {
        // Relocate pushee into the chosen square (stored in f->x/f->y now).
        int def = f->b;
        bb_player* dp = &m->players[def];
        int oldx = dp->x, oldy = dp->y;
        if (f->data & PSH_CROWD) {
            // Crowd resolution is immediate; the follow-up decision comes
            // after. (FFB order; GAME/FOLLOW-UP's "before any other dice" is
            // a known minor divergence — see DECISIONS.md.)
            bool had_ball = (dp->flags & BB_PF_HAS_BALL) != 0;
            m->surfs[BB_TEAM_OF(def)]++; // RL shaping reads this (surf event)
            if (BB_TEAM_OF(def) == m->active_team) bb_turnover(m);
            // bb_drop_ball acts on the GLOBAL carrier; unconditional, it
            // stripped an unrelated carrier elsewhere on the pitch whenever a
            // non-carrier was crowd-surfed (adversarial review H1).
            if (had_ball) bb_drop_ball(m);
            bb_remove_from_pitch(m, def, BB_LOC_RESERVES); // crowd injury relocates
            bb_push(m, BB_PROC_INJURY, def, 1 /* crowd */, 0, 0);
            if (had_ball) {
                bb_push(m, BB_PROC_THROW_IN, 0, 0, (uint8_t)oldx, (uint8_t)oldy);
            }
            f->phase = 3;
            f->x = (uint8_t)oldx;
            f->y = (uint8_t)oldy;
            return;
        }
        bb_place(m, def, f->x, f->y);
        // STRIP BALL: "if an opposition player [holding the ball] is Pushed
        // Back then they will [drop the ball]" — bounce from the destination.
        // Monstrous Mouth blocks it; SURE HANDS too ("Additionally, the
        // Strip Ball Skill cannot be used against this player" — panel
        // finding: every Thrower/Runner archetype carries it).
        if ((dp->flags & BB_PF_HAS_BALL) && !(f->data & PSH_CHAIN) &&
            bb_has_skill(&m->players[f->a].skills, BB_SK_STRIP_BALL) &&
            !bb_has_skill(&dp->skills, BB_SK_MONSTROUS_MOUTH) &&
            !bb_has_skill(&dp->skills, BB_SK_SURE_HANDS)) {
            bb_cover(BB_SK_STRIP_BALL);
            int sx = f->x, sy = f->y;
            bb_drop_ball(m);
            bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)sx, (uint8_t)sy);
        }
        // EYE GOUGE: a player Pushed Back by this player cannot assist until
        // next activated (chain-pushed players unaffected per FAQ).
        if (!(f->data & PSH_CHAIN) &&
            bb_has_skill(&m->players[f->a].skills, BB_SK_EYE_GOUGE)) {
            dp->flags |= BB_PF_EYE_GOUGED;
        }
        if (dp->flags & BB_PF_HAS_BALL) {
            m->ball.x = dp->x;
            m->ball.y = dp->y;
        } else if (m->ball.state == BB_BALL_ON_GROUND && m->ball.x == dp->x &&
                   m->ball.y == dp->y) {
            // Involuntarily moved onto the loose ball: it bounces, no pickup,
            // no turnover.
            bb_push(m, BB_PROC_SCATTER, 0, 1, dp->x, dp->y);
        }
        f->x = (uint8_t)oldx; // remember vacated square for follow-up
        f->y = (uint8_t)oldy;
        if (f->data & PSH_POW) {
            // Knockdown resolves after the follow-up decision (FFB order).
        }
        f->phase = 3;
        return;
    }
    if (f->phase == 3) {
        // Follow-up decision (original block pushes only, not chains).
        if (f->data & PSH_CHAIN) {
            f->phase = 5;
            return;
        }
        // FRENZY: "must Follow-up if able" — no decision.
        bool frenzy = bb_has_skill(&m->players[f->a].skills, BB_SK_FRENZY);
        // Fend: the attacker may not follow up (Juggernaut on a blitz cancels;
        // Frenzy does not cancel Fend).
        bool jugg = (f->data & PSH_FROM_BLITZ) &&
                    bb_has_skill(&m->players[f->a].skills, BB_SK_JUGGERNAUT);
        if (!jugg && (bb_hook_push_flags(m, f->b) & BB_PUSHF_FEND)) {
            f->phase = 5;
            return;
        }
        if (m->players[f->a].flags & BB_PF_ROOTED) {
            f->phase = 5; // rooted players may not follow up
            return;
        }
        if (frenzy) {
            // Forced follow-up into the vacated square.
            bb_player* ap = &m->players[f->a];
            if (ap->location == BB_LOC_ON_PITCH && ap->stance == BB_STANCE_STANDING &&
                !m->grid[f->x][f->y]) {
                bb_place(m, f->a, f->x, f->y);
                if (ap->flags & BB_PF_HAS_BALL) {
                    m->ball.x = ap->x;
                    m->ball.y = ap->y;
                }
            }
            f->phase = 5;
            return;
        }
        bb_need_decision(m, BB_TEAM_OF(f->a));
        return;
    }
    if (f->phase == 5) {
        // Final: crowd resolution, or pow knockdown / TD check.
        // PSH_POW exists only on root (non-chain) frames, where f->a is the
        // block attacker — snapshot it before the pop so the knockdown can
        // carry the causer: the no-causer bb_knockdown dropped Mighty Blow,
        // Claws and Saboteur on the main POW/Stumble path (review M5).
        int att = f->a;
        int def = f->b;
        uint16_t data = f->data;
        // FRENZY: after the original block's push (not a chain link) with the
        // target still Standing and the attacker adjacent — via the forced
        // follow-up, or Stand Firm leaving both in place — the attacker MUST
        // perform a second Block Action against the same player. Pushes
        // spawned by that second block carry PSH_FRENZY_DONE so a third can
        // never happen (review M6).
        bool frenzy2 =
            !(data & (PSH_CHAIN | PSH_CROWD | PSH_POW | PSH_FRENZY_DONE)) &&
            !m->turnover &&
            bb_has_skill(&m->players[att].skills, BB_SK_FRENZY) &&
            m->players[att].location == BB_LOC_ON_PITCH &&
            m->players[att].stance == BB_STANCE_STANDING &&
            m->players[def].location == BB_LOC_ON_PITCH &&
            m->players[def].stance == BB_STANCE_STANDING &&
            bb_adjacent(m->players[att].x, m->players[att].y,
                        m->players[def].x, m->players[def].y);
        bool blitz = (data & PSH_FROM_BLITZ) != 0;
        if (frenzy2 && blitz && m->players[att].moved >= m->players[att].ma) {
            // Blitz: the second block also costs a square of movement; with
            // none left the player must Rush, and if they cannot Rush the
            // second block cannot be performed.
            if (m->players[att].rushes >= bb_max_rushes(m, att)) {
                frenzy2 = false;
            } else {
                bb_player* ap = &m->players[att];
                f->phase = 6; // consume the rush result before the block
                ap->rushes++;
                bb_ctx rc = {BB_TEST_RUSH, (uint8_t)att, BB_NO_PLAYER, (uint8_t)att,
                             (int8_t)ap->x, (int8_t)ap->y, (int8_t)ap->x,
                             (int8_t)ap->y, -1, 1};
                int rmod = bb_hook_mods(m, &rc);
                if (m->weather == BB_WEATHER_BLIZZARD) rmod -= 1;
                bb_push(m, BB_PROC_TEST, att, BB_TEST_RUSH,
                        bb_test_target(2, rmod), 0);
                return;
            }
        }
        bb_pop(m);
        if (data & PSH_CROWD) {
            return; // crowd was resolved at relocation time
        }
        if (data & PSH_POW) {
            bb_knockdown2(m, def, BB_KD_BLOCK, 0, att);
            return;
        }
        if (bb_check_td(m)) {
            return; // pushed into their own end zone while holding: no block
        }
        if (frenzy2) {
            if (blitz) m->players[att].moved++; // the second block's square
            bb_push(m, BB_PROC_BLOCK, att, def, 0, 0);
            bb_top(m)->data |= BLK_FRENZY_2ND | (blitz ? BLK_IS_BLITZ : 0);
        }
        return;
    }
    if (f->phase == 6) {
        // Frenzy second-block Rush (blitz with no movement left) resolved.
        int att = f->a;
        int def = f->b;
        bb_pop(m);
        if (m->ret & 1) {
            bb_push(m, BB_PROC_BLOCK, att, def, 0, 0);
            bb_top(m)->data |= BLK_FRENZY_2ND | BLK_IS_BLITZ;
        } else {
            // Failed rush: knocked down in place, no second block (turnover).
            bb_knockdown(m, att, BB_KD_FAILED_RUSH, 0);
        }
        return;
    }
    m->status = BB_STATUS_ERROR;
}

static int push_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int n = 0;
    if (f->phase == 4) { // Stand Firm window (pushee's coach)
        out[n++] = (bb_action){BB_A_USE_SKILL, BB_SK_STAND_FIRM, 0, 0};
        out[n++] = (bb_action){BB_A_DECLINE_SKILL, BB_SK_STAND_FIRM, 0, 0};
        return n;
    }
    if (f->phase == 0) {
        // Side Step (decision owner = defender): any unoccupied adjacent
        // square instead of the usual three. The predicate mirrors the
        // ownership choice in push_advance so legal/advance can never
        // disagree (review M8).
        if (side_step_active(m, f)) {
            const bb_player* dp = &m->players[f->b];
            for (int dx = -1; dx <= 1; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int x = dp->x + dx, y = dp->y + dy;
                    if (bb_on_pitch_xy(x, y) && !m->grid[x][y]) {
                        out[n++] = (bb_action){BB_A_PUSH_SQUARE, 0, (uint8_t)x, (uint8_t)y};
                    }
                }
            }
            return n;
        }
        int cand[3][2];
        push_candidates(m, f, cand);
        // Empty on-pitch squares first; if none, chains/crowd become legal.
        bool any_empty = false;
        for (int i = 0; i < 3; i++) {
            int x = cand[i][0], y = cand[i][1];
            if (bb_on_pitch_xy(x, y) && !m->grid[x][y]) {
                any_empty = true;
                out[n++] = (bb_action){BB_A_PUSH_SQUARE, 0, (uint8_t)x, (uint8_t)y};
            }
        }
        if (!any_empty) {
            for (int i = 0; i < 3; i++) {
                int x = cand[i][0], y = cand[i][1];
                if (!bb_on_pitch_xy(x, y)) {
                    // Encode crowd squares with arg=1 (x/y may be off-board).
                    out[n++] = (bb_action){BB_A_PUSH_SQUARE, 1,
                                           (uint8_t)(x < 0 ? 0 : (x >= BB_PITCH_LEN ? BB_PITCH_LEN - 1 : x)),
                                           (uint8_t)(y < 0 ? 0 : (y >= BB_PITCH_WID ? BB_PITCH_WID - 1 : y))};
                } else {
                    out[n++] = (bb_action){BB_A_PUSH_SQUARE, 2, (uint8_t)x, (uint8_t)y}; // chain
                }
            }
        }
        return n;
    }
    // phase 3: follow-up.
    out[n++] = (bb_action){BB_A_FOLLOW_UP, 1, 0, 0};
    out[n++] = (bb_action){BB_A_FOLLOW_UP, 0, 0, 0};
    return n;
}

static void push_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (f->phase == 4) { // Stand Firm window
        if (a.type == BB_A_USE_SKILL) {
            // Not moved; a POW still knocks them down in place; no
            // follow-up (no square vacated). Frenzy's second block can
            // still happen (mirror SK#STAND FIRM).
            bb_cover(BB_SK_STAND_FIRM);
            f->data |= PSH_STOOD_FIRM;
            f->phase = 5;
        } else {
            f->data |= PSH_SF_DECLINED;
            f->phase = 0; // re-run: side step / push candidates as normal
        }
        return;
    }
    if (f->phase == 0) {
        if (a.arg == 1) { // crowd
            f->data |= PSH_CROWD;
            f->phase = 2;
            return;
        }
        if (a.arg == 2) { // chain push: occupant must be pushed first
            int occupant = bb_slot_at(m, a.x, a.y);
            f->data |= 0; // keep
            f->phase = 1;
            uint8_t fx = a.x, fy = a.y;
            // Save chosen destination over origin AFTER computing chain dir:
            // chain origin = pushee's square.
            int pushee = f->b;
            int ox = m->players[pushee].x, oy = m->players[pushee].y;
            f->x = fx;
            f->y = fy;
            bb_push(m, BB_PROC_PUSH, pushee, occupant, ox, oy);
            bb_top(m)->data |= PSH_CHAIN;
            return;
        }
        f->x = a.x;
        f->y = a.y;
        f->phase = 2;
        return;
    }
    // phase 3: follow-up decision.
    if (a.arg == 1) {
        int att = f->a;
        bb_place(m, att, f->x, f->y);
        bb_player* ap = &m->players[att];
        if (ap->flags & BB_PF_HAS_BALL) {
            m->ball.x = ap->x;
            m->ball.y = ap->y;
        }
    }
    f->phase = 5;
}

// ===== KNOCKDOWN ==============================================================
// a = slot, b = cause, x = armour modifier.

static void knockdown_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    bb_player* p = &m->players[f.a];
    // A knockdown can be queued behind another resolution that removes the
    // player first (chain push into the crowd mid-action). Knocking down a
    // player who is no longer on the pitch corrupted locations — KO branch
    // overwrote CAS, drive-end then resurrected the casualty (review H2).
    if (p->location != BB_LOC_ON_PITCH) return;
    // STEADY FOOTING: "Whenever this player would be Knocked Down or Fall
    // Over, roll a D6. On a 6, this player does not get Knocked Down."
    if (bb_has_skill(&p->skills, BB_SK_STEADY_FOOTING) && bb_d6(rng) == 6) {
        bb_cover(BB_SK_STEADY_FOOTING);
        return;
    }
    // SABOTEUR (block knockdowns): "before the Armour Roll ... On a 4+ ...
    // the opposition player is also Knocked Down ... [the saboteur] is
    // automatically Knocked Out and the Armour Roll is not made."
    if (f.b == BB_KD_BLOCK && (int)f.y - 1 >= 0 &&
        bb_has_skill(&p->skills, BB_SK_SABOTEUR) && bb_d6(rng) >= 4) {
        bb_cover(BB_SK_SABOTEUR);
        int attacker = (int)f.y - 1;
        bool had = (p->flags & BB_PF_HAS_BALL) != 0;
        int sx = p->x, sy = p->y;
        if (had) bb_drop_ball(m);
        bb_remove_from_pitch(m, f.a, BB_LOC_KO); // auto-KO, no armour
        if (had) bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)sx, (uint8_t)sy);
        // The attacker is also knocked down (turnover only if carrying).
        bb_knockdown(m, attacker, BB_KD_TTM_LANDING, 0);
        return;
    }
    p->stance = BB_STANCE_PRONE;
    p->flags &= (uint16_t)~BB_PF_ROOTED; // going down un-roots
    if (f.b == BB_KD_TTM_LANDING) {
        // TTM landing: turnover only when the thrown player held the ball.
        if (p->flags & BB_PF_HAS_BALL) bb_turnover(m);
    } else if (BB_TEAM_OF(f.a) == m->active_team) {
        bb_turnover(m);
    }
    bool had_ball = (p->flags & BB_PF_HAS_BALL) != 0;
    int bx = p->x, by = p->y;
    if (had_ball && bb_has_skill(&p->skills, BB_SK_SAFE_PAIR_OF_HANDS)) {
        // SAFE PAIR OF HANDS: place the ball in an adjacent unoccupied
        // square instead of bouncing (first empty square; choice TODO).
        for (int dx = -1; dx <= 1 && had_ball; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = bx + dx, ny = by + dy;
                if (!bb_on_pitch_xy(nx, ny) || m->grid[nx][ny]) continue;
                bb_cover(BB_SK_SAFE_PAIR_OF_HANDS);
                bb_drop_ball(m);
                bb_ball_to(m, nx, ny);
                had_ball = false;
                break;
            }
        }
    }
    if (had_ball) {
        bb_drop_ball(m);
        if (BB_TEAM_OF(f.a) != m->active_team) {
            // Losing the ball is a turnover only for the active team; the
            // carrier-down turnover above covers the active case.
        }
        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
    }
    bb_push(m, BB_PROC_ARMOUR, f.a, 0, f.x, f.y); // y = causer+1; armour first
}

// ===== ARMOUR =================================================================
// a = slot, b = 1 if this is a foul (doubles -> sent off handled by FOUL),
// x = modifier. Pops; pushes INJURY if broken. ret = 1 broken / 0 held.

static void armour_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int causer = (int)f.y - 1;
    // IRON HARD SKIN: "Opposition players cannot apply any modifiers when
    // making an Armour Roll against this player. Additionally, the Claws
    // Skill cannot be used against this player."
    bool ihs = bb_has_skill(&m->players[f.a].skills, BB_SK_IRON_HARD_SKIN);
    bool unmodifiable = f.b == 3; // Stab / Projectile Vomit: "cannot be
                                  // modified in any way"
    int d1 = bb_d6(rng), d2 = bb_d6(rng);
    int ext = (ihs || unmodifiable) ? 0 : (int8_t)f.x + bb_hook_armour_mod(m, f.a, causer);
    // CHAINSAW (victim side): "+3 ... when the opposition Coach makes an
    // Armour Roll for this player. This +3 modifier must always be applied."
    if (!unmodifiable && bb_has_skill(&m->players[f.a].skills, BB_SK_CHAINSAW)) {
        ext += 3;
        bb_cover(BB_SK_CHAINSAW);
    }
    int total = d1 + d2 + ext;
    m->ret = 0;
    bool foul_double = f.b && d1 == d2;
    // LONE FOULER: "if there are no players providing an Offensive or
    // Defensive Assist ... may re-roll a failed Armour Roll." (Auto-applied;
    // FAQ: the re-rolled result overrides the original for send-off doubles.)
    if (f.b == 1 && d1 + d2 + ext < m->players[f.a].av && causer >= 0 &&
        (int8_t)f.x == 0 &&
        bb_has_skill(&m->players[causer].skills, BB_SK_LONE_FOULER)) {
        // Only when assists net to zero AND none existed (parent latched it
        // via FOUL frame data; approximated by zero net mod here).
        int n1 = bb_d6(rng), n2 = bb_d6(rng);
        d1 = n1;
        d2 = n2;
        total = d1 + d2 + ext;
        foul_double = f.b && d1 == d2;
    }
    bool broken = total >= m->players[f.a].av;
    bool mb_on_armour = unmodifiable; // suppress MB/Claws on unmodifiable rolls
    bool dp = f.b == 1 && causer >= 0 &&
              bb_has_skill(&m->players[causer].skills, BB_SK_DIRTY_PLAYER);
    if (!broken && !ihs && !unmodifiable && dp && total + 1 >= m->players[f.a].av) {
        broken = true; // Dirty Player +1 spent on the armour roll
        mb_on_armour = true;
    }
    // Claws: an unmodified armour roll of 8+ always breaks armour. Checked
    // BEFORE Mighty Blow so a natural 8+ never wastes the MB spend: Claws
    // breaks for free and MB stays available for the injury roll — the
    // mirror restricts neither skill against the other (panel finding
    // amending D16; the old "MB cannot stack with Claws" comment had no
    // rulebook basis and inverted the Claws->high-AV target gradient).
    if (!broken && !ihs && !unmodifiable && causer >= 0 && d1 + d2 >= 8 &&
        bb_has_skill(&m->players[causer].skills, BB_SK_CLAWS)) {
        broken = true; // MB unspent: mb_on_armour stays false
    }
    if (!broken && !ihs && !unmodifiable && causer >= 0 &&
        bb_has_skill(&m->players[causer].skills, BB_SK_MIGHTY_BLOW) &&
        total + 1 >= m->players[f.a].av) {
        // Mighty Blow (+1): auto-applied to the armour roll when that turns a
        // miss into a break; otherwise saved for the injury roll (D-policy,
        // see DECISIONS.md).
        broken = true;
        mb_on_armour = true;
    }
    if (foul_double) {
        // SNEAKY GIT: "not Sent-off ... if a natural double is rolled for the
        // Armour Roll, so long as the target player's Armour is not broken."
        if (broken || causer < 0 ||
            !bb_has_skill(&m->players[causer].skills, BB_SK_SNEAKY_GIT)) {
            m->ret |= 2;
        }
    }
    if (broken) {
        m->ret |= 1;
        bb_push(m, BB_PROC_INJURY, f.a, 0, 0, f.y);
        if (f.b) bb_top(m)->b = 2; // propagate foul context to injury
        if (mb_on_armour) bb_top(m)->x = 1; // MB consumed on armour
    }
}

// ===== INJURY =================================================================
// a = slot, b: 0 normal, 1 crowd (no armour was rolled), 2 foul context.

static void injury_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int slot = f.a;
    int causer = (int)f.y - 1;
    bb_player* p = &m->players[slot];
    // Direct injuries (Stab/Vomit/Chainsaw) reach here with the victim still
    // standing and possibly holding the ball: any injury outcome makes them
    // at best Stunned, so the ball drops and bounces (after resolution).
    if (p->flags & BB_PF_HAS_BALL) {
        int bx = p->x, by = p->y;
        bool active_carrier = BB_TEAM_OF(slot) == m->active_team;
        if (active_carrier) bb_turnover(m);
        bb_drop_ball(m);
        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
    }
    int d1 = bb_d6(rng), d2 = bb_d6(rng);
    int total = d1 + d2 + bb_hook_injury_mod(m, slot, causer);
    if (causer >= 0 && f.x == 0 &&
        bb_has_skill(&m->players[causer].skills, BB_SK_MIGHTY_BLOW)) {
        total += 1; // Mighty Blow not consumed on the armour roll
    }
    if (f.b == 2 && causer >= 0 && f.x == 0 &&
        bb_has_skill(&m->players[causer].skills, BB_SK_DIRTY_PLAYER)) {
        total += 1; // Dirty Player not consumed on the armour roll
    }
    bool stunty = bb_is_stunty(m, slot);
    bool foul = f.b == 2;
    if (foul && d1 == d2) m->ret |= 2; // doubles on injury: spotted by the ref

    int stun_max = stunty ? BB_INJ_STUNTY_STUN_MAX : BB_INJ_STUN_MAX;
    int ko_max = stunty ? BB_INJ_STUNTY_KO_MAX : BB_INJ_KO_MAX;
    // Thick Skull (BB2025, deterministic): KO only on the top of the KO band;
    // the bottom of the band becomes a Stunned result. No extra roll.
    if (bb_has_skill(&p->skills, BB_SK_THICK_SKULL)) stun_max = ko_max - 1;

    if (total <= stun_max) {
        if (f.b == 1) {
            // Crowd: "stunned" result puts the player in the reserves box.
            p->location = BB_LOC_RESERVES;
        } else {
            p->stance = BB_STANCE_STUNNED;
        }
        return;
    }
    if (total <= ko_max) {
        // APOTHECARY (KO): once per game, the player stays on the pitch
        // Stunned instead (crowd KOs go to Reserves). Auto-policy here would
        // be wrong (saving it for casualties is usually better), so offer a
        // decision via the KO-patch window.
        int team = BB_TEAM_OF(slot);
        if (m->apothecary[team] > 0) {
            bb_push(m, BB_PROC_KO_RECOVERY, slot, f.b, 0, 0); // reuse id as KO-patch window
            return;
        }
        if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_KO);
        else p->location = BB_LOC_KO;
        return;
    }
    if (stunty && total <= BB_INJ_STUNTY_BH_MAX) {
        // Stunty band: straight Badly Hurt, no casualty roll.
        if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_CAS);
        else p->location = BB_LOC_CAS;
        return;
    }
    bb_push(m, BB_PROC_CASUALTY, slot, f.b, 0, f.y); // y = causer+1
}

// ===== CASUALTY ===============================================================
// a = slot. D16 on the casualty table. League persistence comes later; in
// match terms every casualty is out for the game.
// Apothecary window (phase 1: use/decline; phase 2: "may select either of
// the two results" — a CHOOSE_OPTION decision, 0 = original roll in f->x,
// 1 = the apothecary's new roll in f->y).

// Casualty telemetry hook (spectator memorial, eval coroners). Process-wide
// function pointer, NOT match state: bb_match stays memcpy-clean and the
// demo-bank fingerprint is untouched. causer = slot that caused the
// knockdown (-1 = self-inflicted: failed dodge/GFI etc.); ctx mirrors the
// INJURY frame's b (0 = block-family attack, 1 = crowd, 2 = foul); roll is
// the post-Decay D16 index (15-16 = DEAD).
void (*bb_casualty_hook)(const bb_match*, int slot, int causer, int roll,
                         int ctx) = 0;

// Apply one casualty result (rolls are post-Decay table indices). Every
// casualty is out for the match; only the apothecary's Badly Hurt pick
// (phase 2 below) routes to Reserves instead.
static void casualty_resolve(bb_match* m, int slot, int roll, int causer,
                             int ctx) {
    bb_player* p = &m->players[slot];
    p->spp_game = (uint8_t)bb_casualty_table[roll]; // outcome (league mode)
    if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_CAS);
    else p->location = BB_LOC_CAS;
    if (bb_casualty_hook) bb_casualty_hook(m, slot, causer, roll, ctx);
}

static void casualty_advance(bb_match* m, bb_rng* rng) {
    if (bb_top(m)->phase == 1 || bb_top(m)->phase == 2) {
        bb_need_decision(m, BB_TEAM_OF(bb_top(m)->a));
        return;
    }
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int slot = f.a;
    bb_player* p = &m->players[slot];
    // REGENERATION: "before making the Casualty Roll ... On a 4+ this player
    // regenerates and ignores the Casualty ... placed in the Reserves Box."
    if (bb_has_skill(&p->skills, BB_SK_REGENERATION) && bb_d6(rng) >= 4) {
        if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_RESERVES);
        else p->location = BB_LOC_RESERVES;
        return;
    }
    int roll = bb_d16(rng);
    // DECAY: "Apply a +1 modifier to any Casualty Roll made against this
    // player."
    if (bb_has_skill(&p->skills, BB_SK_DECAY) && roll < 16) roll += 1;
    int team = BB_TEAM_OF(slot);
    if (m->apothecary[team] > 0) {
        // Apothecary window: the coach may have a second Casualty Roll made
        // and "may select either of the two results to apply" (mirror
        // GB#APOTHECARY; Badly Hurt selected -> Reserves). x/y hold the two
        // rolls, so the telemetry chain (ctx, causer+1) rides `data`.
        bb_push(m, BB_PROC_CASUALTY, slot, 1, (uint8_t)roll, 0);
        bb_top(m)->phase = 1; // use/decline decision
        bb_top(m)->data = (uint16_t)(((uint16_t)f.b << 8) | f.y);
        return;
    }
    casualty_resolve(m, slot, roll, (int)f.y - 1, f.b);
}

static int casualty_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    if (f->phase == 2) { // pick either casualty result (FFB apothecaryChoice)
        out[0] = (bb_action){BB_A_CHOOSE_OPTION, 0, 0, 0}; // original roll
        out[1] = (bb_action){BB_A_CHOOSE_OPTION, 1, 0, 0}; // apothecary roll
        return 2;
    }
    out[0] = (bb_action){BB_A_APOTHECARY, 1, 0, 0};
    out[1] = (bb_action){BB_A_APOTHECARY, 0, 0, 0};
    return 2;
}

static void casualty_apply(bb_match* m, bb_action a, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int slot = f->a;
    bb_player* p = &m->players[slot];
    int team = BB_TEAM_OF(slot);
    if (f->phase == 1) {
        if (a.arg == 1) { // use the apothecary: second roll, then the pick
            m->apothecary[team]--;
            int roll2 = bb_d16(rng);
            if (bb_has_skill(&p->skills, BB_SK_DECAY) && roll2 < 16) roll2 += 1;
            f->y = (uint8_t)roll2;
            f->phase = 2; // "may select either of the two results to apply"
            return;
        }
        int roll1 = f->x;
        int cs = (int)(f->data & 0xFF) - 1, cx = f->data >> 8;
        bb_pop(m);
        casualty_resolve(m, slot, roll1, cs, cx);
        return;
    }
    // phase 2: result picked (0 = original f->x, 1 = new f->y).
    int pick = a.arg ? f->y : f->x;
    int cs = (int)(f->data & 0xFF) - 1, cx = f->data >> 8;
    bb_pop(m);
    if (bb_casualty_table[pick] == BB_CAS_BADLY_HURT) {
        // Patched-up: "placed into their Reserves Box instead".
        if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_RESERVES);
        else p->location = BB_LOC_RESERVES;
        p->spp_game = BB_CAS_BADLY_HURT;
        return;
    }
    casualty_resolve(m, slot, pick, cs, cx);
}

// ===== FOUL ===================================================================
// a = fouler, b = victim. Armour with net assists; natural doubles on armour
// or injury -> sent off (turnover).

static void foul_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (f->phase == 0) {
        int off = count_assists_ex(m, f->a, f->b, true);
        int def = count_assists_ex(m, f->b, f->a, true);
        int mod = off - def;
        // DIRTY PLAYER (+1): "may apply a +1 modifier to either the Armour
        // Roll or Injury Roll" — auto-policy like Mighty Blow (armour first
        // if it converts; ARMOUR/INJURY procs read the causer's DP via the
        // foul flag). Modelled by the same MB machinery: DP acts as MB for
        // fouls. We pass it via the armour mod when no assists offset is
        // pending: handled inside ARMOUR via causer skill check (foul ctx).
        f->data = (uint16_t)((off == 0 && def == 0) ? 1 : 0); // lone-foul latch
        f->phase = 1;
        m->ret = 0;
        bb_push(m, BB_PROC_ARMOUR, f->b, 1, mod & 0xFF, f->a + 1); // y = fouler+1
        return;
    }
    if (f->phase == 1) {
        // Children done; check for the ref.
        bool spotted = (m->ret & 2) != 0;
        int fouler = f->a;
        if (!spotted) {
            bb_pop(m);
            return;
        }
        // BRIBE: may be used when a player is sent off — D6 2+: the player
        // is not sent off (bribe spent either way). Auto-used before Argue
        // the Call (FAQ: bribes usable even when arguing is unavailable).
        if (m->bribes[BB_TEAM_OF(fouler)] > 0) {
            m->bribes[BB_TEAM_OF(fouler)]--;
            if (bb_d6(rng) >= 2) {
                bb_pop(m);
                bb_turnover(m); // the foul still turned over? No: a bribed
                // send-off is cancelled entirely — no turnover from send-off.
                m->turnover = 0;
                return;
            }
        }
        // Sent off: the fouling coach may Argue the Call (unless already
        // ejected from the dugout).
        if (m->coach_ejected[BB_TEAM_OF(fouler)]) {
            bb_pop(m);
            if (m->players[fouler].flags & BB_PF_HAS_BALL) {
                int bx = m->players[fouler].x, by = m->players[fouler].y;
                bb_drop_ball(m);
                bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
            }
            bb_remove_from_pitch(m, fouler, BB_LOC_SENT_OFF);
            bb_turnover(m);
            return;
        }
        f->phase = 2;
        bb_need_decision(m, BB_TEAM_OF(fouler));
        return;
    }
    m->status = BB_STATUS_ERROR;
}

static int foul_legal(const bb_match* m, bb_action* out) {
    (void)m;
    out[0] = (bb_action){BB_A_CHOOSE_OPTION, 1, 0, 0}; // argue the call
    out[1] = (bb_action){BB_A_CHOOSE_OPTION, 0, 0, 0}; // accept the send-off
    return 2;
}

static void foul_apply(bb_match* m, bb_action a, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int fouler = f->a;
    int team = BB_TEAM_OF(fouler);
    bool stays = false;
    if (a.arg == 1) {
        int die = bb_d6(rng);
        if (die == 1) {
            m->coach_ejected[team] = 1; // "You're outta here!"
        } else if (die == 6) {
            stays = true; // returned to the pitch; the turnover still stands
        }
    }
    bb_pop(m);
    if (!stays) {
        // A sent-off ball carrier drops the ball; it bounces from their square.
        if (m->players[fouler].flags & BB_PF_HAS_BALL) {
            int bx = m->players[fouler].x, by = m->players[fouler].y;
            bb_drop_ball(m);
            bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
        }
        bb_remove_from_pitch(m, fouler, BB_LOC_SENT_OFF);
    }
    bb_turnover(m);
}

const bb_proc_vtable bb_proc_block_vtable = {block_advance, block_legal, block_apply};
const bb_proc_vtable bb_proc_push_vtable = {push_advance, push_legal, push_apply};
const bb_proc_vtable bb_proc_knockdown_vtable = {knockdown_advance, 0, 0};
const bb_proc_vtable bb_proc_armour_vtable = {armour_advance, 0, 0};
const bb_proc_vtable bb_proc_injury_vtable = {injury_advance, 0, 0};
const bb_proc_vtable bb_proc_casualty_vtable = {casualty_advance, casualty_legal, casualty_apply};
const bb_proc_vtable bb_proc_foul_vtable = {foul_advance, foul_legal, foul_apply};

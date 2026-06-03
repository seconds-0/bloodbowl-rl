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

static int count_assists(const bb_match* m, int for_slot, int against_slot) {
    return count_assists_ex(m, for_slot, against_slot, false);
}

enum { PSH_POW = 1 << 0, PSH_CHAIN = 1 << 1, PSH_MOVED = 1 << 2, PSH_FUP = 1 << 3,
       PSH_CROWD = 1 << 4, PSH_FROM_BLITZ = 1 << 5, PSH_STOOD_FIRM = 1 << 6 };

// ===== BLOCK ==================================================================
// a = attacker, b = defender.
// data: bits 0-2 die0, 3-5 die1, 6-8 die2, 9-10 ndice-1, bit11 chooser-is-defender,
//       bit12 reroll used.
// phase 0: compute pool, roll; 1: reroll window; 2: choose die; 3: resolving
//          (wrestle window: phase 4).

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
        // (phase 0 runs once per BLOCK frame; a Frenzy second block is a new
        // Block Action and correctly rolls Foul Appearance again.)
        if (bb_has_skill(&m->players[def].skills, BB_SK_FOUL_APPEARANCE)) {
            if (bb_d6(rng) == 1) {
                bb_pop(m);
                return;
            }
        }
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
        int st_d = base_d + count_assists(m, def, att);
        if (f->data & BLK_IS_BLITZ) st_a += bb_hook_st_mod_blitz(m, att); // Horns
        int nd = 1;
        bool def_chooses = false;
        if (st_a > st_d) nd = st_a > 2 * st_d ? 3 : 2;
        else if (st_d > st_a) {
            nd = st_d > 2 * st_a ? 3 : 2;
            def_chooses = true;
        }
        f->data = (uint16_t)((f->data & BLK_IS_BLITZ) | ((nd - 1) << 9) |
                             (def_chooses ? BLK_DEF_CHOOSES : 0));
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
    m->status = BB_STATUS_ERROR;
}

static int block_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int n = 0;
    if (f->phase == 1) {
        out[n++] = (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0};
        out[n++] = (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0};
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
            f->data |= BLK_RR_USED;
            int loner = bb_loner_value(m, att);
            if (!(loner > 0 && bb_roll(rng, 6) < loner)) {
                blk_roll_pool(f, rng);
            }
        }
        f->phase = 2;
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
                bb_pop(m);
                bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
                bb_top(m)->data |= PSH_FROM_BLITZ;
                return;
            }
            // Wrestle (either player): both players are PLACED Prone — no
            // armour rolls, no knockdown turnover. (Rules allow declining;
            // auto-applied here — see DECISIONS.md.) A carrier placed prone
            // drops the ball; an ACTIVE carrier placed prone is a turnover.
            if ((bb_has_wrestle(m, att) && !(m->players[att].flags & BB_PF_DISTRACTED)) ||
                (bb_has_wrestle(m, def) && !(m->players[def].flags & BB_PF_DISTRACTED))) {
                bb_pop(m);
                int both[2] = {def, att};
                for (int i = 0; i < 2; i++) {
                    bb_player* p = &m->players[both[i]];
                    p->stance = BB_STANCE_PRONE;
                    if (p->flags & BB_PF_HAS_BALL) {
                        int bx = p->x, by = p->y;
                        if (BB_TEAM_OF(both[i]) == m->active_team) bb_turnover(m);
                        bb_drop_ball(m);
                        bb_push(m, BB_PROC_SCATTER, 0, 1, (uint8_t)bx, (uint8_t)by);
                    }
                }
                return;
            }
            // Block skill: a player with Block (not Distracted) stays up.
            bool att_down = !(bb_has_block(m, att) && !(m->players[att].flags & BB_PF_DISTRACTED));
            bool def_down = !(bb_has_block(m, def) && !(m->players[def].flags & BB_PF_DISTRACTED));
            bb_pop(m);
            // Defender resolves first, attacker's knockdown (turnover) after.
            if (att_down) bb_knockdown2(m, att, BB_KD_BLOCK, 0, def);
            if (def_down) bb_knockdown2(m, def, BB_KD_BLOCK, 0, att);
            return;
        }
        case BB_BD_PUSH_1:
        case BB_BD_PUSH_2: {
            uint16_t blitz = f->data & BLK_IS_BLITZ;
            uint16_t f2 = f->data & BLK_FRENZY_2ND;
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            if (blitz) bb_top(m)->data |= PSH_FROM_BLITZ;
            if (f2) bb_top(m)->data |= 1 << 7; // PSH_FRENZY_DONE
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
            if (f2) bb_top(m)->data |= 1 << 7;
            return;
        }
        case BB_BD_POW: {
            uint16_t blitz = f->data & BLK_IS_BLITZ;
            uint16_t f2 = f->data & BLK_FRENZY_2ND;
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            bb_top(m)->data |= 1; // pow flag
            if (blitz) bb_top(m)->data |= PSH_FROM_BLITZ;
            if (f2) bb_top(m)->data |= 1 << 7;
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
        if (m->players[f->b].flags & BB_PF_ROOTED) def_flags |= BB_PUSHF_STAND_FIRM;
        bool jugg = (f->data & PSH_FROM_BLITZ) &&
                    bb_has_skill(&m->players[f->a].skills, BB_SK_JUGGERNAUT);
        if (((def_flags & BB_PUSHF_STAND_FIRM) && !jugg) ||
            (m->players[f->b].flags & BB_PF_ROOTED)) {
            // Stand Firm / Rooted: the player is not moved; a POW still
            // knocks them down in place; no follow-up (no square vacated).
            f->data |= PSH_STOOD_FIRM;
            f->phase = 5;
            return;
        }
        bool side_step = (def_flags & BB_PUSHF_SIDE_STEP) && !jugg &&
                         !bb_has_skill(&m->players[f->a].skills, BB_SK_GRAB);
        // Side Step: the DEFENDER's coach chooses the square (any adjacent
        // free square, not just the usual three) — handled in legal/apply via
        // the decision owner.
        bb_need_decision(m, side_step ? BB_TEAM_OF(f->b) : m->active_team);
        return;
    }
    if (f->phase == 1) {
        // Chain child finished; destination square is now free — relocate.
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
            if (BB_TEAM_OF(def) == m->active_team) bb_turnover(m);
            bb_drop_ball(m);
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
        int def = f->b;
        uint16_t data = f->data;
        bb_pop(m);
        if (data & PSH_CROWD) {
            return; // crowd was resolved at relocation time
        }
        if (data & PSH_POW) {
            bb_knockdown(m, def, BB_KD_BLOCK, 0);
        } else {
            bb_check_td(m); // pushed into their own end zone while holding
        }
        return;
    }
    m->status = BB_STATUS_ERROR;
}

static int push_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int n = 0;
    if (f->phase == 0) {
        // Side Step (decision owner = defender): any unoccupied adjacent
        // square instead of the usual three.
        bool jugg = (f->data & PSH_FROM_BLITZ) &&
                    bb_has_skill(&m->players[f->a].skills, BB_SK_JUGGERNAUT);
        if ((bb_hook_push_flags(m, f->b) & BB_PUSHF_SIDE_STEP) && !jugg &&
            !bb_has_skill(&m->players[f->a].skills, BB_SK_GRAB)) {
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
            if (n > 0) return n;
            // No free square: fall through to the normal three candidates.
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
    (void)rng;
    bb_frame f = *bb_top(m);
    bb_pop(m);
    bb_player* p = &m->players[f.a];
    p->stance = BB_STANCE_PRONE;
    p->flags &= (uint16_t)~BB_PF_ROOTED; // going down un-roots
    if (BB_TEAM_OF(f.a) == m->active_team) bb_turnover(m);
    bool had_ball = (p->flags & BB_PF_HAS_BALL) != 0;
    int bx = p->x, by = p->y;
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
    if (!broken && !ihs && !unmodifiable && causer >= 0 &&
        bb_has_skill(&m->players[causer].skills, BB_SK_MIGHTY_BLOW) &&
        total + 1 >= m->players[f.a].av) {
        // Mighty Blow (+1): auto-applied to the armour roll when that turns a
        // miss into a break; otherwise saved for the injury roll (D-policy,
        // see DECISIONS.md).
        broken = true;
        mb_on_armour = true;
    }
    // Claws: an unmodified armour roll of 8+ always breaks armour.
    if (!broken && !ihs && !unmodifiable && causer >= 0 && d1 + d2 >= 8 &&
        bb_has_skill(&m->players[causer].skills, BB_SK_CLAWS)) {
        broken = true;
        mb_on_armour = true; // claws break leaves MB for... rules: MB cannot
                             // be used with Claws on the same roll; spend it.
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
    bb_push(m, BB_PROC_CASUALTY, slot, f.b, 0, 0);
}

// ===== CASUALTY ===============================================================
// a = slot. D16 on the casualty table. League persistence comes later; in
// match terms every casualty is out for the game. TODO(phase3): apothecary.

static void casualty_advance(bb_match* m, bb_rng* rng) {
    if (bb_top(m)->phase == 1) {
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
        // Apothecary window: coach may have a second Casualty Roll made and
        // pick either result (Badly Hurt selected -> Reserves).
        bb_push(m, BB_PROC_CASUALTY, slot, 1, (uint8_t)roll, 0);
        bb_top(m)->phase = 1; // decision phase
        return;
    }
    p->spp_game = (uint8_t)bb_casualty_table[roll]; // outcome (league mode)
    if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_CAS);
    else p->location = BB_LOC_CAS;
}

static int casualty_legal(const bb_match* m, bb_action* out) {
    (void)m;
    out[0] = (bb_action){BB_A_APOTHECARY, 1, 0, 0};
    out[1] = (bb_action){BB_A_APOTHECARY, 0, 0, 0};
    return 2;
}

static void casualty_apply(bb_match* m, bb_action a, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int slot = f.a;
    bb_player* p = &m->players[slot];
    int team = BB_TEAM_OF(slot);
    int roll1 = f.x;
    if (a.arg == 1) {
        m->apothecary[team]--;
        int roll2 = bb_d16(rng);
        if (bb_has_skill(&p->skills, BB_SK_DECAY) && roll2 < 16) roll2 += 1;
        // The controlling coach picks either result; auto-pick the better
        // (lower) one — strictly dominant.
        int pick = bb_casualty_table[roll1] <= bb_casualty_table[roll2] ? roll1 : roll2;
        if (bb_casualty_table[pick] == BB_CAS_BADLY_HURT) {
            if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_RESERVES);
            else p->location = BB_LOC_RESERVES;
            p->spp_game = BB_CAS_BADLY_HURT;
            return;
        }
        p->spp_game = (uint8_t)bb_casualty_table[pick];
        if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_CAS);
        else p->location = BB_LOC_CAS;
        return;
    }
    p->spp_game = (uint8_t)bb_casualty_table[roll1];
    if (p->location == BB_LOC_ON_PITCH) bb_remove_from_pitch(m, slot, BB_LOC_CAS);
    else p->location = BB_LOC_CAS;
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

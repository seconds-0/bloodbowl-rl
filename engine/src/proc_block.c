// proc_block.c — BLOCK, PUSH (incl. chains & crowd), KNOCKDOWN, ARMOUR,
// INJURY, CASUALTY, FOUL.
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/gen_tables.h"

// --- assists -----------------------------------------------------------------
static int count_assists(const bb_match* m, int for_slot, int against_slot) {
    int n = 0;
    const bb_player* target = &m->players[against_slot];
    int team = BB_TEAM_OF(for_slot);
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (s == for_slot) continue;
        if (m->players[s].location != BB_LOC_ON_PITCH) continue;
        if (!bb_adjacent(m->players[s].x, m->players[s].y, target->x, target->y)) continue;
        if (bb_can_assist(m, s, against_slot)) n++;
    }
    return n;
}

// ===== BLOCK ==================================================================
// a = attacker, b = defender.
// data: bits 0-2 die0, 3-5 die1, 6-8 die2, 9-10 ndice-1, bit11 chooser-is-defender,
//       bit12 reroll used.
// phase 0: compute pool, roll; 1: reroll window; 2: choose die; 3: resolving
//          (wrestle window: phase 4).

enum { BLK_RR_USED = 1 << 12, BLK_DEF_CHOOSES = 1 << 11 };

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
        int st_a = m->players[att].st + count_assists(m, att, def);
        int st_d = m->players[def].st + count_assists(m, def, att);
        int nd = 1;
        bool def_chooses = false;
        if (st_a > st_d) nd = st_a > 2 * st_d ? 3 : 2;
        else if (st_d > st_a) {
            nd = st_d > 2 * st_a ? 3 : 2;
            def_chooses = true;
        }
        f->data = (uint16_t)(((nd - 1) << 9) | (def_chooses ? BLK_DEF_CHOOSES : 0));
        blk_roll_pool(f, rng);
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
            bb_knockdown(m, att, BB_KD_BLOCK, 0);
            return;
        case BB_BD_BOTH_DOWN: {
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
            if (att_down) bb_knockdown(m, att, BB_KD_BLOCK, 0);
            if (def_down) bb_knockdown(m, def, BB_KD_BLOCK, 0);
            return;
        }
        case BB_BD_PUSH_1:
        case BB_BD_PUSH_2:
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            return;
        case BB_BD_STUMBLE: {
            bool dodge = bb_has_dodge_skill(m, def) &&
                         !(m->players[def].flags & BB_PF_DISTRACTED) &&
                         !bb_has_skill(&m->players[att].skills, BB_SK_TACKLE);
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            if (!dodge) bb_top(m)->data |= 1; // pow flag
            return;
        }
        case BB_BD_POW:
            bb_pop(m);
            bb_push(m, BB_PROC_PUSH, att, def, ax, ay);
            bb_top(m)->data |= 1; // pow flag
            return;
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

enum { PSH_POW = 1 << 0, PSH_CHAIN = 1 << 1, PSH_MOVED = 1 << 2, PSH_FUP = 1 << 3,
       PSH_CROWD = 1 << 4 };

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
        bb_need_decision(m, m->active_team); // attacking coach picks the square
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
    bb_push(m, BB_PROC_ARMOUR, f.a, 0, f.x, 0); // resolves before the bounce
}

// ===== ARMOUR =================================================================
// a = slot, b = 1 if this is a foul (doubles -> sent off handled by FOUL),
// x = modifier. Pops; pushes INJURY if broken. ret = 1 broken / 0 held.

static void armour_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int d1 = bb_d6(rng), d2 = bb_d6(rng);
    int total = d1 + d2 + (int8_t)f.x;
    m->ret = 0;
    if (f.b) { // foul: report doubles to the FOUL parent via high bit
        if (d1 == d2) m->ret |= 2;
    }
    if (total >= m->players[f.a].av) {
        m->ret |= 1;
        bb_push(m, BB_PROC_INJURY, f.a, 0, 0, 0);
        if (f.b) bb_top(m)->b = 2; // propagate foul context to injury
    }
}

// ===== INJURY =================================================================
// a = slot, b: 0 normal, 1 crowd (no armour was rolled), 2 foul context.

static void injury_advance(bb_match* m, bb_rng* rng) {
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int slot = f.a;
    bb_player* p = &m->players[slot];
    int d1 = bb_d6(rng), d2 = bb_d6(rng);
    int total = d1 + d2;
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
    bb_frame f = *bb_top(m);
    bb_pop(m);
    int slot = f.a;
    bb_player* p = &m->players[slot];
    int roll = bb_d16(rng);
    (void)bb_casualty_table[roll]; // outcome recorded for league mode later
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
        int off = count_assists(m, f->a, f->b);
        int def = count_assists(m, f->b, f->a);
        int mod = off - def;
        f->phase = 1;
        m->ret = 0;
        bb_push(m, BB_PROC_ARMOUR, f->b, 1, mod & 0xFF, 0);
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
const bb_proc_vtable bb_proc_casualty_vtable = {casualty_advance, 0, 0};
const bb_proc_vtable bb_proc_foul_vtable = {foul_advance, foul_legal, foul_apply};

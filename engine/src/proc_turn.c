// proc_turn.c — TEAM_TURN, ACTIVATION, TURNOVER.
#include "bb/bb_proc.h"
#include "bb/bb_hooks.h"

// ===== TEAM_TURN =============================================================
// a = team. phase 0: turn start bookkeeping. phase 1: activation loop.
// phase 2: turn end bookkeeping.

static void turn_start(bb_match* m, int team) {
    m->active_team = (uint8_t)team;
    m->turn[team]++;
    m->blitz_used = 0;
    m->pass_used = 0;
    m->handoff_used = 0;
    m->foul_used = 0;
    m->ttm_used = 0;
    m->secure_used = 0;
    m->turnover = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        bb_player* p = &m->players[s];
        p->flags &= (uint16_t)~(BB_PF_USED | BB_PF_ACTIVATING | BB_PF_USED_SKILL_A |
                                BB_PF_USED_SKILL_B | BB_PF_BLITZED);
        p->moved = 0;
        p->rushes = 0;
        p->skill_rr_used = 0;
        // Players who START their team's turn Stunned are marked; only those
        // roll over to Prone at the END of this turn (players stunned during
        // the turn wait for the end of the NEXT turn).
        if (p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STUNNED) {
            p->stance = BB_STANCE_STUNNED_USED;
        }
    }
}

static void pick_me_up(bb_match* m, bb_rng* rng, int helping_team) {
    for (int s = helping_team * BB_TEAM_SLOTS; s < (helping_team + 1) * BB_TEAM_SLOTS; s++) {
        bb_player* p = &m->players[s];
        if (p->location != BB_LOC_ON_PITCH || p->stance != BB_STANCE_PRONE) continue;
        bool near = false;
        for (int s2 = helping_team * BB_TEAM_SLOTS;
             s2 < (helping_team + 1) * BB_TEAM_SLOTS && !near; s2++) {
            const bb_player* q = &m->players[s2];
            if (q->location != BB_LOC_ON_PITCH || q->stance != BB_STANCE_STANDING) continue;
            if (!bb_has_skill(&q->skills, BB_SK_PICK_ME_UP)) continue;
            int dx = q->x - p->x, dy = q->y - p->y;
            if (dx < 0) dx = -dx;
            if (dy < 0) dy = -dy;
            if ((dx > dy ? dx : dy) <= 3) near = true;
        }
        if (near && bb_d6(rng) >= 5) p->stance = BB_STANCE_STANDING;
    }
}

static void turn_end(bb_match* m, int team) {
    // Only players who STARTED this turn Stunned (marked at turn start) roll
    // over to Prone now.
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        bb_player* p = &m->players[s];
        if (p->location == BB_LOC_ON_PITCH && p->stance == BB_STANCE_STUNNED_USED) {
            p->stance = BB_STANCE_PRONE;
        }
    }
    m->turnover = 0;
    m->cheer_assist[team] = 0; // Cheering Fans buff is "next turn" only (review LOW)
    // Next team takes over (MATCH reads active_team to alternate).
    m->active_team = (uint8_t)(1 - team);
}

static bool can_activate(const bb_match* m, int s) {
    const bb_player* p = &m->players[s];
    if (p->location != BB_LOC_ON_PITCH) return false;
    if (p->flags & BB_PF_USED) return false;
    if (p->stance == BB_STANCE_STUNNED || p->stance == BB_STANCE_STUNNED_USED) return false;
    return true;
}

static void team_turn_advance(bb_match* m, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int team = f->a;
    if (f->phase == 0) {
        turn_start(m, team);
        f->phase = 1;
        return;
    }
    if (f->phase == 1) {
        if (m->turnover) {
            f->phase = 2;
            return;
        }
        bool any = false;
        for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
            if (can_activate(m, s)) {
                any = true;
                break;
            }
        }
        if (!any) {
            f->phase = 2;
            return;
        }
        bb_need_decision(m, team);
        return;
    }
    {
        bb_rng* prng = rng; // PICK-ME-UP rolls at the end of the opponent's turn
        pick_me_up(m, prng, 1 - team);
    }
    turn_end(m, team);
    bb_pop(m);
}

static int team_turn_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int team = f->a;
    int n = 0;
    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        if (can_activate(m, s)) {
            out[n++] = (bb_action){BB_A_ACTIVATE, (uint8_t)s, 0, 0};
        }
    }
    out[n++] = (bb_action){BB_A_END_TURN, 0, 0, 0};
    return n;
}

static void team_turn_apply(bb_match* m, bb_action a, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    if (a.type == BB_A_END_TURN) {
        f->phase = 2;
        return;
    }
    bb_push(m, BB_PROC_ACTIVATION, a.arg, 0, 0, 0);
}

// ===== ACTIVATION ============================================================
// a = player slot, b = declared bb_act_kind. phase 0: declare action kind.
// phase 1: child (MOVE machine) is running / wrap up on re-entry.
// phase 2: negatrait gate failed — team re-roll window (USE/DECLINE).

static bool has_adjacent_standing_opponent(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = p->x + dx, ny = p->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(slot) &&
                m->players[s].stance == BB_STANCE_STANDING) {
                return true;
            }
        }
    }
    return false;
}

static bool has_adjacent_downed_opponent(const bb_match* m, int slot) {
    const bb_player* p = &m->players[slot];
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = p->x + dx, ny = p->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s >= 0 && BB_TEAM_OF(s) != BB_TEAM_OF(slot) &&
                m->players[s].stance != BB_STANCE_STANDING) {
                return true;
            }
        }
    }
    return false;
}

static void activation_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_frame* f = bb_top(m);
    int slot = f->a;
    if (f->phase == 0) {
        m->players[slot].flags &= (uint16_t)~BB_PF_EYE_GOUGED; // recovers
        // DISTRACTED clears when the player is next activated (FAQ: before
        // declaring). The old clear lived inside the gate-success branch, so
        // gate-less players — i.e. nearly every Hypnotic Gaze victim — stayed
        // Distracted for the whole drive (review H4).
        m->players[slot].flags &= (uint16_t)~BB_PF_DISTRACTED;
        m->players[slot].flags |= BB_PF_ACTIVATING;
        // The negatrait gate rolls AFTER the declaration ("after declaring
        // their Action", mirror) — in activation_apply.
        bb_need_decision(m, BB_TEAM_OF(slot));
        return;
    }
    if (f->phase == 2) { // negatrait gate failed: team re-roll window
        bb_need_decision(m, BB_TEAM_OF(slot));
        return;
    }
    // Child finished (or turnover unwound it).
    bb_player* p = &m->players[slot];
    p->flags &= (uint16_t)~BB_PF_ACTIVATING;
    p->flags |= BB_PF_USED;
    bb_pop(m);
}

// Situational gate modifier (mirror text): REALLY STUPID "+2 ... if they
// have any Standing team-mates who are not Distracted, and do not have the
// Really Stupid Trait, adjacent"; UNCHANNELLED FURY "+2 ... if they have
// declared a Block Action or a Blitz Action".
static int gate_modifier(const bb_match* m, int slot, int gskill, int kind) {
    if (gskill == BB_SK_UNCHANNELLED_FURY) {
        return (kind == BB_ACT_BLOCK || kind == BB_ACT_BLITZ) ? 2 : 0;
    }
    if (gskill != BB_SK_REALLY_STUPID) return 0;
    const bb_player* p = &m->players[slot];
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            if (!dx && !dy) continue;
            int nx = p->x + dx, ny = p->y + dy;
            if (!bb_on_pitch_xy(nx, ny)) continue;
            int s = bb_slot_at(m, nx, ny);
            if (s < 0 || BB_TEAM_OF(s) != BB_TEAM_OF(slot)) continue;
            const bb_player* q = &m->players[s];
            if (q->stance != BB_STANCE_STANDING) continue;
            if (q->flags & BB_PF_DISTRACTED) continue;
            if (bb_has_skill(&q->skills, BB_SK_REALLY_STUPID)) continue;
            return 2;
        }
    }
    return 0;
}

// Does the gate roll for this declaration? (Take Root only when Standing
// and not already Rooted, mirror SK#TAKE ROOT.)
static int gate_skill_for(const bb_match* m, int slot, int* target, int* gk) {
    int gskill = bb_hook_activation_gate(m, slot, target, gk);
    if (gskill < 0) return -1;
    if (*gk == BB_GATE_ROOTED &&
        ((m->players[slot].flags & BB_PF_ROOTED) ||
         m->players[slot].stance != BB_STANCE_STANDING)) {
        return -1;
    }
    return gskill;
}

// Apply a failed negatrait gate. ROOTED failures continue the action in
// place; the others end the activation (Distracted for LOSE_ACT_AND_TZ:
// "If a player becomes Distracted during their activation, then their
// activation immediately ends").
static bool gate_fail(bb_match* m, bb_frame* f, int gk) {
    bb_player* p = &m->players[f->a];
    if (gk == BB_GATE_ROOTED) {
        // TAKE ROOT: rooted until the drive ends or they go down; may still
        // act from their square.
        p->flags |= BB_PF_ROOTED;
        return false; // the declared action continues
    }
    if (gk == BB_GATE_LOSE_ACT_AND_TZ) p->flags |= BB_PF_DISTRACTED;
    p->flags &= (uint16_t)~BB_PF_ACTIVATING;
    p->flags |= BB_PF_USED; // activation lost
    f->phase = 1;           // ACTIVATION advance pops on next entry
    return true;
}

// Mirror of proc_test.c's team_reroll_available: gate rolls are plain D6
// rolls during your own team turn — re-rollable with a team re-roll (the
// mirror's exclusion list covers only Scatter/Armour/Injury/Casualty/
// Throw-in/Bribe/Argue the Call/Crowd).
static bool gate_team_reroll_available(const bb_match* m, int team) {
    return m->rerolls[team] > 0 && m->active_team == team && !bb_in_kickoff(m);
}

static int activation_legal(const bb_match* m, bb_action* out) {
    const bb_frame* f = &m->stack[m->stack_top - 1];
    int slot = f->a;
    const bb_player* p = &m->players[slot];
    int n = 0;
    if (f->phase == 2) { // gate failed: team re-roll window
        out[n++] = (bb_action){BB_A_USE_REROLL, BB_RR_TEAM, 0, 0};
        out[n++] = (bb_action){BB_A_DECLINE_REROLL, 0, 0, 0};
        return n;
    }
    out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_MOVE, 0, 0};
    if ((p->stance == BB_STANCE_STANDING ||
         (p->stance == BB_STANCE_PRONE && bb_has_skill(&p->skills, BB_SK_JUMP_UP))) &&
        has_adjacent_standing_opponent(m, slot)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_BLOCK, 0, 0};
    }
    if (!m->blitz_used) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_BLITZ, 0, 0};
    }
    // A player need not hold the ball to declare a Pass/Hand-off action —
    // they may pick it up during the move part (pick-up-then-throw).
    // MY BALL: may not declare actions that would give up possession.
    bool my_ball = bb_has_skill(&p->skills, BB_SK_MY_BALL) && (p->flags & BB_PF_HAS_BALL);
    if (!m->pass_used && !my_ball) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_PASS, 0, 0};
    }
    if (!m->handoff_used && !my_ball) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_HANDOFF, 0, 0};
    }
    if (!m->foul_used && has_adjacent_downed_opponent(m, slot)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_FOUL, 0, 0};
    }
    // Secure the Ball (BB2025): ball loose on the ground and not within two
    // squares of any standing, non-distracted opposition player.
    if (!m->secure_used && m->ball.state == BB_BALL_ON_GROUND) {
        bool safe = true;
        int opp = 1 - BB_TEAM_OF(slot);
        for (int s2 = opp * BB_TEAM_SLOTS; s2 < (opp + 1) * BB_TEAM_SLOTS && safe; s2++) {
            const bb_player* q = &m->players[s2];
            if (q->location != BB_LOC_ON_PITCH) continue;
            if (q->stance != BB_STANCE_STANDING) continue;
            if (q->flags & BB_PF_DISTRACTED) continue;
            int dx = q->x - m->ball.x, dy = q->y - m->ball.y;
            if (dx < 0) dx = -dx;
            if (dy < 0) dy = -dy;
            int cheb = dx > dy ? dx : dy;
            if (cheb <= 2) safe = false;
        }
        // UNSTEADY: "may not declare Secure the Ball Actions."
        if (safe && !bb_has_skill(&p->skills, BB_SK_UNSTEADY)) {
            out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_SECURE_BALL, 0, 0};
        }
    }
    // STAB: "When this player is activated, they can declare a Stab Special
    // Action; there is no limit to the number of players that can declare
    // this Special Action each Turn."
    if (p->stance == BB_STANCE_STANDING &&
        bb_has_skill(&p->skills, BB_SK_STAB) &&
        has_adjacent_standing_opponent(m, slot)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_STAB, 0, 0};
    }
    // HYPNOTIC GAZE: declared like a Move Action; gaze ends the activation.
    if (bb_has_skill(&p->skills, BB_SK_HYPNOTIC_GAZE)) {
        out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_GAZE, 0, 0};
    }
    // THROW TEAM-MATE: one per turn; needs the trait + an adjacent Right
    // Stuff team-mate (even Prone). KICK TEAM-MATE: separate budget.
    {
        bool mate_adjacent = false;
        for (int dx = -1; dx <= 1 && !mate_adjacent; dx++) {
            for (int dy = -1; dy <= 1; dy++) {
                if (!dx && !dy) continue;
                int nx = p->x + dx, ny = p->y + dy;
                if (!bb_on_pitch_xy(nx, ny)) continue;
                int s2 = bb_slot_at(m, nx, ny);
                if (s2 >= 0 && BB_TEAM_OF(s2) == BB_TEAM_OF(slot) &&
                    bb_has_skill(&m->players[s2].skills, BB_SK_RIGHT_STUFF)) {
                    mate_adjacent = true;
                    break;
                }
            }
        }
        if (mate_adjacent && p->stance == BB_STANCE_STANDING) {
            if (!m->ttm_used && bb_has_skill(&p->skills, BB_SK_THROW_TEAM_MATE)) {
                out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_TTM, 0, 0};
            }
            if (!m->ktm_used && bb_has_skill(&p->skills, BB_SK_KICK_TEAM_MATE)) {
                out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_KTM, 0, 0};
            }
        }
    }
    // CHAINSAW / BREATHE FIRE: target a marked standing opponent.
    if (p->stance == BB_STANCE_STANDING && has_adjacent_standing_opponent(m, slot)) {
        if (bb_has_skill(&p->skills, BB_SK_CHAINSAW)) {
            out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_CHAINSAW, 0, 0};
        }
        if (bb_has_skill(&p->skills, BB_SK_BREATHE_FIRE)) {
            out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_BREATHE_FIRE, 0, 0};
        }
        if (bb_has_skill(&p->skills, BB_SK_PROJECTILE_VOMIT)) {
            out[n++] = (bb_action){BB_A_DECLARE, BB_ACT_VOMIT, 0, 0};
        }
    }
    return n;
}

static void activation_begin_action(bb_match* m, bb_frame* f, bb_rng* rng);

static void activation_apply(bb_match* m, bb_action a, bb_rng* rng) {
    bb_frame* f = bb_top(m);
    int slot = f->a;
    if (f->phase == 2) { // negatrait gate re-roll window
        int target = 0, gk = 0;
        int gskill = gate_skill_for(m, slot, &target, &gk);
        if (gskill < 0) { // engine-bug canary: window without a gate
            m->status = BB_STATUS_ERROR;
            return;
        }
        if (a.type == BB_A_USE_REROLL) {
            int team = BB_TEAM_OF(slot);
            m->rerolls[team]--;
            // Drive-scoped bonuses (Brilliant Coaching) spend first.
            if (m->bonus_rerolls[team]) m->bonus_rerolls[team]--;
            int loner = bb_loner_value(m, slot);
            if (loner > 0 && bb_roll(rng, 6) < loner) {
                // LONER: the re-roll is wasted; the failure stands.
                if (gate_fail(m, f, gk)) return;
                activation_begin_action(m, f, rng); // rooted: action continues
                return;
            }
            int mod = gate_modifier(m, slot, gskill, f->b);
            if (bb_d6(rng) + mod >= target) {
                activation_begin_action(m, f, rng); // passed on the re-roll
                return;
            }
        }
        // Declined, or the re-roll failed too.
        if (gate_fail(m, f, gk)) return;
        activation_begin_action(m, f, rng); // rooted: action continues
        return;
    }
    f->phase = 1;
    f->b = a.arg; // action kind
    // Once-per-turn actions latch on DECLARATION, even if never performed —
    // a failed negatrait gate still burns the declared Blitz/Pass/... .
    switch (a.arg) {
        case BB_ACT_BLITZ: m->blitz_used = 1; break;
        case BB_ACT_PASS: m->pass_used = 1; break;
        case BB_ACT_HANDOFF: m->handoff_used = 1; break;
        case BB_ACT_FOUL: m->foul_used = 1; break;
        case BB_ACT_SECURE_BALL: m->secure_used = 1; break;
        case BB_ACT_TTM: m->ttm_used = 1; break;
        case BB_ACT_KTM: m->ktm_used = 1; break;
        default: break;
    }
    // Negatrait activation gate — rolled AFTER declaring the Action (mirror
    // SK texts), so Unchannelled Fury's +2 can see a Block/Blitz
    // declaration. On a failure the coach may spend a team re-roll (gate
    // rolls are not in the mirror's no-re-roll list).
    int target = 0, gk = 0;
    int gskill = gate_skill_for(m, slot, &target, &gk);
    if (gskill >= 0) {
        int mod = gate_modifier(m, slot, gskill, f->b);
        if (bb_d6(rng) + mod < target) {
            if (gate_team_reroll_available(m, BB_TEAM_OF(slot))) {
                f->phase = 2; // offer the re-roll window
                return;
            }
            if (gate_fail(m, f, gk)) return;
            // rooted: the declared action continues in place
        }
    }
    activation_begin_action(m, f, rng);
}

static void activation_begin_action(bb_match* m, bb_frame* f, bb_rng* rng) {
    f->phase = 1;
    bb_player* pl = &m->players[f->a];
    int savage_mate = -1; // Animal Savagery lash-out target (resolved last-pushed)
    // BLOODLUST (X+): after declaring, roll D6 (+1 for Block/Blitz); failure
    // downgrades to a Move Action (the once-per-turn declaration still
    // counts). The end-of-activation Thrall bite is TODO (needs Thrall
    // keyword data) — flagged in DECISIONS.md.
    if (pl->p_bloodlust > 0 && bb_has_skill(&pl->skills, BB_SK_BLOODLUST)) {
        int die = bb_d6(rng);
        int bonus = (f->b == BB_ACT_BLOCK || f->b == BB_ACT_BLITZ) ? 1 : 0;
        if (die == 1 || die + bonus < pl->p_bloodlust) {
            f->b = BB_ACT_MOVE; // downgraded
            bb_cover(BB_SK_BLOODLUST);
        }
    }
    // ANIMAL SAVAGERY: D6 (+2 Block/Blitz): 1-3 -> lash out at an adjacent
    // standing team-mate (first found; choice TODO), else Distracted.
    if (bb_has_skill(&pl->skills, BB_SK_ANIMAL_SAVAGERY)) {
        int die = bb_d6(rng);
        int bonus = (f->b == BB_ACT_BLOCK || f->b == BB_ACT_BLITZ) ? 2 : 0;
        if (die + bonus <= 3) {
            bb_cover(BB_SK_ANIMAL_SAVAGERY);
            int mate = -1;
            for (int dx = -1; dx <= 1 && mate < 0; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    if (!dx && !dy) continue;
                    int nx = pl->x + dx, ny = pl->y + dy;
                    if (!bb_on_pitch_xy(nx, ny)) continue;
                    int s2 = bb_slot_at(m, nx, ny);
                    if (s2 >= 0 && BB_TEAM_OF(s2) == BB_TEAM_OF(f->a) &&
                        m->players[s2].stance == BB_STANCE_STANDING) {
                        mate = s2;
                        break;
                    }
                }
            }
            if (mate >= 0) {
                // Knocked down; turnover only if the mate held the ball.
                // Pushed AFTER the MOVE frame below so it resolves FIRST
                // (LIFO) — the rules knock the mate down immediately, before
                // the action; deferring let a still-standing "downed" mate
                // assist/TZ/catch through the whole action (review H2).
                savage_mate = mate;
            } else {
                pl->flags |= BB_PF_DISTRACTED;
            }
        }
    }
    // ANIMOSITY: when declaring a Pass/Hand-off, D6: on 1 the player refuses
    // and the activation ends. (Keyword targeting is checked at throw time —
    // approximation: the gate fires on declaration; see DECISIONS.md.)
    if ((f->b == BB_ACT_PASS || f->b == BB_ACT_HANDOFF) &&
        bb_has_skill(&pl->skills, BB_SK_ANIMOSITY)) {
        if (bb_d6(rng) == 1) {
            bb_cover(BB_SK_ANIMOSITY);
            pl->flags &= (uint16_t)~BB_PF_ACTIVATING;
            pl->flags |= BB_PF_USED;
            f->phase = 1; // ACTIVATION advance pops on next entry
            if (savage_mate >= 0) {
                bb_knockdown2(m, savage_mate, BB_KD_TTM_LANDING, 0, f->a);
            }
            return;       // no MOVE pushed: activation over
        }
    }
    int actor = f->a;
    bb_push(m, BB_PROC_MOVE, actor, f->b, 0, 0);
    if (savage_mate >= 0) {
        bb_knockdown2(m, savage_mate, BB_KD_TTM_LANDING, 0, actor);
    }
}

// ===== TURNOVER ==============================================================
// The latch in m->turnover is read by action procs (MOVE, TEAM_TURN); this
// dedicated proc exists for explicit unwinding when needed.

static void turnover_advance(bb_match* m, bb_rng* rng) {
    (void)rng;
    bb_turnover(m);
    bb_pop(m);
}

const bb_proc_vtable bb_proc_team_turn_vtable = {team_turn_advance, team_turn_legal, team_turn_apply};
const bb_proc_vtable bb_proc_activation_vtable = {activation_advance, activation_legal, activation_apply};
const bb_proc_vtable bb_proc_turnover_vtable = {turnover_advance, 0, 0};

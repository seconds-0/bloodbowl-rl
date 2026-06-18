#include "bb/bb_reachability.h"
#include "bb/bb_blockev.h"
#include "bb/bb_hooks.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"
#include "bb/gen_teams.h"
#include <string.h>

static const int8_t DIR8[8][2] = {
    {-1, -1}, {0, -1}, {1, -1}, {-1, 0},
    {1, 0},   {-1, 1}, {0, 1},  {1, 1},
};

static bb_reach_cost reach_unreachable(void) {
    return (bb_reach_cost){BB_REACH_UNREACHABLE, BB_REACH_UNREACHABLE};
}

static int reach_cost_less(bb_reach_cost a, uint8_t alen,
                           bb_reach_cost b, uint8_t blen) {
    if (a.dodges != b.dodges) return a.dodges < b.dodges;
    if (a.gfis != b.gfis) return a.gfis < b.gfis;
    return alen < blen;
}

static int reach_len_less(bb_reach_cost a, uint8_t alen,
                          bb_reach_cost b, uint8_t blen) {
    if (alen != blen) return alen < blen;
    if (a.dodges != b.dodges) return a.dodges < b.dodges;
    return a.gfis < b.gfis;
}

static int reach_cost_reachable(bb_reach_cost c) {
    return c.dodges != BB_REACH_UNREACHABLE;
}

static void reach_field_compute_ordered(const bb_match* m, int mover,
                                        int prefer_len,
                                        bb_reach_field* out) {
    uint8_t done[BB_PITCH_LEN][BB_PITCH_WID];
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            out->cost[x][y] = reach_unreachable();
            out->len[x][y] = 0;
            out->prev_x[x][y] = -1;
            out->prev_y[x][y] = -1;
            done[x][y] = 0;
        }
    }
    if (mover < 0 || mover >= BB_NUM_PLAYERS) return;

    const bb_player* p = &m->players[mover];
    if (p->location != BB_LOC_ON_PITCH || p->stance != BB_STANCE_STANDING) return;

    int sx = p->x, sy = p->y;
    out->cost[sx][sy] = (bb_reach_cost){0, 0};
    out->len[sx][sy] = 0;

    int ma_left = p->ma - p->moved;
    if (ma_left < 0) ma_left = 0;
    int rush_left = bb_max_rushes(m, mover) - p->rushes;
    if (rush_left < 0) rush_left = 0;
    int budget = ma_left + rush_left;
    if (budget > 39) budget = 39;

    if (p->flags & BB_PF_ROOTED) return;

    int team = BB_TEAM_OF(mover);
    for (;;) {
        int ux = -1, uy = -1;
        bb_reach_cost best = reach_unreachable();
        uint8_t best_len = 0xFF;
        for (int x = 0; x < BB_PITCH_LEN; x++) {
            for (int y = 0; y < BB_PITCH_WID; y++) {
                bb_reach_cost c = out->cost[x][y];
                if (done[x][y] || !reach_cost_reachable(c)) continue;
                int better = prefer_len ?
                    reach_len_less(c, out->len[x][y], best, best_len) :
                    reach_cost_less(c, out->len[x][y], best, best_len);
                if (ux < 0 || better) {
                    ux = x;
                    uy = y;
                    best = c;
                    best_len = out->len[x][y];
                }
            }
        }
        if (ux < 0) break;
        done[ux][uy] = 1;

        int steps = out->len[ux][uy];
        if (steps >= budget) continue;
        int from_tz = bb_tackle_zones(m, team, ux, uy) > 0;
        for (int d = 0; d < 8; d++) {
            int nx = ux + DIR8[d][0];
            int ny = uy + DIR8[d][1];
            if (!bb_on_pitch_xy(nx, ny)) continue;
            if (m->grid[nx][ny]) continue;

            int is_rush = steps >= ma_left;
            bb_reach_cost nc = best;
            if (from_tz && nc.dodges < BB_REACH_UNREACHABLE) nc.dodges++;
            if (is_rush && nc.gfis < BB_REACH_UNREACHABLE) nc.gfis++;
            if (nc.dodges == BB_REACH_UNREACHABLE ||
                nc.gfis == BB_REACH_UNREACHABLE) {
                continue;
            }
            uint8_t nlen = (uint8_t)(steps + 1);
            int better = prefer_len ?
                reach_len_less(nc, nlen, out->cost[nx][ny], out->len[nx][ny]) :
                reach_cost_less(nc, nlen, out->cost[nx][ny], out->len[nx][ny]);
            if (!reach_cost_reachable(out->cost[nx][ny]) ||
                better) {
                out->cost[nx][ny] = nc;
                out->len[nx][ny] = nlen;
                out->prev_x[nx][ny] = (int8_t)ux;
                out->prev_y[nx][ny] = (int8_t)uy;
            }
        }
    }
}

void bb_reach_field_compute(const bb_match* m, int mover, bb_reach_field* out) {
    reach_field_compute_ordered(m, mover, 0, out);
}

bb_reach_access bb_min_access_cost(const bb_match* m, int team, int tx, int ty) {
    bb_reach_access access = {false, false};
    if (!bb_on_pitch_xy(tx, ty)) return access;

    for (int s = team * BB_TEAM_SLOTS; s < (team + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* p = &m->players[s];
        if (p->location != BB_LOC_ON_PITCH) continue;
        if (p->stance != BB_STANCE_STANDING) continue;
        if (p->flags & BB_PF_ROOTED) continue;

        bb_reach_field field;
        bb_reach_field_compute(m, s, &field);
        for (int d = 0; d < 8; d++) {
            int ax = tx + DIR8[d][0];
            int ay = ty + DIR8[d][1];
            if (!bb_on_pitch_xy(ax, ay)) continue;
            bb_reach_cost c = field.cost[ax][ay];
            if (!reach_cost_reachable(c)) continue;
            if (c.dodges == 0 && c.gfis == 0) access.any_free = true;
            if ((int)c.dodges + (int)c.gfis == 1) access.any_one_roll = true;
        }
        if (access.any_free && access.any_one_roll) return access;
    }
    return access;
}

bool bb_carrier_exposure_endzone_exempt(const bb_match* m, int carrier) {
    if (carrier < 0 || carrier >= BB_NUM_PLAYERS) return false;
    const bb_player* c = &m->players[carrier];
    if (c->location != BB_LOC_ON_PITCH) return false;
    if (c->stance != BB_STANCE_STANDING) return false;
    if (c->flags & BB_PF_ROOTED) return false;
    int ez = bb_endzone_x(BB_TEAM_OF(carrier));
    int dist = c->x > ez ? c->x - ez : ez - c->x;
    return dist <= c->ma + bb_max_rushes(m, carrier);
}

bb_carrier_exposure bb_carrier_exposure_eval(const bb_match* m, int team) {
    bb_carrier_exposure ex = {false, false};
    if (team != BB_HOME && team != BB_AWAY) return ex;
    if (m->ball.state != BB_BALL_HELD || m->ball.carrier == BB_NO_PLAYER) return ex;

    int carrier = m->ball.carrier;
    if (BB_TEAM_OF(carrier) != team) return ex;
    const bb_player* c = &m->players[carrier];
    if (c->location != BB_LOC_ON_PITCH || c->stance != BB_STANCE_STANDING) return ex;
    if (bb_carrier_exposure_endzone_exempt(m, carrier)) return ex;

    if (bb_is_marked(m, carrier)) {
        ex.full = true;
        return ex;
    }

    bb_reach_access access = bb_min_access_cost(m, 1 - team, c->x, c->y);
    if (access.any_free) {
        ex.full = true;
    } else if (access.any_one_roll) {
        ex.soft = true;
    }
    return ex;
}

int bb_def_threat_turns(const bb_match* m, int slot) {
    if (slot < 0 || slot >= BB_NUM_PLAYERS) return -1;
    const bb_player* p = &m->players[slot];
    if (p->location != BB_LOC_ON_PITCH) return -1;
    if (p->stance != BB_STANCE_STANDING) return -1;
    if (p->flags & BB_PF_ROOTED) return -1;

    // Per-turn straight-line reach: full MA plus the GFI/Sprint budget. Use the
    // raw stat (not remaining), per D133-A this is a positional threat readout,
    // not an in-activation move plan. bb_max_rushes is Sprint-aware.
    int reach = (int)p->ma + bb_max_rushes(m, slot);
    if (reach <= 0) return -1; // immobile (MA 0, no rushes): cannot get downfield

    // x-axis distance to the player's OWN scoring endzone column (= our
    // defensive endzone), mirroring the R6v1 endzone-exemption measure.
    int ez = bb_endzone_x(BB_TEAM_OF(slot));
    int dist = p->x > ez ? p->x - ez : ez - p->x;

    return (dist + reach - 1) / reach; // ceil(dist / reach); 0 if already there
}

bb_def_threat bb_def_threat_eval(const bb_match* m, int team) {
    bb_def_threat dt = {0, 0};
    if (team != BB_HOME && team != BB_AWAY) return dt;

    int opp = 1 - team;
    for (int s = opp * BB_TEAM_SLOTS; s < (opp + 1) * BB_TEAM_SLOTS; s++) {
        int turns = bb_def_threat_turns(m, s);
        if (turns < 0) continue;           // ineligible (off-pitch/down/rooted)
        if (bb_is_marked(m, s)) continue;  // mitigated: must dodge to leave
        if (turns <= 1) dt.n_threats_1turn++;
        if (turns <= 2) dt.n_threats_2turn++;
    }
    return dt;
}

static int carrier_threat_valid_carrier(const bb_match* m, int carrier) {
    if (carrier < 0 || carrier >= BB_NUM_PLAYERS) return 0;
    const bb_player* c = &m->players[carrier];
    return c->location == BB_LOC_ON_PITCH && c->stance == BB_STANCE_STANDING;
}

static void carrier_threat_init(bb_carrier_threat_breakdown* out) {
    if (!out) return;
    out->carrier = BB_NO_PLAYER;
    out->carrier_team = -1;
    out->baseline = bb_carrier_threat_baseline();
    out->adjacent_excess = 0.0f;
    out->blitz_excess = 0.0f;
    out->uncapped_total = 0.0f;
    out->capped_total = 0.0f;
    out->enemies_considered = 0;
    out->adjacent_enemies = 0;
    out->reachable_enemies = 0;
}

static int carrier_threat_skill_rr_available(const bb_match* m, int slot,
                                             int kind, int already_used,
                                             int to_x, int to_y,
                                             int is_blitz) {
    if (already_used) return 0;
    if (m->players[slot].skill_rr_used & (uint16_t)(1u << kind)) return 0;
    const bb_player* p = &m->players[slot];
    bb_ctx c = {(uint8_t)kind, (uint8_t)slot, BB_NO_PLAYER, (uint8_t)slot,
                (int8_t)p->x, (int8_t)p->y, (int8_t)to_x, (int8_t)to_y,
                -1, (uint8_t)is_blitz};
    return bb_hook_reroll(m, &c) >= 0;
}

static void carrier_threat_apply_test(const bb_match* m, int slot, int kind,
                                      float raw_p, int to_x, int to_y,
                                      int is_blitz, float state[2][2]) {
    float next[2][2] = {{0.0f, 0.0f}, {0.0f, 0.0f}};
    int is_dodge = kind == BB_TEST_DODGE;
    for (int d = 0; d < 2; d++) {
        for (int r = 0; r < 2; r++) {
            float mass = state[d][r];
            if (mass == 0.0f) continue;
            int used = is_dodge ? d : r;
            int can_rr = carrier_threat_skill_rr_available(
                m, slot, kind, used, to_x, to_y, is_blitz);
            next[d][r] += mass * raw_p; // initial success, reroll preserved
            if (can_rr) {
                int nd = d;
                int nr = r;
                if (is_dodge) nd = 1;
                else nr = 1;
                next[nd][nr] += mass * (1.0f - raw_p) * raw_p;
            }
        }
    }
    for (int d = 0; d < 2; d++) {
        for (int r = 0; r < 2; r++) state[d][r] = next[d][r];
    }
}

static float carrier_threat_path_probability(const bb_match* m, int slot,
                                             const bb_reach_field* field,
                                             int tx, int ty) {
    bb_reach_cost c = field->cost[tx][ty];
    if (!reach_cost_reachable(c)) return 0.0f;

    int len = field->len[tx][ty];
    if (len <= 0) return 1.0f;
    if (len > 39) return 0.0f;

    int px[40], py[40];
    int x = tx, y = ty;
    for (int i = len - 1; i >= 0; i--) {
        px[i] = x;
        py[i] = y;
        int nx = field->prev_x[x][y];
        int ny = field->prev_y[x][y];
        if (nx < 0 || ny < 0) return 0.0f;
        x = nx;
        y = ny;
    }

    bb_match sim = *m;
    float state[2][2] = {{1.0f, 0.0f}, {0.0f, 0.0f}};
    for (int i = 0; i < len; i++) {
        int rush_test, dodge_test, pickup_test;
        float rush_p, dodge_p, pickup_p;
        bb_step_success_components(&sim, slot, px[i], py[i], 1,
                                   &rush_test, &rush_p, &dodge_test, &dodge_p,
                                   &pickup_test, &pickup_p);
        if (rush_test) {
            carrier_threat_apply_test(&sim, slot, BB_TEST_RUSH, rush_p,
                                      px[i], py[i], 1, state);
        }
        if (dodge_test) {
            carrier_threat_apply_test(&sim, slot, BB_TEST_DODGE, dodge_p,
                                      px[i], py[i], 1, state);
        }
        // Carrier-threat paths never intentionally pick up the ball (it is
        // held by the defender), but preserve the component helper contract.
        if (pickup_test) {
            state[0][0] *= pickup_p;
            state[0][1] *= pickup_p;
            state[1][0] *= pickup_p;
            state[1][1] *= pickup_p;
        }

        bb_player* p = &sim.players[slot];
        if (p->moved >= p->ma) p->rushes++;
        p->moved++;
        bb_place(&sim, slot, px[i], py[i]);
    }

    return state[0][0] + state[0][1] + state[1][0] + state[1][1];
}

static float carrier_threat_best_path_probability(const bb_match* m, int slot,
                                                  const bb_reach_field* cost_field,
                                                  const bb_reach_field* len_field,
                                                  int tx, int ty) {
    float best = carrier_threat_path_probability(m, slot, cost_field, tx, ty);
    // The public reach field stores the cheapest (dodges,gfis,len) predecessor
    // chain. For carrier threat, that can under-price a high-success shorter
    // route with more formal "cost", so replay a private length-first field
    // as well and keep the higher pure success probability.
    float by_len = carrier_threat_path_probability(m, slot, len_field, tx, ty);
    return by_len > best ? by_len : best;
}

static float carrier_threat_block_p_def_down_at(const bb_match* m, int enemy,
                                                int carrier, int x, int y,
                                                int is_blitz) {
    bb_match sim = *m;
    if (sim.players[enemy].x != x || sim.players[enemy].y != y) {
        bb_place(&sim, enemy, x, y);
    }
    bb_blockev ev;
    bb_block_ev(&sim, enemy, carrier, is_blitz, NULL, &ev);
    return ev.p_def_down;
}

float bb_carrier_threat_baseline(void) {
    bb_match m;
    memset(&m, 0, sizeof(m));
    m.team_id[BB_HOME] = BB_TEAM_HUMAN;
    m.team_id[BB_AWAY] = BB_TEAM_HUMAN;
    for (int s = 0; s < BB_NUM_PLAYERS; s++) {
        m.players[s].location = BB_LOC_ABSENT;
    }
    m.weather = BB_WEATHER_PERFECT;
    m.active_team = BB_HOME;
    m.status = BB_STATUS_RUNNING;

    int diver = BB_HOME * BB_TEAM_SLOTS;
    int carrier = BB_AWAY * BB_TEAM_SLOTS;
    bb_player* dp = &m.players[diver];
    bb_player* cp = &m.players[carrier];
    *dp = (bb_player){0};
    *cp = (bb_player){0};
    dp->location = BB_LOC_ABSENT;
    cp->location = BB_LOC_ABSENT;
    dp->ma = 6;
    dp->st = 3;
    dp->ag = 3;
    dp->pa = 4;
    dp->av = 9;
    dp->stance = BB_STANCE_STANDING;
    cp->ma = 6;
    cp->st = 4; // ST3 into ST4 is the engine's 2d-red reference.
    cp->ag = 3;
    cp->pa = 4;
    cp->av = 9;
    cp->stance = BB_STANCE_STANDING;
    bb_add_skill(&dp->skills, BB_SK_DODGE);
    bb_place(&m, diver, 10, 7);
    bb_place(&m, carrier, 12, 7);

    // The "three tackle zones" reference is the block target's TZ plus two
    // cage-corner markers on the destination square. The origin is also
    // marked so the engine requires a dodge test.
    int marker1 = BB_AWAY * BB_TEAM_SLOTS + 1;
    int marker2 = BB_AWAY * BB_TEAM_SLOTS + 2;
    int marker3 = BB_AWAY * BB_TEAM_SLOTS + 3;
    bb_player* m1 = &m.players[marker1];
    bb_player* m2 = &m.players[marker2];
    bb_player* m3 = &m.players[marker3];
    *m1 = (bb_player){0};
    *m2 = (bb_player){0};
    *m3 = (bb_player){0};
    m1->location = m2->location = m3->location = BB_LOC_ABSENT;
    m1->ma = m2->ma = m3->ma = 6;
    m1->st = m2->st = m3->st = 3;
    m1->ag = m2->ag = m3->ag = 3;
    m1->pa = m2->pa = m3->pa = 4;
    m1->av = m2->av = m3->av = 9;
    m1->stance = m2->stance = m3->stance = BB_STANCE_STANDING;
    bb_place(&m, marker1, 10, 6); // marks origin
    bb_place(&m, marker2, 11, 6); // marks destination
    bb_place(&m, marker3, 11, 8); // marks destination

    float dodge_p = 1.0f;
    int rush_test, dodge_test, pickup_test;
    float rush_p, pickup_p;
    bb_step_success_components(&m, diver, 11, 7, 1,
                               &rush_test, &rush_p, &dodge_test, &dodge_p,
                               &pickup_test, &pickup_p);
    if (dodge_test && carrier_threat_skill_rr_available(&m, diver,
            BB_TEST_DODGE, 0, 11, 7, 1)) {
        dodge_p = dodge_p + (1.0f - dodge_p) * dodge_p;
    }

    bb_blockev ev;
    bb_place(&m, diver, 11, 7);
    bb_block_ev(&m, diver, carrier, 1, NULL, &ev);
    return dodge_p * ev.p_def_down;
}

float bb_carrier_threat_eval(const bb_match* m,
                             bb_carrier_threat_breakdown* out) {
    carrier_threat_init(out);
    if (!m) return 0.0f;
    if (m->ball.state != BB_BALL_HELD || m->ball.carrier == BB_NO_PLAYER) {
        return 0.0f;
    }
    int carrier = m->ball.carrier;
    if (!carrier_threat_valid_carrier(m, carrier)) return 0.0f;

    int team = BB_TEAM_OF(carrier);
    const bb_player* c = &m->players[carrier];
    float baseline = out ? out->baseline : bb_carrier_threat_baseline();
    float adjacent_sum = 0.0f;
    float best_blitz = 0.0f;

    if (out) {
        out->carrier = carrier;
        out->carrier_team = team;
    }

    int opp = 1 - team;
    for (int s = opp * BB_TEAM_SLOTS; s < (opp + 1) * BB_TEAM_SLOTS; s++) {
        const bb_player* e = &m->players[s];
        if (e->location != BB_LOC_ON_PITCH || e->stance != BB_STANCE_STANDING) {
            continue;
        }
        if (out) out->enemies_considered++;

        if (bb_adjacent(e->x, e->y, c->x, c->y)) {
            float pkd = carrier_threat_block_p_def_down_at(
                m, s, carrier, e->x, e->y, 0);
            float excess = pkd - baseline;
            if (excess < 0.0f) excess = 0.0f;
            adjacent_sum += excess;
            if (out) out->adjacent_enemies++;
            continue;
        }

        bb_reach_field field;
        bb_reach_field_compute(m, s, &field);
        bb_reach_field len_field;
        reach_field_compute_ordered(m, s, 1, &len_field);
        float best_enemy = 0.0f;
        int reached = 0;
        bb_reach_cost best_cost = reach_unreachable();
        for (int d = 0; d < 8; d++) {
            int ax = c->x + DIR8[d][0];
            int ay = c->y + DIR8[d][1];
            if (!bb_on_pitch_xy(ax, ay)) continue;
            bb_reach_cost rc = field.cost[ax][ay];
            if (!reach_cost_reachable(rc)) continue;
            if (!reached ||
                rc.dodges < best_cost.dodges ||
                (rc.dodges == best_cost.dodges && rc.gfis < best_cost.gfis)) {
                best_cost = rc;
                reached = 1;
            }
        }
        if (!reached) continue;

        for (int d = 0; d < 8; d++) {
            int ax = c->x + DIR8[d][0];
            int ay = c->y + DIR8[d][1];
            if (!bb_on_pitch_xy(ax, ay)) continue;
            bb_reach_cost rc = field.cost[ax][ay];
            if (!reach_cost_reachable(rc)) continue;
            if (rc.dodges != best_cost.dodges || rc.gfis != best_cost.gfis) {
                continue;
            }

            float preach = carrier_threat_best_path_probability(
                m, s, &field, &len_field, ax, ay);
            if (preach <= 0.0f) continue;
            float pkd = carrier_threat_block_p_def_down_at(m, s, carrier, ax, ay, 1);
            float threat = preach * pkd;
            float excess = threat - baseline;
            if (excess < 0.0f) excess = 0.0f;
            if (excess > best_enemy) best_enemy = excess;
        }
        if (out) out->reachable_enemies++;
        if (best_enemy > best_blitz) best_blitz = best_enemy;
    }

    float total = adjacent_sum + best_blitz;
    float capped = total < BB_CARRIER_THREAT_T_MAX ? total : BB_CARRIER_THREAT_T_MAX;
    if (out) {
        out->adjacent_excess = adjacent_sum;
        out->blitz_excess = best_blitz;
        out->uncapped_total = total;
        out->capped_total = capped;
    }
    return capped;
}

#include "bb/bb_reachability.h"
#include "bb/bb_proc.h"
#include "bb/bb_skills.h"

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

static int reach_cost_reachable(bb_reach_cost c) {
    return c.dodges != BB_REACH_UNREACHABLE;
}

void bb_reach_field_compute(const bb_match* m, int mover, bb_reach_field* out) {
    uint8_t reach_len[BB_PITCH_LEN][BB_PITCH_WID];
    uint8_t done[BB_PITCH_LEN][BB_PITCH_WID];
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            out->cost[x][y] = reach_unreachable();
            reach_len[x][y] = 0;
            done[x][y] = 0;
        }
    }
    if (mover < 0 || mover >= BB_NUM_PLAYERS) return;

    const bb_player* p = &m->players[mover];
    if (p->location != BB_LOC_ON_PITCH || p->stance != BB_STANCE_STANDING) return;

    int sx = p->x, sy = p->y;
    out->cost[sx][sy] = (bb_reach_cost){0, 0};

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
                if (ux < 0 || reach_cost_less(c, reach_len[x][y], best, best_len)) {
                    ux = x;
                    uy = y;
                    best = c;
                    best_len = reach_len[x][y];
                }
            }
        }
        if (ux < 0) break;
        done[ux][uy] = 1;

        int steps = reach_len[ux][uy];
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
            if (!reach_cost_reachable(out->cost[nx][ny]) ||
                reach_cost_less(nc, nlen, out->cost[nx][ny], reach_len[nx][ny])) {
                out->cost[nx][ny] = nc;
                reach_len[nx][ny] = nlen;
            }
        }
    }
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

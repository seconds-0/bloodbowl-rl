// bb_reachability.h - pure movement reachability queries over the board.
#ifndef BB_REACHABILITY_H
#define BB_REACHABILITY_H

#include "bb/bb_match.h"

#define BB_REACH_UNREACHABLE 0xFF

// Lexicographic movement cost to stand on a square: dodges first, then GFIs.
// BB_REACH_UNREACHABLE in .dodges means the square cannot be reached.
typedef struct {
    uint8_t dodges;
    uint8_t gfis;
} bb_reach_cost;

typedef struct {
    bb_reach_cost cost[BB_PITCH_LEN][BB_PITCH_WID];
} bb_reach_field;

// R6v1 aggregate around a target square. any_free means at least one standing,
// non-rooted player of `team` can reach an adjacent square with no dodge/GFI.
// any_one_roll means at least one such path costs exactly one dodge or GFI.
typedef struct {
    bool any_free;
    bool any_one_roll;
} bb_reach_access;

// Pure 8-connected Dijkstra for one mover. Occupied squares are hard obstacles
// except for the mover's source. A dodge is counted when leaving a marked
// square; a GFI is counted once the path exceeds remaining normal movement.
void bb_reach_field_compute(const bb_match* m, int mover, bb_reach_field* out);

// Aggregate free / one-roll adjacent access to (tx, ty) for players of `team`.
bb_reach_access bb_min_access_cost(const bb_match* m, int team, int tx, int ty);

// R6v1 scoring-dash exemption: a standing non-rooted carrier can reach its
// scoring endzone column with MA + max rushes (Sprint-aware) in a pure run.
bool bb_carrier_exposure_endzone_exempt(const bb_match* m, int carrier);

typedef struct {
    bool full;
    bool soft;
} bb_carrier_exposure;

// Pure R6v1 classification for the team whose own turn just ended. This does
// not apply reward magnitudes; it only reports which tier, if any, should fire.
bb_carrier_exposure bb_carrier_exposure_eval(const bb_match* m, int team);

// R12 v1 (D133-A): per-PLAYER downfield scoring threat, NOT a reachability
// Dijkstra. `turns_to_score(p) = ceil(dist_to_our_endzone / (MA + max_rushes))`
// for each STANDING, on-pitch, non-rooted opposing player; an UNMITIGATED
// threat at horizon N is one with turns_to_score <= N that is NOT marked
// (a marked deep mover must dodge to leave, so it is treated as covered).
typedef struct {
    uint8_t n_threats_1turn;  // unmarked opponents that can score in <= 1 turn
    uint8_t n_threats_2turn;  // unmarked opponents that can score in <= 2 turns
} bb_def_threat;

// Single-player horizon: minimum number of own activations (each worth
// MA + max rushes squares of straight-line movement) for `slot` to reach its
// scoring endzone column, ignoring tackle zones (ball-agnostic, per D133-A).
// Returns -1 for an INELIGIBLE player (off-pitch / non-standing / rooted / zero
// reach); 0 means already standing on the endzone column (turns_to_score 0).
int bb_def_threat_turns(const bb_match* m, int slot);

// Count UNMITIGATED 1-turn and 2-turn downfield scoring threats that `team`
// (the defending team, i.e. the team whose own turn just ended) faces from the
// OTHER team. Pure geometry, O(players), no ball model, no Dijkstra.
bb_def_threat bb_def_threat_eval(const bb_match* m, int team);

#endif // BB_REACHABILITY_H

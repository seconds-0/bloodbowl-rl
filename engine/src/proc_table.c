// proc_table.c — procedure dispatch table (filled at load time).
#include "bb/bb_proc.h"

extern const bb_proc_vtable bb_proc_match_vtable;
extern const bb_proc_vtable bb_proc_pregame_vtable;
extern const bb_proc_vtable bb_proc_setup_vtable;
extern const bb_proc_vtable bb_proc_kickoff_vtable;
extern const bb_proc_vtable bb_proc_team_turn_vtable;
extern const bb_proc_vtable bb_proc_activation_vtable;
extern const bb_proc_vtable bb_proc_move_vtable;
extern const bb_proc_vtable bb_proc_test_vtable;
extern const bb_proc_vtable bb_proc_block_vtable;
extern const bb_proc_vtable bb_proc_push_vtable;
extern const bb_proc_vtable bb_proc_knockdown_vtable;
extern const bb_proc_vtable bb_proc_armour_vtable;
extern const bb_proc_vtable bb_proc_injury_vtable;
extern const bb_proc_vtable bb_proc_casualty_vtable;
extern const bb_proc_vtable bb_proc_pass_vtable;
extern const bb_proc_vtable bb_proc_catch_vtable;
extern const bb_proc_vtable bb_proc_scatter_vtable;
extern const bb_proc_vtable bb_proc_throw_in_vtable;
extern const bb_proc_vtable bb_proc_handoff_vtable;
extern const bb_proc_vtable bb_proc_foul_vtable;
extern const bb_proc_vtable bb_proc_touchdown_vtable;
extern const bb_proc_vtable bb_proc_turnover_vtable;
extern const bb_proc_vtable bb_proc_end_drive_vtable;
extern const bb_proc_vtable bb_proc_ko_recovery_vtable;

bb_proc_vtable bb_proc_table[BB_PROC_COUNT];

__attribute__((constructor)) static void bb_proc_table_init(void) {
    bb_proc_table[BB_PROC_MATCH] = bb_proc_match_vtable;
    bb_proc_table[BB_PROC_PREGAME] = bb_proc_pregame_vtable;
    bb_proc_table[BB_PROC_SETUP] = bb_proc_setup_vtable;
    bb_proc_table[BB_PROC_KICKOFF] = bb_proc_kickoff_vtable;
    bb_proc_table[BB_PROC_TEAM_TURN] = bb_proc_team_turn_vtable;
    bb_proc_table[BB_PROC_ACTIVATION] = bb_proc_activation_vtable;
    bb_proc_table[BB_PROC_MOVE] = bb_proc_move_vtable;
    bb_proc_table[BB_PROC_TEST] = bb_proc_test_vtable;
    bb_proc_table[BB_PROC_BLOCK] = bb_proc_block_vtable;
    bb_proc_table[BB_PROC_PUSH] = bb_proc_push_vtable;
    bb_proc_table[BB_PROC_KNOCKDOWN] = bb_proc_knockdown_vtable;
    bb_proc_table[BB_PROC_ARMOUR] = bb_proc_armour_vtable;
    bb_proc_table[BB_PROC_INJURY] = bb_proc_injury_vtable;
    bb_proc_table[BB_PROC_CASUALTY] = bb_proc_casualty_vtable;
    bb_proc_table[BB_PROC_PASS] = bb_proc_pass_vtable;
    bb_proc_table[BB_PROC_CATCH] = bb_proc_catch_vtable;
    bb_proc_table[BB_PROC_SCATTER] = bb_proc_scatter_vtable;
    bb_proc_table[BB_PROC_THROW_IN] = bb_proc_throw_in_vtable;
    bb_proc_table[BB_PROC_HANDOFF] = bb_proc_handoff_vtable;
    bb_proc_table[BB_PROC_FOUL] = bb_proc_foul_vtable;
    bb_proc_table[BB_PROC_TOUCHDOWN] = bb_proc_touchdown_vtable;
    bb_proc_table[BB_PROC_TURNOVER] = bb_proc_turnover_vtable;
    bb_proc_table[BB_PROC_END_DRIVE] = bb_proc_end_drive_vtable;
    bb_proc_table[BB_PROC_KO_RECOVERY] = bb_proc_ko_recovery_vtable;
}

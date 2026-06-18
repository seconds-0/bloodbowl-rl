// Headless one-frame BBTV screenshot harness. Procgens a match, steps it to a
// mid-game board, populates HUD + event feed, renders the real bbe_render path,
// and exports a PNG for visual review. Build: see the clang line in the dispatch.
#include "bloodbowl.h"

int main(int argc, char** argv) {
    const char* out = argc > 1 ? argv[1] : "bbtv.png";
    Bloodbowl* env = (Bloodbowl*)calloc(1, sizeof(Bloodbowl));
    env->seed = 7; env->episode = 1;
    bb_rng_seed(&env->procgen, 424242u, 11);
    bb_match_init_random(&env->match, &env->procgen);

    // Step the match into a mid-game shape: advance + apply random legal actions
    // so players spread off the line and a few events occur.
    bb_rng play; bb_rng_seed(&play, 99u, 7);
    bb_advance(&env->match, &play);
    for (int i = 0; i < 120; i++) {
        if (env->match.status != BB_STATUS_DECISION) { bb_advance(&env->match, &play); continue; }
        bb_action legal[BB_LEGAL_MAX];
        int n = bb_legal_actions(&env->match, legal);
        if (n <= 0) break;
        bb_apply(&env->match, legal[bb_rng_next(&play) % (uint32_t)n], &play);
    }

    // HUD realism: a plausible scoreline (profile label via BBE_PROFILE env).
    env->match.score[0] = 2; env->match.score[1] = 1;

    // Seed representative per-team stats (raw bb_apply doesn't run the counter
    // hooks; this lets us review the panel layout with real-looking numbers).
    env->ep_blocks_thrown_team[0]=12; env->ep_blocks_thrown_team[1]=7;
    env->ep_block_tier_team[0][2]=5; env->ep_block_tier_team[0][1]=4; // 3d,2d (good)
    env->ep_block_tier_team[0][0]=2; env->ep_block_tier_team[0][3]=1; // 1d, 2d-red
    env->ep_block_tier_team[1][2]=2; env->ep_block_tier_team[1][1]=2;
    env->ep_block_tier_team[1][0]=2; env->ep_block_tier_team[1][3]=1;
    env->ep_dodge_att[0]=10; env->ep_dodge_ok[0]=8; env->ep_dodge_att[1]=9; env->ep_dodge_ok[1]=6;
    env->ep_gfi_att[0]=6;  env->ep_gfi_ok[0]=5;  env->ep_gfi_att[1]=4; env->ep_gfi_ok[1]=3;
    env->ep_pickup_att[0]=3; env->ep_pickup_ok[0]=2; env->ep_pickup_att[1]=2; env->ep_pickup_ok[1]=1;
    env->ep_turnovers[0]=1; env->ep_turnovers[1]=2;
    env->ep_pass_att[0]=1; env->ep_pass_att[1]=0;
    env->ep_handoff_att[0]=1; env->ep_handoff_att[1]=0;
    env->ep_foul_att[0]=2; env->ep_foul_att[1]=0;
    env->ep_tds_team[0]=2; env->ep_tds_team[1]=1;

    SetTraceLogLevel(LOG_WARNING);
    bbe_render_draw(env); // frame 0: init window + register feed hook
    // Seed the event feed so the sidebar shows representative content.
    BBE_FEED(env, BBE_EV_BLOCK_THROWN, 3, 18);
    BBE_FEED(env, BBE_EV_KNOCKDOWN, 18, -1);
    BBE_FEED(env, BBE_EV_DODGE, 5, -1);
    BBE_FEED(env, BBE_EV_GFI, 5, -1);
    BBE_FEED(env, BBE_EV_PICKUP_OK, 7, -1);
    BBE_FEED(env, BBE_EV_BLITZ_DECL, 2, 20);
    BBE_FEED(env, BBE_EV_TD, 7, -1);
    BBE_FEED(env, BBE_EV_TURNOVER, -1, -1);

    for (int f = 0; f < 30; f++) bbe_render_draw(env);
    TakeScreenshot(out);
    CloseWindow();
    free(env);
    return 0;
}

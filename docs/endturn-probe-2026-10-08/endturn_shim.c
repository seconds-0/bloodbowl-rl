// END_TURN probe: the play harness's engine shim, unchanged, plus read-only
// accessors for the env's per-step reward components.
//
// The harness's shim (play_harness/native/bbplay.c at the pinned commit) is
// included as it is, so every function the harness calls is compiled from the
// pinned source with the pinned flags (build_shim.sh repeats build.sh's). The
// four functions below only read what the env already keeps or computes.
// Nothing here writes to a session.
#include "bbplay.c"

_Static_assert(BBE_REWARD_COMPONENT_COUNT == 28, "the probe names 28 reward components");

static const char* const bbp_probe_names[BBE_REWARD_COMPONENT_COUNT] = {
    [BBE_REWARD_SETUP_DONE] = "setup_done",
    [BBE_REWARD_SETUP_AUTOFIX] = "setup_autofix",
    [BBE_REWARD_BALL_GAIN] = "ball_gain",
    [BBE_REWARD_BALL_LOSS] = "ball_loss",
    [BBE_REWARD_DISTANCE_BALL] = "distance_ball",
    [BBE_REWARD_DISTANCE_ENDZONE] = "distance_endzone",
    [BBE_REWARD_INJURY_INFLICTED] = "injury_inflicted",
    [BBE_REWARD_INJURY_TAKEN] = "injury_taken",
    [BBE_REWARD_SEND_OFF] = "send_off",
    [BBE_REWARD_TOUCHBACK] = "touchback",
    [BBE_REWARD_SURF_INFLICTED] = "surf_inflicted",
    [BBE_REWARD_SURF_TAKEN] = "surf_taken",
    [BBE_REWARD_BLOCK_EXPOSURE] = "block_exposure",
    [BBE_REWARD_BLOCK_SELF_INJURY] = "block_self_injury",
    [BBE_REWARD_BLOCK_SEQUENCE] = "block_sequence",
    [BBE_REWARD_BLOCK_TURNOVER] = "block_turnover",
    [BBE_REWARD_POSSESSION] = "possession",
    [BBE_REWARD_BLOCK_ASSIST] = "block_assist",
    [BBE_REWARD_RUSH] = "rush",
    [BBE_REWARD_CARRIER_EXPOSURE] = "carrier_exposure",
    [BBE_REWARD_CARRIER_EXPOSURE_SOFT] = "carrier_exposure_soft",
    [BBE_REWARD_CARRIER_THREAT] = "carrier_threat",
    [BBE_REWARD_DEFENSIVE_THREAT] = "defensive_threat",
    [BBE_REWARD_DEFENSIVE_THREAT_SOFT] = "defensive_threat_soft",
    [BBE_REWARD_TOUCHDOWN] = "touchdown",
    [BBE_REWARD_RESULT_WINLOSS] = "result_winloss",
    [BBE_REWARD_RESULT_DRAW] = "result_draw",
    [BBE_REWARD_STATMATCH] = "statmatch",
};

int bbp_probe_component_count(void) { return BBE_REWARD_COMPONENT_COUNT; }

const char* bbp_probe_component_name(int i) {
    return (i >= 0 && i < BBE_REWARD_COMPONENT_COUNT) ? bbp_probe_names[i] : "";
}

// The latest c_step's reward components for (HOME, AWAY): out[a * COUNT + c].
// Valid after a step that did not end the match. A terminal step resets the
// env to the next match before it returns, which zeroes these; the caller
// then sees zeros here and the terminal reward in bbp_last_rewards.
int bbp_probe_step_components(bbp_session* s, float* out, int cap) {
    int n = BBE_REWARD_COMPONENT_COUNT;
    if (!s || !out || cap < BBE_AGENTS * n) return -1;
    for (int a = 0; a < BBE_AGENTS; a++) {
        for (int c = 0; c < n; c++) out[a * n + c] = s->env.step_reward_component[a][c];
    }
    return n;
}

// The env's own design envelope for one step's reward (bbe_reward_clip_threshold),
// for this session's reward table: the limit the probe holds every reward to.
float bbp_probe_reward_clip_threshold(bbp_session* s) {
    return s ? bbe_reward_clip_threshold(&s->env) : -1.0f;
}

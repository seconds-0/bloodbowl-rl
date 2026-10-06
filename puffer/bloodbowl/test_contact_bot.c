#define BB_TEST_MAIN
#include "bb_test.h"
#include "bloodbowl.h"

enum {
    CONTACT_GAMES = 200,
    CONTACT_HOOK_GAMES = 24,
    CONTACT_DECISION_CAP = BBE_MAX_DECISIONS,
};

static int action_in_legal(bb_action a, const bb_action* legal, int n) {
    for (int i = 0; i < n; i++) {
        if (bb_action_eq(a, legal[i])) return 1;
    }
    return 0;
}

static void hash_bytes(uint64_t* h, const void* ptr, size_t len) {
    const unsigned char* p = (const unsigned char*)ptr;
    for (size_t i = 0; i < len; i++) {
        *h ^= (uint64_t)p[i];
        *h *= 1099511628211ull;
    }
}

typedef struct {
    int completed;
    long decisions;
    uint64_t digest;
    float n;
    float blocks_thrown;
    float blocks_thrown_t0;
    float blocks_thrown_t1;
    float tds;
    float tds_t0;
    float tds_t1;
    float end_turn_removed;
} ContactHookStats;

typedef struct {
    long bot_decisions;
    long bot_end_turn_beside_activate; // bot lists holding both types
    long bot_early_end_turns;          // ... at which the bot picks END_TURN
    long policy_removed;               // learner lists the rule shortened
    long learner_removed[BBE_AGENTS];  // ... by seat
    long bank_decisions;               // frozen-bank seat decisions
    long bank_end_turn_beside_activate; // ... whose list holds both types
} ContactSeatStats;

// Set by the no_early_end_turn tests; every other test runs with the flag off
// and the contact bot (type 0).
static int contact_no_early_end_turn = 0;
static int contact_bot_type = 0;
static ContactSeatStats* contact_seat_stats = NULL;

// With the rule on, a scripted seat's list and a frozen-bank seat's list are
// the engine's own list, and a learner seat's list is that list without
// END_TURN beside an ACTIVATE.
static void contact_check_seat_list(const Bloodbowl* env) {
    static bb_action engine_legal[BB_LEGAL_MAX];
    const bb_match* m = &env->match;
    if (m->status != BB_STATUS_DECISION) return;
    int n = bb_legal_actions(m, engine_legal);
    int activates = 0, end_turns = 0;
    for (int i = 0; i < n; i++) {
        activates += engine_legal[i].type == BB_A_ACTIVATE;
        end_turns += engine_legal[i].type == BB_A_END_TURN;
    }
    if (bbe_seat_is_scripted(env, m->decision_team)) {
        BB_CHECK_EQ(env->legal_end_turn_removed, 0);
        BB_CHECK_EQ(env->n_legal, n);
        for (int i = 0; i < n && i < env->n_legal; i++) {
            BB_CHECK(bb_action_eq(env->legal[i], engine_legal[i]));
        }
        contact_seat_stats->bot_decisions++;
        if (activates > 0 && end_turns > 0) {
            // The pick c_step is about to make: both bots are pure functions
            // of the match and the list.
            bb_action pick = env->scripted_opponent_type == 1
                ? bbe_offense_bot_pick(m, env->legal, env->n_legal)
                : bbe_contact_bot_pick(m, env->legal, env->n_legal);
            contact_seat_stats->bot_end_turn_beside_activate++;
            contact_seat_stats->bot_early_end_turns +=
                pick.type == BB_A_END_TURN;
        }
    } else if (bbe_seat_is_frozen_bank(env, m->decision_team)) {
        BB_CHECK_EQ(env->legal_end_turn_removed, 0);
        BB_CHECK_EQ(env->n_legal, n);
        for (int i = 0; i < n && i < env->n_legal; i++) {
            BB_CHECK(bb_action_eq(env->legal[i], engine_legal[i]));
        }
        contact_seat_stats->bank_decisions++;
        contact_seat_stats->bank_end_turn_beside_activate +=
            activates > 0 && end_turns > 0;
    } else if (activates > 0 && end_turns > 0) {
        BB_CHECK(bbe_seat_is_learner(env, m->decision_team));
        BB_CHECK_EQ(env->legal_end_turn_removed, 1);
        BB_CHECK_EQ(env->n_legal, n - end_turns);
        contact_seat_stats->policy_removed++;
        contact_seat_stats->learner_removed[m->decision_team]++;
    }
}

static ContactHookStats run_contact_hook_tagged(int scripted, int scripted_team,
                                                uint64_t seed, int games,
                                                int scripted_bank_tag,
                                                int env_tag) {
    Bloodbowl env;
    memset(&env, 0, sizeof env);
    env.scripted_bank_tag = scripted_bank_tag;
    env.tag = env_tag;
    env.no_early_end_turn = contact_no_early_end_turn;
    env.scripted_opponent_type = contact_bot_type;
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    env.num_agents = BBE_AGENTS;
    env.seed = seed;
    env.scripted_opponent = scripted;
    env.scripted_opponent_team = scripted_team;
    env.max_decisions = CONTACT_DECISION_CAP;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env.obs_ptr[a] = obs + a * BBE_OBS_SIZE;
        env.action_ptr[a] = actions + a * 3;
        env.action_mask_ptr[a] = masks + a * BBE_MASK_SIZE;
        env.reward_ptr[a] = rewards + a;
        env.terminal_ptr[a] = terminals + a;
    }
    c_reset(&env);

    bb_rng pol;
    bb_rng_seed(&pol, seed ^ 0x51C1A7EDu, 5);
    ContactHookStats out = {.digest = 1469598103934665603ull};
    int episode_decisions = 0;
    while (out.completed < games &&
           out.decisions < (long)games * CONTACT_DECISION_CAP) {
        if (contact_seat_stats) contact_check_seat_list(&env);
        // Everything a policy is shown, as well as what was played.
        hash_bytes(&out.digest, obs, sizeof obs);
        hash_bytes(&out.digest, masks, sizeof masks);
        for (int a = 0; a < BBE_AGENTS; a++) {
            bbe_sample_joint_uniform(&env, a, env.action_ptr[a], &pol);
        }
        hash_bytes(&out.digest, actions, sizeof actions);
        c_step(&env);
        hash_bytes(&out.digest, rewards, sizeof rewards);
        hash_bytes(&out.digest, terminals, sizeof terminals);
        out.decisions++;
        episode_decisions++;
        if (terminals[0] != 0.0f) {
            BB_CHECK(episode_decisions < CONTACT_DECISION_CAP);
            out.completed++;
            episode_decisions = 0;
        }
    }

    out.n = env.log.n;
    out.blocks_thrown = env.log.blocks_thrown;
    out.blocks_thrown_t0 = env.log.blocks_thrown_t0;
    out.blocks_thrown_t1 = env.log.blocks_thrown_t1;
    out.tds = env.log.tds;
    out.tds_t0 = env.log.tds_t0;
    out.tds_t1 = env.log.tds_t1;
    out.end_turn_removed = env.log.end_turn_removed;
    return out;
}

static ContactHookStats run_contact_hook(int scripted, int scripted_team,
                                         uint64_t seed, int games) {
    return run_contact_hook_tagged(scripted, scripted_team, seed, games, 0, 0);
}

BB_TEST(contact_bot_full_games_terminate_and_make_contact) {
    long total_blocks = 0;
    long total_tds = 0;
    long total_decisions = 0;
    int completed = 0;

    for (int g = 0; g < CONTACT_GAMES; g++) {
        bb_rng procgen;
        bb_rng dice;
        bb_rng_seed(&procgen, 0xC0A7AC7u + (uint64_t)g * 9973u, 11);
        bb_rng_seed(&dice, 0xB10CBB01u + (uint64_t)g * 7919u, 1);

        bb_match m;
        bb_procgen_params pp = bb_procgen_params_default();
        bb_match_init_random_p(&m, &procgen, &pp);
        bb_advance(&m, &dice);

        int decisions = 0;
        int blocks = 0;
        while (m.status == BB_STATUS_DECISION && decisions < CONTACT_DECISION_CAP) {
            bb_action legal[BB_LEGAL_MAX];
            int n = bb_legal_actions(&m, legal);
            BB_CHECK(n > 0);
            if (n <= 0) break;

            bb_action pick = bbe_contact_bot_pick(&m, legal, n);
            BB_CHECK(action_in_legal(pick, legal, n));
            if (!action_in_legal(pick, legal, n)) break;

            if (pick.type == BB_A_CHOOSE_DIE) blocks++;
            bb_apply(&m, pick, &dice);
            decisions++;
            BB_CHECK(m.status != BB_STATUS_ERROR);
            if (m.status == BB_STATUS_ERROR) break;
        }

        BB_CHECK_EQ(m.status, BB_STATUS_MATCH_OVER);
        BB_CHECK(decisions < CONTACT_DECISION_CAP);
        total_blocks += blocks;
        total_tds += (long)m.score[0] + (long)m.score[1];
        total_decisions += decisions;
        completed += m.status == BB_STATUS_MATCH_OVER;
    }

    BB_CHECK_EQ(completed, CONTACT_GAMES);
    BB_CHECK(total_blocks > CONTACT_GAMES * 4);
    BB_CHECK(total_blocks < CONTACT_GAMES * 300);
    BB_CHECK(total_tds > 0);
    printf("contact_bot: games=%d decisions=%ld blocks_thrown=%ld tds=%ld\n",
           CONTACT_GAMES, total_decisions, total_blocks, total_tds);
}

BB_TEST(contact_bot_c_step_hook_logs_per_team_and_off_is_inert) {
    ContactHookStats bot = run_contact_hook(
        1, BB_AWAY, 0xB07C057u, CONTACT_HOOK_GAMES);
    BB_CHECK_EQ(bot.completed, CONTACT_HOOK_GAMES);
    BB_CHECK_EQ((int)bot.n, CONTACT_HOOK_GAMES);
    BB_CHECK(bot.blocks_thrown_t1 > (float)CONTACT_HOOK_GAMES * 2.0f);
    BB_CHECK(bot.blocks_thrown_t0 + bot.blocks_thrown_t1 == bot.blocks_thrown);
    BB_CHECK(bot.tds_t0 + bot.tds_t1 == bot.tds);

    ContactHookStats off_away_side = run_contact_hook(
        0, BB_AWAY, 0x0FF51DEu, 6);
    ContactHookStats off_home_side = run_contact_hook(
        0, BB_HOME, 0x0FF51DEu, 6);
    BB_CHECK_EQ(off_away_side.completed, off_home_side.completed);
    BB_CHECK(off_away_side.digest == off_home_side.digest);
    BB_CHECK_EQ((int)off_away_side.n, (int)off_home_side.n);
}

BB_TEST(contact_bot_scripted_bank_tag_gates_the_bot_on_the_env_tag) {
    // scripted_bank_tag = b+1 confines the bot to the envs tagged for frozen
    // bank b. In an untagged env (tag 0, pure self-play) or an env of another
    // bank the step is byte-identical to no bot at all; in the matching env
    // it is byte-identical to the global scripted opponent.
    const uint64_t seed = 0x5C817BA9u;
    ContactHookStats unscripted = run_contact_hook_tagged(0, BB_AWAY, seed, 6, 0, 0);
    ContactHookStats scripted = run_contact_hook_tagged(1, BB_AWAY, seed, 6, 0, 0);
    BB_CHECK(unscripted.digest != scripted.digest);
    BB_CHECK(scripted.blocks_thrown_t1 > unscripted.blocks_thrown_t1);

    ContactHookStats bank_untagged_env = run_contact_hook_tagged(1, BB_AWAY, seed, 6, 2, 0);
    ContactHookStats bank_other_env = run_contact_hook_tagged(1, BB_AWAY, seed, 6, 2, 1);
    ContactHookStats bank_matching_env = run_contact_hook_tagged(1, BB_AWAY, seed, 6, 2, 2);
    BB_CHECK(bank_untagged_env.digest == unscripted.digest);
    BB_CHECK(bank_other_env.digest == unscripted.digest);
    BB_CHECK(bank_matching_env.digest == scripted.digest);
    BB_CHECK_EQ(bank_matching_env.completed, scripted.completed);
    BB_CHECK(bank_matching_env.blocks_thrown_t1 == scripted.blocks_thrown_t1);
    // Tag 0 = global semantics, unchanged: every env is scripted.
    ContactHookStats global_tagged_env = run_contact_hook_tagged(1, BB_AWAY, seed, 6, 0, 3);
    BB_CHECK(global_tagged_env.digest == scripted.digest);
}

// --- no_early_end_turn and scripted seats -----------------------------------
// The rule is a restriction on POLICY seats. The contact bot ranks END_TURN
// below every ACTIVATE and never ends a turn early; the offense bot does so
// rarely. Neither may lose the option: the bot is handed the engine's list.

BB_TEST(no_early_end_turn_hands_the_bot_the_engine_list_with_end_turn_in_it) {
    ContactSeatStats seats = {0};
    contact_seat_stats = &seats;
    contact_no_early_end_turn = 1;
    ContactHookStats away_bot = run_contact_hook(1, BB_AWAY, 0x0E0B07u, 12);
    ContactSeatStats away = seats;
    memset(&seats, 0, sizeof seats);
    ContactHookStats home_bot = run_contact_hook(1, BB_HOME, 0x0E0B07u, 12);
    ContactSeatStats home = seats;
    contact_no_early_end_turn = 0;
    contact_seat_stats = NULL;

    BB_CHECK_EQ(away_bot.completed, 12);
    BB_CHECK_EQ(home_bot.completed, 12);
    // The bot was offered END_TURN beside an ACTIVATE (the choice the rule
    // takes from a policy), and the policy seat in the same games was not.
    BB_CHECK(away.bot_end_turn_beside_activate > 0);
    BB_CHECK(home.bot_end_turn_beside_activate > 0);
    BB_CHECK(away.policy_removed > 0);
    BB_CHECK(home.policy_removed > 0);
    // The panel counts the policy seat's removals only, never the bot's seat.
    BB_CHECK(away_bot.end_turn_removed == (float)away.policy_removed);
    BB_CHECK(home_bot.end_turn_removed == (float)home.policy_removed);
    printf("no_early_end_turn bot seats: away bot decisions=%ld with "
           "END_TURN+ACTIVATE=%ld policy removals=%ld; home bot decisions=%ld "
           "with END_TURN+ACTIVATE=%ld policy removals=%ld\n",
           away.bot_decisions, away.bot_end_turn_beside_activate,
           away.policy_removed, home.bot_decisions,
           home.bot_end_turn_beside_activate, home.policy_removed);
}

BB_TEST(no_early_end_turn_leaves_bot_versus_bot_games_byte_identical) {
    // scripted_opponent_team 2 seats a bot on both sides, so no seat is a
    // policy seat and the flag must change nothing at all.
    const uint64_t seed = 0xB07B07u;
    ContactHookStats off = run_contact_hook(1, 2, seed, 8);
    contact_no_early_end_turn = 1;
    ContactHookStats on = run_contact_hook(1, 2, seed, 8);
    contact_no_early_end_turn = 0;
    BB_CHECK_EQ(off.completed, 8);
    BB_CHECK_EQ(on.completed, off.completed);
    BB_CHECK_EQ(on.decisions, off.decisions);
    BB_CHECK(on.digest == off.digest);
    BB_CHECK(on.tds == off.tds);
    BB_CHECK(on.blocks_thrown == off.blocks_thrown);
    BB_CHECK(on.end_turn_removed == 0.0f);
    BB_CHECK(off.end_turn_removed == 0.0f);
}

BB_TEST(no_early_end_turn_still_lets_the_offense_bot_end_its_turn_early) {
    // Offense bot on both seats, rule on: it ends team turns with a player
    // still to activate, as it does with the rule off, in the same games.
    const uint64_t seed = 0x0FFB07u;
    const int games = 60;
    contact_bot_type = 1;
    ContactHookStats off = run_contact_hook(1, 2, seed, games);
    ContactSeatStats seats = {0};
    contact_seat_stats = &seats;
    contact_no_early_end_turn = 1;
    ContactHookStats on = run_contact_hook(1, 2, seed, games);
    contact_no_early_end_turn = 0;
    contact_seat_stats = NULL;
    contact_bot_type = 0;
    BB_CHECK_EQ(on.completed, games);
    BB_CHECK(on.digest == off.digest);
    BB_CHECK_EQ(on.decisions, off.decisions);
    BB_CHECK(seats.bot_early_end_turns > 0);
    BB_CHECK_EQ(seats.policy_removed, 0);
    printf("no_early_end_turn offense bot both seats: games=%d decisions=%ld "
           "lists with END_TURN+ACTIVATE=%ld early END_TURN picks=%ld\n",
           games, on.decisions, seats.bot_end_turn_beside_activate,
           seats.bot_early_end_turns);
}

BB_TEST(no_early_end_turn_changes_a_policy_seat_but_not_the_flag_off_run) {
    // Same seed, bot AWAY: flag off twice is one trajectory; flag on is
    // another, because the HOME policy seat lost END_TURN.
    const uint64_t seed = 0x0E0FF0u;
    ContactHookStats off = run_contact_hook(1, BB_AWAY, seed, 6);
    ContactHookStats off_again = run_contact_hook(1, BB_AWAY, seed, 6);
    contact_no_early_end_turn = 1;
    ContactHookStats on = run_contact_hook(1, BB_AWAY, seed, 6);
    contact_no_early_end_turn = 0;
    BB_CHECK(off.digest == off_again.digest);
    BB_CHECK(on.digest != off.digest);
    BB_CHECK_EQ(on.completed, 6);
}

// --- no_early_end_turn restricts learner seats only --------------------------
// The env knows a frozen-bank seat from its selfplay tag: tag b+1 means slot 1
// (AWAY) is routed to frozen bank b and slot 0 is the learner; tag 0 is a
// mirror env with the learner on both seats.

BB_TEST(no_early_end_turn_restricts_both_seats_of_a_mirror_env) {
    ContactSeatStats seats = {0};
    contact_seat_stats = &seats;
    contact_no_early_end_turn = 1;
    ContactHookStats mirror = run_contact_hook_tagged(0, BB_AWAY, 0x31220u, 8, 0, 0);
    contact_no_early_end_turn = 0;
    contact_seat_stats = NULL;
    BB_CHECK_EQ(mirror.completed, 8);
    BB_CHECK(seats.learner_removed[BB_HOME] > 0);
    BB_CHECK(seats.learner_removed[BB_AWAY] > 0);
    BB_CHECK_EQ(seats.bank_decisions, 0);
    BB_CHECK_EQ(seats.bot_decisions, 0);
    BB_CHECK(mirror.end_turn_removed ==
             (float)(seats.learner_removed[BB_HOME] + seats.learner_removed[BB_AWAY]));
}

BB_TEST(no_early_end_turn_leaves_the_frozen_bank_seat_the_engine_list) {
    // A bank env (tag 2 = frozen bank 1 on slot 1), no scripted opponent: the
    // bank's seat keeps END_TURN beside ACTIVATE, the learner's does not.
    ContactSeatStats seats = {0};
    contact_seat_stats = &seats;
    contact_no_early_end_turn = 1;
    ContactHookStats bank = run_contact_hook_tagged(0, BB_AWAY, 0x31220u, 8, 0, 2);
    ContactSeatStats on = seats;
    memset(&seats, 0, sizeof seats);
    // The same env with a scripted bank configured for ANOTHER tag: slot 1 is
    // still a frozen policy's seat here, not a bot's.
    ContactHookStats other = run_contact_hook_tagged(1, BB_AWAY, 0x31220u, 8, 4, 2);
    ContactSeatStats other_seats = seats;
    contact_no_early_end_turn = 0;
    contact_seat_stats = NULL;

    BB_CHECK_EQ(bank.completed, 8);
    BB_CHECK(on.bank_decisions > 0);
    BB_CHECK(on.bank_end_turn_beside_activate > 0);
    BB_CHECK(on.learner_removed[BB_HOME] > 0);
    BB_CHECK_EQ(on.learner_removed[BB_AWAY], 0);
    BB_CHECK_EQ(on.bot_decisions, 0);
    // The panel counts the learner seat's removals and nothing of the bank's.
    BB_CHECK(bank.end_turn_removed == (float)on.learner_removed[BB_HOME]);
    BB_CHECK(other.digest == bank.digest);
    BB_CHECK_EQ(other_seats.bot_decisions, 0);
    BB_CHECK_EQ(other_seats.bank_end_turn_beside_activate,
                on.bank_end_turn_beside_activate);
    printf("no_early_end_turn bank env: bank seat decisions=%ld with "
           "END_TURN+ACTIVATE=%ld (kept); learner seat removals=%ld\n",
           on.bank_decisions, on.bank_end_turn_beside_activate,
           on.learner_removed[BB_HOME]);
}

BB_TEST(no_early_end_turn_scripted_bank_env_restricts_the_learner_seat_only) {
    // The env of the scripted bank (tag == scripted_bank_tag): slot 1 is the
    // bot, slot 0 the learner.
    ContactSeatStats seats = {0};
    contact_seat_stats = &seats;
    contact_no_early_end_turn = 1;
    ContactHookStats bot_bank = run_contact_hook_tagged(1, BB_AWAY, 0x31220u, 8, 4, 4);
    contact_no_early_end_turn = 0;
    contact_seat_stats = NULL;
    BB_CHECK_EQ(bot_bank.completed, 8);
    BB_CHECK(seats.bot_end_turn_beside_activate > 0);
    BB_CHECK_EQ(seats.bank_decisions, 0);
    BB_CHECK(seats.learner_removed[BB_HOME] > 0);
    BB_CHECK_EQ(seats.learner_removed[BB_AWAY], 0);
    BB_CHECK(bot_bank.end_turn_removed == (float)seats.learner_removed[BB_HOME]);
}

BB_TEST(no_early_end_turn_exam_layout_restricts_the_champion_whichever_seat) {
    // The exam: scripted_opponent global (no bank tag, env tag 0), the bot on
    // one seat and the champion on the other.
    for (int bot_team = 0; bot_team < 2; bot_team++) {
        ContactSeatStats seats = {0};
        contact_seat_stats = &seats;
        contact_no_early_end_turn = 1;
        ContactHookStats exam = run_contact_hook_tagged(1, bot_team, 0xE8A3u, 8, 0, 0);
        contact_no_early_end_turn = 0;
        contact_seat_stats = NULL;
        int champion = 1 - bot_team;
        BB_CHECK_EQ(exam.completed, 8);
        BB_CHECK(seats.learner_removed[champion] > 0);
        BB_CHECK_EQ(seats.learner_removed[bot_team], 0);
        BB_CHECK(seats.bot_end_turn_beside_activate > 0);
        BB_CHECK_EQ(seats.bank_decisions, 0);
        BB_CHECK(exam.end_turn_removed == (float)seats.learner_removed[champion]);
    }
}

BB_TEST(no_early_end_turn_reads_the_env_tag_only_when_the_flag_is_on) {
    // Flag off against flag on in a bank env differ only through the learner
    // seat; in a mirror env through both. Flag off, a tag changes nothing.
    const uint64_t seed = 0x7A6ED0u;
    ContactHookStats off_mirror = run_contact_hook_tagged(0, BB_AWAY, seed, 6, 0, 0);
    ContactHookStats off_bank = run_contact_hook_tagged(0, BB_AWAY, seed, 6, 0, 2);
    BB_CHECK(off_mirror.digest == off_bank.digest);
    contact_no_early_end_turn = 1;
    ContactHookStats on_mirror = run_contact_hook_tagged(0, BB_AWAY, seed, 6, 0, 0);
    ContactHookStats on_bank = run_contact_hook_tagged(0, BB_AWAY, seed, 6, 0, 2);
    contact_no_early_end_turn = 0;
    BB_CHECK(on_mirror.digest != off_mirror.digest);
    BB_CHECK(on_bank.digest != off_bank.digest);
    BB_CHECK(on_bank.digest != on_mirror.digest);
    BB_CHECK(on_bank.end_turn_removed > 0.0f);
    BB_CHECK(on_bank.end_turn_removed < on_mirror.end_turn_removed);
}

BB_TEST(no_early_end_turn_kickoff_reset_never_opens_on_a_shortened_list) {
    // Selfplay tags arrive after the first reset. A kick-off start opens in
    // the pre-game sequence, so no list is shortened before the tags exist
    // and a frozen-bank seat is never restricted by a stale tag.
    static Bloodbowl env;
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    for (uint64_t seed = 1; seed <= 200; seed++) {
        memset(&env, 0, sizeof env);
        env.num_agents = BBE_AGENTS;
        env.seed = seed * 7919u;
        env.no_early_end_turn = 1;
        env.exclude_team = env.force_home_team = env.force_away_team = -1;
        for (int a = 0; a < BBE_AGENTS; a++) {
            env.obs_ptr[a] = obs + a * BBE_OBS_SIZE;
            env.action_ptr[a] = actions + a * 3;
            env.action_mask_ptr[a] = masks + a * BBE_MASK_SIZE;
            env.reward_ptr[a] = rewards + a;
            env.terminal_ptr[a] = terminals + a;
        }
        c_reset(&env);
        BB_CHECK_EQ(env.match.status, BB_STATUS_DECISION);
        BB_CHECK_EQ(env.legal_end_turn_removed, 0);
        for (int i = 0; i < env.n_legal; i++) {
            BB_CHECK(env.legal[i].type != BB_A_END_TURN);
            BB_CHECK(env.legal[i].type != BB_A_ACTIVATE);
        }
    }
}

BB_TEST(no_early_end_turn_gives_a_late_tagged_bot_seat_its_end_turn_back) {
    // Selfplay tags are assigned after the first reset. A scripted-bank seat
    // can therefore meet a list that was shortened while the env was still
    // untagged; the bot path restores the engine's list before it picks.
    static Bloodbowl env;
    static uint8_t obs[BBE_AGENTS * BBE_OBS_SIZE];
    static float actions[BBE_AGENTS * 3];
    static unsigned char masks[BBE_AGENTS * BBE_MASK_SIZE];
    static float rewards[BBE_AGENTS];
    static float terminals[BBE_AGENTS];
    static bb_action engine_legal[BB_LEGAL_MAX];
    memset(&env, 0, sizeof env);
    env.num_agents = BBE_AGENTS;
    env.seed = 0x7A61A7Eu;
    env.scripted_opponent = 1;
    env.scripted_opponent_team = BB_AWAY;
    env.scripted_bank_tag = 2;
    env.tag = 0;
    env.no_early_end_turn = 1;
    env.exclude_team = env.force_home_team = env.force_away_team = -1;
    for (int a = 0; a < BBE_AGENTS; a++) {
        env.obs_ptr[a] = obs + a * BBE_OBS_SIZE;
        env.action_ptr[a] = actions + a * 3;
        env.action_mask_ptr[a] = masks + a * BBE_MASK_SIZE;
        env.reward_ptr[a] = rewards + a;
        env.terminal_ptr[a] = terminals + a;
    }
    c_reset(&env);
    bb_rng pol;
    bb_rng_seed(&pol, 0x7A6u, 5);
    int guard = 0;
    while (!(env.legal_end_turn_removed &&
             env.match.decision_team == BB_AWAY) && guard++ < 50000) {
        for (int a = 0; a < BBE_AGENTS; a++) {
            bbe_sample_joint_uniform(&env, a, env.action_ptr[a], &pol);
        }
        c_step(&env);
    }
    BB_CHECK(env.legal_end_turn_removed);
    BB_CHECK_EQ(env.match.decision_team, BB_AWAY);
    BB_CHECK(!bbe_seat_is_scripted(&env, BB_AWAY));

    env.tag = 2; // the env now belongs to the scripted bank
    BB_CHECK(bbe_seat_is_scripted(&env, BB_AWAY));
    BB_CHECK(!bbe_seat_is_scripted(&env, BB_HOME));
    int n_engine = bb_legal_actions(&env.match, engine_legal);
    BB_CHECK_EQ(env.n_legal, n_engine - 1);
    bbe_unrestrict_legal(&env);
    BB_CHECK_EQ(env.legal_end_turn_removed, 0);
    BB_CHECK_EQ(env.n_legal, n_engine);
    int end_turns = 0;
    for (int i = 0; i < env.n_legal; i++) {
        BB_CHECK(bb_action_eq(env.legal[i], engine_legal[i]));
        end_turns += env.legal[i].type == BB_A_END_TURN;
    }
    BB_CHECK_EQ(end_turns, 1);

    // And c_step takes that path itself: shorten the list again by hand, as
    // the untagged refresh did, and step the bot seat through it.
    bbe_restrict_end_turn(&env);
    BB_CHECK(env.legal_end_turn_removed);
    for (int a = 0; a < BBE_AGENTS; a++) {
        bbe_sample_joint_uniform(&env, a, env.action_ptr[a], &pol);
    }
    c_step(&env);
    BB_CHECK(env.match.status != BB_STATUS_ERROR);
    BB_CHECK(env.log.error_episodes == 0.0f);
}

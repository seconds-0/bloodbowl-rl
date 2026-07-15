// Deterministically classify S1-S6 opportunity facts in a BBS1 state bank.
// Output is one JSON object per record, in source order. Hash pinning,
// aggregation, and manifest publication belong to report_scenario_coverage.py.
#include "bank_scenario_predicates.h"
#include "bank_scenario_scan.h"

#include "bb/bb_actions.h"
#include "bb/bb_match.h"
#include "bb/bb_proc.h"
#include "bb/gen_skills.h"
#include "bb/gen_teams.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { HEADER_BYTES = 16, META_BYTES = 12 };

static uint32_t little_u32(const uint8_t* bytes) {
    return (uint32_t)bytes[0] |
           ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) |
           ((uint32_t)bytes[3] << 24);
}

uint32_t bbs_scenario_local_fingerprint(void) {
    return (uint32_t)sizeof(bb_match) * 2654435761u
         ^ ((uint32_t)BB_TEAM_COUNT << 20)
         ^ ((uint32_t)BB_SKILL_COUNT << 10)
         ^ (uint32_t)BB_A_TYPE_COUNT;
}

static int scan_error(const char** error, const char* message) {
    if (error) *error = message;
    return 2;
}

static int record_content_valid(const bb_match* match) {
    if (match->team_id[0] >= BB_TEAM_COUNT ||
        match->team_id[1] >= BB_TEAM_COUNT ||
        match->stack_top > BB_STACK_MAX) {
        return 0;
    }
    for (int slot = 0; slot < BB_NUM_PLAYERS; slot++) {
        const bb_player* player = &match->players[slot];
        if (player->position_id >= BB_MAX_POSITIONS ||
            player->location > BB_LOC_ABSENT ||
            player->stance > BB_STANCE_STUNNED_USED) {
            return 0;
        }
        if (player->location == BB_LOC_ON_PITCH &&
            (!bb_on_pitch_xy(player->x, player->y) ||
             match->grid[player->x][player->y] != slot + 1)) {
            return 0;
        }
    }
    for (int x = 0; x < BB_PITCH_LEN; x++) {
        for (int y = 0; y < BB_PITCH_WID; y++) {
            uint8_t value = match->grid[x][y];
            if (value == 0) continue;
            int slot = value - 1;
            if (slot >= BB_NUM_PLAYERS ||
                match->players[slot].location != BB_LOC_ON_PITCH ||
                match->players[slot].x != x ||
                match->players[slot].y != y) {
                return 0;
            }
        }
    }
    if (match->ball.state > BB_BALL_IN_AIR) return 0;
    if (match->ball.state == BB_BALL_ON_GROUND &&
        !bb_on_pitch_xy(match->ball.x, match->ball.y)) {
        return 0;
    }
    if (match->ball.state == BB_BALL_HELD &&
        (match->ball.carrier >= BB_NUM_PLAYERS ||
         match->players[match->ball.carrier].location != BB_LOC_ON_PITCH)) {
        return 0;
    }
    return 1;
}

static int emit_record(FILE* output, uint64_t index, uint32_t replay_id,
                       uint32_t command, uint8_t half, uint8_t turn,
                       const bb_match* match,
                       const bbs_scenario_facts* facts) {
    return fprintf(output,
           "{\"active_team\":%u,\"ball_state\":%u,\"command\":%" PRIu32
           ",\"eligible_players\":%u,\"half\":%u,\"record_index\":%" PRIu64
           ",\"replay_id\":%" PRIu32
           ",\"s1\":%u,\"s1_ball_tackle_zones\":%u"
           ",\"s1_cheapest_dodges\":%u,\"s1_cheapest_gfis\":%u"
           ",\"s1_has_sure_hands\":%u,\"s1_recoverers\":%u"
           ",\"s2\":%u,\"s2_cheapest_dodges\":%u"
           ",\"s2_cheapest_gfis\":%u,\"s2_opponent_reachers\":%u"
           ",\"s3\":%u,\"s3_risk_mask\":%u"
           ",\"s3_zero_roll_players\":%u"
           ",\"s4\":%u,\"s4_full\":%u,\"s4_r6v1_full\":%u"
           ",\"s4_r6v1_soft\":%u,\"s4_soft\":%u"
           ",\"s5\":%u,\"s5_carrier_marked\":%u,\"s5_horizon\":%d"
           ",\"s5_team_threats_1turn\":%u,\"s5_team_threats_2turn\":%u"
           ",\"s6\":%u,\"s6_class_changing_moves\":%u"
           ",\"s6_dynamic_blocks\":%u,\"s6_fixed_class_mask\":%u"
           ",\"s6a\":%u,\"s6b\":%u,\"team_id_0\":%u"
           ",\"team_id_1\":%u,\"turn\":%u,\"weather\":%u}\n",
           match->active_team, facts->ball_state, command,
           facts->eligible_players, half, index, replay_id,
           facts->s1, facts->s1_ball_tackle_zones,
           facts->s1_cheapest_dodges, facts->s1_cheapest_gfis,
           facts->s1_has_sure_hands, facts->s1_recoverers,
           facts->s2, facts->s2_cheapest_dodges,
           facts->s2_cheapest_gfis, facts->s2_opponent_reachers,
           facts->s3, facts->s3_risk_mask,
           facts->s3_zero_roll_players,
           facts->s4, facts->s4_full, facts->s4_r6v1_full,
           facts->s4_r6v1_soft, facts->s4_soft,
           facts->s5, facts->s5_carrier_marked, facts->s5_horizon,
           facts->s5_team_threats_1turn, facts->s5_team_threats_2turn,
           facts->s6, facts->s6_class_changing_moves,
           facts->s6_dynamic_blocks, facts->s6_fixed_class_mask,
           facts->s6a, facts->s6b, match->team_id[0], match->team_id[1],
           turn, match->weather) < 0 ? 2 : 0;
}

int bbs_scan_stream(FILE* file, FILE* output, const char** error) {
    if (error) *error = NULL;
    if (!file || !output) return scan_error(error, "null input/output stream");
    uint8_t header[HEADER_BYTES];
    if (fread(header, 1, sizeof(header), file) != sizeof(header)) {
        return scan_error(error, "truncated header");
    }
    uint32_t version = little_u32(header + 4);
    uint32_t match_size = little_u32(header + 8);
    uint32_t fingerprint = little_u32(header + 12);
    if (memcmp(header, "BBS1", 4) != 0) {
        return scan_error(error, "bad BBS1 magic");
    }
    if (version != 1) return scan_error(error, "unsupported BBS1 version");
    if (match_size != sizeof(bb_match)) {
        return scan_error(error, "match size differs from local ABI");
    }
    if (fingerprint != bbs_scenario_local_fingerprint()) {
        return scan_error(error, "engine fingerprint differs from local build");
    }

    if (fseek(file, 0, SEEK_END) != 0) {
        return scan_error(error, "cannot seek to end");
    }
    long file_bytes = ftell(file);
    if (file_bytes < HEADER_BYTES) {
        return scan_error(error, "invalid file size");
    }
    size_t record_bytes = META_BYTES + sizeof(bb_match);
    long body_bytes = file_bytes - HEADER_BYTES;
    if (body_bytes <= 0 || body_bytes % (long)record_bytes != 0) {
        return scan_error(error, "body is not a positive whole-record multiple");
    }
    uint64_t records = (uint64_t)(body_bytes / (long)record_bytes);
    if (fseek(file, HEADER_BYTES, SEEK_SET) != 0) {
        return scan_error(error, "cannot seek to first record");
    }

    for (uint64_t index = 0; index < records; index++) {
        uint8_t metadata[META_BYTES];
        bb_match match;
        if (fread(metadata, 1, sizeof(metadata), file) != sizeof(metadata) ||
            fread(&match, sizeof(match), 1, file) != 1) {
            return scan_error(error, "truncated record");
        }
        uint32_t replay_id = little_u32(metadata);
        uint32_t command = little_u32(metadata + 4);
        uint8_t half = metadata[8];
        uint8_t turn = metadata[9];
        if (replay_id == 0 || metadata[10] != 0 || metadata[11] != 0) {
            return scan_error(error, "invalid record metadata");
        }
        if (half < 1 || half > 3 || turn < 1 || turn > 8) {
            return scan_error(error, "metadata half/turn out of range");
        }
        if (!record_content_valid(&match)) {
            return scan_error(error, "record content indices are invalid");
        }
        if (match.half != half || match.active_team > BB_AWAY ||
            match.turn[match.active_team] != turn) {
            return scan_error(error, "metadata and match clock disagree");
        }
        bbs_scenario_facts facts;
        if (bbs_classify_scenarios(&match, &facts) != 0) {
            return scan_error(error, "record is not a fresh team-turn boundary");
        }
        if (emit_record(output, index, replay_id, command, half, turn,
                        &match, &facts) != 0 || ferror(output)) {
            return scan_error(error, "cannot write output");
        }
    }
    if (fgetc(file) != EOF) {
        return scan_error(error, "unconsumed trailing bytes");
    }
    if (ferror(file)) return scan_error(error, "cannot read input");
    if (fflush(output) != 0 || ferror(output)) {
        return scan_error(error, "cannot flush output");
    }
    return 0;
}

#ifndef BBS_SCANNER_LIBRARY
int main(int argc, char** argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s bank.bbs\n", argv[0]);
        return 2;
    }
    const char* path = argv[1];
    FILE* file = fopen(path, "rb");
    if (!file) {
        fprintf(stderr, "scenario scan failed for %s: %s\n",
                path, strerror(errno));
        return 2;
    }
    const char* error = NULL;
    int result = bbs_scan_stream(file, stdout, &error);
    if (fclose(file) != 0 && result == 0) {
        error = "cannot close input";
        result = 2;
    }
    if (result != 0) {
        fprintf(stderr, "scenario scan failed for %s: %s\n",
                path, error ? error : "unknown failure");
    }
    return result;
}
#endif

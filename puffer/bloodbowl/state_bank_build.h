#ifndef BBE_STATE_BANK_BUILD_H
#define BBE_STATE_BANK_BUILD_H

/*
 * Repository-native builds are deliberately incapable of opening a training
 * state bank.  The installer replaces this file with a bridge to the single
 * generated authority in src/exact_action_build_hash.h.
 */
#define PUFFER_STATE_BANK_CONTRACT_SCHEMA "none"
#define PUFFER_STATE_BANK_PRODUCER_SCHEMA "none"
#define PUFFER_STATE_BANK_AUTHORIZATION_SCHEMA "none"
#define PUFFER_STATE_BANK_COMPILED_KIND 0
#define PUFFER_STATE_BANK_KIND_NAME "none"
#define PUFFER_STATE_BANK_RULESET "none"
#define PUFFER_STATE_BANK_BBS_SHA256 "unused"
#define PUFFER_STATE_BANK_PRODUCER_MANIFEST_SHA256 "unused"
#define PUFFER_STATE_BANK_TRAINING_CONTRACT_SHA256 "unused"
#define PUFFER_STATE_BANK_PRODUCER_ENGINE_SOURCE_SHA256 "unused"
#define PUFFER_STATE_BANK_LOADER_ENGINE_SOURCE_SHA256 "unused"
#define PUFFER_STATE_BANK_BBS_BYTES 0
#define PUFFER_STATE_BANK_RECORDS 0
#define PUFFER_STATE_BANK_BBS_VERSION 0
#define PUFFER_STATE_BANK_MATCH_SIZE 0
#define PUFFER_STATE_BANK_ENGINE_FINGERPRINT 0
#define PUFFER_STATE_BANK_CONTRACT_IDENTITY "none"
#define PUFFER_STATE_BANK_BBS_PATH "unused"
#define PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH "unused"
#define PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH "unused"

#endif

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
#define PUFFER_STATE_BANK_STRATA_SCHEMA "bloodbowl-legacy-state-bank-strata-v1"
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

/*
 * Qualification fixtures are a separate compile-time role, not a state-bank
 * kind.  Repository-native and ordinary installed builds are intentionally
 * inert.  The dedicated F5 installer replaces these literals in its generated
 * build authority; no runtime configuration can enable the role.
 */
#define PUFFER_QUALIFICATION_FIXTURE_ENABLED 0
#define PUFFER_QUALIFICATION_FIXTURE_ROLE "none"
#define PUFFER_QUALIFICATION_FIXTURE_SCHEMA "none"
#define PUFFER_QUALIFICATION_FIXTURE_QUALIFICATION_ONLY 0
#define PUFFER_QUALIFICATION_FIXTURE_MATCH_SHA256 "unused"
#define PUFFER_QUALIFICATION_FIXTURE_BBS_SHA256 "unused"
#define PUFFER_QUALIFICATION_FIXTURE_BUNDLE_SHA256 "unused"
#define PUFFER_QUALIFICATION_FIXTURE_BBS_SOURCE_ID UINT32_C(0)
#define PUFFER_QUALIFICATION_FIXTURE_AUTHORED_SOURCE_ID UINT32_C(0)
#define PUFFER_QUALIFICATION_FIXTURE_MAX_DECISIONS 0
#define PUFFER_QUALIFICATION_FIXTURE_REWARD_CONTRACT "none"
#define PUFFER_QUALIFICATION_FIXTURE_REFERENCE_TRACE_SCHEMA "none"
#define PUFFER_QUALIFICATION_FIXTURE_REFERENCE_TRACE_SHA256 "unused"

#endif

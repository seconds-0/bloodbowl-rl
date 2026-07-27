#include "bloodbowl.h"

#ifndef PUFFER_ENV_SOURCE_HASH
#error "state-bank validator requires a compiled environment source identity"
#endif

typedef struct {
    const char* kind;
    const char* bank;
    const char* bank_sha256;
    const char* producer_manifest;
    const char* producer_manifest_sha256;
    const char* training_contract;
    const char* training_contract_sha256;
    const char* producer_engine_source_sha256;
    const char* loader_engine_source_sha256;
    const char* environment_source_sha256;
    const char* contract_identity;
    const char* selector_family;
    uint64_t bytes;
    uint64_t records;
    uint32_t selector_threshold;
    int have_bytes;
    int have_records;
    int have_selector_threshold;
} validate_args;

static int state_bank_parse_u64(const char* text, uint64_t* output) {
    if (text == NULL || text[0] == '\0' || text[0] == '-' ||
        text[0] == '+') {
        return -1;
    }
    errno = 0;
    char* end = NULL;
    unsigned long long value = strtoull(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0') return -1;
    *output = (uint64_t)value;
    return 0;
}

static int state_bank_parse_u32_canonical(const char* text,
                                          uint32_t* output) {
    if (text == NULL || text[0] == '\0') return -1;
    if (text[0] == '0' && text[1] != '\0') return -1;
    uint64_t value = 0;
    for (const unsigned char* p = (const unsigned char*)text;
         *p != '\0'; p++) {
        if (*p < '0' || *p > '9') return -1;
        uint32_t digit = (uint32_t)(*p - '0');
        if (value > (UINT32_MAX - digit) / 10u) return -1;
        value = value * 10u + digit;
    }
    *output = (uint32_t)value;
    return 0;
}

static int set_once(const char** field, const char* value) {
    if (*field != NULL) return -1;
    *field = value;
    return 0;
}

static int parse_args(int argc, char** argv, validate_args* args) {
    memset(args, 0, sizeof *args);
    for (int i = 1; i < argc; i++) {
        const char* option = argv[i];
        if (i + 1 >= argc) return -1;
        const char* value = argv[++i];
#define ARG(name, field)                                                       \
        if (strcmp(option, name) == 0) {                                       \
            if (set_once(&args->field, value) != 0) return -1;                \
            continue;                                                          \
        }
        ARG("--kind", kind)
        ARG("--bank", bank)
        ARG("--bank-sha256", bank_sha256)
        ARG("--producer-manifest", producer_manifest)
        ARG("--producer-manifest-sha256", producer_manifest_sha256)
        ARG("--training-contract", training_contract)
        ARG("--training-contract-sha256", training_contract_sha256)
        ARG("--producer-engine-source-sha256",
            producer_engine_source_sha256)
        ARG("--loader-engine-source-sha256", loader_engine_source_sha256)
        ARG("--environment-source-sha256", environment_source_sha256)
        ARG("--contract-identity", contract_identity)
        ARG("--selector-family", selector_family)
#undef ARG
        if (strcmp(option, "--bytes") == 0) {
            if (args->have_bytes ||
                state_bank_parse_u64(value, &args->bytes) != 0) return -1;
            args->have_bytes = 1;
            continue;
        }
        if (strcmp(option, "--records") == 0) {
            if (args->have_records ||
                state_bank_parse_u64(value, &args->records) != 0) return -1;
            args->have_records = 1;
            continue;
        }
        if (strcmp(option, "--selector-threshold") == 0) {
            if (args->have_selector_threshold ||
                state_bank_parse_u32_canonical(
                    value, &args->selector_threshold) != 0) {
                return -1;
            }
            args->have_selector_threshold = 1;
            continue;
        }
        return -1;
    }
    return args->kind != NULL && args->bank != NULL &&
           args->bank_sha256 != NULL &&
           args->producer_manifest != NULL &&
           args->producer_manifest_sha256 != NULL &&
           args->training_contract != NULL &&
           args->training_contract_sha256 != NULL &&
           args->producer_engine_source_sha256 != NULL &&
           args->loader_engine_source_sha256 != NULL &&
           args->environment_source_sha256 != NULL &&
           args->contract_identity != NULL &&
           args->selector_family != NULL &&
           args->have_bytes && args->have_records &&
           args->have_selector_threshold ? 0 : -1;
}

int main(int argc, char** argv) {
    validate_args args;
    if (parse_args(argc, argv, &args) != 0) {
        fprintf(stderr,
                "usage: %s --kind strict-replay --bank PATH "
                "--bank-sha256 HEX --producer-manifest PATH "
                "--producer-manifest-sha256 HEX "
                "--training-contract PATH "
                "--training-contract-sha256 HEX --bytes N --records N "
                "--producer-engine-source-sha256 HEX "
                "--loader-engine-source-sha256 HEX "
                "--environment-source-sha256 HEX "
                "--contract-identity TEXT "
                "--selector-family FAMILY "
                "--selector-threshold N\n",
                argv[0]);
        return 2;
    }
    if (strcmp(args.kind, "strict-replay") != 0) {
        fprintf(stderr, "state-bank validation failed: %s\n",
                bbe_state_bank_error_name(
                    strcmp(args.kind, "authored-scenario") == 0
                        ? BBE_SB_REQUEST_AUTHORED_DISABLED
                        : BBE_SB_REQUEST_KIND_UNKNOWN));
        return 1;
    }
    if (!bbe_sha256_valid_hex(args.environment_source_sha256) ||
        strcmp(args.environment_source_sha256,
               PUFFER_ENV_SOURCE_HASH) != 0) {
        fprintf(stderr,
                "state-bank validation failed: "
                "environment source sha256 differs from the compiled "
                "validator source identity\n");
        return 1;
    }
    bbe_state_bank_selector_family selector_family;
    bbe_state_bank_error error = bbe_state_bank_selector_family_parse(
        args.selector_family, &selector_family);
    if (error != BBE_SB_OK ||
        args.selector_threshold >
            bbe_state_bank_selector_max_threshold(selector_family)) {
        if (error == BBE_SB_OK) error = BBE_SB_SELECTOR_THRESHOLD;
        fprintf(stderr, "state-bank validation failed: %s\n",
                bbe_state_bank_error_name(error));
        return 1;
    }
    bbe_state_bank_request request = {
        "bloodbowl-state-bank-training-contract-v1",
        "bloodbowl-state-bank-producer-v1",
        "bloodbowl-state-bank-authorization-v1",
        BBE_STATE_BANK_STRICT_REPLAY,
        "strict-replay",
        "BB2025",
        args.bank_sha256,
        args.producer_manifest_sha256,
        args.training_contract_sha256,
        args.producer_engine_source_sha256,
        args.loader_engine_source_sha256,
        args.bytes,
        args.records,
        1,
        sizeof(bb_match),
        bbe_state_fingerprint(),
        args.contract_identity,
        args.bank,
        args.producer_manifest,
        args.training_contract,
        0,
    };
    bbe_state_bank_candidate candidate;
    error = bbe_state_bank_load_candidate(&request, &candidate);
    if (error != BBE_SB_OK) {
        fprintf(stderr, "state-bank validation failed: %s\n",
                bbe_state_bank_error_name(error));
        return 1;
    }

    bbe_state_bank_stratum_descriptor descriptor;
    error = bbe_state_bank_candidate_stratum_descriptor(
        &candidate, selector_family, args.selector_threshold, &descriptor);
    if (error == BBE_SB_OK && descriptor.eligible_records == 0) {
        error = BBE_SB_SELECTOR_EMPTY;
    }
    if (error != BBE_SB_OK) {
        fprintf(stderr, "state-bank validation failed: %s\n",
                bbe_state_bank_error_name(error));
        bbe_state_bank_candidate_close(&candidate);
        return 1;
    }

    uint32_t source_min = UINT32_MAX, source_max = 0;
    uint32_t command_min = UINT32_MAX, command_max = 0;
    int legal_min = INT_MAX, legal_max = 0;
    for (size_t i = 0; i < candidate.count; i++) {
        const bbe_state_bank_meta* meta = &candidate.metadata[i];
        if (meta->source_id < source_min) source_min = meta->source_id;
        if (meta->source_id > source_max) source_max = meta->source_id;
        if (meta->command < command_min) command_min = meta->command;
        if (meta->command > command_max) command_max = meta->command;
        bb_action legal[BB_LEGAL_MAX];
        int count = bb_legal_actions(&candidate.matches[i], legal);
        if (count < legal_min) legal_min = count;
        if (count > legal_max) legal_max = count;
    }
    printf("{\"schema\":\"bloodbowl-state-bank-validation-v2\","
           "\"kind\":\"strict-replay\",\"kind_value\":1,"
           "\"bank_sha256\":\"%s\","
           "\"producer_manifest_sha256\":\"%s\","
           "\"training_contract_sha256\":\"%s\","
           "\"producer_engine_source_sha256\":\"%s\","
           "\"loader_engine_source_sha256\":\"%s\","
           "\"contract_identity\":\"%s\","
           "\"bytes\":%llu,\"records\":%llu,"
           "\"bbs_version\":1,\"match_size\":%u,"
           "\"engine_fingerprint\":%u,"
           "\"source_id_min\":%u,\"source_id_max\":%u,"
           "\"command_min\":%u,\"command_max\":%u,"
           "\"legal_actions_min\":%d,\"legal_actions_max\":%d,"
           "\"environment_source_sha256\":\"%s\","
           "\"strata_schema\":\"%s\","
           "\"strata_family\":\"%s\","
           "\"strata_threshold\":%u,"
           "\"strata_eligible_records\":%u,"
           "\"strata_sha256\":\"%s\"}\n",
           args.bank_sha256,
           args.producer_manifest_sha256,
           args.training_contract_sha256,
           args.producer_engine_source_sha256,
           args.loader_engine_source_sha256,
           args.contract_identity,
           (unsigned long long)args.bytes,
           (unsigned long long)candidate.count,
           (unsigned)sizeof(bb_match),
           (unsigned)bbe_state_fingerprint(),
           source_min, source_max, command_min, command_max,
           legal_min, legal_max,
           PUFFER_ENV_SOURCE_HASH,
           PUFFER_STATE_BANK_STRATA_SCHEMA,
           bbe_state_bank_selector_family_name(descriptor.family),
           descriptor.threshold,
           descriptor.eligible_records,
           descriptor.sha256);
    bbe_state_bank_candidate_close(&candidate);
    return 0;
}

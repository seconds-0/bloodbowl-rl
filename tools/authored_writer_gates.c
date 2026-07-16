#include "authored_identity_internal.h"

int ad_authored_fresh_admission_gate(const bb_match* match) {
    return bb_state_bank_boundary_valid(match);
}

int ad_authored_resumable_admission_gate(const bb_match* match) {
    return bb_state_bank_resumable_valid(match);
}

int ad_authored_continuation_gate(const bb_match* match,
                                  char error[AD_ERROR_CAP]) {
    return ad_verify_one_action_continuation(
        match, NULL, NULL, NULL, error);
}

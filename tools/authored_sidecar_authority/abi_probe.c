#include "authored_sidecar.h"

#include <stddef.h>

typedef int (*ad_sidecar_signature)(
    const ad_bbs_record*, size_t, const ad_recipe*, size_t,
    char*, size_t, size_t*, char*, size_t, size_t*, char[AD_ERROR_CAP]);

static ad_sidecar_signature const signature = ad_serialize_authored_sidecars;

_Static_assert(AD_AUTHORED_SIDECAR_SCHEMA_VERSION == 1u,
               "sidecar schema version differs");
_Static_assert(AD_AUTHORED_PROOF_BUNDLE_COUNT == 26,
               "proof count differs");
_Static_assert(AD_ERROR_CAP == 192, "error capacity differs");
_Static_assert(AD_AUTHORED_RECORDS_JSONL_LENGTH == 39460u,
               "records JSONL length differs");
_Static_assert(AD_AUTHORED_RECIPES_JSONL_LENGTH == 119389u,
               "recipes JSONL length differs");

int main(void) {
    return signature == NULL;
}

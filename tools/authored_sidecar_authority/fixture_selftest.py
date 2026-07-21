#!/usr/bin/env python3
"""Prove each frozen malicious source mutation is rejected for its reason."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from source_check import check_active_text, check_text, verify_candidate


def expect_rejected(label: str, callback, expected: str) -> None:
    try:
        callback()
    except RuntimeError as error:
        if expected not in str(error):
            raise RuntimeError(
                f"fixture {label} rejected for wrong reason: {error}"
            ) from error
    else:
        raise RuntimeError(f"malicious fixture accepted: {label}")


def compliant_source(oracle: dict[str, object]) -> str:
    keys = list(oracle["record_keys"]) + list(oracle["recipe_keys"])
    key_literals = ",".join(f'"{key}"' for key in keys)
    return f'''#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum {{ AD_SIDECAR_BBS_LENGTH = 58568 }};
static const char oracle_digest[] =
    "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1";
void ad_sidecar_sha256(void* bytes, size_t length, void* digest) {{
    (void)bytes; (void)length; (void)digest;
}}
int ad_sidecar_hash_actions(void* a, void* t, size_t n, void* digest) {{
    (void)a; (void)t; (void)n; (void)digest; return 0;
}}
int ad_sidecar_hash_dice(void* s, void* v, size_t n, void* digest) {{
    (void)s; (void)v; (void)n; (void)digest; return 0;
}}
int ad_sidecar_hash_legal(void* a, size_t n, void* digest) {{
    (void)a; (void)n; (void)digest; return 0;
}}
static int ad_sidecar_find_legal(void* match, int type, int arg, void* action) {{
    bb_action legal[BB_LEGAL_MAX];
    int count = bb_legal_actions(match, legal);
    for (int i = 0; i < count; i++) {{
        if (legal[i].type == type && legal[i].arg0 == arg) {{
            *(bb_action*)action = legal[i];
            return 1;
        }}
    }}
    return 0;
}}
int ad_sidecar_f5_end_activation_legal(void* match) {{
    bb_match probe = *(bb_match*)match;
    bb_rng rng;
    bb_action action;
    uint8_t die = 6;
    bb_rng_script(&rng, &die, 1);
    if (!ad_sidecar_find_legal(
            &probe, BB_A_ACTIVATE, probe.ball.carrier, &action)) return 0;
    if (bb_apply(&probe, action, &rng) != BB_STATUS_DECISION ||
        bb_rng_error(&rng)) return 0;
    if (rng.script_pos != 0) return 0;
    if (!ad_sidecar_find_legal(&probe, BB_A_DECLARE, BB_ACT_MOVE, &action))
        return 0;
    if (bb_apply(&probe, action, &rng) != BB_STATUS_DECISION ||
        bb_rng_error(&rng)) return 0;
    if (rng.script_pos != 0) return 0;
    return ad_sidecar_find_legal(
        &probe, BB_A_END_ACTIVATION, -1, &action);
}}
static int ad_sidecar_build_rows(void) {{
    const char* keys[] = {{{key_literals}}};
    const char* domains[] = {{"BBACT1","BBDIE1","BBLEG1"}};
    int f1 = ad_f1_pass_opportunity_valid();
    int f2 = ad_f2_handoff_target_count();
    int f4 = ad_f4_pending_dodge_reroll_valid();
    int f5 = bb_can_score_without_dice();
    int f5_end = ad_sidecar_f5_end_activation_legal();
    int marked = bb_is_marked();
    int legal_count = bb_legal_actions(match, legal_actions);
    int packed = bb_action_pack();
    int ha = ad_sidecar_hash_actions(
        recipe->actions, recipe->decision_teams, recipe->action_count,
        actions_digest);
    int hd = ad_sidecar_hash_dice(
        recipe->dice_sides, recipe->dice_values, recipe->dice_count,
        dice_digest);
    int hl = ad_sidecar_hash_legal(
        legal_actions, legal_count, legal_digest);
    return (int)(sizeof keys + sizeof domains + sizeof oracle_digest) +
        f1 + f2 + f4 + f5 + f5_end + marked + legal_count + packed + ha + hd +
        hl + actions_digest[0] + dice_digest[0] + legal_digest[0];
}}
static int ad_sidecar_checked_extent(void* p, size_t n, void* r) {{
    (void)p; (void)n; (void)r; return 0;
}}
static int ad_sidecar_ranges_overlap(void* a, void* b) {{
    (void)a; (void)b; return 0;
}}
int ad_sidecar_alias_contract(
    const void* records, size_t record_count,
    const void* recipes, size_t recipe_count,
    char* records_jsonl, size_t records_capacity, size_t* records_length,
    char* recipes_jsonl, size_t recipes_capacity, size_t* recipes_length,
    char* error) {{
    uintptr_t starts[7] = {{0}};
    uintptr_t ends[7] = {{UINTPTR_MAX}};
    size_t record_extent_count =
        record_count > AD_AUTHORED_PROOF_BUNDLE_COUNT
            ? record_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;
    size_t recipe_extent_count =
        recipe_count > AD_AUTHORED_PROOF_BUNDLE_COUNT
            ? recipe_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;
    if (record_extent_count > SIZE_MAX / sizeof *records ||
        recipe_extent_count > SIZE_MAX / sizeof *recipes) return -1;
    ad_sidecar_checked_extent(
        records, record_extent_count * sizeof *records, &starts[0]);
    ad_sidecar_checked_extent(
        recipes, recipe_extent_count * sizeof *recipes, &starts[1]);
    ad_sidecar_checked_extent(records_jsonl, records_capacity, &starts[2]);
    ad_sidecar_checked_extent(records_length, sizeof *records_length, &starts[3]);
    ad_sidecar_checked_extent(recipes_jsonl, recipes_capacity, &starts[4]);
    ad_sidecar_checked_extent(recipes_length, sizeof *recipes_length, &starts[5]);
    ad_sidecar_checked_extent(error, 192, &starts[6]);
    for (size_t left = 0; left < 7; left++)
        for (size_t right = left + 1; right < 7; right++)
            if (ad_sidecar_ranges_overlap(&starts[left], &ends[right])) return -1;
    return 0;
}}
int ad_sidecar_reconcile_bundle(void) {{
    return 0;
}}
static int ad_sidecar_stage_pair(void* records, size_t count, char* error) {{
    char* bbs = NULL;
    size_t bbs_length = 0;
    if (ad_build_authored_proof_bundle() != 0) return -1;
    if (ad_identify_authored_proof_bundle() != 0) return -1;
    if (ad_sidecar_reconcile_bundle() != 0) return -1;
    FILE* stream = open_memstream(&bbs, &bbs_length);
    if (stream == NULL) return -1;
    /* MUTATION */
    if (ad_bbs_write(stream, records, count, error) != 0) return -1;
    if (fflush(stream) != 0) return -1;
    if (fclose(stream) != 0) return -1;
    if (bbs_length != AD_SIDECAR_BBS_LENGTH) return -1;
    ad_sidecar_sha256(bbs, bbs_length, bbs_digest);
    if (memcmp(bbs_digest, AD_SIDECAR_BBS_SHA256, sizeof bbs_digest) != 0) return -1;
    free(bbs);
    return ad_sidecar_build_rows();
}}
int ad_serialize_authored_sidecars(
    void* records, size_t record_count, void* recipes, size_t recipe_count,
    char* records_jsonl, size_t records_capacity, size_t* records_length,
    char* recipes_jsonl, size_t recipes_capacity, size_t* recipes_length,
    char error[192]) {{
    /* PUBLIC_MUTATION */
    if (ad_sidecar_alias_contract(
            records, record_count, recipes, recipe_count,
            records_jsonl, records_capacity, records_length,
            recipes_jsonl, recipes_capacity, recipes_length, error) != 0)
        return -1;
    if (record_count != AD_AUTHORED_PROOF_BUNDLE_COUNT ||
        recipe_count != AD_AUTHORED_PROOF_BUNDLE_COUNT) return -1;
    if (records_capacity < AD_AUTHORED_RECORDS_JSONL_LENGTH ||
        recipes_capacity < AD_AUTHORED_RECIPES_JSONL_LENGTH) return -1;
    if (ad_sidecar_stage_pair(records, record_count, error) != 0) return -1;
    memcpy(records_jsonl, staged_records, staged_records_length);
    memcpy(recipes_jsonl, staged_recipes, staged_recipes_length);
    *records_length = staged_records_length;
    *recipes_length = staged_recipes_length;
    error[0] = '\\0';
    return 0;
}}
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("oracle", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    oracle = json.loads(args.oracle.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest["schema"] != "bloodbowl-authored-sidecar-malicious-fixtures-v1":
        raise RuntimeError("unknown malicious fixture schema")
    base = compliant_source(oracle)
    check_text(base, oracle)
    check_active_text(base)
    active_mutation = base.replace(
        "memcpy(records_jsonl", "macro_substitute(records_jsonl", 1)
    try:
        check_active_text(active_mutation)
    except RuntimeError as error:
        if "active public stage/commit calls differ" not in str(error):
            raise RuntimeError(
                f"active preprocessor fixture rejected for wrong reason: {error}"
            ) from error
    else:
        raise RuntimeError("active preprocessor substitution was accepted")

    explicit_mutations = (
        (
            "literal-comment-forbidden-call",
            base.replace(
                "/* MUTATION */",
                'const char* left = "/*"; system("ignored"); '
                'const char* right = "*/";', 1),
            "system",
        ),
        (
            "parenthesized-forbidden-call",
            base.replace("/* MUTATION */", '(fopen)("ignored", "w");', 1),
            "fopen",
        ),
        (
            "aliased-forbidden-call",
            base.replace(
                "/* MUTATION */",
                "FILE* (*operation)(const char*, const char*) = fopen; "
                "(void)operation;", 1),
            "fopen",
        ),
        (
            "consumed-f5-die",
            base.replace(
                "bb_rng_script(&rng, &die, 1);",
                "bb_rng_script(&rng, &die, 1); (void)bb_d6(&rng);", 1),
            "bb_d6",
        ),
        (
            "ignored-f5-and-hash-results",
            base.replace(
                "f1 + f2 + f4 + f5 + f5_end + marked + legal_count + packed + ha + hd +\n"
                "        hl + actions_digest[0] + dice_digest[0] + legal_digest[0];",
                "f1 + f2 + f4 + f5 + marked + legal_count + packed;", 1),
            "ignores",
        ),
        (
            "cast-hides-unconsumed-action-digest",
            base.replace(
                "recipe->actions, recipe->decision_teams, recipe->action_count,\n"
                "        actions_digest);",
                "recipe->actions, recipe->decision_teams,\n"
                "        (size_t)recipe->action_count, actions_digest);",
                1).replace(" + actions_digest[0]", "", 1),
            "row ignores framed digest: ad_sidecar_hash_actions",
        ),
        (
            "conditional-dynamic-extent-narrowing",
            base.replace(
                "size_t recipe_extent_count =\n"
                "        recipe_count > AD_AUTHORED_PROOF_BUNDLE_COUNT\n"
                "            ? recipe_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;",
                "size_t recipe_extent_count =\n"
                "        recipe_count > AD_AUTHORED_PROOF_BUNDLE_COUNT\n"
                "            ? recipe_count : AD_AUTHORED_PROOF_BUNDLE_COUNT;\n"
                "    if (record_count > AD_AUTHORED_PROOF_BUNDLE_COUNT &&\n"
                "            records_capacity > AD_AUTHORED_RECORDS_JSONL_LENGTH)\n"
                "        record_extent_count = AD_AUTHORED_PROOF_BUNDLE_COUNT;",
                1),
            "alias extent count is reassigned: record_extent_count",
        ),
    )
    for label, mutation, expected in explicit_mutations:
        expect_rejected(
            label, lambda mutation=mutation: check_text(mutation, oracle),
            expected)
        expect_rejected(
            f"active-{label}",
            lambda mutation=mutation: check_active_text(mutation), expected)

    alias_block = '''    if (ad_sidecar_alias_contract(
            records, record_count, recipes, recipe_count,
            records_jsonl, records_capacity, records_length,
            recipes_jsonl, recipes_capacity, recipes_length, error) != 0)
        return -1;
'''
    delayed_alias = base.replace(
        alias_block,
        "    int ad_sidecar_alias_contract_marker = 0;\n"
        "    (void)ad_sidecar_alias_contract_marker;\n", 1)
    delayed_alias = delayed_alias.replace(
        "        recipes_capacity < AD_AUTHORED_RECIPES_JSONL_LENGTH) return -1;",
        "        recipes_capacity < AD_AUTHORED_RECIPES_JSONL_LENGTH) "
        "return -1;\n" + alias_block.rstrip(), 1)
    expect_rejected(
        "delayed-real-alias-call",
        lambda: check_text(delayed_alias, oracle),
        "alias safety is not established before count/capacity checks")
    expect_rejected(
        "active-delayed-real-alias-call",
        lambda: check_active_text(delayed_alias),
        "active alias proof follows count/capacity handling")

    quoted_system = base.replace("#include <stdio.h>", '#include "stdio.h"', 1)
    expect_rejected(
        "quoted-system-header-shadow",
        lambda: check_text(quoted_system, oracle),
        "system include may be shadowed by quoted lookup")

    with tempfile.TemporaryDirectory(prefix="sidecar-ownership-selftest-") as raw:
        candidate = Path(raw)
        alternate = candidate / "tools" / "alternate_sidecar.c"
        alternate.parent.mkdir(parents=True)
        alternate.write_text(
            "typedef int result_code;\n"
            "result_code ad_serialize_authored_sidecars(void) { return 0; }\n",
            encoding="utf-8")
        expect_rejected(
            "out-of-path-typedef-return-serializer",
            lambda: verify_candidate(candidate, oracle),
            "serializer symbol occurs outside owned/authority paths")
    seen: set[str] = set()
    for fixture in manifest["fixtures"]:
        name = fixture["name"]
        if name in seen:
            raise RuntimeError(f"duplicate fixture name: {name}")
        seen.add(name)
        mutated = base
        if "delete_key" in fixture:
            token = f'"{fixture["delete_key"]}"'
            if token not in mutated:
                raise RuntimeError(f"fixture token absent: {name}")
            mutated = mutated.replace(token, "", 1)
        else:
            old = fixture["replace"]
            if old not in mutated:
                raise RuntimeError(f"fixture replacement absent: {name}")
            mutated = mutated.replace(old, fixture["with"], 1)
        expect_rejected(name, lambda: check_text(mutated, oracle),
                        fixture["expected"])
    print(f"sidecar malicious fixtures rejected: {len(seen) + 17}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

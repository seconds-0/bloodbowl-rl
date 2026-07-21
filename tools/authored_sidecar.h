// authored_sidecar.h — pure in-memory authored proof metadata serialization.
#ifndef AUTHORED_SIDECAR_H
#define AUTHORED_SIDECAR_H

#include "authored_drill.h"

#include <stddef.h>

#define AD_AUTHORED_SIDECAR_SCHEMA_VERSION 1u
#define AD_AUTHORED_RECORDS_JSONL_LENGTH 39460u
#define AD_AUTHORED_RECIPES_JSONL_LENGTH 119389u

// Serialize exactly one complete authored proof bundle into the paired
// revision-1 canonical JSONL streams. `records` and `recipes` may be permuted,
// but every record recipe pointer must refer into the supplied recipe array and
// the two arrays must describe the same complete immutable 26-recipe set.
// Output order is always the legacy A9 proof schedule.
//
// The byte outputs are length-delimited and are not NUL-terminated. Capacities
// may exceed the returned lengths. On success, only bytes [0, length) change;
// bytes at and beyond length remain untouched. On any failure, both output
// buffers and both returned lengths remain byte-for-byte unchanged.
//
// Inputs, complete supplied/fixed input extents, output capacity extents,
// returned-length objects, and error storage must be pairwise disjoint. Alias
// and checked-extent rejection precede every diagnostic write. All counts and
// capacities are element/byte counts, never inclusive maxima.
int ad_serialize_authored_sidecars(
    const ad_bbs_record* records, size_t record_count,
    const ad_recipe* recipes, size_t recipe_count,
    char* records_jsonl, size_t records_capacity, size_t* records_length,
    char* recipes_jsonl, size_t recipes_capacity, size_t* recipes_length,
    char error[AD_ERROR_CAP]);

#endif // AUTHORED_SIDECAR_H

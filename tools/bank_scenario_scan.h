#ifndef BANK_SCENARIO_SCAN_H
#define BANK_SCENARIO_SCAN_H

#include <stdint.h>
#include <stdio.h>

uint32_t bbs_scenario_local_fingerprint(void);

// Scan one seekable BBS1 stream into canonical JSONL. Neither stream is
// closed. On failure, *error points to a static diagnostic string.
int bbs_scan_stream(FILE* input, FILE* output, const char** error);

#endif

#ifndef BBE_TEST_SUPPORT_VECENV_H
#define BBE_TEST_SUPPORT_VECENV_H

#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const char* key;
    double value;
    void* ptr;
} DictItem;

typedef struct {
    DictItem* items;
    int size;
    int capacity;
} Dict;

static inline DictItem* dict_get_unsafe(Dict* dict, const char* key) {
    if (dict == NULL || key == NULL) return NULL;
    for (int i = 0; i < dict->size; i++) {
        if (dict->items[i].key != NULL &&
            strcmp(dict->items[i].key, key) == 0) {
            return &dict->items[i];
        }
    }
    return NULL;
}

static inline DictItem* dict_get(Dict* dict, const char* key) {
    DictItem* item = dict_get_unsafe(dict, key);
    if (item == NULL) {
        fprintf(stderr, "dict_get failed to find key: %s\n", key);
        abort();
    }
    return item;
}

static inline void dict_set(Dict* dict, const char* key, double value) {
    if (dict == NULL || dict->size < 0 || dict->size >= dict->capacity ||
        dict->items == NULL) {
        abort();
    }
    DictItem* existing = dict_get_unsafe(dict, key);
    if (existing != NULL) {
        existing->value = value;
        return;
    }
    dict->items[dict->size++] =
        (DictItem){.key = key, .value = value, .ptr = NULL};
}

typedef struct StaticVec {
    int agents_per_buffer;
    int* agent_perm;
    void* observations;
    float* actions;
    float* rewards;
    float* terminals;
    unsigned char* action_mask;
    unsigned int* joint_actions;
    int* joint_action_offsets;
    int* joint_action_counts;
    int* joint_buffer_counts;
} StaticVec;

static inline size_t obs_element_size(void) {
    return sizeof(unsigned char);
}

#endif

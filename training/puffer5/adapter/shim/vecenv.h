// 4.0 vecenv.h API shim for compiling the unmodified 4.0 puffer/bloodbowl/
// binding.c inside the PufferLib 5.0 adapter translation unit
// (bloodbowl5_env.c). It provides only what binding.c references: the
// StaticVec fields used by my_setup_perm / my_pack_joint_actions, the 4.0
// dict accessors (dict_get returning a DictItem*), and obs_element_size.
// The Dict type itself is 5.0's (src/ini.h), included before binding.c.
#pragma once

#include <stddef.h>
#include <stdint.h>

typedef struct StaticVec {
    uint8_t* observations;
    float* actions;
    float* rewards;
    float* terminals;
    unsigned char* action_mask;
    int* agent_perm;
    int agents_per_buffer;
    uint32_t* joint_actions;
    int* joint_action_offsets;
    int* joint_action_counts;
    int* joint_buffer_counts;
} StaticVec;

static inline DictItem* bbe4_dict_get_item(Dict* dict, const char* key) {
    DictItem* item = dict_find(dict, key);
    if (item == NULL) {
        fprintf(stderr, "bloodbowl5: missing kwarg %s\n", key);
        exit(1);
    }
    return item;
}

#define dict_get bbe4_dict_get_item
#define dict_get_unsafe dict_find

static inline size_t obs_element_size(void) {
    return 1;
}

#!/usr/bin/env python3
"""Build the immutable sidecar JSONL oracle from trusted binary facts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct


RECORD_KEYS = (
    "schema", "record_index", "source_kind", "bbs_source_id",
    "capture_decision_index", "identity_schema_version",
    "authored_source_id", "template_id", "template_key",
    "recipe_revision", "cell_id", "variant_id", "variant_seed_u64",
    "family", "boundary", "raw_match_sha256",
    "initialized_match_sha256", "actions_sha256", "dice_sha256",
    "legal_actions_count", "legal_actions_sha256", "half", "home_turn",
    "away_turn", "active_team", "decision_team", "home_score",
    "away_score", "kicking_team", "weather", "home_rerolls",
    "away_rerolls", "home_players_pitch", "away_players_pitch",
    "home_players_reserve", "away_players_reserve", "home_players_ko",
    "away_players_ko", "home_players_casualty",
    "away_players_casualty", "home_players_sent_off",
    "away_players_sent_off", "ball_state", "ball_carrier",
    "procedure_depth", "procedure_ids", "f1_carrier_pressure",
    "f2_handoff_targets", "f3_capture_turn", "f3_orientation",
    "f4_reroll_options", "f5_score_without_dice",
    "f5_end_activation_legal",
)

RECIPE_KEYS = (
    "schema", "record_index", "identity_schema_version",
    "authored_source_id", "template_id", "template_key",
    "recipe_revision", "cell_id", "variant_id", "variant_seed_u64",
    "procgen_seed_u64", "procgen_stream_u64", "game_seed_u64",
    "game_stream_u64", "controller_seed_u64", "controller_stream_u64",
    "recipe_kind", "capture_turn", "capture_active_team",
    "capture_handoff_target_bucket", "capture_pass_carrier_pressure",
    "home_team", "away_team", "exclude_team", "skillup_max_players",
    "skillup_max_each", "skillup_secondary_pct_bits",
    "initialized_match_sha256", "raw_match_sha256", "action_count",
    "actions", "decision_teams", "actions_sha256", "dice_count",
    "dice_sides", "dice_values", "dice_sha256",
)

TEAM_IDS = (
    "amazon", "black_orc", "bretonnian", "chaos_chosen", "chaos_dwarf",
    "chaos_renegades", "dark_elf", "dwarf", "elven_union", "gnome",
    "goblin", "halfling", "high_elf", "human", "imperial_nobility",
    "khorne", "lizardmen", "necromantic_horror", "norse", "nurgle",
    "ogre", "old_world_alliance", "orc", "shambling_undead", "skaven",
    "snotling", "tomb_kings", "underworld_denizens", "vampire",
    "wood_elf",
)

PROCEDURE_IDS = (
    "none", "match", "pregame", "setup", "kickoff", "team-turn",
    "activation", "move", "dodge", "rush", "pickup", "block", "push",
    "knockdown", "armour", "injury", "casualty", "pass", "catch",
    "scatter", "throw-in", "handoff", "foul", "ttm", "test",
    "touchdown", "turnover", "end-drive", "ko-recovery",
)


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, length: int) -> bytes:
        end = self.offset + length
        if length < 0 or end > len(self.data):
            raise ValueError("truncated fact corpus")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def action_preimage(actions: list[int], teams: list[int]) -> bytes:
    require(len(actions) == len(teams), "action vector lengths differ")
    return b"BBACT1\0" + u32(len(actions)) + b"".join(
        u32(action) + bytes((team,))
        for action, team in zip(actions, teams, strict=True)
    )


def dice_preimage(sides: list[int], values: list[int]) -> bytes:
    require(len(sides) == len(values), "dice vector lengths differ")
    return b"BBDIE1\0" + u32(len(sides)) + b"".join(
        bytes((side, value))
        for side, value in zip(sides, values, strict=True)
    )


def legal_preimage(actions: list[int]) -> bytes:
    require(actions == sorted(set(actions)), "legal vector is not sorted unique")
    return b"BBLEG1\0" + u32(len(actions)) + b"".join(map(u32, actions))


def compact_line(row: dict[str, object], keys: tuple[str, ...]) -> bytes:
    require(tuple(row) == keys, "canonical key order differs")
    encoded = json.dumps(
        row, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii") + b"\n"
    require(all(byte == 0x0A or 0x20 <= byte <= 0x7E for byte in encoded),
            "JSONL contains a noncanonical byte")
    return encoded


def hash_vector(preimage: bytes) -> dict[str, object]:
    return {
        "length": len(preimage),
        "preimage_hex": preimage.hex(),
        "sha256": digest(preimage),
    }


def parse_record(reader: Reader, match_size: int, expected_index: int) -> tuple[dict[str, object], dict[str, object]]:
    index = reader.u32()
    require(index == expected_index, "fact record order differs")
    bbs_source_id = reader.u32()
    decision_index = reader.u32()
    variant_seed = reader.u64()
    identity_schema = reader.u32()
    authored_source_id = reader.u32()
    template_id = reader.u32()
    recipe_revision = reader.u32()
    cell_id = reader.u32()
    variant_id = reader.u32()
    key_length = reader.u32()
    template_key = reader.take(key_length).decode("ascii")

    procgen_seed = reader.u64()
    procgen_stream = reader.u64()
    game_seed = reader.u64()
    game_stream = reader.u64()
    controller_seed = reader.u64()
    controller_stream = reader.u64()
    recipe_kind = reader.i32()
    capture_turn = reader.i32()
    capture_active_team = reader.i32()
    handoff_bucket = reader.i32()
    pass_pressure = reader.i32()
    home_team = reader.i32()
    away_team = reader.i32()
    exclude_team = reader.i32()
    skillup_max_players = reader.i32()
    skillup_max_each = reader.i32()
    secondary_bits = reader.u32()

    initialized = reader.take(match_size)
    captured = reader.take(match_size)
    action_count = reader.u32()
    actions: list[int] = []
    decision_teams: list[int] = []
    for _ in range(action_count):
        actions.append(reader.u32())
        decision_teams.append(reader.u8())
    dice_count = reader.u32()
    dice_sides: list[int] = []
    dice_values: list[int] = []
    for _ in range(dice_count):
        dice_sides.append(reader.u8())
        dice_values.append(reader.u8())
    legal_count = reader.u32()
    legal_actions = [reader.u32() for _ in range(legal_count)]
    locations = [[reader.u32() for _ in range(6)] for _ in range(2)]
    half = reader.u32()
    turns = [reader.u32(), reader.u32()]
    active_team = reader.u32()
    decision_team = reader.u32()
    scores = [reader.u32(), reader.u32()]
    kicking_team = reader.u32()
    weather = reader.u32()
    rerolls = [reader.u32(), reader.u32()]
    ball_state = reader.u32()
    ball_carrier = reader.i32()
    procedure_depth = reader.u32()
    procedure_ids = [reader.u32() for _ in range(procedure_depth)]
    family_id = reader.u32()
    f1_pressure = reader.u32()
    f2_target_count = reader.u32()
    f3_turn = reader.u32()
    f3_orientation = reader.u32()
    f4_mask = reader.u32()
    f5_score = reader.u32()
    f5_end = reader.u32()

    require(identity_schema == 1 and recipe_revision == 1,
            "identity version differs")
    require(bbs_source_id == 0xA9000000 + index,
            "legacy source ID differs")
    require(decision_index == action_count and action_count < 8192,
            "capture action count differs")
    require(dice_count <= 8192, "dice count exceeds authority")
    require(all(team in (0, 1) for team in decision_teams),
            "decision team differs")
    require(all(1 <= side <= 255 and 1 <= value <= side
                for side, value in zip(dice_sides, dice_values, strict=True)),
            "dice domain differs")
    require(1 <= legal_count <= 4096, "legal count differs")
    require(half in (1, 2) and active_team in (0, 1) and
            decision_team in (0, 1) and kicking_team in (0, 1),
            "captured scalar domain differs")
    require(weather in range(5), "weather differs")
    require(all(sum(team_locations) == 16 for team_locations in locations),
            "player location counts differ")
    require(procedure_ids in ([1, 5], [1, 5, 6, 7, 24]),
            "procedure shape differs")

    actions_hash = digest(action_preimage(actions, decision_teams))
    dice_hash = digest(dice_preimage(dice_sides, dice_values))
    legal_hash = digest(legal_preimage(legal_actions))
    initialized_hash = digest(initialized)
    captured_hash = digest(captured)
    family = {1: "f1", 2: "f2", 3: "f3", 4: "f4", 5: "f5"}[family_id]
    ball_token = {
        0: "off-pitch", 1: "ground", 2: "held", 3: "in-air"
    }[ball_state]
    require((ball_token == "held") == (0 <= ball_carrier < 32),
            "ball carrier representation differs")
    f4_options = [
        name for bit, name in enumerate(("decline", "dodge", "pro", "team"))
        if f4_mask & (1 << bit)
    ]
    require(f4_mask & ~0xF == 0, "unknown F4 option bit")

    record = {
        "schema": "bloodbowl-authored-record-v1",
        "record_index": index,
        "source_kind": "authored",
        "bbs_source_id": bbs_source_id,
        "capture_decision_index": decision_index,
        "identity_schema_version": identity_schema,
        "authored_source_id": authored_source_id,
        "template_id": template_id,
        "template_key": template_key,
        "recipe_revision": recipe_revision,
        "cell_id": cell_id,
        "variant_id": variant_id,
        "variant_seed_u64": f"{variant_seed:016x}",
        "family": family,
        "boundary": "pending-dodge-reroll" if family == "f4" else "fresh-team-turn",
        "raw_match_sha256": captured_hash,
        "initialized_match_sha256": initialized_hash,
        "actions_sha256": actions_hash,
        "dice_sha256": dice_hash,
        "legal_actions_count": legal_count,
        "legal_actions_sha256": legal_hash,
        "half": half,
        "home_turn": turns[0],
        "away_turn": turns[1],
        "active_team": active_team,
        "decision_team": decision_team,
        "home_score": scores[0],
        "away_score": scores[1],
        "kicking_team": kicking_team,
        "weather": weather,
        "home_rerolls": rerolls[0],
        "away_rerolls": rerolls[1],
        "home_players_pitch": locations[0][0],
        "away_players_pitch": locations[1][0],
        "home_players_reserve": locations[0][1],
        "away_players_reserve": locations[1][1],
        "home_players_ko": locations[0][2],
        "away_players_ko": locations[1][2],
        "home_players_casualty": locations[0][3],
        "away_players_casualty": locations[1][3],
        "home_players_sent_off": locations[0][4],
        "away_players_sent_off": locations[1][4],
        "ball_state": ball_token,
        "ball_carrier": ball_carrier,
        "procedure_depth": procedure_depth,
        "procedure_ids": procedure_ids,
        "f1_carrier_pressure": {0: "none", 1: "open", 2: "marked"}[f1_pressure],
        "f2_handoff_targets": "none" if f2_target_count == 0 else
            "one" if f2_target_count == 1 else "two-or-more",
        "f3_capture_turn": f3_turn,
        "f3_orientation": {0: "none", 1: "home", 2: "away"}[f3_orientation],
        "f4_reroll_options": f4_options,
        "f5_score_without_dice": bool(f5_score),
        "f5_end_activation_legal": bool(f5_end),
    }
    require((family == "f1") == (f1_pressure in (1, 2)), "F1 inactivity differs")
    require((family == "f2") == (f2_target_count > 0), "F2 inactivity differs")
    require((family == "f3") == (f3_turn in range(1, 9)), "F3 inactivity differs")
    require((family == "f4") == bool(f4_options), "F4 inactivity differs")
    require((family == "f5") == (f5_score == 1 and f5_end == 1),
            "F5 inactivity differs")

    recipe = {
        "schema": "bloodbowl-authored-recipe-v1",
        "record_index": index,
        "identity_schema_version": identity_schema,
        "authored_source_id": authored_source_id,
        "template_id": template_id,
        "template_key": template_key,
        "recipe_revision": recipe_revision,
        "cell_id": cell_id,
        "variant_id": variant_id,
        "variant_seed_u64": f"{variant_seed:016x}",
        "procgen_seed_u64": f"{procgen_seed:016x}",
        "procgen_stream_u64": f"{procgen_stream:016x}",
        "game_seed_u64": f"{game_seed:016x}",
        "game_stream_u64": f"{game_stream:016x}",
        "controller_seed_u64": f"{controller_seed:016x}",
        "controller_stream_u64": f"{controller_stream:016x}",
        "recipe_kind": recipe_kind,
        "capture_turn": capture_turn,
        "capture_active_team": capture_active_team,
        "capture_handoff_target_bucket": handoff_bucket,
        "capture_pass_carrier_pressure": pass_pressure,
        "home_team": home_team,
        "away_team": away_team,
        "exclude_team": exclude_team,
        "skillup_max_players": skillup_max_players,
        "skillup_max_each": skillup_max_each,
        "skillup_secondary_pct_bits": f"{secondary_bits:08x}",
        "initialized_match_sha256": initialized_hash,
        "raw_match_sha256": captured_hash,
        "action_count": action_count,
        "actions": actions,
        "decision_teams": decision_teams,
        "actions_sha256": actions_hash,
        "dice_count": dice_count,
        "dice_sides": dice_sides,
        "dice_values": dice_values,
        "dice_sha256": dice_hash,
    }
    return record, recipe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("facts", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    fact_bytes = args.facts.read_bytes()
    reader = Reader(fact_bytes)
    require(reader.take(8) == b"ADSFACT1", "fact magic differs")
    version = reader.u32()
    count = reader.u32()
    layout = {
        "bb_match": reader.u32(),
        "ad_recipe": reader.u32(),
        "ad_bbs_record": reader.u32(),
        "ad_authored_identity": reader.u32(),
        "bb_team_count": reader.u32(),
        "bb_skill_count": reader.u32(),
        "bb_action_type_count": reader.u32(),
        "bb_proc_count": reader.u32(),
        "bb_legal_max": reader.u32(),
        "ad_max_actions": reader.u32(),
        "ad_max_dice": reader.u32(),
        "ad_error_cap": reader.u32(),
    }
    require(version == 1 and count == 26, "fact header differs")
    require(layout["bb_match"] == 2240 and layout["bb_team_count"] == 30 and
            layout["bb_proc_count"] == 29 and layout["bb_legal_max"] == 4096 and
            layout["ad_max_actions"] == 8192 and layout["ad_max_dice"] == 8192 and
            layout["ad_error_cap"] == 192,
            "frozen layout differs")
    bbs_length = reader.u32()
    bbs = reader.take(bbs_length)
    require(bbs_length == 58568, "BBS returned length differs")
    require(digest(bbs) == "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1",
            "BBS digest differs")
    team_ids = tuple(
        reader.take(reader.u32()).decode("ascii")
        for _ in range(layout["bb_team_count"])
    )
    require(team_ids == TEAM_IDS, "generated team ID catalogue differs")

    records: list[dict[str, object]] = []
    recipes: list[dict[str, object]] = []
    for index in range(count):
        record, recipe = parse_record(reader, layout["bb_match"], index)
        records.append(record)
        recipes.append(recipe)
    require(reader.offset == len(reader.data), "trailing fact bytes")

    records_bytes = b"".join(compact_line(row, RECORD_KEYS) for row in records)
    recipes_bytes = b"".join(compact_line(row, RECIPE_KEYS) for row in recipes)
    require(records_bytes.count(b"\n") == count and
            recipes_bytes.count(b"\n") == count,
            "JSONL line count differs")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "records.jsonl").write_bytes(records_bytes)
    (args.output / "recipes.jsonl").write_bytes(recipes_bytes)

    vector_sets = {
        "actions": [
            action_preimage([], []),
            action_preimage([0x01020304], [1]),
            action_preimage([0, 0xFFFFFFFF, 0x78563412], [0, 1, 0]),
        ],
        "dice": [
            dice_preimage([], []),
            dice_preimage([6], [4]),
            dice_preimage([2, 6, 8], [1, 6, 3]),
        ],
        "legal": [
            legal_preimage([]),
            legal_preimage([0x01020304]),
            legal_preimage([0, 0x78563412, 0xFFFFFFFF]),
        ],
    }
    oracle = {
        "schema": "bloodbowl-authored-sidecar-authority-v1",
        "authority_version": 1,
        "production_header": "tools/authored_sidecar.h",
        "production_source": "tools/authored_sidecar.c",
        "production_symbol": "ad_serialize_authored_sidecars",
        "feature_test_macro": "_POSIX_C_SOURCE=200809L",
        "record_count": count,
        "fact_corpus": {
            "length": len(fact_bytes),
            "sha256": digest(fact_bytes),
        },
        "record_keys": list(RECORD_KEYS),
        "recipe_keys": list(RECIPE_KEYS),
        "layout": layout,
        "team_ids": list(team_ids),
        "procedure_ids": list(PROCEDURE_IDS),
        "enum_mappings": {
            "ball_state": ["off-pitch", "ground", "held", "in-air"],
            "recipe_kind": [
                "first-team-turn", "legacy-F3", "legacy-F1", "legacy-F2",
                "F5", "F4", "exact-F3", "exact-F2", "exact-F1",
            ],
            "f1_pressure": ["none", "open", "marked"],
            "f2_bucket": ["none", "exactly-one", "two-or-more"],
            "f4_options": ["decline", "dodge", "pro", "team"],
        },
        "bbs_open_memstream": {
            "returned_length": bbs_length,
            "returned_sha256": digest(bbs),
            "embedded_nul_count": bbs.count(b"\0"),
            "first_embedded_nul_offset": bbs.index(b"\0"),
            "convenience_nul_excluded": True,
        },
        "outputs": {
            "records.jsonl": {
                "length": len(records_bytes),
                "sha256": digest(records_bytes),
                "line_count": count,
            },
            "recipes.jsonl": {
                "length": len(recipes_bytes),
                "sha256": digest(recipes_bytes),
                "line_count": count,
            },
        },
        "nist_sha256": {
            "empty": digest(b""),
            "abc": digest(b"abc"),
            "million_a": hashlib.sha256(b"a" * 1_000_000).hexdigest(),
        },
        "framed_hash_vectors": {
            name: [hash_vector(preimage) for preimage in preimages]
            for name, preimages in vector_sets.items()
        },
        "abi": {
            "return_type": "int",
            "fixed_output_lengths": {
                "AD_AUTHORED_RECORDS_JSONL_LENGTH": len(records_bytes),
                "AD_AUTHORED_RECIPES_JSONL_LENGTH": len(recipes_bytes),
            },
            "parameters": [
                ["records", "const ad_bbs_record*"],
                ["record_count", "size_t"],
                ["recipes", "const ad_recipe*"],
                ["recipe_count", "size_t"],
                ["records_jsonl", "char*"],
                ["records_capacity", "size_t"],
                ["records_length", "size_t*"],
                ["recipes_jsonl", "char*"],
                ["recipes_capacity", "size_t"],
                ["recipes_length", "size_t*"],
                ["error", "char[AD_ERROR_CAP]"],
            ],
            "count_semantics": "exactly-26-elements",
            "capacity_semantics": "byte-count-not-inclusive",
            "output_termination": "length-delimited-no-NUL",
            "failure_atomicity": "both-buffers-and-both-lengths-unchanged",
            "alias_contract": "all-complete-extents-pairwise-disjoint",
        },
        "authority_files": {},
    }
    (args.output / "oracle.unsealed.json").write_text(
        json.dumps(oracle, indent=2) + "\n", encoding="ascii"
    )
    print(json.dumps({"outputs": oracle["outputs"], "layout": layout}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

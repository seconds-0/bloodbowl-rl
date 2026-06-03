#!/usr/bin/env python3
"""Stage FFB/FUMBBL client art for the raylib spectator.

Copies the needed subset of vendor/ffb's bundled icon resources into
vendor/PufferLib/resources/bloodbowl/ (the renderer's cwd-relative default)
and writes iconmap.txt mapping our (team_id, position_id) -> iconset file.

Mapping: slug normalization + mechanical fuzz rules + a curated alias table
(BB2025 renamed several BB2020/LRB6 positions). Exits 1 if any of the 159
positions fails to map — fix the table, never ship a partial map silently.

Run via the PufferLib venv (needs PyYAML):
  vendor/PufferLib/.venv/bin/python tools/stage_spectator_art.py
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FFB_ICONS = ROOT / "vendor/ffb/ffb-resources/src/main/resources/icons"
ICONSETS = FFB_ICONS / "cached/players/iconsets"
OUT = ROOT / "vendor/PufferLib/resources/bloodbowl"

# Curated aliases for positions whose BB2025 display names don't mechanically
# match FUMBBL's BB2020/LRB6 iconset filenames. Key: (team_slug, pos_slug).
# Role-matched by hand (BB2025 renamed these positions; art chosen by role).
ALIASES = {
    # BB2025 Amazons: Eagle = linewoman, Python = thrower (FUMBBL's older set
    # used "eagle warrior" for its thrower art), Piranha = blitzer.
    ("amazon", "eaglewarrior"): "amazon_triballinewoman",
    ("amazon", "pythonwarrior"): "amazon_eaglewarriorthrower",
    ("amazon", "piranhawarrior"): "amazon_piranhawarriorblitzer",
    ("bretonnian", "bretonniansquire"): "bretonnian_linemen",
    ("bretonnian", "bretonnianknightcatcher"): "bretonnian_yeomen",
    ("bretonnian", "bretonnianknightthrower"): "bretonnian_yeomen",
    ("bretonnian", "grailknight"): "bretonnian_blitzers",
    ("chaoschosen", "beastmanlineman"): "chaoschosen_beastmanrunner",
    ("chaoschosen", "chaoschosen"): "chaoschosen_chosenblocker",
    ("chaosrenegade", "renegadehuman"): "chaosrenegade_renegadehumanlineman",
    ("dwarf", "dwarflineman"): "dwarf_blocker",
    ("highelf", "phoenixwarrior"): "highelf_thrower",
    ("highelf", "dragonprince"): "highelf_blitzer",
    ("highelf", "whitelion"): "highelf_catcher",
    ("lizardmen", "skinklineman"): "lizardmen_skinkrunner",
    ("norse", "norseraider"): "norse_lineman",
    ("norse", "ulfwerener"): "norse_ulfwerenar",
    ("norse", "yhetee"): "norse_snowtroll",
    ("oldworldalliance", "dwarflineman"): "oldworldalliance_dwarfblocker",
    ("skaven", "skavenclanrat"): "skaven_lineman",
    ("tombkings", "tombkingsthrower"): "tombkings_anointedthrower",
    ("tombkings", "tombkingsblitzer"): "tombkings_anointedblitzer",
    ("underworlddenizens", "snotlinglineman"): "underworlddenizens_underworldsnotlings",
    ("underworlddenizens", "skavenclanrat"): "underworlddenizens_skavenlineman",
}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


TEAM_ALIASES = {"chaosrenegades": "chaosrenegade"}


def team_slug(display: str) -> str:
    t = slug(display)
    return TEAM_ALIASES.get(t, t)


def resolve(tslug: str, pos_display: str, files: set) -> str | None:
    """Return iconset filename (sans .png) for this team slug + position."""
    pslug = slug(pos_display)
    if (tslug, pslug) in ALIASES:
        cand = ALIASES[(tslug, pslug)]
        return cand if cand in files else None

    # Mechanical candidates, in confidence order.
    words = re.findall(r"[A-Za-z0-9]+", pos_display)
    cands = [f"{tslug}_{pslug}"]
    for i in range(1, len(words)):  # strip leading words: "Human Lineman" -> lineman
        cands.append(f"{tslug}_{slug(''.join(words[i:]))}")
    for c in cands:
        if c in files:
            return c

    # Scoped containment: unique team file whose position key contains (or is
    # contained by) ours — catches "Troll" -> chaoschosen_chaostroll etc.
    team_files = [f for f in files if f.startswith(tslug + "_")]
    contains = [f for f in team_files if pslug in f[len(tslug) + 1:] or f[len(tslug) + 1:] in pslug]
    if len(contains) == 1:
        return contains[0]
    return None


def main() -> int:
    teams = (
        yaml.safe_load(open(ROOT / "engine/data/spec/teams_a.yaml"))["teams"]
        + yaml.safe_load(open(ROOT / "engine/data/spec/teams_b.yaml"))["teams"]
    )
    files = {p.stem for p in ICONSETS.glob("*.png")}

    rows, missing = [], []
    for ti, t in enumerate(teams):
        ts = team_slug(t["display"])
        for pi, p in enumerate(t["positions"]):
            m = resolve(ts, p["display"], files)
            if m is None:
                missing.append((ti, t["display"], pi, p["display"], ts))
            else:
                rows.append((ti, pi, m))

    if missing:
        print(f"UNMAPPED ({len(missing)}):")
        for ti, td, pi, pd, ts in missing:
            tf = sorted(f[len(ts) + 1:] for f in files if f.startswith(ts + "_"))
            print(f"  team {ti} ({td}) pos {pi} ({pd})  [team files: {', '.join(tf)}]")
        return 1

    # Stage art.
    icons_out = OUT / "iconsets"
    icons_out.mkdir(parents=True, exist_ok=True)
    needed = {m for _, _, m in rows}
    for m in needed:
        shutil.copy2(ICONSETS / f"{m}.png", icons_out / f"{m}.png")
    for rel in [
        "game/sball_30x30.png",
        "decorations/holdball.png",
        "decorations/prone.gif",
        "decorations/stunned.gif",
        "players/normalHome.png",
        "players/normalAway.png",
        "players/largeHome.png",
        "players/largeAway.png",
        "players/smallHome.png",
        "players/smallAway.png",
    ]:
        dst = OUT / Path(rel).name
        shutil.copy2(FFB_ICONS / rel, dst)
    with zipfile.ZipFile(FFB_ICONS / "cached/pitches/default.zip") as z:
        (OUT / "pitch.png").write_bytes(z.read("nice.png"))

    with open(OUT / "iconmap.txt", "w") as f:
        for ti, pi, m in rows:
            f.write(f"{ti} {pi} iconsets/{m}.png\n")

    print(f"mapped {len(rows)}/{len(rows) + len(missing)} positions; "
          f"staged {len(needed)} iconsets -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

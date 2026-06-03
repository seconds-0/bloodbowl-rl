#!/usr/bin/env python3
"""fetch_replays.py — polite, resumable FUMBBL match/replay fetcher.

Validation layer 7 needs real FUMBBL games. This fetcher follows the etiquette
rules in .claude/skills/fumbbl-data (FUMBBL is a volunteer-run hobby server):

  * >= 1.1 s between network requests (cache hits never hit the network)
  * exponential backoff on 429/5xx/connection errors
  * descriptive User-Agent with a contact address
  * JSON API only, never HTML scraping (web pages sit behind Anubis anti-bot)
  * everything cached forever in validation/replay_cache/ (replays are
    immutable once uploaded)

Discovery route (all documented endpoints):

  1. GET /api/match/current
       -> in-progress matches. NOTE (verified live 2026-06-03): the `id`
       field here is a GAME id (~1.9M range), NOT a match id (~4.5M range).
       We only use it for the `teams[].id` values of Competitive-division
       games currently being played.
  2. GET /api/team/matches/<teamId>
       -> that team's 25 most recent matches (newest first; paginate with
       lastBatch[24]['id']-1). Entries carry the full match-summary shape
       (id, replayId, division, conceded, ...).
  3. GET /api/match/get/<matchId>     -> curation metadata (cached)
  4. GET /api/replay/get/<replayId>/gz -> gzipped replay JSON (cached)

Curation filter (skill section 5): division == "Competitive",
conceded == "None", replayId present.

Usage:
  python3 validation/fetch_replays.py --count 30          # discover + fetch
  python3 validation/fetch_replays.py --match-ids 4585231 4585119
  python3 validation/fetch_replays.py --status            # manifest summary

Cache layout (validation/replay_cache/):
  match_<matchId>.json        match summary JSON
  replay_<replayId>.json.gz   replay, kept gzipped on disk
  team_matches_<teamId>.json  discovery page (refetch with --refresh-discovery)
  manifest.json               curated index of everything fetched
"""

import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "https://fumbbl.com/api"
USER_AGENT = "bloodbowl-rl-research/0.1 (alexander.t.huth@gmail.com)"
THROTTLE_SECONDS = 1.1
MAX_RETRIES = 5
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replay_cache")
MANIFEST_PATH = os.path.join(CACHE_DIR, "manifest.json")

_last_request_time = 0.0


def _throttle():
    global _last_request_time
    wait = THROTTLE_SECONDS - (time.monotonic() - _last_request_time)
    if wait > 0:
        time.sleep(wait)
    _last_request_time = time.monotonic()


def _http_get(path, binary=False):
    """GET BASE_URL+path with throttle + exponential backoff.

    Returns bytes (binary=True) or parsed JSON. Returns None on 404 or on a
    body that is not JSON when JSON was expected (FUMBBL returns 200 + 'null'
    or an HTML error page for some bad ids).
    """
    url = BASE_URL + path
    for attempt in range(MAX_RETRIES):
        _throttle()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if binary:
                return data
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504):
                delay = 2.0 * (2 ** attempt)
                print(f"  HTTP {e.code} on {path}; backing off {delay:.0f}s "
                      f"(attempt {attempt + 1}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(delay)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            delay = 2.0 * (2 ** attempt)
            print(f"  {type(e).__name__} on {path}; backing off {delay:.0f}s "
                  f"(attempt {attempt + 1}/{MAX_RETRIES})", file=sys.stderr)
            time.sleep(delay)
    print(f"  giving up on {path} after {MAX_RETRIES} attempts", file=sys.stderr)
    return None


# --- cache helpers -----------------------------------------------------------

def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        return _read_json(MANIFEST_PATH)
    return {}


def save_manifest(manifest):
    _write_json(MANIFEST_PATH, manifest)


# --- fetchers (cache-first) --------------------------------------------------

def fetch_match(match_id):
    """Match summary JSON, cached forever."""
    path = _cache_path(f"match_{match_id}.json")
    if os.path.exists(path):
        return _read_json(path)
    match = _http_get(f"/match/get/{match_id}")
    if match is None or not isinstance(match, dict) or "id" not in match:
        return None
    _write_json(path, match)
    return match


def fetch_replay_gz(replay_id):
    """Download the gzipped replay; keep it gzipped on disk. Returns path."""
    path = _cache_path(f"replay_{replay_id}.json.gz")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    data = _http_get(f"/replay/get/{replay_id}/gz", binary=True)
    if data is None or len(data) < 100:
        return None
    # Sanity: must be gzip (magic 1f 8b) and decompress to JSON-looking bytes.
    if data[:2] != b"\x1f\x8b":
        print(f"  replay {replay_id}: response is not gzip, skipping",
              file=sys.stderr)
        return None
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        with gzip.open(tmp, "rb") as f:
            head = f.read(64)
        if not head.lstrip().startswith(b"{"):
            raise ValueError("decompressed payload is not a JSON object")
    except Exception as e:
        print(f"  replay {replay_id}: bad gz payload ({e}), skipping",
              file=sys.stderr)
        os.unlink(tmp)
        return None
    os.replace(tmp, path)
    return path


def fetch_team_matches(team_id, refresh=False):
    """First page (25 newest matches) of a team's match history."""
    path = _cache_path(f"team_matches_{team_id}.json")
    if os.path.exists(path) and not refresh:
        return _read_json(path)
    matches = _http_get(f"/team/matches/{team_id}")
    if matches is None or not isinstance(matches, list):
        return []
    _write_json(path, matches)
    return matches


# --- discovery ---------------------------------------------------------------

def discover_competitive_match_ids(want, refresh=False, max_teams=12):
    """Collect recent Competitive-division match ids, newest first.

    /api/match/current -> team ids playing Competitive right now ->
    /api/team/matches/<teamId> -> recent finished matches.
    """
    print("discovery: GET /match/current ...")
    current = _http_get("/match/current")
    if not isinstance(current, list):
        print("  /match/current unavailable; cannot discover", file=sys.stderr)
        return []
    team_ids = []
    for game in current:
        if game.get("division") != "Competitive":
            continue
        for team in game.get("teams", []):
            tid = team.get("id")
            if tid and tid not in team_ids:
                team_ids.append(tid)
    print(f"  {len(current)} games in progress; "
          f"{len(team_ids)} Competitive team ids")

    candidates = {}
    for tid in team_ids[:max_teams]:
        page = fetch_team_matches(tid, refresh=refresh)
        kept = 0
        for entry in page:
            mid = entry.get("id")
            if not mid:
                continue
            # Filter on the cheap summary before fetching anything else.
            if entry.get("division") not in (None, "Competitive"):
                continue
            if entry.get("conceded") not in (None, "None"):
                continue
            candidates[mid] = entry
            kept += 1
        print(f"  team {tid}: {len(page)} matches, {kept} candidates")
        if len(candidates) >= want * 4:  # plenty of headroom for later filters
            break
    return sorted(candidates.keys(), reverse=True)


# --- curation + main flow ----------------------------------------------------

def curate_and_fetch(match_id, manifest):
    """Fetch match metadata, apply curation filter, fetch replay.

    Returns "added", "cached", or a skip-reason string.
    """
    key = str(match_id)
    if key in manifest:
        rid = manifest[key]["replayId"]
        if os.path.exists(_cache_path(f"replay_{rid}.json.gz")):
            return "cached"
    match = fetch_match(match_id)
    if match is None:
        return "no match JSON"
    if match.get("division") != "Competitive":
        return f"division={match.get('division')!r}"
    if match.get("conceded") not in (None, "None"):
        return f"conceded={match.get('conceded')!r}"
    replay_id = match.get("replayId")
    if not replay_id:
        return "no replayId"
    gz_path = fetch_replay_gz(replay_id)
    if gz_path is None:
        return "replay download failed"

    def team_info(t):
        rating = (t.get("coach", {}).get("rating", {}) or {}).get("pre", {}) or {}
        return {
            "id": t.get("id"),
            "name": t.get("name"),
            "race": (t.get("roster") or {}).get("name"),
            "coach": (t.get("coach") or {}).get("name"),
            "cr": rating.get("cr"),
            "r": rating.get("r"),          # optional on older matches
            "bracket": rating.get("bracket"),
            "teamValue": t.get("teamValue"),
            "score": t.get("score"),
        }

    manifest[key] = {
        "matchId": match_id,
        "replayId": replay_id,
        "division": match.get("division"),
        "divisionId": match.get("divisionId"),
        "tournamentId": match.get("tournamentId"),
        "conceded": match.get("conceded"),
        "date": match.get("date"),
        "time": match.get("time"),
        "team1": team_info(match.get("team1", {})),
        "team2": team_info(match.get("team2", {})),
        "replay_file": os.path.basename(gz_path),
    }
    save_manifest(manifest)
    return "added"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", type=int, default=30,
                    help="target number of curated replays in the cache")
    ap.add_argument("--match-ids", type=int, nargs="*", default=None,
                    help="fetch these specific match ids (skips discovery)")
    ap.add_argument("--refresh-discovery", action="store_true",
                    help="refetch team-match pages (they go stale, replays don't)")
    ap.add_argument("--status", action="store_true",
                    help="print manifest summary and exit")
    args = ap.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    manifest = load_manifest()

    if args.status:
        print(f"{len(manifest)} curated replays in {CACHE_DIR}")
        for key in sorted(manifest, key=int, reverse=True):
            e = manifest[key]
            print(f"  match {e['matchId']}  replay {e['replayId']}  "
                  f"{e['date']}  {e['team1']['race']} {e['team1']['score']}-"
                  f"{e['team2']['score']} {e['team2']['race']}  "
                  f"({e['team1']['bracket']}/{e['team2']['bracket']})")
        return 0

    if args.match_ids:
        ids = args.match_ids
    else:
        have = len(manifest)
        if have >= args.count:
            print(f"cache already has {have} >= {args.count} replays; nothing to do "
                  f"(use --count to raise the target)")
            return 0
        ids = discover_competitive_match_ids(args.count - have,
                                             refresh=args.refresh_discovery)
        if not ids:
            print("discovery produced no candidates", file=sys.stderr)
            return 1

    added = skipped = 0
    for mid in ids:
        if not args.match_ids and len(manifest) >= args.count:
            break
        result = curate_and_fetch(mid, manifest)
        if result in ("added", "cached"):
            added += result == "added"
            print(f"match {mid}: {result} (replay {manifest[str(mid)]['replayId']})")
        else:
            skipped += 1
            print(f"match {mid}: skipped ({result})")

    print(f"\ndone: {added} new, {skipped} skipped, "
          f"{len(manifest)} total curated replays in cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Scripted stand-ins for the human seat.

They only see the JSON API (payloads round-trip through json), which is what
proves a browser client can drive every decision the engine presents.
"""
from __future__ import annotations

import json
import random


def _json_roundtrip(payload):
    return json.loads(json.dumps(payload))


def all_actions(legal):
    """Annotated actions plus the compact setup placements, as dicts with id and type."""
    out = list(legal["actions"])
    for kind, rows in (legal.get("compact") or {}).items():
        out.extend({"id": row[0], "type": kind, "arg": row[1], "x": row[2], "y": row[3]}
                   for row in rows)
    return out


class RandomDriver:
    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def choose(self, legal, session=None):
        action = self.rng.choice(all_actions(legal))
        return {"action_id": action["id"], "state_version": legal["state_version"]}


class ContactBotDriver:
    """Uses the session's contact-bot hint endpoint, then submits by id."""

    def choose(self, legal, session):
        idx = session.bot_suggestion()
        return {"action_id": idx, "state_version": legal["state_version"]}


class CoverageDriver:
    """Random driver that always picks an action type it has not submitted yet
    when one is on offer, so every presented decision type gets driven."""

    def __init__(self, seed=0, submitted=None):
        self.rng = random.Random(seed)
        self.submitted = submitted if submitted is not None else set()

    def choose(self, legal, session=None):
        actions = all_actions(legal)
        fresh = [a for a in actions if a["type"] not in self.submitted]
        action = self.rng.choice(fresh or actions)
        self.submitted.add(action["type"])
        return {"action_id": action["id"], "state_version": legal["state_version"]}


class ScriptedActionsDriver:
    """Replays a fixed list of engine actions (determinism tests)."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.pos = 0

    def choose(self, legal, session=None):
        a = self.actions[self.pos]
        self.pos += 1
        return {"action": {"type": a[0], "arg": a[1], "x": a[2], "y": a[3]},
                "state_version": legal["state_version"]}


def play_to_completion(session, driver, max_submissions=20000):
    submissions = 0
    while True:
        legal = _json_roundtrip(session.legal())
        if legal["awaiting"] == "over":
            break
        if legal["awaiting"] != "human":
            raise AssertionError("session idle while the policy should act")
        request = _json_roundtrip(driver.choose(legal, session))
        response = _json_roundtrip(session.submit(request))
        if not response["ok"]:
            raise AssertionError(f"submission rejected: {response}")
        submissions += 1
        if submissions > max_submissions:
            raise AssertionError("submission budget exhausted")
    return submissions

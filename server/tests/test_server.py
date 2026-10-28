import random
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "pipeline"))

import levels  # noqa: E402
from app import create_app  # noqa: E402


def test_level_update_rules():
    assert levels.update(3.0, 0.85, 3) == 3.0
    assert levels.update(3.0, 1.0, 3) == 3.3  # capped gain
    assert levels.update(3.0, 0.5, 3) == 2.5  # capped loss
    assert levels.update(3.0, 1.0, 1) == 3.15  # acing an easy one counts half
    assert levels.update(1.0, 0.0, 1) == 1.0  # floor


def test_pick_target_stays_close():
    rng = random.Random(1)
    picks = [levels.pick_target(3.4, rng) for _ in range(1000)]
    assert {grades[0] for grades, _ in picks} == {3}
    assert all(3.2 <= aim <= 3.6 for _, aim in picks)
    near_edge = [levels.pick_target(1.95, rng)[0][0] for _ in range(1000)]
    assert 0.2 < near_edge.count(2) / 1000 < 0.5  # sometimes just over into grade 2
    assert min(levels.pick_target(1.0, rng)[1] for _ in range(200)) == 1.0  # never below the floor


def test_practice_flow(client):
    p = client.post("/api/players", json={"name": "Garrett", "level": 3}).json()
    assert client.post("/api/players", json={"name": "Garrett"}).status_code == 409

    nxt = client.get("/api/next", params={"player_id": p["id"], "mode": "wait", "grade": 3}).json()
    ex = nxt["excerpt"]
    assert ex["grade"] == 3 and ex["score_url"].endswith("/score.mxl")
    assert client.get(ex["score_url"]).content == b"PK fake"

    r = client.post("/api/attempts", json={"player_id": p["id"], "excerpt_id": ex["id"], "mode": "wait",
                                           "steps": 50, "wrong": 0, "duration_ms": 60000}).json()
    assert r["performance"] == 1.0 and r["level_before"] == 3.0 and r["level_after"] == 3.3

    # The same piece isn't served again while it's recent.
    again = client.get("/api/next", params={"player_id": p["id"], "mode": "wait", "grade": 3})
    assert again.json()["excerpt"]["piece_id"] != ex["piece_id"]

    players = client.get("/api/players").json()
    lv = players[0]["levels"]
    assert (lv["wait"], lv["tempo"], lv["wait:left"]) == (3.3, 3.0, 4.3) and players[0]["attempts"] == 1
    assert client.get(f"/api/players/{p['id']}/attempts").json()[0]["level_after"] == 3.3


def test_license_filter_and_library(client):
    p = client.post("/api/players", json={"name": "A"}).json()
    # p2 has a license conflict, so with the filter on only p1's grade-3 excerpt can be served.
    first = client.get("/api/next", params={"player_id": p["id"], "mode": "tempo", "grade": 3,
                                            "license_only": True}).json()
    assert first["excerpt"]["piece_id"] == "p1"

    lib = client.get("/api/library", params={"grade": 3}).json()
    assert lib["total"] == 2
    assert client.get("/api/library", params={"grade": 3, "license_only": True}).json()["total"] == 1

    detail = client.get("/api/excerpts/p1-3").json()
    assert "density" in detail["terms"] and detail["features"]["notes"] == 49

    s = client.get("/api/admin/summary").json()
    assert s["excerpts"] == 10 and s["grades"][2]["excerpts"] == 2


def test_admin_edits(client):
    p = client.post("/api/players", json={"name": "B"}).json()
    r = client.patch(f"/api/players/{p['id']}", json={"levels": {"tempo": 12}}).json()
    assert r["levels"]["tempo"] == 9.0  # clamped
    assert client.delete(f"/api/players/{p['id']}").status_code == 204
    assert client.get("/api/players").json() == []


def test_one_hand_levels(client):
    p = client.post("/api/players", json={"name": "C", "level": 3}).json()
    assert p["levels"]["tempo:right"] == 4.0  # head start over hands together
    nxt = client.get("/api/next", params={"player_id": p["id"], "mode": "wait", "hands": "left", "grade": 4}).json()
    r = client.post("/api/attempts", json={"player_id": p["id"], "excerpt_id": nxt["excerpt"]["id"], "mode": "wait",
                                           "hands": "left", "steps": 20, "wrong": 0, "wrong_left": 0}).json()
    assert (r["level_before"], r["level_after"]) == (4.0, 4.3)
    lv = client.get("/api/players").json()[0]["levels"]
    assert (lv["wait"], lv["wait:left"], lv["wait:right"]) == (3.0, 4.3, 4.0)  # hands-together level untouched
    a = client.get(f"/api/players/{p['id']}/attempts").json()[0]
    assert a["hands"] == "left" and a["wrong_left"] == 0
    assert client.patch(f"/api/players/{p['id']}", json={"levels": {"wait:both": 2}}).status_code == 422


def test_migrates_old_attempts_table(tmp_path, client):
    """A database from before the hands columns gets them added on startup."""
    old = tmp_path / "old.sqlite"
    db = sqlite3.connect(old)
    db.execute("CREATE TABLE attempts (id INTEGER PRIMARY KEY, player_id INTEGER, excerpt_id TEXT, piece_id TEXT, "
               "grade INTEGER, mode TEXT, finished_at TEXT, bpm INTEGER, duration_ms INTEGER, wrong INTEGER, "
               "note_pct REAL, timing_pct REAL, performance REAL, level_before REAL, level_after REAL, details TEXT)")
    db.commit()
    db.close()
    create_app(old, tmp_path / "library")
    cols = {r[1] for r in sqlite3.connect(old).execute("PRAGMA table_info(attempts)")}
    assert {"hands", "wrong_left", "missed_right"} <= cols


def test_target_difficulty_moves_through_the_grade():
    cut = (4.5, 5.8, 7.8, 10.0, 11.8, 12.4, 13.0, 15.5)
    assert levels.target_difficulty(1.0, 1, cut) == levels.EASIEST
    assert levels.target_difficulty(1.5, 1, cut) == pytest.approx((levels.EASIEST + 4.5) / 2)
    assert levels.target_difficulty(2.0, 2, cut) == 4.5
    assert levels.target_difficulty(1.9, 2, cut) == 4.5  # grade above: its easy end
    assert levels.target_difficulty(2.1, 1, cut) == 4.5  # grade below: its hard end

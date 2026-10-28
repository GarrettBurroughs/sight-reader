import json
import random
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "pipeline"))

import levels  # noqa: E402
from app import create_app  # noqa: E402
from catalog import SCHEMA as LIBRARY_SCHEMA  # noqa: E402
import features  # noqa: E402
from musicxml import parse, read_mxl  # noqa: E402

MINUET = ROOT / "web" / "public" / "scores" / "minuet-in-g.musicxml"


@pytest.fixture
def client(tmp_path):
    """A library with one piece and an excerpt at each grade 1-9 (plus a second piece at grade 3)."""
    lib = tmp_path / "library"
    (lib / "excerpts").mkdir(parents=True)
    f = features.compute(parse(read_mxl(str(MINUET))).measures[:8])
    db = sqlite3.connect(lib / "library.sqlite")
    db.executescript(LIBRARY_SCHEMA)
    for piece, ok in (("p1", 1), ("p2", 0)):
        db.execute("INSERT INTO pieces VALUES (?, '', ?, 'Petzold', NULL, 'publicdomain', ?, NULL, 0, 0, 16)",
                   (piece, f"Piece {piece}", ok))
    rows = [(f"p1-{g}", "p1", g) for g in range(1, 10)] + [("p2-3", "p2", 3)]
    for ex_id, piece, grade in rows:
        (lib / "excerpts" / f"{ex_id}.mxl").write_bytes(b"PK fake")
        db.execute("INSERT INTO excerpts VALUES (?, ?, 0, '1', 8, ?, ?, ?, 1, '3/4', 1.0, ?)",
                   (ex_id, piece, f"excerpts/{ex_id}.mxl", grade * 2.0, grade, json.dumps(f)))
    db.commit()
    db.close()
    return TestClient(create_app(tmp_path / "app.sqlite", lib))


def test_level_update_rules():
    assert levels.update(3.0, 0.85, 3) == 3.0
    assert levels.update(3.0, 1.0, 3) == 3.3  # capped gain
    assert levels.update(3.0, 0.5, 3) == 2.5  # capped loss
    assert levels.update(3.0, 1.0, 1) == 3.15  # acing an easy one counts half
    assert levels.update(1.0, 0.0, 1) == 1.0  # floor


def test_grade_preference_mostly_own_grade():
    rng = random.Random(1)
    firsts = [levels.grade_preference(3.4, rng)[0] for _ in range(1000)]
    assert 0.6 < firsts.count(3) / 1000 < 0.8
    assert set(firsts) == {2, 3, 4}


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
    assert players[0]["levels"] == {"wait": 3.3, "tempo": 3.0} and players[0]["attempts"] == 1
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

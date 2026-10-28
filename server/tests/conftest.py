import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "pipeline"))

from app import create_app  # noqa: E402
from catalog import SCHEMA as LIBRARY_SCHEMA  # noqa: E402
import features  # noqa: E402
from musicxml import parse, read_mxl  # noqa: E402

MINUET = ROOT / "web" / "public" / "scores" / "minuet-in-g.musicxml"


@pytest.fixture
def library(tmp_path):
    """A library with one piece and an excerpt at each grade 1-9 (plus a second piece at grade 3)."""
    lib = tmp_path / "library"
    (lib / "excerpts").mkdir(parents=True)
    f = features.compute(parse(read_mxl(str(MINUET))).measures[:8])
    db = sqlite3.connect(lib / "library.sqlite")
    db.executescript(LIBRARY_SCHEMA)
    for piece, ok in (("p1", 1), ("p2", 0)):
        db.execute("INSERT INTO pieces VALUES (?, 'pdmx', '', ?, 'Petzold', NULL, 'publicdomain', ?, NULL, 0, 0, 16)",
                   (piece, f"Piece {piece}", ok))
    rows = [(f"p1-{g}", "p1", g) for g in range(1, 10)] + [("p2-3", "p2", 3)]
    for ex_id, piece, grade in rows:
        (lib / "excerpts" / f"{ex_id}.mxl").write_bytes(b"PK fake")
        db.execute("INSERT INTO excerpts VALUES (?, ?, 0, '1', 8, ?, ?, ?, 1, '3/4', 1.0, ?)",
                   (ex_id, piece, f"excerpts/{ex_id}.mxl", grade * 2.0, grade, json.dumps(f)))
    db.commit()
    db.close()
    return lib


@pytest.fixture
def client(tmp_path, library):
    return TestClient(create_app(tmp_path / "app.sqlite", library))

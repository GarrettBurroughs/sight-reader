"""Sight-reader API: serves library excerpts, records attempts, tracks player levels.

    server/.venv/bin/uvicorn app:create_app --factory --app-dir server --port 8000

The web dev server proxies /api here. Player data lives in server/data/app.sqlite;
the excerpt library (read-only) comes from pipeline/data/library.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import levels

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from features import difficulty_terms  # noqa: E402

Mode = Literal["wait", "tempo"]
RECENT_PIECES = 15  # don't serve a piece again within this many attempts

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS levels (
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  mode TEXT NOT NULL,
  level REAL NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (player_id, mode)
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY,
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  excerpt_id TEXT NOT NULL,
  piece_id TEXT NOT NULL,
  grade INTEGER NOT NULL,
  mode TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  bpm INTEGER,
  duration_ms INTEGER,
  wrong INTEGER,
  note_pct REAL,
  timing_pct REAL,
  performance REAL NOT NULL,
  level_before REAL NOT NULL,
  level_after REAL NOT NULL,
  details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_player ON attempts(player_id, finished_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlayerIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    level: float = Field(default=levels.START_LEVEL, ge=levels.MIN_LEVEL, le=levels.MAX_LEVEL)


class PlayerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    levels: dict[Mode, float] | None = None


class AttemptIn(BaseModel):
    player_id: int
    excerpt_id: str
    mode: Mode
    duration_ms: int = 0
    wrong: int = 0
    steps: int | None = None  # wait mode
    bpm: int | None = None  # tempo mode, and the rest below
    total: int | None = None
    played: int | None = None
    missed: int | None = None
    note_pct: float | None = None
    timing_pct: float | None = None
    mean_offset_ms: float | None = None


def create_app(app_db: Path | None = None, library_dir: Path | None = None, license_only: bool | None = None) -> FastAPI:
    app_db = Path(app_db or os.environ.get("SIGHTREADER_DB", ROOT / "server" / "data" / "app.sqlite"))
    library_dir = Path(library_dir or os.environ.get("SIGHTREADER_LIBRARY", ROOT / "pipeline" / "data" / "library"))
    if license_only is None:
        license_only = os.environ.get("SIGHTREADER_LICENSE_ONLY") == "1"
    library_db = library_dir / "library.sqlite"
    if not library_db.exists():
        raise SystemExit(f"No library at {library_db}; run pipeline/catalog.py first.")
    app_db.parent.mkdir(parents=True, exist_ok=True)

    def connect() -> sqlite3.Connection:
        # uri=True so the library can be attached read-only with a file: URI.
        db = sqlite3.connect(f"file:{app_db}", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("ATTACH DATABASE ? AS lib", (f"file:{library_db}?mode=ro",))
        return db

    with connect() as db:
        db.executescript(SCHEMA)
    app = FastAPI(title="Sight Reader")

    def license_clause(only: bool | None) -> str:
        return "AND p.no_license_conflict = 1" if (license_only if only is None else only) else ""

    def player_or_404(db: sqlite3.Connection, player_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such player")
        return row

    def player_levels(db: sqlite3.Connection, player_id: int) -> dict[str, float]:
        rows = dict(db.execute("SELECT mode, level FROM levels WHERE player_id = ?", (player_id,)).fetchall())
        return {m: rows.get(m, levels.START_LEVEL) for m in levels.MODES}

    def excerpt_meta(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "piece_id": row["piece_id"],
            "title": row["title"],
            "composer": row["composer"],
            "grade": row["grade"],
            "difficulty": row["difficulty"],
            "start_bar": row["start_bar"],
            "n_bars": row["n_bars"],
            "time_signature": row["time_signature"],
            "key_fifths": row["key_fifths"],
            "notes_per_quarter": row["notes_per_quarter"],
            "no_license_conflict": bool(row["no_license_conflict"]),
            "score_url": f"/api/excerpts/{row['id']}/score.mxl",
        }

    EXCERPT_SELECT = """
        SELECT e.*, p.title, p.composer, p.no_license_conflict, p.genres, p.license, p.rating, p.n_favorites
        FROM lib.excerpts e JOIN lib.pieces p ON p.id = e.piece_id
    """

    # ---- Players ----

    @app.get("/api/players")
    def list_players():
        with connect() as db:
            rows = db.execute(
                """SELECT pl.*, COUNT(a.id) AS attempts, MAX(a.finished_at) AS last_played
                   FROM players pl LEFT JOIN attempts a ON a.player_id = pl.id
                   GROUP BY pl.id ORDER BY pl.name"""
            ).fetchall()
            return [{**dict(r), "levels": player_levels(db, r["id"])} for r in rows]

    @app.post("/api/players", status_code=201)
    def create_player(body: PlayerIn):
        with connect() as db:
            try:
                cur = db.execute("INSERT INTO players (name, created_at) VALUES (?, ?)", (body.name.strip(), now()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "A player with that name exists")
            for mode in levels.MODES:
                db.execute("INSERT INTO levels VALUES (?, ?, ?, ?)", (cur.lastrowid, mode, body.level, now()))
            return {"id": cur.lastrowid, "name": body.name.strip(), "levels": {m: body.level for m in levels.MODES}}

    @app.patch("/api/players/{player_id}")
    def patch_player(player_id: int, body: PlayerPatch):
        with connect() as db:
            player_or_404(db, player_id)
            if body.name:
                db.execute("UPDATE players SET name = ? WHERE id = ?", (body.name.strip(), player_id))
            for mode, level in (body.levels or {}).items():
                level = max(levels.MIN_LEVEL, min(levels.MAX_LEVEL, level))
                db.execute(
                    "INSERT INTO levels VALUES (?, ?, ?, ?) ON CONFLICT (player_id, mode) "
                    "DO UPDATE SET level = excluded.level, updated_at = excluded.updated_at",
                    (player_id, mode, level, now()),
                )
            return {"id": player_id, "levels": player_levels(db, player_id)}

    @app.delete("/api/players/{player_id}", status_code=204)
    def delete_player(player_id: int):
        with connect() as db:
            player_or_404(db, player_id)
            db.execute("DELETE FROM players WHERE id = ?", (player_id,))

    @app.get("/api/players/{player_id}/attempts")
    def player_attempts(player_id: int, limit: int = Query(200, le=2000)):
        with connect() as db:
            player_or_404(db, player_id)
            rows = db.execute(
                """SELECT a.*, p.title FROM attempts a LEFT JOIN lib.pieces p ON p.id = a.piece_id
                   WHERE a.player_id = ? ORDER BY a.id DESC LIMIT ?""",
                (player_id, limit),
            ).fetchall()
            return [{**dict(r), "details": json.loads(r["details"])} for r in rows]

    # ---- Practice ----

    @app.get("/api/next")
    def next_excerpt(player_id: int, mode: Mode, grade: int | None = Query(None, ge=1, le=9),
                     license_only: bool | None = None):
        with connect() as db:
            player_or_404(db, player_id)
            level = player_levels(db, player_id)[mode]
            grades = [grade] if grade else levels.grade_preference(level)
            for g in grades:
                row = db.execute(
                    EXCERPT_SELECT
                    + f"""WHERE e.grade = ? {license_clause(license_only)}
                          AND e.id NOT IN (SELECT excerpt_id FROM attempts WHERE player_id = ?)
                          AND e.piece_id NOT IN (SELECT piece_id FROM attempts WHERE player_id = ?
                                                 ORDER BY id DESC LIMIT ?)
                          ORDER BY random() LIMIT 1""",
                    (g, player_id, player_id, RECENT_PIECES),
                ).fetchone()
                if row:
                    return {"level": level, "excerpt": excerpt_meta(row)}
            raise HTTPException(404, "No unplayed excerpts left at that grade")

    @app.post("/api/attempts", status_code=201)
    def record_attempt(body: AttemptIn):
        with connect() as db:
            player_or_404(db, body.player_id)
            ex = db.execute("SELECT id, piece_id, grade FROM lib.excerpts WHERE id = ?", (body.excerpt_id,)).fetchone()
            if not ex:
                raise HTTPException(404, "No such excerpt")
            perf = levels.performance(body.mode, steps=body.steps, wrong=body.wrong, note_pct=body.note_pct,
                                      timing_pct=body.timing_pct)
            before = player_levels(db, body.player_id)[body.mode]
            after = levels.update(before, perf, ex["grade"])
            note_pct = body.note_pct if body.mode == "tempo" else round(100 * perf, 1)
            db.execute(
                """INSERT INTO attempts (player_id, excerpt_id, piece_id, grade, mode, finished_at, bpm,
                   duration_ms, wrong, note_pct, timing_pct, performance, level_before, level_after, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (body.player_id, ex["id"], ex["piece_id"], ex["grade"], body.mode, now(), body.bpm, body.duration_ms,
                 body.wrong, note_pct, body.timing_pct, round(perf, 4), before, after, body.model_dump_json()),
            )
            db.execute(
                "INSERT INTO levels VALUES (?, ?, ?, ?) ON CONFLICT (player_id, mode) "
                "DO UPDATE SET level = excluded.level, updated_at = excluded.updated_at",
                (body.player_id, body.mode, after, now()),
            )
            return {"performance": round(perf, 4), "level_before": before, "level_after": after}

    # ---- Library ----

    @app.get("/api/excerpts/{excerpt_id}")
    def get_excerpt(excerpt_id: str):
        with connect() as db:
            row = db.execute(EXCERPT_SELECT + "WHERE e.id = ?", (excerpt_id,)).fetchone()
            if not row:
                raise HTTPException(404, "No such excerpt")
            features = json.loads(row["features"])
            attempts = db.execute(
                """SELECT a.id, a.mode, a.finished_at, a.performance, a.level_before, a.level_after, pl.name AS player
                   FROM attempts a JOIN players pl ON pl.id = a.player_id WHERE a.excerpt_id = ? ORDER BY a.id DESC""",
                (excerpt_id,),
            ).fetchall()
            return {
                **excerpt_meta(row),
                "genres": row["genres"],
                "license": row["license"],
                "rating": row["rating"],
                "n_favorites": row["n_favorites"],
                "features": features,
                "terms": {k: round(v, 3) for k, v in difficulty_terms(features).items()},
                "attempts": [dict(a) for a in attempts],
            }

    @app.get("/api/excerpts/{excerpt_id}/score.mxl")
    def excerpt_score(excerpt_id: str):
        with connect() as db:
            row = db.execute("SELECT file FROM lib.excerpts WHERE id = ?", (excerpt_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such excerpt")
        return FileResponse(library_dir / row["file"], media_type="application/vnd.recordare.musicxml")

    @app.get("/api/library")
    def library(grade: int | None = Query(None, ge=1, le=9), q: str | None = None, license_only: bool | None = None,
                sort: Literal["difficulty", "grade", "title", "attempts"] = "difficulty",
                order: Literal["asc", "desc"] = "asc", limit: int = Query(50, le=500), offset: int = 0):
        where, params = ["1 = 1"], []
        if grade:
            where.append("e.grade = ?")
            params.append(grade)
        if q:
            where.append("(p.title LIKE ? OR p.composer LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        sql_where = " AND ".join(where) + " " + license_clause(license_only)
        sort_col = {"difficulty": "e.difficulty", "grade": "e.grade", "title": "p.title", "attempts": "attempts"}[sort]
        with connect() as db:
            total = db.execute(
                f"SELECT COUNT(*) FROM lib.excerpts e JOIN lib.pieces p ON p.id = e.piece_id WHERE {sql_where}", params
            ).fetchone()[0]
            rows = db.execute(
                f"""SELECT e.*, p.title, p.composer, p.no_license_conflict,
                       (SELECT COUNT(*) FROM attempts a WHERE a.excerpt_id = e.id) AS attempts
                    FROM lib.excerpts e JOIN lib.pieces p ON p.id = e.piece_id
                    WHERE {sql_where} ORDER BY {sort_col} {order}, e.id LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()
            return {"total": total, "rows": [{**excerpt_meta(r), "attempts": r["attempts"]} for r in rows]}

    @app.get("/api/admin/summary")
    def summary():
        with connect() as db:
            grades = db.execute(
                """SELECT e.grade, COUNT(*) AS excerpts, SUM(p.no_license_conflict) AS license_ok,
                          COUNT(DISTINCT e.piece_id) AS pieces
                   FROM lib.excerpts e JOIN lib.pieces p ON p.id = e.piece_id GROUP BY e.grade ORDER BY e.grade"""
            ).fetchall()
            return {
                "pieces": db.execute("SELECT COUNT(*) FROM lib.pieces").fetchone()[0],
                "excerpts": db.execute("SELECT COUNT(*) FROM lib.excerpts").fetchone()[0],
                "players": db.execute("SELECT COUNT(*) FROM players").fetchone()[0],
                "attempts": db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
                "license_only": license_only,
                "grades": [dict(g) for g in grades],
            }

    return app


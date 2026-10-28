"""Sight-reader API: serves library excerpts, records attempts, tracks player levels.

    server/.venv/bin/uvicorn app:create_app --factory --app-dir server --port 8000

Locally the web dev server proxies /api here. In the cloud image this also serves the built
web app (SIGHTREADER_STATIC), requires a password (SIGHTREADER_PASSWORD), and keeps the
player database replicated to GCS (SIGHTREADER_BUCKET, see persistence.py). Player data
lives in server/data/app.sqlite; the excerpt library (read-only) comes from pipeline/data/library.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import sqlite3
import zipfile
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import levels
from auth import Auth
from persistence import Persistence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from features import GRADE_CUTOFFS, difficulty_terms  # noqa: E402

Mode = Literal["wait", "tempo"]
RECENT_PIECES = 15  # don't serve a piece again within this many attempts
NEAREST = 25  # pick at random among this many excerpts closest to the target difficulty

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS levels (
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  mode TEXT NOT NULL,               -- a levels.level_key: "wait", "tempo:left"...
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
  hands TEXT NOT NULL DEFAULT 'both',
  finished_at TEXT NOT NULL,
  bpm INTEGER,
  duration_ms INTEGER,
  wrong INTEGER,
  wrong_right INTEGER,
  wrong_left INTEGER,
  missed_right INTEGER,
  missed_left INTEGER,
  note_pct REAL,
  timing_pct REAL,
  performance REAL NOT NULL,
  level_before REAL NOT NULL,
  level_after REAL NOT NULL,
  details TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_player ON attempts(player_id, finished_at);
"""
# Columns added after the first release, for databases created before them.
ADDED_COLUMNS = {
    "attempts": {
        "hands": "TEXT NOT NULL DEFAULT 'both'",
        "wrong_right": "INTEGER",
        "wrong_left": "INTEGER",
        "missed_right": "INTEGER",
        "missed_left": "INTEGER",
    },
}
Hands = Literal["both", "right", "left"]
Length = Literal["excerpt", "section", "full"]  # 8 bars, 16 bars, the whole piece


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlayerIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    level: float = Field(default=levels.START_LEVEL, ge=levels.MIN_LEVEL, le=levels.MAX_LEVEL)


class PlayerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    levels: dict[str, float] | None = None  # keyed by levels.level_key


class AttemptIn(BaseModel):
    player_id: int
    excerpt_id: str
    mode: Mode
    hands: Hands = "both"
    duration_ms: int = 0
    wrong: int = 0
    wrong_right: int | None = None  # wrong presses put down to each hand
    wrong_left: int | None = None
    missed_right: int | None = None  # tempo mode: notes not played, by hand
    missed_left: int | None = None
    steps: int | None = None  # wait mode
    bpm: int | None = None  # tempo mode, and the rest below
    total: int | None = None
    played: int | None = None
    missed: int | None = None
    note_pct: float | None = None
    timing_pct: float | None = None
    mean_offset_ms: float | None = None


READY_WAIT_SECONDS = 25  # how long a request waits for the database while an instance starts
IPAD_PROJECT = Path(os.environ.get("SIGHTREADER_IPAD", ROOT / "ipad" / "SightReader.swiftpm"))
# The shell's remembered address starts as this default; downloads point it at the site they came from.
DEFAULT_ADDRESS = re.compile(r'(@AppStorage\("serverAddress"\) private var address = ")[^"]*(")')


def create_app(app_db: Path | None = None, library_dir: Path | None = None, license_only: bool | None = None,
               persistence: Persistence | None = None, auth: Auth | None = None,
               static_dir: Path | None = None) -> FastAPI:
    app_db = Path(app_db or os.environ.get("SIGHTREADER_DB", ROOT / "server" / "data" / "app.sqlite"))
    library_dir = Path(library_dir or os.environ.get("SIGHTREADER_LIBRARY", ROOT / "pipeline" / "data" / "library"))
    if license_only is None:
        license_only = os.environ.get("SIGHTREADER_LICENSE_ONLY") == "1"
    library_db = library_dir / "library.sqlite"
    if not library_db.exists():
        raise SystemExit(f"No library at {library_db}; run pipeline/catalog.py first.")
    app_db.parent.mkdir(parents=True, exist_ok=True)
    static_dir = static_dir or (Path(os.environ["SIGHTREADER_STATIC"]) if os.environ.get("SIGHTREADER_STATIC") else None)
    auth = auth or Auth(os.environ.get("SIGHTREADER_PASSWORD"), os.environ.get("SIGHTREADER_SESSION_KEY"),
                        secure_cookie=os.environ.get("SIGHTREADER_SECURE_COOKIE") == "1")

    def connect() -> sqlite3.Connection:
        # uri=True so the library can be attached read-only with a file: URI.
        db = sqlite3.connect(f"file:{app_db}", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        db.execute("ATTACH DATABASE ? AS lib", (f"file:{library_db}?mode=ro",))
        return db

    def init_db() -> None:
        with connect() as db:
            db.execute("PRAGMA main.journal_mode = WAL")  # Litestream replicates the WAL (not the read-only library)
            db.executescript(SCHEMA)
            for table, columns in ADDED_COLUMNS.items():
                existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                for name, decl in columns.items():
                    if name not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    persistence = persistence or Persistence.from_env(app_db, init_db)
    if not persistence.bucket:
        persistence.start()  # local: ready at once, without waiting for the startup hook

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        persistence.start()
        yield
        persistence.stop()

    app = FastAPI(title="Sight Reader", lifespan=lifespan)

    @app.middleware("http")
    async def wait_for_database(request: Request, call_next):
        """Hold API requests while a new instance takes over the database (see persistence.py)."""
        if request.url.path.startswith("/api/") and request.url.path != "/api/health" and not persistence.ready.is_set():
            ready = await anyio.to_thread.run_sync(persistence.ready.wait, READY_WAIT_SECONDS)
            if not ready:
                return JSONResponse({"detail": "Starting up; try again in a moment"}, status_code=503)
        return await call_next(request)

    auth.install(app)  # added last, so it runs first

    @app.get("/api/ipad-app.zip")
    def ipad_app(request: Request):
        """The Swift Playgrounds project, preset to open this site. Open the zip on the iPad (Files app)."""
        site = str(request.base_url).rstrip("/")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(IPAD_PROJECT.rglob("*")):
                if not f.is_file() or ":" in f.name or f.name == ".DS_Store":
                    continue
                data = f.read_text()
                if f.name == "ContentView.swift":
                    data = DEFAULT_ADDRESS.sub(rf"\g<1>{site}\g<2>", data)
                z.writestr(f"SightReader.swiftpm/{f.relative_to(IPAD_PROJECT)}", data)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="SightReader.swiftpm.zip"'})

    @app.get("/api/health")
    def health():
        return {"ok": persistence.failed is None, "ready": persistence.ready.is_set(),
                "version": os.environ.get("SIGHTREADER_VERSION", "dev"), "error": persistence.failed}

    def license_clause(only: bool | None) -> str:
        return "AND p.no_license_conflict = 1" if (license_only if only is None else only) else ""

    def player_or_404(db: sqlite3.Connection, player_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such player")
        return row

    def player_levels(db: sqlite3.Connection, player_id: int) -> dict[str, float]:
        """Every level key. One-hand levels not played yet start a little above hands together."""
        rows = dict(db.execute("SELECT mode, level FROM levels WHERE player_id = ?", (player_id,)).fetchall())
        out = {}
        for mode in levels.MODES:
            both = rows.get(mode, levels.START_LEVEL)
            out[mode] = both
            for hands in levels.HANDS[1:]:
                key = levels.level_key(mode, hands)
                out[key] = rows.get(key, round(min(levels.MAX_LEVEL, both + levels.ONE_HAND_HEAD_START), 2))
        return out

    def excerpt_meta(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "piece_id": row["piece_id"],
            "kind": row["kind"],
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
            "source": row["source"],
            "score_url": f"/api/excerpts/{row['id']}/score.mxl",
        }

    EXCERPT_SELECT = """
        SELECT e.*, p.title, p.composer, p.no_license_conflict, p.source, p.genres, p.license, p.rating, p.n_favorites
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
            return {"id": cur.lastrowid, "name": body.name.strip(), "levels": player_levels(db, cur.lastrowid)}

    @app.patch("/api/players/{player_id}")
    def patch_player(player_id: int, body: PlayerPatch):
        with connect() as db:
            player_or_404(db, player_id)
            if body.name:
                db.execute("UPDATE players SET name = ? WHERE id = ?", (body.name.strip(), player_id))
            for mode, level in (body.levels or {}).items():
                if mode not in levels.LEVEL_KEYS:
                    raise HTTPException(422, f"Unknown level {mode!r}")
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
    def next_excerpt(player_id: int, mode: Mode, hands: Hands = "both", length: Length = "excerpt",
                     grade: int | None = Query(None, ge=1, le=9), license_only: bool | None = None):
        with connect() as db:
            player_or_404(db, player_id)
            level = player_levels(db, player_id)[levels.level_key(mode, hands)]
            grades, aim = levels.pick_target(level)
            if grade:
                grades, aim = [grade], grade + 0.5  # a fixed grade: aim at its middle
            # One hand alone needs something to play: at least two notes a bar in that hand
            # (measured over the passage the features describe).
            hand_clause = (
                f"AND json_extract(e.features, '$.{'rh' if hands == 'right' else 'lh'}.notes') "
                f">= 2 * json_extract(e.features, '$.bars')"
                if hands != "both" else ""
            )
            for g in grades:
                target = levels.target_difficulty(aim, g, GRADE_CUTOFFS)
                rows = db.execute(
                    EXCERPT_SELECT
                    + f"""WHERE e.kind = ? AND e.grade = ? {license_clause(license_only)} {hand_clause}
                          AND e.id NOT IN (SELECT excerpt_id FROM attempts WHERE player_id = ?)
                          AND e.piece_id NOT IN (SELECT piece_id FROM attempts WHERE player_id = ?
                                                 ORDER BY id DESC LIMIT ?)
                          ORDER BY abs(e.difficulty - ?) LIMIT ?""",
                    (length, g, player_id, player_id, RECENT_PIECES, target, NEAREST),
                ).fetchall()
                if rows:
                    return {"level": level, "excerpt": excerpt_meta(random.choice(rows))}
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
            key = levels.level_key(body.mode, body.hands)
            before = player_levels(db, body.player_id)[key]
            after = levels.update(before, perf, ex["grade"])
            note_pct = body.note_pct if body.mode == "tempo" else round(100 * perf, 1)
            db.execute(
                """INSERT INTO attempts (player_id, excerpt_id, piece_id, grade, mode, hands, finished_at, bpm,
                   duration_ms, wrong, wrong_right, wrong_left, missed_right, missed_left, note_pct, timing_pct,
                   performance, level_before, level_after, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (body.player_id, ex["id"], ex["piece_id"], ex["grade"], body.mode, body.hands, now(), body.bpm,
                 body.duration_ms, body.wrong, body.wrong_right, body.wrong_left, body.missed_right, body.missed_left,
                 note_pct, body.timing_pct, round(perf, 4), before, after, body.model_dump_json()),
            )
            db.execute(
                "INSERT INTO levels VALUES (?, ?, ?, ?) ON CONFLICT (player_id, mode) "
                "DO UPDATE SET level = excluded.level, updated_at = excluded.updated_at",
                (body.player_id, key, after, now()),
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
                """SELECT a.id, a.mode, a.hands, a.finished_at, a.performance, a.level_before, a.level_after, pl.name AS player
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
                source: Literal["pdmx", "generated"] | None = None, kind: Length | None = None,
                sort: Literal["difficulty", "grade", "title", "attempts"] = "difficulty",
                order: Literal["asc", "desc"] = "asc", limit: int = Query(50, le=500), offset: int = 0):
        where, params = ["1 = 1"], []
        if grade:
            where.append("e.grade = ?")
            params.append(grade)
        if source:
            where.append("p.source = ?")
            params.append(source)
        if kind:
            where.append("e.kind = ?")
            params.append(kind)
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
                f"""SELECT e.*, p.title, p.composer, p.no_license_conflict, p.source,
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
                """SELECT e.grade, SUM(e.kind = 'excerpt') AS excerpts, SUM(e.kind = 'section') AS sections,
                          SUM(e.kind = 'full') AS full, SUM(p.no_license_conflict) AS license_ok,
                          COUNT(DISTINCT e.piece_id) AS pieces
                   FROM lib.excerpts e JOIN lib.pieces p ON p.id = e.piece_id GROUP BY e.grade ORDER BY e.grade"""
            ).fetchall()
            return {
                "pieces": db.execute("SELECT COUNT(*) FROM lib.pieces").fetchone()[0],
                "excerpts": db.execute("SELECT COUNT(*) FROM lib.excerpts").fetchone()[0],
                "players": db.execute("SELECT COUNT(*) FROM players").fetchone()[0],
                "attempts": db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
                "generated": db.execute("SELECT COUNT(*) FROM lib.pieces WHERE source = 'generated'").fetchone()[0],
                "license_only": license_only,
                "grades": [dict(g) for g in grades],
            }

    if static_dir:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")  # after the API routes

    return app


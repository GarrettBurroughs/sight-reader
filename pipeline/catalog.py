"""Build the excerpt library from PDMX.

    python3 catalog.py [--limit N] [--workers N] [--no-license-conflict-only]

Reads data/raw/PDMX.csv and the extracted scores in data/pdmx/, and writes
data/library/library.sqlite plus one .mxl per excerpt under data/library/excerpts/.
Generated beginner exercises (generate.py) are added alongside, under data/library/exercises/.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import excerpts
import features
import generate
from musicxml import ScoreError, parse, read_mxl, write_mxl

DATA = Path(__file__).resolve().parent / "data"
CSV_PATH = DATA / "raw" / "PDMX.csv"
PDMX_DIR = DATA / "pdmx"
OUT = DATA / "library"
BUILD = DATA / "library.building"  # built here, then swapped in, so a running server never sees a half-built library
GRADES = 9

SCHEMA = """
CREATE TABLE pieces (
  id TEXT PRIMARY KEY,           -- PDMX file stem, or the exercise id
  source TEXT NOT NULL,          -- 'pdmx' or 'generated'
  pdmx_path TEXT NOT NULL,
  title TEXT,
  composer TEXT,
  genres TEXT,
  license TEXT,
  no_license_conflict INTEGER NOT NULL,
  rating REAL,
  n_ratings INTEGER,
  n_favorites INTEGER,
  n_bars INTEGER
);
CREATE TABLE excerpts (
  id TEXT PRIMARY KEY,
  piece_id TEXT NOT NULL REFERENCES pieces(id),
  kind TEXT NOT NULL,            -- 'excerpt' (8 bars), 'section' (16 bars) or 'full' (the whole piece)
  start_index INTEGER NOT NULL,  -- 0-based measure index in the original score
  start_bar TEXT,                -- the original's printed measure number
  n_bars INTEGER NOT NULL,
  file TEXT NOT NULL,            -- relative to the library directory
  difficulty REAL NOT NULL,      -- raw score of the hardest 8-bar passage, bigger is harder
  grade INTEGER NOT NULL,        -- 1-9, see features.GRADE_CUTOFFS
  key_fifths INTEGER,
  time_signature TEXT,
  notes_per_quarter REAL,
  features TEXT NOT NULL         -- JSON of the hardest passage, see features.compute and excerpts.hardest
);
CREATE INDEX excerpts_grade ON excerpts(kind, grade);
CREATE INDEX excerpts_piece ON excerpts(piece_id);
"""


def na(value: str) -> str | None:
    return None if value in ("", "NA") else value


def text(value: str) -> str | None:
    """A text field, undoing PDMX's double-encoded UTF-8 (e.g. 'Ã©' for 'é') where present."""
    value = na(value)
    if value is None:
        return None
    for codec in ("latin-1", "cp1252"):
        try:
            return value.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return value


def candidates(license_only: bool, limit: int | None):
    """Rows of PDMX.csv that might be solo piano: one track, piano program, valid, deduplicated."""
    csv.field_size_limit(sys.maxsize)
    n = 0
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if row["n_tracks"] != "1" or row["tracks"] != "0":
                continue
            if row["subset:all_valid"] != "True" or row["subset:deduplicated"] != "True":
                continue
            if license_only and row["subset:no_license_conflict"] != "True":
                continue
            yield row
            n += 1
            if limit and n >= limit:
                return


def process(row: dict) -> tuple[dict | None, list[dict], str | None]:
    """Parse one score and cut its excerpts. Returns (piece, excerpts, rejection reason)."""
    stem = Path(row["mxl"]).stem
    try:
        score = parse(read_mxl(str(PDMX_DIR / row["mxl"])))
        excerpts.check_piano(score)
        spans = [("excerpt", s, excerpts.EXCERPT_BARS) for s in excerpts.windows(score)]
        spans += [("section", s, excerpts.SECTION_BARS)
                  for s in excerpts.windows(score, excerpts.SECTION_BARS, excerpts.MAX_SECTIONS)]
        if excerpts.full_piece_ok(score):
            spans.append(("full", 0, len(score.measures)))
    except ScoreError as e:
        return None, [], re.sub(r"\d+", "N", str(e))  # group "3 staves", "5 staves"... together
    except Exception as e:  # malformed XML and other surprises: skip the file
        return None, [], f"error: {type(e).__name__}"
    if not spans:
        return None, [], "nothing usable to play"

    title = text(row["title"]) or text(row["song_name"]) or "Untitled"
    composer = text(row["composer_name"]) or text(row["artist_name"])
    piece = {
        "id": stem,
        "source": "pdmx",
        "pdmx_path": row["mxl"],
        "title": title,
        "composer": composer,
        "genres": na(row["genres"]),
        "license": na(row["license"]),
        "no_license_conflict": int(row["subset:no_license_conflict"] == "True"),
        "rating": float(row["rating"]) if na(row["rating"]) else None,
        "n_ratings": int(float(row["n_ratings"] or 0)),
        "n_favorites": int(float(row["n_favorites"] or 0)),
        "n_bars": len(score.measures),
    }

    out = []
    for kind, start, bars in spans:
        window = score.measures[start : start + bars]
        d, f = excerpts.hardest(score, start, bars)
        # Ids stay stable across rebuilds, so saved attempts keep pointing at the same music.
        ex_id = {"excerpt": f"{stem}-{start}", "section": f"{stem}-s{start}", "full": f"{stem}-full"}[kind]
        rel = f"excerpts/{stem[2:4]}/{ex_id}.mxl"
        bar = window[0].element.get("number")
        name = title if kind == "full" else f"{title} (bars {bar}–{window[-1].element.get('number')})"
        root = excerpts.cut(score, start, name, composer, bars)
        (BUILD / rel).parent.mkdir(parents=True, exist_ok=True)
        write_mxl(root, str(BUILD / rel))
        out.append(
            {
                "id": ex_id,
                "piece_id": stem,
                "kind": kind,
                "start_index": start,
                "start_bar": bar,
                "n_bars": len(window),
                "file": rel,
                "difficulty": d,
                "grade": features.grade(d),
                "key_fifths": f["key_fifths"],
                "time_signature": f"{f['beats']}/{f['beat_type']}",
                "notes_per_quarter": round(f["notes_per_quarter"], 3),
                "features": json.dumps(f, separators=(",", ":")),
            }
        )
    return piece, out, None


def exercises(per_stage: int) -> tuple[list[dict], list[dict]]:
    """Generate the beginner exercises and catalog them like excerpts (one piece each)."""
    pieces, rows = [], []
    for ex_id, title, stage, path in generate.build(BUILD, per_stage):
        window = parse(read_mxl(str(path))).measures
        f = features.compute(window)
        d = features.difficulty(f)
        pieces.append({
            "id": ex_id, "source": "generated", "pdmx_path": "", "title": title, "composer": "Generated exercise",
            "genres": f"exercise-stage-{stage.number}", "license": "generated", "no_license_conflict": 1,
            "rating": None, "n_ratings": 0, "n_favorites": 0, "n_bars": len(window),
        })
        rows.append({
            "id": ex_id, "piece_id": ex_id, "kind": "excerpt", "start_index": 0, "start_bar": "1", "n_bars": len(window),
            "file": str(path.relative_to(BUILD)), "difficulty": d, "grade": features.grade(d),
            "key_fifths": f["key_fifths"], "time_signature": f"{f['beats']}/{f['beat_type']}",
            "notes_per_quarter": round(f["notes_per_quarter"], 3), "features": json.dumps(f, separators=(",", ":")),
        })
    return pieces, rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="only look at the first N candidate scores")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--no-license-conflict-only", action="store_true", help="skip scores PDMX flags with a license conflict")
    ap.add_argument("--exercises-per-stage", type=int, default=250, help="generated beginner exercises per stage (0 for none)")
    args = ap.parse_args()

    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    rows = list(candidates(args.no_license_conflict_only, args.limit))
    print(f"{len(rows)} candidate scores, {args.workers} workers")
    pieces, all_excerpts, rejected = [], [], Counter()
    t0 = time.time()
    with Pool(args.workers) as pool:
        for i, (piece, exs, reason) in enumerate(pool.imap_unordered(process, rows, chunksize=8), 1):
            if piece:
                pieces.append(piece)
                all_excerpts.extend(exs)
            else:
                rejected[reason] += 1
            if i % 2000 == 0:
                print(f"  {i}/{len(rows)}  {len(pieces)} pieces, {len(all_excerpts)} excerpts  ({time.time() - t0:.0f}s)")

    if args.exercises_per_stage:
        ex_pieces, ex_rows = exercises(args.exercises_per_stage)
        pieces += ex_pieces
        all_excerpts += ex_rows
        print(f"  + {len(ex_rows)} generated exercises")
    if not all_excerpts:
        sys.exit("No excerpts produced.")

    db = sqlite3.connect(BUILD / "library.sqlite")
    db.executescript(SCHEMA)
    db.executemany(
        "INSERT INTO pieces VALUES (:id,:source,:pdmx_path,:title,:composer,:genres,:license,:no_license_conflict,"
        ":rating,:n_ratings,:n_favorites,:n_bars)",
        pieces,
    )
    db.executemany(
        "INSERT INTO excerpts VALUES (:id,:piece_id,:kind,:start_index,:start_bar,:n_bars,:file,:difficulty,:grade,"
        ":key_fifths,:time_signature,:notes_per_quarter,:features)",
        all_excerpts,
    )
    db.commit()
    db.close()
    old = DATA / "library.old"
    if OUT.exists():
        OUT.rename(old)
    BUILD.rename(OUT)
    shutil.rmtree(old, ignore_errors=True)

    print(f"\nDone in {time.time() - t0:.0f}s: {len(pieces)} pieces, {len(all_excerpts)} excerpts -> {OUT}")
    print("Rejected:", ", ".join(f"{r} {n}" for r, n in rejected.most_common(12)))
    for kind in ("excerpt", "section", "full"):
        per_grade = Counter(e["grade"] for e in all_excerpts if e["kind"] == kind)
        print(f"{kind:8} per grade:", ", ".join(f"{g}: {per_grade[g]}" for g in range(1, GRADES + 1)))


if __name__ == "__main__":
    main()

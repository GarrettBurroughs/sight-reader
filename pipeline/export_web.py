"""Copy a sample of graded excerpts into the web app, for trying the grading out before the server exists.

    python3 export_web.py [--per-grade 30] [--no-license-conflict-only]

Writes web/public/library/index.json and the excerpt files next to it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from catalog import GRADES, OUT

WEB_LIBRARY = Path(__file__).resolve().parents[1] / "web" / "public" / "library"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-grade", type=int, default=30)
    ap.add_argument("--no-license-conflict-only", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(OUT / "library.sqlite")
    db.row_factory = sqlite3.Row
    license_filter = "AND p.no_license_conflict = 1" if args.no_license_conflict_only else ""
    # Empty the folder rather than recreating it, so the running dev server keeps watching it.
    WEB_LIBRARY.mkdir(parents=True, exist_ok=True)
    for old in WEB_LIBRARY.iterdir():
        old.unlink()

    index = []
    for grade in range(1, GRADES + 1):
        # One excerpt per piece, favouring pieces people liked, with some randomness.
        rows = db.execute(
            f"""
            SELECT e.id, e.grade, e.difficulty, e.file, e.start_bar, p.title, p.composer
            FROM excerpts e JOIN pieces p ON p.id = e.piece_id
            WHERE e.grade = ? {license_filter}
            GROUP BY e.piece_id
            ORDER BY (p.n_favorites > 0) DESC, random()
            LIMIT ?
            """,
            (grade, args.per_grade),
        ).fetchall()
        for r in rows:
            shutil.copy(OUT / r["file"], WEB_LIBRARY / f"{r['id']}.mxl")
            index.append(
                {
                    "id": r["id"],
                    "grade": r["grade"],
                    "difficulty": r["difficulty"],
                    "title": r["title"],
                    "composer": r["composer"],
                    "file": f"library/{r['id']}.mxl",
                }
            )
    (WEB_LIBRARY / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"Exported {len(index)} excerpts to {WEB_LIBRARY}")


if __name__ == "__main__":
    main()

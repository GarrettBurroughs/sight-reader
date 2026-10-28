"""Show how well-known pieces score, to sanity-check difficulty() and GRADE_CUTOFFS.

    python3 anchors.py

Run after catalog.py. Each row: excerpt difficulty spread and median grade for a piece
(matched loosely by title and composer), next to its rough Henle level.
"""

from __future__ import annotations

import sqlite3
import statistics

from catalog import OUT
from features import GRADE_CUTOFFS, grade

# (name, title LIKE, composer-or-title LIKE alternatives, rough Henle level)
ANCHORS = [
    ("Ode to Joy (easy)", "%ode to joy%", ["%"], 1),
    ("Minuet in G, Anh. 114", "%minuet%g%", ["%petzold%", "%bach%"], 2),
    ("Clementi Sonatina op. 36/1", "%sonatina%36%1%", ["%clementi%"], 2),
    ("Satie Gymnopedie 1", "%gymnop%", ["%satie%"], 3),
    ("Bach Prelude in C, WTC I", "%prelude%c%", ["%bach%"], 3),
    ("Chopin Prelude op. 28/4", "%prelude%28%4%", ["%chopin%"], 3),
    ("Fur Elise", "%elise%", ["%beethoven%"], 3),
    ("Mozart Sonata K545", "%545%", ["%mozart%"], 4),
    ("Bach Invention 1", "%invention%1%", ["%bach%"], 4),
    ("Moonlight Sonata", "%moonlight%", ["%beethoven%"], 5),
    ("Chopin Etudes op. 10", "%tude%10%", ["%chopin%"], 8),
    ("Liszt La Campanella", "%campanella%", ["%liszt%"], 9),
]


def main() -> None:
    db = sqlite3.connect(OUT / "library.sqlite")
    print(f"cutoffs: {GRADE_CUTOFFS}\n")
    print(f"{'piece':30} {'henle':>5} {'grade':>5}  {'n':>3}  difficulty p25 / median / p75")
    for name, title, alternatives, henle in ANCHORS:
        where = " OR ".join("lower(coalesce(p.composer, '') || ' ' || p.title) LIKE ?" for _ in alternatives)
        ds = sorted(
            d
            for (d,) in db.execute(
                f"SELECT e.difficulty FROM excerpts e JOIN pieces p ON p.id = e.piece_id "
                f"WHERE lower(p.title) LIKE ? AND ({where})",
                [title, *alternatives],
            )
        )
        if not ds:
            print(f"{name:30} {henle:>5}     -  none found")
            continue
        median = statistics.median(ds)
        print(f"{name:30} {henle:>5} {grade(median):>5}  {len(ds):>3}  {ds[len(ds) // 4]:5.2f} / {median:5.2f} / {ds[3 * len(ds) // 4]:5.2f}")


if __name__ == "__main__":
    main()

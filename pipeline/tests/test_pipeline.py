import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import excerpts  # noqa: E402
import features  # noqa: E402
from musicxml import parse, read_mxl, write_mxl  # noqa: E402

MINUET = Path(__file__).resolve().parents[2] / "web" / "public" / "scores" / "minuet-in-g.musicxml"


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.score = parse(read_mxl(str(MINUET)))

    def test_parse(self):
        self.assertEqual(len(self.score.measures), 16)
        first = self.score.measures[0]
        self.assertEqual((first.attrs.beats, first.attrs.beat_type, first.attrs.fifths), (3, 4, 1))
        self.assertEqual(first.length, 3)
        played = [n.midi for n in first.notes if n.played and n.staff == 2]
        self.assertEqual(played, [55, 59, 62, 57])  # G3 B3 D4 chord, then A3

    def test_piano_and_windows(self):
        excerpts.check_piano(self.score)
        self.assertEqual(excerpts.windows(self.score), [0, 8])

    def test_cut_round_trip(self):
        root = excerpts.cut(self.score, 8, "Minuet (bars 9-16)", "Petzold")
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/x.mxl"
            write_mxl(root, path)
            again = parse(read_mxl(path))
        self.assertEqual(len(again.measures), 8)
        self.assertEqual(again.measures[0].element.get("number"), "1")
        self.assertEqual(again.measures[0].attrs.fifths, 1)
        self.assertEqual(again.measures[0].attrs.clefs, {1: ("G", 2), 2: ("F", 4)})
        self.assertEqual(again.measures[-1].element.find("barline/bar-style").text, "light-heavy")

    def test_features(self):
        f = features.compute(self.score.measures[0:8])
        self.assertEqual(f["notes"], 49)  # 32 right hand + 17 left hand
        self.assertEqual(f["lh"]["max_chord"], 3)
        self.assertEqual(f["shortest"], 0.5)
        self.assertEqual(f["out_of_key_per_bar"], 0.0)  # F# is in G major
        self.assertGreater(features.difficulty(f), 0)


if __name__ == "__main__":
    unittest.main()

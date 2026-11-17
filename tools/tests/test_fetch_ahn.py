"""AHN elevation for the Netherlands (tools/fetch_ahn.py) in the form tools/build_terrain.py reads."""
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools import tests  # noqa: F401  (puts tools/ on the path)
import build_terrain
import fetch_ahn


class Ahn(unittest.TestCase):
    def test_fill_gaps(self):
        h = np.full((5, 5), -3.0, np.float32)
        h[2, 2] = np.nan
        self.assertEqual(fetch_ahn.fill_gaps(h)[2, 2], -3.0)
        empty = np.full((4, 4), np.nan, np.float32)
        self.assertTrue(np.isnan(fetch_ahn.fill_gaps(empty)).all())

    def test_fill_gaps_only_between_land(self):
        """A hole with ground on both sides (a building, a canal) is filled; open water reaching the edge is not, and nor is a
        hole wider than twice the reach."""
        edge = np.full((1, 200), np.nan, np.float32)
        edge[0, 0] = 1.0
        self.assertTrue(np.isnan(fetch_ahn.fill_gaps(edge, passes=3)[0, 1:]).all())
        between = np.full((1, 12), np.nan, np.float32)
        between[0, 0], between[0, 11] = 1.0, 3.0
        filled = fetch_ahn.fill_gaps(between, passes=64)
        self.assertFalse(np.isnan(filled).any())
        self.assertTrue(1.0 <= filled[0, 5] <= 3.0)
        wide = np.full((1, 102), np.nan, np.float32)
        wide[0, 0], wide[0, 101] = 1.0, 3.0
        self.assertTrue(np.isnan(fetch_ahn.fill_gaps(wide, passes=10)[0, 50]))

    def test_cell_name(self):
        self.assertEqual(fetch_ahn.cell_name(53, 5), 'n53e005')
        self.assertEqual(fetch_ahn.cell_name(51, 3), 'n51e003')

    def test_written_tile_reads_in_build_terrain(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            h = np.linspace(-5, 5, 100, dtype=np.float32).reshape(10, 10)
            h[0, 0] = np.nan
            fetch_ahn.write_cell(tmp, 53, 5, h)
            build_terrain.init(tmp)
            self.assertEqual(set(build_terrain.CELLS), {(53, 5)})
            a, x0, y0, sx, sy = build_terrain.dem((53, 5))
            self.assertEqual((x0, y0), (5.0, 53.0))
            self.assertAlmostEqual(sx, 1 / 3600)
            self.assertAlmostEqual(sy, 1 / 3600)
            self.assertTrue(np.isnan(a[0, 0]))        # no data comes back as NaN
            self.assertAlmostEqual(float(a[9, 9]), 5.0, places=4)
        finally:
            build_terrain.dem.cache_clear()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()

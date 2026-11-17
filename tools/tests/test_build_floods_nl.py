"""Flood defences and flood scenarios for the Netherlands (tools/build_floods_nl.py)."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools import tests  # noqa: F401  (puts tools/ on the path)
import build_floods_nl as bf
from map_schema import unpack


def square(x, y, w, h):
    """A GeoJSON-style ring in RD New metres (closed, counter-clockwise)."""
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]


def feature(legend, *rings):
    return {'type': 'Feature', 'geometry': {'type': 'MultiPolygon', 'coordinates': [list(rings)]}, 'properties': {'legenda': legend}}


GRID = bf.Grid(x0=0, y0=0, pitch=25, nx=40, ny=40)


class Classes(unittest.TestCase):
    def test_depth_legend_to_class(self):
        self.assertEqual(bf.depth_class('minder dan 0,5 m'), 1)
        self.assertEqual(bf.depth_class('tussen 0,5 en 1,0 m'), 2)
        self.assertEqual(bf.depth_class('tussen 1,0 en 1,5 m'), 3)
        self.assertEqual(bf.depth_class('tussen 1,5 en 2,0 m'), 4)
        self.assertEqual(bf.depth_class('tussen 2,0 en 5,0 m'), 5)
        self.assertEqual(bf.depth_class('meer dan 5,0 m'), 6)

    def test_unknown_legend_is_an_error(self):
        with self.assertRaises(ValueError):
            bf.depth_class('tussen 5,0 en 9,0 m')

    def test_labels_are_english(self):
        self.assertEqual(bf.DEPTHS[0], 'less than 0.5 m deep')
        self.assertEqual(bf.DEPTHS[2], 'between 1.0 and 2.0 m deep')
        self.assertEqual(bf.DEPTHS[4], 'more than 5 m deep')

    def test_six_legend_classes_become_five(self):
        out = bf.merge_depths(np.array([0, 1, 2, 3, 4, 5, 6], np.uint8))
        self.assertEqual(out.tolist(), [0, 1, 2, 3, 3, 4, 5])
        self.assertEqual(len(bf.DEPTHS), 5)

    def test_downsample_keeps_the_sample_points(self):
        cls = np.arange(16, dtype=np.uint8).reshape(4, 4)
        grid = bf.Grid(x0=1000, y0=2000, pitch=25, nx=4, ny=4)
        out, g = bf.downsample(cls, grid, 2)
        self.assertEqual(out.tolist(), [[0, 2], [8, 10]])
        self.assertEqual((g.pitch, g.nx, g.ny), (50, 2, 2))
        # the first output cell is centred on the first input cell's centre: 1012.5
        self.assertEqual(g.x0 + g.pitch / 2, grid.x0 + grid.pitch / 2)
        self.assertEqual(g.y0 + g.pitch / 2, grid.y0 + grid.pitch / 2)


class Burn(unittest.TestCase):
    def test_square_covers_the_sample_points_inside_it(self):
        diff = np.zeros((GRID.ny, GRID.nx), np.uint8)
        bf.burn_page(diff, [feature('minder dan 0,5 m', square(100, 200, 50, 75))], GRID)
        cls = bf.coverage(diff)
        rows, cols = np.nonzero(cls)
        self.assertEqual((cols.min(), cols.max()), (4, 5))          # x 100..150 -> sample points 112.5 and 137.5
        self.assertEqual((rows.min(), rows.max()), (8, 10))         # y 200..275 -> 212.5, 237.5, 262.5
        self.assertEqual(int(cls[8, 4]), 1)
        self.assertEqual(rows.size, 6)

    def test_legend_property_may_be_upper_case(self):
        f = feature('meer dan 5,0 m', square(0, 0, 100, 100))
        f['properties'] = {'LEGENDA': 'meer dan 5,0 m'}                 # the t10000 layer spells it so
        diff = np.zeros((GRID.ny, GRID.nx), np.uint8)
        bf.burn_page(diff, [f], GRID)
        self.assertEqual(int(bf.coverage(diff)[0, 0]), 6)

    def test_hole_is_left_out(self):
        diff = np.zeros((GRID.ny, GRID.nx), np.uint8)
        outer, hole = square(0, 0, 200, 200), square(50, 50, 100, 100)[::-1]
        bf.burn_page(diff, [feature('meer dan 5,0 m', outer, hole)], GRID)
        cls = bf.coverage(diff)
        self.assertEqual(int(cls[0, 0]), 6)
        self.assertEqual(int(cls[3, 3]), 0)                          # centre 87.5, 87.5 is inside the hole
        self.assertEqual(int(np.count_nonzero(cls)), 8 * 8 - 4 * 4)

    def test_two_classes_side_by_side(self):
        diff = np.zeros((GRID.ny, GRID.nx), np.uint8)
        bf.burn_page(diff, [feature('minder dan 0,5 m', square(0, 0, 100, 100)), feature('tussen 1,5 en 2,0 m', square(100, 0, 100, 100))], GRID)
        cls = bf.coverage(diff)
        self.assertEqual(int(cls[0, 3]), 1)
        self.assertEqual(int(cls[0, 4]), 4)

    def test_pages_add_up(self):
        a = np.zeros((GRID.ny, GRID.nx), np.uint8)
        bf.burn_page(a, [feature('minder dan 0,5 m', square(0, 0, 100, 100))], GRID)
        bf.burn_page(a, [feature('minder dan 0,5 m', square(100, 0, 100, 100))], GRID)
        self.assertEqual(int(np.count_nonzero(bf.coverage(a))), 32)

    def test_slanted_sides_are_filled_too(self):
        diff = np.zeros((GRID.ny, GRID.nx), np.uint8)
        triangle = [[0, 0], [410, 0], [0, 410], [0, 0]]                  # below the diagonal x + y = 410, which no cell centre sits on
        bf.burn_page(diff, [feature('minder dan 0,5 m', triangle)], GRID)
        cls = bf.coverage(diff)
        for j in range(16):
            for i in range(16):
                inside = (i + 0.5) * 25 + (j + 0.5) * 25 < 410
                self.assertEqual(int(cls[j, i]) == 1, inside, (i, j))

    def test_closed_outlines_leave_every_row_balanced(self):
        diff = np.zeros((GRID.ny, GRID.nx), np.uint8)
        bf.burn_page(diff, [feature('minder dan 0,5 m', square(100, 200, 50, 75), [[300, 300], [380, 320], [340, 400], [300, 300]])], GRID)
        self.assertEqual(bf.unbalanced_rows(diff), 0)
        diff[3, 3] ^= 1                                                  # a stray edge: the fill would run on to the edge of the map
        self.assertEqual(bf.unbalanced_rows(diff), 1)

    def test_outside_the_grid_is_ignored(self):
        diff = np.zeros((GRID.ny, GRID.nx), np.uint8)
        bf.burn_page(diff, [feature('minder dan 0,5 m', square(-500, -500, 100, 100)), feature('minder dan 0,5 m', square(5000, 5000, 100, 100))], GRID)
        self.assertEqual(int(np.count_nonzero(bf.coverage(diff))), 0)


class Trace(unittest.TestCase):
    def area(self, ring):
        a = 0
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            a += x0 * y1 - x1 * y0
        return a / 2

    def test_one_rectangle_is_one_ring_of_four_corners(self):
        m = np.zeros((6, 6), bool)
        m[1:3, 2:5] = True
        rings = bf.trace(m)
        self.assertEqual(len(rings), 1)
        self.assertEqual(sorted(rings[0]), [(2, 1), (2, 3), (5, 1), (5, 3)])

    def test_a_hole_makes_a_second_ring_and_the_areas_add_up(self):
        m = np.ones((7, 7), bool)
        m[3, 3] = False
        rings = bf.trace(m)
        self.assertEqual(len(rings), 2)
        self.assertEqual(round(sum(self.area(r) for r in rings)), 48)

    def test_two_separate_cells_are_two_rings(self):
        m = np.zeros((5, 5), bool)
        m[0, 0] = m[3, 3] = True
        self.assertEqual(len(bf.trace(m)), 2)

    def test_cells_that_only_touch_at_a_corner_still_cover_the_same_area(self):
        m = np.zeros((4, 4), bool)
        m[0, 0] = m[1, 1] = True
        rings = bf.trace(m)
        self.assertEqual(round(sum(self.area(r) for r in rings)), 2)

    def test_empty(self):
        self.assertEqual(bf.trace(np.zeros((3, 3), bool)), [])

    def test_ring_area(self):
        self.assertEqual(bf.ring_area([(0, 0), (10, 0), (10, 5), (0, 5)]), 50)
        self.assertEqual(bf.ring_area([(0, 0), (0, 5), (10, 5), (10, 0)]), 50)           # either way round


class Simplify(unittest.TestCase):
    def test_a_staircase_becomes_a_diagonal(self):
        ring = [(0, 0), (1, 0), (1, 1), (2, 1), (2, 2), (3, 2), (3, 3), (0, 3)]
        out = bf.simplify_ring(ring, 1.1)
        self.assertLess(len(out), len(ring))
        self.assertIn((0, 0), out)
        self.assertIn((0, 3), out)

    def test_small_rings_survive_as_triangles_at_least(self):
        ring = [(0, 0), (1, 0), (1, 1), (0, 1)]
        self.assertGreaterEqual(len(bf.simplify_ring(ring, 5)), 3)


class Dikes(unittest.TestCase):
    def test_dike_rows(self):
        gj = {'features': [{'type': 'Feature', 'geometry': {'type': 'MultiLineString', 'coordinates': [[[155000, 463000], [155100, 463100]]]},
                            'properties': {'TRAJECT_ID': '14-3', 'NORM_OG': 3000, 'NORM_SW': 10000}}]}
        rows = list(bf.dike_rows(gj))
        self.assertEqual(len(rows), 1)
        name, parts = rows[0]
        self.assertEqual(name, 'Dike section 14-3 (safety standard: flooding no more likely than 1 in 3,000 a year)')
        lon, lat = parts[0][0], parts[0][1]
        self.assertAlmostEqual(lon, 5.39, delta=0.02)           # RD 155000, 463000 is the Onze Lieve Vrouwetoren in Amersfoort
        self.assertAlmostEqual(lat, 52.155, delta=0.02)

    def test_a_dike_without_a_norm_still_has_a_name(self):
        gj = {'features': [{'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[155000, 463000], [155100, 463100]]},
                            'properties': {'TRAJECT_ID': '99-9'}}]}
        self.assertEqual(list(bf.dike_rows(gj))[0][0], 'Dike section 99-9')


class Write(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_water(self):
        path = self.tmp / 'water.sqlite'
        db = sqlite3.connect(path)
        db.executescript('''CREATE TABLE feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB, origin TEXT);
          CREATE VIRTUAL TABLE feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);
          CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);''')
        db.execute("INSERT INTO feat VALUES (1,'water','lake','Plas',9,x'00000000','nhd:NL')")
        db.execute('INSERT INTO feat_idx VALUES (1,5,5.1,52,52.1,9,30)')
        db.commit()
        db.close()
        return path

    def test_writes_flood_and_dike_features_and_keeps_the_rest(self):
        path = self.make_water()
        parts = [[4.0, 52.0, 4.1, 52.0, 4.1, 52.1, 4.0, 52.1]]
        n = bf.write_features(path, floods=[('t100', 3, parts)], dikes=[('Dike section 1-1', [[4.0, 52.0, 4.1, 52.1]])], counts={'t100': 1})
        self.assertEqual(n, {'flood': 1, 'dike': 1})
        db = sqlite3.connect(path)
        rows = db.execute("SELECT layer, cls, name, minz, origin FROM feat ORDER BY id").fetchall()
        self.assertEqual(rows[0][:2], ('water', 'lake'))
        self.assertEqual(rows[1], ('flood', 't100-3', 'between 1.0 and 2.0 m deep', bf.FLOOD_MINZ, bf.ORIGIN))
        self.assertEqual(rows[2][:3], ('dike', 'primary', 'Dike section 1-1'))
        got = db.execute("SELECT geom FROM feat WHERE layer='flood'").fetchone()[0]
        self.assertAlmostEqual(unpack(got)[0][0], 4.0, places=5)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM feat_idx').fetchone()[0], 3)
        self.assertIsNotNone(db.execute("SELECT value FROM meta WHERE key=?", (bf.ORIGIN,)).fetchone())

    def test_rerun_replaces_only_its_own_rows(self):
        path = self.make_water()
        parts = [[4.0, 52.0, 4.1, 52.0, 4.1, 52.1]]
        for _ in range(2):
            bf.write_features(path, floods=[('t10', 1, parts)], dikes=[], counts={})
        db = sqlite3.connect(path)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM feat WHERE layer='flood'").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM feat WHERE layer='water'").fetchone()[0], 1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM feat_idx').fetchone()[0], 2)


class Blocks(unittest.TestCase):
    def test_small_pieces_are_dropped(self):
        cls = np.zeros((10, 10), np.uint8)
        cls[0, 0] = 2                                              # one cell
        cls[5:9, 5:9] = 2                                          # sixteen cells
        grid = bf.Grid(x0=100000, y0=400000, pitch=100, nx=10, ny=10)
        keep = list(bf.flood_polygons(cls, grid, block=10, tol_m=0, min_area_m2=100000))
        self.assertEqual(len(keep), 1)
        self.assertEqual(len(keep[0][1]), 1)                       # only the big square, 160,000 m2
        both = list(bf.flood_polygons(cls, grid, block=10, tol_m=0, min_area_m2=0))
        self.assertEqual(len(both[0][1]), 2)

    def test_a_class_grid_is_cut_into_blocks_per_scenario_class(self):
        cls = np.zeros((10, 10), np.uint8)
        cls[0:2, 0:2] = 1
        cls[0:2, 8:10] = 1
        cls[8:10, 8:10] = 3
        grid = bf.Grid(x0=100000, y0=400000, pitch=100, nx=10, ny=10)
        out = list(bf.flood_polygons(cls, grid, block=5, tol_m=0))
        self.assertEqual(sorted({c for c, _ in out}), [1, 3])
        self.assertEqual(len(out), 3)                              # (class 1, block 0,0), (class 1, block 0,1), (class 3, block 1,1)
        for c, parts in out:
            for p in parts:
                self.assertEqual(len(p) % 2, 0)
                self.assertTrue(all(3.0 < v < 7.5 for v in p[0::2]))      # lon, in degrees, in the Netherlands
                self.assertTrue(all(50.0 < v < 54.0 for v in p[1::2]))


if __name__ == '__main__':
    unittest.main()

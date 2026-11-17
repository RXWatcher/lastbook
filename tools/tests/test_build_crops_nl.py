"""Food crops that keep producing, for the Netherlands, from RVO's BRP crop parcels (tools/build_crops_nl.py)."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools import tests  # noqa: F401  (puts tools/ on the path)
from tools.tests.test_build_bag import polygon
import build_crops_nl


def make_brp(path, parcels):
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE brp_gewas(id INTEGER PRIMARY KEY, geom BLOB, category TEXT, gewas TEXT, gewascode INT, jaar INT, status TEXT)')
    for (x, y, w, h), code, name in parcels:
        ring = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        db.execute('INSERT INTO brp_gewas(geom, category, gewas, gewascode, jaar, status) VALUES (?,?,?,?,?,?)',
                   (polygon(ring), 'Bouwland', name, code, 2025, 'Definitief'))
    db.commit()
    db.close()


class Crops(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_crop_for(self):
        self.assertEqual(build_crops_nl.crop_for(1096), ('Apples', 'orchard'))
        self.assertEqual(build_crops_nl.crop_for(1869), ('Blueberries', 'berries'))
        self.assertEqual(build_crops_nl.crop_for(2710), ('Asparagus', 'perennial_veg'))
        self.assertEqual(build_crops_nl.crop_for(1099), ('Wine grapes', 'vineyard'))
        self.assertIsNone(build_crops_nl.crop_for(2014))       # potatoes ("Aardappelen" contains "appel")
        self.assertIsNone(build_crops_nl.crop_for(796))        # Christmas trees ("Kerstbomen" contains "kers")
        self.assertIsNone(build_crops_nl.crop_for(2700))       # strawberry propagation, not a harvest

    def test_block_resource(self):
        gpkg = self.tmp / 'brp.gpkg'
        make_brp(gpkg, [((140000, 440000, 600, 600), 1096, 'Appels. Aangeplant voorafgaande aan lopende seizoen.'),
                        ((150000, 440000, 600, 600), 2014, 'Aardappelen, consumptie')])
        out = self.tmp / 'crops.sqlite'
        build_crops_nl.build(gpkg, out, box=[5.0, 51.8, 5.5, 52.0])
        db = sqlite3.connect(out)
        rows = db.execute('SELECT kind, name, detail, source FROM resource').fetchall()
        self.assertTrue(rows)
        self.assertEqual({(k, n) for k, n, _, _ in rows}, {('orchard', 'Apples')})
        detail = json.loads(rows[0][2])
        self.assertEqual(set(detail), {'crop', 'crop_ha', 'perennial_ha', 'year'})
        self.assertAlmostEqual(sum(json.loads(d)['crop_ha'] for _, _, d, _ in rows), 36.0, delta=4)    # 600 m x 600 m = 36 ha
        self.assertEqual(db.execute('SELECT count(*) FROM spatial').fetchone()[0], len(rows))
        self.assertTrue(db.execute('SELECT count(*) FROM tile WHERE z=13').fetchone()[0] >= 1)
        self.assertTrue(db.execute('SELECT count(*) FROM tile WHERE z=7').fetchone()[0] >= 1)
        meta = dict(db.execute('SELECT key, value FROM meta'))
        self.assertEqual(json.loads(meta['built'])['year'], 2025)
        self.assertIn('RVO', meta['source'])
        db.close()


if __name__ == '__main__':
    unittest.main()

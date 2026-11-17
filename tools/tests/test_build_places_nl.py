"""The place finder for the Netherlands (tools/build_places_nl.py)."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools import tests  # noqa: F401  (puts tools/ on the path)
from tools.tests.test_build_bag import polygon
import build_map_osm
import build_places_nl
import map_schema


def square(x0, y0, size):
    return [x0, y0, x0 + size, y0, x0 + size, y0 + size, x0, y0 + size, x0, y0]


class Places(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        nat = sqlite3.connect(self.tmp / 'national.sqlite')
        map_schema.create_map_tables(nat)
        w = map_schema.MapWriter(nat)
        w.add('place', 'city', 'Utrecht', 6, [[5.12, 52.09]])
        w.poi('hospital_seh', 'UMC Utrecht', 5.18, 52.09)
        w.poi('pharmacy', None, 5.10, 52.08)                     # unnamed: nothing to find it by
        w.finish({})
        nat.close()
        bag = sqlite3.connect(self.tmp / 'bag.gpkg')
        bag.execute('CREATE TABLE woonplaats(feature_id INTEGER PRIMARY KEY, geom BLOB, status TEXT, woonplaats TEXT, bronhouder_identificatie TEXT)')
        # 's-Gravenhage: a 2 km square in RD around the Binnenhof (RD 81000, 455000)
        bag.execute("INSERT INTO woonplaats(geom, status, woonplaats, bronhouder_identificatie) VALUES (?,?,?,?)",
                    (polygon([(80000, 454000), (82000, 454000), (82000, 456000), (80000, 456000), (80000, 454000)]),
                     'Woonplaats aangewezen', "'s-Gravenhage", '0518'))
        bag.commit()
        bag.close()
        adm = build_map_osm.admin_db(self.tmp / 'admin.sqlite')
        for kind, name, code, ring in (('municipality', 'Den Haag', '0518', square(4.2, 52.0, 0.2)),
                                       ('province', 'Zuid-Holland', None, square(3.8, 51.7, 1.2))):
            b = map_schema.bbox([ring])
            adm.execute('INSERT INTO admin VALUES (?,?,?,?,?,?,?,?)', (kind, name, code, *b, map_schema.pack([ring])))
        adm.commit()
        adm.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self):
        out = self.tmp / 'places.sqlite'
        build_places_nl.build(self.tmp / 'national.sqlite', self.tmp / 'bag.gpkg', self.tmp / 'admin.sqlite', out)
        db = sqlite3.connect(out)
        rows = db.execute('SELECT name, kind, detail, rank, source FROM place ORDER BY name, kind').fetchall()
        hits = {q: [r[0] for r in db.execute('SELECT p.name FROM place_fts f JOIN place p ON p.id=f.rowid WHERE place_fts MATCH ?', (q,))]
                for q in ('"den"* "haag"*', '"gravenhage"*', '"utrecht"*')}
        db.close()
        return rows, hits

    def test_aliases_present(self):
        rows, hits = self.build()
        woon = [r for r in rows if r[0] == "'s-Gravenhage"]
        self.assertEqual(woon, [("'s-Gravenhage", 'town or village', 'Den Haag municipality, Zuid-Holland', 3, 'Kadaster BAG')])
        self.assertIn(('Den Haag', 'town or village', "also called 's-Gravenhage, Zuid-Holland", 3, 'Kadaster BAG'), rows)
        self.assertIn('Den Haag', hits['"den"* "haag"*'])
        self.assertIn("'s-Gravenhage", hits['"gravenhage"*'])

    def test_admin_and_osm_rows(self):
        rows, hits = self.build()
        self.assertIn(('Den Haag', 'municipality', 'Zuid-Holland', 2, 'OpenStreetMap'), rows)
        self.assertIn(('Zuid-Holland', 'province', 'Netherlands', 2, 'OpenStreetMap'), rows)
        self.assertIn(('Utrecht', 'city', 'Netherlands (OpenStreetMap)', 1, 'OpenStreetMap'), rows)
        self.assertIn(('UMC Utrecht', 'hospital seh', 'Netherlands (OpenStreetMap)', 4, 'OpenStreetMap'), rows)
        self.assertEqual(len([r for r in rows if r[1] == 'pharmacy']), 0)
        self.assertEqual(sorted(hits['"utrecht"*']), ['UMC Utrecht', 'Utrecht'])

    def test_centroid_square(self):
        self.assertEqual(build_places_nl.centroid([[0, 0, 1, 0, 1, 1, 0, 1, 0, 0]]), (0.5, 0.5))
        self.assertTrue(build_places_nl.inside(0.5, 0.5, [[0, 0, 1, 0, 1, 1, 0, 1, 0, 0]]))
        self.assertFalse(build_places_nl.inside(1.5, 0.5, [[0, 0, 1, 0, 1, 1, 0, 1, 0, 0]]))


if __name__ == '__main__':
    unittest.main()

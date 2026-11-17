"""The street map builder for an OSM PBF (tools/build_map_osm.py) and the schema it shares with tools/build_map.py."""
import sqlite3
import unittest
from array import array

from tools import tests  # noqa: F401  (puts tools/ on the path)
import map_schema
import build_map_osm


class Classify(unittest.TestCase):
    def test_classify_roads(self):
        self.assertEqual(build_map_osm.classify({'highway': 'track', 'tracktype': 'grade2'}, 'way'), [('feat', 'road', 'track_grade2')])
        self.assertEqual(build_map_osm.classify({'highway': 'residential', 'name': 'Damrak'}, 'way'), [('feat', 'road', 'residential')])

    def test_classify_help_points(self):
        c = build_map_osm.classify
        self.assertEqual(c({'emergency': 'defibrillator'}, 'node'), [('poi', 'defibrillator', None)])
        self.assertEqual(c({'emergency': 'assembly_point'}, 'node'), [('poi', 'assembly_point', None)])
        self.assertEqual(c({'amenity': 'hospital', 'emergency': 'yes'}, 'area'), [('poi', 'hospital_seh', None)])
        self.assertEqual(c({'amenity': 'hospital'}, 'area'), [('poi', 'hospital', None)])
        self.assertEqual(c({'amenity': 'doctors', 'name': 'Huisartsenpost Utrecht'}, 'node'), [('poi', 'huisartsenpost', None)])
        self.assertEqual(c({'amenity': 'clinic', 'name': 'HAP Gouda'}, 'node'), [('poi', 'huisartsenpost', None)])
        self.assertEqual(c({'amenity': 'doctors', 'name': 'Haptonomie'}, 'node'), [('poi', 'doctors', None)])
        self.assertEqual(c({'shop': 'supermarket'}, 'node'), [('poi', 'supermarket', None)])
        self.assertEqual(c({'natural': 'spring'}, 'node'), [('poi', 'spring', None)])

    def test_classify_areas(self):
        c = build_map_osm.classify
        self.assertEqual(c({'natural': 'water', 'water': 'lake'}, 'area'), [('feat', 'water', 'lake')])
        self.assertEqual(c({'natural': 'water'}, 'area'), [('feat', 'water', 'water')])
        self.assertEqual(c({'natural': 'wetland'}, 'area'), [('feat', 'wet', 'wetland')])
        self.assertEqual(c({'landuse': 'farmland'}, 'area'), [('feat', 'land', 'farm')])      # LANDUSE_KEEP's style name, as build_map stores it
        self.assertEqual(c({'leisure': 'nature_reserve'}, 'area'), [('feat', 'land', 'park')])
        self.assertEqual(c({'natural': 'beach'}, 'area'), [('feat', 'beach', 'beach')])
        self.assertEqual(c({'waterway': 'canal'}, 'way'), [('feat', 'waterway', 'canal')])
        self.assertEqual(c({'railway': 'rail'}, 'way'), [('feat', 'rail', 'rail')])
        self.assertEqual(c({'place': 'town', 'name': 'Gouda'}, 'node'), [('feat', 'place', 'town')])
        self.assertEqual(c({'place': 'town'}, 'node'), [])             # a place without a name has nothing to show

    def test_classify_skips_buildings(self):
        self.assertEqual(build_map_osm.classify({'building': 'yes'}, 'area'), [])
        self.assertEqual(build_map_osm.classify({'building': 'yes', 'amenity': 'pharmacy'}, 'area'), [('poi', 'pharmacy', None)])


class Schema(unittest.TestCase):
    def test_pack_unchanged(self):
        """map_schema.pack is build_map.pack moved: nparts, then npts and delta-coded lon/lat x 1e6 per part."""
        packed = map_schema.pack([[1.0, 2.0, 1.5, 2.5], [0.0, 0.0]])
        self.assertEqual(array('i', packed).tolist(), [2, 2, 1000000, 2000000, 500000, 500000, 1, 0, 0])

    def test_writer_tables(self):
        db = sqlite3.connect(':memory:')
        map_schema.create_map_tables(db)
        w = map_schema.MapWriter(db)
        w.add('road', 'residential', 'Damrak', 13, [[4.89, 52.37, 4.90, 52.38]])
        w.poi('defibrillator', None, 4.89, 52.37)
        w.finish({'source': 'test'})
        self.assertEqual(db.execute('SELECT layer, cls, name, minz FROM feat').fetchall(), [('road', 'residential', 'Damrak', 13)])
        self.assertEqual(db.execute('SELECT minx, maxx, miny, maxy, minz, maxz FROM feat_idx').fetchone()[4:], (13, 30))
        self.assertEqual(db.execute('SELECT cls, lon, lat FROM poi').fetchall(), [('defibrillator', 4.89, 52.37)])
        self.assertEqual(dict(db.execute('SELECT key, value FROM meta')), {'source': 'test'})
        self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='poi_cls'").fetchone())


if __name__ == '__main__':
    unittest.main()

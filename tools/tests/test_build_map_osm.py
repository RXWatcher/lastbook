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

    def test_huisartsenpost_names(self):
        c = build_map_osm.classify
        hap = [('poi', 'huisartsenpost', None)]
        doctors = lambda name, **kw: dict({'amenity': 'doctors', 'name': name}, **kw)
        for name in ('Huisartsenspoedpost Breda', 'Huisartenspoedpost Zeist', 'Spoedpost', 'Spoedpost Alrijne', 'Spoedpost Huisartsen Apeldoorn',
                     'Dokterswacht Friesland', 'dokterswacht Friesland', 'SMC Huisartsenpost', 'huisartsenpost Arnhem Noord', 'HAP Havelte'):
            self.assertEqual(c(doctors(name), 'node'), hap, name)
        self.assertEqual(c({'amenity': 'clinic', 'name': 'Huisartsenspoedpost Dirksland'}, 'node'), hap)
        self.assertEqual(c({'healthcare': 'doctor', 'name': 'Huisartsenspoedpost'}, 'node'), hap)           # no amenity tag
        self.assertEqual(c({'building': 'hospital', 'healthcare': 'yes', 'name': 'Huisartsenpost'}, 'area'), hap)
        # ordinary practices, emergency departments, dentists, pharmacies and food shops are not out-of-hours GP posts
        for tags in (doctors('Huisartsenpraktijk Acht'), doctors('Huisartsenmaatschap Delfgauw'), doctors('Spoedeisende hulp'),
                     doctors('Spoedtest', healthcare='sample_collection'), doctors('Haptonomie Utrecht'), doctors('Hapert Medisch'),
                     {'amenity': 'dentist', 'name': 'Tandartsspoedpraktijk'}, {'amenity': 'dentist', 'name': 'Spoed Tandarts Zeeland'},
                     {'amenity': 'pharmacy', 'name': 'Spoedapotheek Den Haag'}, {'amenity': 'fast_food', 'name': 'De Snelle Hap'},
                     {'amenity': 'parking', 'name': 'Huisartsenspoedpost Zeist'}, {'amenity': 'restaurant', 'name': 'Hap Hmm'},
                     {'emergency': 'emergency_ward_entrance', 'name': 'Spoedpost Ter Gooi'}, doctors('Huisartsenpraktijk H. Post'),
                     doctors('Lijfarts Spoedpoli')):
            self.assertNotEqual(c(tags, 'node'), hap, tags)

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


class EmergencyDepartments(unittest.TestCase):
    """A hospital that OpenStreetMap does not tag emergency=yes, but which has an emergency-ward entrance mapped at it, has an SEH."""

    def test_entrance_marks_hospital(self):
        db = sqlite3.connect(':memory:')
        map_schema.create_map_tables(db)
        w = map_schema.MapWriter(db)
        w.poi('hospital', 'ZGT Hengelo', 6.7900, 52.2650)
        w.poi('hospital', 'Far away hospital', 5.0000, 52.0000)
        w.poi('hospital_seh', 'Already tagged', 4.9000, 52.3700)
        w.poi('clinic', 'A clinic beside an entrance', 6.7901, 52.2651)
        n = build_map_osm.mark_emergency_departments(db, [(6.7915, 52.2660)])      # about 140 m away
        self.assertEqual(n, 1)
        self.assertEqual(dict(db.execute('SELECT name, cls FROM poi')), {
            'ZGT Hengelo': 'hospital_seh', 'Far away hospital': 'hospital', 'Already tagged': 'hospital_seh', 'A clinic beside an entrance': 'clinic'})

    def test_entrance_nodes_are_collected(self):
        self.assertTrue(build_map_osm.is_emergency_entrance({'emergency': 'emergency_ward_entrance'}))
        self.assertFalse(build_map_osm.is_emergency_entrance({'emergency': 'defibrillator'}))


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

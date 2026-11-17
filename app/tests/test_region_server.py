"""The server's map info, help labels and water results follow the installed region (engine/regions.py)."""
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server

NL_CREDITS = '© OpenStreetMap contributors · Kadaster BAG · AHN · RVO BRP · Natural Earth'


class RegionServer(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        (self.data / 'derived/geo').mkdir(parents=True)
        (self.data / 'pack.json').write_text(json.dumps({'name': 'small', 'map': 'base'}))
        server._pack.clear()
        server.map_contents.cache_clear()

    def tearDown(self):
        server._pack.clear()
        server.map_contents.cache_clear()
        shutil.rmtree(self.data, ignore_errors=True)

    def info(self, region):
        (self.data / 'map-set.json').write_text(json.dumps({'name': region}))
        with patch.object(server, 'HERE', self.data):
            return server.map_info()

    def test_region_in_map_info_nl(self):
        db = sqlite3.connect(self.data / 'derived/geo/national.sqlite')
        db.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES ('data_as_of', '2026-11-16T21:21:03Z');")
        db.close()
        r = self.info('NL')['region']
        self.assertEqual((r['id'], r['name'], r['kind'], r['units']), ('NL', 'Netherlands', 'country', 'metric'))
        self.assertEqual(r['attribution'], NL_CREDITS)
        self.assertEqual(r['search_hint'], 'Find an address, postcode or town')
        self.assertEqual(r['data_as_of'], '2026-11-16')

    def test_region_in_map_info_us(self):
        r = self.info('CA')['region']
        self.assertEqual((r['id'], r['units'], r['attribution'], r['data_as_of']), ('CA', 'imperial', None, None))
        self.assertEqual(r['search_hint'], 'Find an address, town or ZIP')

    def test_region_in_map_info_none(self):
        with patch.object(server, 'HERE', self.data):
            r = server.map_info()['region']
        self.assertEqual((r['id'], r['units'], r['attribution']), (None, 'imperial', None))

    def test_nl_datasets(self):
        labels = ' '.join(d['label'] for d in self.info('NL')['datasets'])
        self.assertIn('Kadaster BAG', labels)
        self.assertIn('AHN', labels)
        self.assertNotIn('USGS', labels)
        us = ' '.join(d['label'] for d in self.info('CA')['datasets'])
        self.assertIn('USGS', us)

    def test_help_labels(self):
        self.assertEqual(server.HELP['hospital_seh'], 'Hospital with emergency department')
        self.assertEqual(server.HELP['huisartsenpost'], 'Out-of-hours GP (huisartsenpost)')
        self.assertEqual(server.HELP['defibrillator'], 'Defibrillator (AED)')
        self.assertEqual(server.HELP['assembly_point'], 'Emergency assembly point')
        for cls in ('hospital_seh', 'huisartsenpost', 'defibrillator', 'assembly_point'):
            self.assertIn(cls, server.TILE_POI)

    def test_water_places_metric(self):
        water = self.data / 'water.sqlite'
        db = sqlite3.connect(water)
        db.executescript("CREATE TABLE resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT, origin TEXT);"
                         "CREATE VIRTUAL TABLE water_fts USING fts5(name, other);"
                         "INSERT INTO resource VALUES (1,'osm:1','lake','IJsselmeer',52.8,5.3,'{}','x','osm');"
                         "INSERT INTO water_fts(rowid,name,other) VALUES (1,'IJsselmeer','');")
        db.close()
        (self.data / 'map-set.json').write_text(json.dumps({'name': 'NL'}))
        with patch.object(server, 'HERE', self.data), patch.object(server, 'WATERDB', water):
            r = server.water_places('IJsselmeer', near=(52.09, 5.12))
        self.assertEqual(r[0]['name'], 'IJsselmeer')
        self.assertTrue(r[0]['detail'].startswith('Netherlands · '), r[0]['detail'])
        self.assertTrue(r[0]['detail'].endswith(' km away'), r[0]['detail'])


if __name__ == '__main__':
    unittest.main()

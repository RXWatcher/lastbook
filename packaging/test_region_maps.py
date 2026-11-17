"""A region's map set (packaging/region_maps.py): assembled from the builders' files, checked, zipped with its address index and
listed for setup.

  .venv/bin/python -I -B packaging/test_region_maps.py -v
"""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / 'packaging', ROOT / 'tools'):
    sys.path.insert(0, str(p))
import map_sets                       # noqa: E402
import region_maps                    # noqa: E402
import map_schema                     # noqa: E402
from engine import address_nl         # noqa: E402
from engine.setup import manifest     # noqa: E402

ELEVEN = {'derived/geo/national.sqlite', 'derived/geo/map.sqlite', 'derived/geo/water.sqlite', 'derived/geo/terrain.sqlite',
          'derived/geo/buildings.sqlite', 'derived/geo/crops.sqlite', 'derived/geo/places.sqlite', 'derived/geo/national-status.json',
          'derived/geo/socal-cells.json', 'library-data/geography/resources/atlas.sqlite', 'map-set.json'}


def make_sources(src):
    """The builders' outputs, in miniature: one road in Utrecht, one tile, one building, one crop cell, one place, one address."""
    src.mkdir(parents=True)
    db = sqlite3.connect(src / 'national.sqlite')
    map_schema.create_map_tables(db)
    w = map_schema.MapWriter(db)
    w.add('road', 'residential', 'Neude', 13, [[5.118, 52.092, 5.119, 52.093]])
    w.poi('defibrillator', None, 5.118, 52.092)
    w.finish({'source': 'OpenStreetMap contributors (ODbL 1.0)', 'data_as_of': '2026-11-16T21:00:00Z'})
    db.close()
    db = sqlite3.connect(src / 'water.sqlite')
    db.executescript('CREATE TABLE resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT, origin TEXT);'
                     'CREATE VIRTUAL TABLE spatial USING rtree(id, minx, maxx, miny, maxy);'
                     'CREATE TABLE feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB, origin TEXT);'
                     'CREATE VIRTUAL TABLE feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);'
                     'CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT); CREATE TABLE nhd_seen(pid TEXT PRIMARY KEY, origin TEXT);'
                     'CREATE VIRTUAL TABLE water_fts USING fts5(name, other);')
    db.close()
    db = sqlite3.connect(src / 'terrain.sqlite')
    db.executescript("CREATE TABLE tile(z INT, x INT, y INT, png BLOB, PRIMARY KEY(z,x,y)) WITHOUT ROWID; CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);"
                     "CREATE TABLE done(x INT, y INT, h8 BLOB, PRIMARY KEY(x,y)) WITHOUT ROWID; INSERT INTO tile VALUES (12, 2106, 1351, x'00');"
                     "INSERT INTO done VALUES (131, 84, NULL); INSERT INTO meta VALUES ('source', 'AHN4 DTM');")
    db.close()
    db = sqlite3.connect(src / 'buildings.sqlite')
    for t in ('bldg', 'bldg_socal', 'bldg_osm'):
        db.execute(f'CREATE TABLE {t}(x INT, y INT, part INT, n INT, data BLOB, PRIMARY KEY(x,y,part)) WITHOUT ROWID')
    db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)')
    db.execute("INSERT INTO bldg VALUES (8424, 5405, 0, 1, x'00')")      # z14 tile holding Utrecht's Neude
    db.commit()
    db.close()
    db = sqlite3.connect(src / 'crops.sqlite')
    db.executescript('CREATE TABLE resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT);'
                     'CREATE VIRTUAL TABLE spatial USING rtree(id, minx, maxx, miny, maxy);'
                     'CREATE TABLE tile(z INT, x INT, y INT, png BLOB, PRIMARY KEY(z,x,y)) WITHOUT ROWID; CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);')
    db.close()
    db = sqlite3.connect(src / 'places.sqlite')
    db.executescript("CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, detail TEXT, lat REAL, lon REAL, rank INTEGER, source TEXT);"
                     "CREATE VIRTUAL TABLE place_fts USING fts5(name, detail, content='place', content_rowid='id', tokenize='unicode61');"
                     "INSERT INTO place(name,kind,detail,lat,lon,rank,source) VALUES ('Utrecht','city','Netherlands (OpenStreetMap)',52.09,5.12,1,'OpenStreetMap');"
                     "INSERT INTO place_fts(place_fts) VALUES ('rebuild');")
    db.close()
    (src / 'addresses').mkdir()
    db = sqlite3.connect(src / 'addresses' / 'NL.sqlite')
    address_nl.create_index(db)
    db.execute("INSERT INTO nl_addr VALUES ('3512AE', 11, '', '', 'Neude', 'neude', 'Utrecht', 'utrecht', 52.0925, 5.1185)")
    address_nl.finish_index(db, 1, 'test')
    db.close()


class RegionMaps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / 'geo-nl'
        make_sources(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_assemble_and_check(self):
        dest = self.tmp / 'NL'
        info = region_maps.assemble('NL', self.src, dest)
        files = {p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()}
        self.assertEqual(files, ELEVEN)
        self.assertEqual(info['name'], 'NL')
        self.assertEqual(region_maps.check(dest, 'NL'), [])
        status = json.loads((dest / 'derived/geo/national-status.json').read_text())
        self.assertEqual(status, {'state': 'complete', 'stage': 'ready', 'features': 1})
        db = sqlite3.connect(dest / 'derived/geo/terrain.sqlite')
        self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='done'").fetchone())
        db.close()

    def test_check_catches(self):
        dest = self.tmp / 'NL'
        region_maps.assemble('NL', self.src, dest)
        db = sqlite3.connect(dest / 'derived/geo/map.sqlite')
        db.execute("INSERT INTO poi VALUES (1, 'hospital', 'x', 5.1, 52.1)")
        db.commit()
        db.close()
        (dest / 'derived/geo/extra.sqlite').write_bytes(b'')
        fails = region_maps.check(dest, 'NL')
        self.assertTrue(any('map.sqlite' in f for f in fails), fails)
        self.assertTrue(any('extra' in f for f in fails), fails)

    def test_check_catches_buildings_outside(self):
        dest = self.tmp / 'NL'
        region_maps.assemble('NL', self.src, dest)
        db = sqlite3.connect(dest / 'derived/geo/buildings.sqlite')
        db.execute("INSERT INTO bldg VALUES (2861, 6551, 0, 1, x'00')")    # Los Angeles
        db.commit()
        db.close()
        self.assertTrue(any('outside' in f for f in region_maps.check(dest, 'NL')))

    def test_package_entries_validate(self):
        dest = self.tmp / 'NL'
        region_maps.assemble('NL', self.src, dest)
        zips = self.tmp / 'zips'
        entries = region_maps.package('NL', dest, self.src / 'addresses' / 'NL.sqlite', zips)
        with zipfile.ZipFile(zips / 'Lastbook-Map-NL.zip') as z:
            self.assertEqual(set(z.namelist()), ELEVEN)
        with zipfile.ZipFile(zips / 'Lastbook-Addresses-NL.zip') as z:
            self.assertEqual(z.namelist(), ['derived/geo/addresses/NL.sqlite'])
        maps, addresses = entries
        m = manifest.validate({'version': 1, 'maps': [maps], 'address_indexes': [addresses]})
        self.assertIsNotNone(m)
        self.assertEqual((m['maps'][0]['local_only'], m['maps'][0]['kind'], m['maps'][0]['available']), (True, 'country', True))
        self.assertEqual(m['address_indexes'][0]['local_only'], True)
        self.assertEqual(maps['files'][0]['url'], 'https://downloads.lastbook.org/maps/Lastbook-Map-NL.zip')

    def test_merge_into_manifest(self):
        dest = self.tmp / 'NL'
        region_maps.assemble('NL', self.src, dest)
        entries = region_maps.package('NL', dest, self.src / 'addresses' / 'NL.sqlite', self.tmp / 'zips')
        path = self.tmp / 'release' / 'manifest-v1.json'
        region_maps.list_in_manifest(path, *entries)
        region_maps.list_in_manifest(path, *entries)              # twice: replaced, not repeated
        m = json.loads(path.read_text())
        self.assertEqual([x['id'] for x in m['maps']], ['NL'])
        self.assertEqual([x['id'] for x in m['address_indexes']], ['NL'])
        self.assertEqual(m['version'], 1)

    def test_state_maps_shares_the_contract(self):
        self.assertEqual(map_sets.ALLOWED, ELEVEN)
        text = (ROOT / 'packaging' / 'state_maps.py').read_text()
        self.assertIn('from map_sets import ALLOWED, make_zip', text)


if __name__ == '__main__':
    unittest.main()

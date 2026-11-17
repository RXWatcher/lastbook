"""Flood outlines and dike lines (tools/build_floods_nl.py) come out of the server as their own tiles, and not in the base tile."""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

server = None     # imported in setUp: importing it here would fix its data folder before test_bridge's fixture sets one

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from map_schema import pack            # noqa: E402

Z, X, Y = 10, 524, 338                 # a zoom-10 tile over Rotterdam (lon 4.21 to 4.57, lat 51.8 to 52.0)
SQUARE = [[4.3, 51.9, 4.5, 51.9, 4.5, 52.0, 4.3, 52.0]]


class FloodTiles(unittest.TestCase):
    def setUp(self):
        global server
        import server
        self.tmp = Path(tempfile.mkdtemp())
        self.water = self.tmp / 'water.sqlite'
        db = sqlite3.connect(self.water)
        db.executescript('''CREATE TABLE resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT, origin TEXT);
          CREATE TABLE feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB, origin TEXT);
          CREATE VIRTUAL TABLE feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);''')
        for i, (layer, cls, name, minz, parts) in enumerate([
                ('water', 'lake', 'Plas', 8, SQUARE), ('flood', 't100-3', 'between 1.0 and 1.5 m deep', 8, SQUARE),
                ('flood', 't1000-5', 'between 2.0 and 5.0 m deep', 8, SQUARE), ('dike', 'primary', 'Dike section 1-1', 7, [[4.3, 51.95, 4.5, 51.95]]),
                ('flood', 't100-1', 'less than 0.5 m deep', 8, [[9.0, 40.0, 9.1, 40.0, 9.1, 40.1]])], 1):
            db.execute('INSERT INTO feat VALUES (?,?,?,?,?,?,?)', (i, layer, cls, name, minz, pack(parts), 'x' if layer == 'water' else 'floods-nl'))
            xs, ys = parts[0][0::2], parts[0][1::2]
            db.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (i, min(xs), max(xs), min(ys), max(ys), minz, 30))
        db.execute("INSERT INTO resource VALUES (1,'a','reservoir','Plas',51.95,4.4,'{}','x','x')")
        db.execute("INSERT INTO resource VALUES (2,'b','lake','Meer',51.95,4.4,'{}','x','x')")
        db.commit()
        db.close()
        self.patch = patch.object(server, 'WATERDB', self.water)
        self.patch.start()
        server._flood_tile.cache_clear()
        server._map_tile.cache_clear()
        server.map_contents.cache_clear()
        if hasattr(server._tls, 'water'):
            del server._tls.water

    def tearDown(self):
        self.patch.stop()
        server._flood_tile.cache_clear()
        server._map_tile.cache_clear()
        server.map_contents.cache_clear()
        for a in ('water', 'floods'):
            if hasattr(server._tls, a):
                delattr(server._tls, a)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tile(self, want, z=Z):
        return json.loads(server.flood_tile(z, X, Y, want))

    def test_scenario_and_dike(self):
        layers = self.tile('t100,dike')['layers']
        self.assertEqual([(c, n) for c, n, _ in layers['flood']], [('t100-3', 'between 1.0 and 1.5 m deep')])
        self.assertEqual([c for c, _, _ in layers['dike']], ['primary'])
        self.assertNotIn('water', layers)

    def test_only_what_was_asked_for(self):
        layers = self.tile('t1000')['layers']
        self.assertEqual([c for c, _, _ in layers['flood']], ['t1000-5'])
        self.assertNotIn('dike', layers)
        self.assertEqual(self.tile('dike')['layers'].keys(), {'dike'})

    def test_nothing_asked_nothing_returned(self):
        self.assertEqual(self.tile('')['layers'], {})
        self.assertEqual(self.tile('nonsense,t5')['layers'], {})

    def test_flood_is_a_filled_ring_inside_the_tile(self):
        parts = self.tile('t100')['layers']['flood'][0][2]
        ring = parts[0]
        self.assertGreaterEqual(len(ring), 6)
        self.assertTrue(all(0 <= v <= 512 for v in ring))

    def test_zoom_below_the_features_minimum_has_no_flood(self):
        self.assertEqual(self.tile('t100,dike', z=7)['layers'].get('flood'), None)

    def test_far_away_tile_is_empty(self):
        self.assertEqual(json.loads(server.flood_tile(Z, 0, 0, 't100,dike'))['layers'], {})

    def test_base_tile_leaves_them_out(self):
        class Db:                                      # no street map: a water file alone
            pass
        with patch.object(server, 'mapdb', return_value=sqlite3.connect(':memory:')), patch.object(server, 'national_mapdb', return_value=None):
            mem = server.mapdb()
            mem.executescript('CREATE TABLE feat(id,layer,cls,name,minz,geom); CREATE VIRTUAL TABLE feat_idx USING rtree(id,minx,maxx,miny,maxy,minz,maxz);')
            with patch.object(server, 'mapdb', return_value=mem):
                layers = json.loads(server._map_tile(Z, X, Y, 'v'))['layers']
        self.assertEqual(sorted(layers), ['water'])

    def test_map_contents_names_the_flood_layers(self):
        with patch.object(server, 'HERE', self.tmp), patch.object(server, 'MAPDB', self.tmp / 'none.sqlite'):
            kinds = server.map_contents()['layers']
        self.assertIn('dike', kinds)
        self.assertIn('flood_t100', kinds)
        self.assertIn('flood_t1000', kinds)
        self.assertNotIn('flood_t10', kinds)


if __name__ == '__main__':
    unittest.main()

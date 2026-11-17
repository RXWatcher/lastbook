"""Building outlines and Dutch addresses from Kadaster BAG (tools/build_bag.py)."""
import gzip
import json
import shutil
import sqlite3
import struct
import tempfile
import unittest
import zlib
from array import array
from pathlib import Path

from tools import tests  # noqa: F401  (puts tools/ on the path)
import build_bag
import build_buildings
from engine import address_nl


def gpkg_geom(wkb, srs=28992):
    return b'GP' + bytes([0, 1]) + struct.pack('<i', srs) + wkb


def point(x, y):
    return gpkg_geom(struct.pack('<BIdd', 1, 1, x, y))


def polygon(ring):
    return gpkg_geom(struct.pack('<BII', 1, 3, 1) + struct.pack('<I', len(ring)) + b''.join(struct.pack('<dd', *p) for p in ring))


ADDRESS_COLS = ('feature_id INTEGER PRIMARY KEY, geom BLOB, status TEXT, openbare_ruimte_naam TEXT, huisnummer INT, huisletter TEXT, '
                'toevoeging TEXT, postcode TEXT, woonplaats_naam TEXT')


def make_bag(path):
    db = sqlite3.connect(path)
    for t in ('verblijfsobject', 'ligplaats', 'standplaats'):
        db.execute(f'CREATE TABLE {t}({ADDRESS_COLS})')
    db.execute('CREATE TABLE pand(feature_id INTEGER PRIMARY KEY, geom BLOB, identificatie TEXT, status TEXT)')
    rows = [(point(121400, 487900), 'Verblijfsobject in gebruik', 'Damrak', 1, None, None, '1012LG', 'Amsterdam'),
            (point(121401, 487901), 'Verblijfsobject in gebruik', 'Damrak', 1, 'A', None, '1012LG', 'Amsterdam'),
            (point(121402, 487902), 'Verblijfsobject in gebruik (niet ingemeten)', 'Damrak', 3, None, 'II', '1012LG', 'Amsterdam'),
            (point(121403, 487903), 'Verblijfsobject gevormd', 'Damrak', 5, None, None, '1012LG', 'Amsterdam')]   # not built yet
    db.executemany('INSERT INTO verblijfsobject(geom,status,openbare_ruimte_naam,huisnummer,huisletter,toevoeging,postcode,woonplaats_naam) '
                   'VALUES (?,?,?,?,?,?,?,?)', rows)
    db.execute('INSERT INTO ligplaats(geom,status,openbare_ruimte_naam,huisnummer,postcode,woonplaats_naam) VALUES (?,?,?,?,?,?)',
               (polygon([(121500, 488000), (121510, 488000), (121510, 488004), (121500, 488000)]), 'Plaats aangewezen', 'Prins Hendrikkade', 40,
                '1012TL', 'Amsterdam'))
    db.executemany('INSERT INTO pand(geom,identificatie,status) VALUES (?,?,?)', [
        (polygon([(121390, 487890), (121410, 487890), (121410, 487910), (121390, 487910), (121390, 487890)]), '0363100012345678', 'Pand in gebruik'),
        (polygon([(121600, 487890), (121610, 487890), (121610, 487900), (121600, 487890)]), '0363100012345679', 'Bouwvergunning verleend')])   # not built
    db.commit()
    db.close()


class Bag(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_encode_matches_build_buildings(self):
        ring = [[4.8950, 52.3750], [4.8960, 52.3750], [4.8960, 52.3756], [4.8950, 52.3756], [4.8950, 52.3750]]
        src = self.tmp / 'one.csv.gz'
        with gzip.open(src, 'wt') as f:
            f.write(json.dumps({'type': 'Feature', 'properties': {'height': -1}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}) + '\n')
        rows, n, skipped, _ = build_buildings.convert((0, src, False))
        self.assertEqual((n, skipped), (1, 0))
        rec, keys = build_bag.encode_building([tuple(p) for p in ring[:-1]], 0)
        self.assertEqual(keys, {(x, y) for x, y, *_ in rows})
        for x, y, part, count, data in rows:
            self.assertEqual(zlib.decompress(data), rec.tobytes())

    def test_address_rows(self):
        gpkg = self.tmp / 'bag.gpkg'
        make_bag(gpkg)
        out = self.tmp / 'out'
        build_bag.build(gpkg, out)
        db = sqlite3.connect(out / 'addresses' / 'NL.sqlite')
        rows = db.execute('SELECT postcode, num, letter, addition, street, norm, city, city_norm FROM nl_addr ORDER BY street, num, letter').fetchall()
        self.assertEqual(rows, [('1012LG', 1, '', '', 'Damrak', 'damrak', 'Amsterdam', 'amsterdam'),
                                ('1012LG', 1, 'A', '', 'Damrak', 'damrak', 'Amsterdam', 'amsterdam'),
                                ('1012LG', 3, '', 'II', 'Damrak', 'damrak', 'Amsterdam', 'amsterdam'),
                                ('1012TL', 40, '', '', 'Prins Hendrikkade', 'prins hendrikkade', 'Amsterdam', 'amsterdam')])
        lat, lon = db.execute("SELECT lat, lon FROM nl_addr WHERE num=1 AND letter=''").fetchone()
        self.assertAlmostEqual(lat, 52.3758, places=2)     # RD 121400,487900 is on the Damrak
        self.assertAlmostEqual(lon, 4.8979, places=2)
        self.assertEqual(dict(db.execute('SELECT key, value FROM meta'))['style'], 'nl')
        db.close()
        hit = address_nl.find('Damrak 3-2', [out / 'addresses' / 'NL.sqlite'])
        self.assertEqual([h['name'] for h in hit], ['Damrak 3-II'])

    def test_buildings_table(self):
        gpkg = self.tmp / 'bag.gpkg'
        make_bag(gpkg)
        out = self.tmp / 'out'
        build_bag.build(gpkg, out)
        db = sqlite3.connect(out / 'buildings.sqlite')
        self.assertEqual(dict(db.execute('SELECT key, value FROM meta'))['buildings'], '1')
        n = sum(c for (c,) in db.execute('SELECT n FROM bldg'))
        self.assertGreaterEqual(n, 1)
        for t in ('bldg_socal', 'bldg_osm'):
            self.assertEqual(db.execute(f'SELECT count(*) FROM {t}').fetchone()[0], 0)
        rec = array('i', zlib.decompress(db.execute('SELECT data FROM bldg').fetchone()[0]))
        self.assertEqual((rec[0], rec[1]), (4, 0))     # four points (the closing one dropped), no height
        db.close()

    def test_heights_from_3dbag(self):
        gpkg = self.tmp / 'bag.gpkg'
        make_bag(gpkg)
        heights = self.tmp / 'heights.sqlite'
        db = sqlite3.connect(heights)
        db.executescript('CREATE TABLE height(pand INTEGER PRIMARY KEY, dm INT) WITHOUT ROWID; CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);'
                         "INSERT INTO height VALUES (363100012345678, 215), (363100012345679, 99);")
        db.commit(); db.close()
        out = self.tmp / 'out'
        build_bag.build(gpkg, out, heights=heights)
        db = sqlite3.connect(out / 'buildings.sqlite')
        meta = dict(db.execute('SELECT key, value FROM meta'))
        self.assertEqual((meta['buildings'], meta['with_height']), ('1', '1'))
        self.assertIn('3DBAG by tudelft3d and 3DGI', meta['source'])
        rec = array('i', zlib.decompress(db.execute('SELECT data FROM bldg').fetchone()[0]))
        self.assertEqual((rec[0], rec[1]), (4, 215))   # the building under construction has no record, so its height is not used
        db.close()

    def test_buildings_only(self):
        gpkg = self.tmp / 'bag.gpkg'
        make_bag(gpkg)
        out = self.tmp / 'out'
        self.assertEqual(build_bag.build(gpkg, out, addresses=False), (0, 1))
        self.assertTrue((out / 'buildings.sqlite').exists())
        self.assertFalse((out / 'addresses').exists())

    def test_no_heights_file_keeps_zero(self):
        gpkg = self.tmp / 'bag.gpkg'
        make_bag(gpkg)
        out = self.tmp / 'out'
        build_bag.build(gpkg, out)
        meta = dict(sqlite3.connect(out / 'buildings.sqlite').execute('SELECT key, value FROM meta'))
        self.assertEqual(meta['with_height'], '0')
        self.assertNotIn('3DBAG', meta['source'])


if __name__ == '__main__':
    unittest.main()

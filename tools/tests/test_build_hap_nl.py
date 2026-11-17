"""The out-of-hours GP post merge (tools/build_hap_nl.py): Wikidata's list added to national.sqlite without doubling OpenStreetMap's."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools import tests  # noqa: F401  (puts tools/ on the path)
import map_schema
import build_hap_nl

CSV = '''i,name,c,web,located
http://www.wikidata.org/entity/Q1,Huisartsenpost Tilburg,Point(5.0646 51.5727),https://example.org/,http://www.wikidata.org/entity/Q26430
http://www.wikidata.org/entity/Q2,Spoedpost Uden,Point(5.6069 51.6743),,http://www.wikidata.org/entity/Q9872
http://www.wikidata.org/entity/Q3,Huisartsenpost Zonder Plek,,,
http://www.wikidata.org/entity/Q4,"Huisartsenpost Utrecht, Noord",Point(5.1372 52.0826),,
http://www.wikidata.org/entity/Q5,Huisartsenpost Buiten Beeld,Point(2.0 49.0),,
'''


def national(path, hap=()):
    db = sqlite3.connect(path)
    map_schema.create_map_tables(db)
    db.execute("INSERT INTO poi VALUES (10,'pharmacy','Apotheek',5.0,52.0)")
    for i, (name, lon, lat) in enumerate(hap):
        db.execute("INSERT INTO poi VALUES (?,?,?,?,?)", (20 + i, 'huisartsenpost', name, lon, lat))
    db.execute("INSERT INTO meta VALUES ('source','OpenStreetMap contributors')")
    db.commit()
    db.close()


class Parse(unittest.TestCase):
    def test_rows(self):
        rows, nocoord = build_hap_nl.parse(CSV)
        self.assertEqual(nocoord, 1)
        self.assertEqual([r[0] for r in rows], ['Huisartsenpost Tilburg', 'Spoedpost Uden', 'Huisartsenpost Utrecht, Noord'])
        self.assertEqual(rows[0][1:], (5.0646, 51.5727))        # lon, lat

    def test_outside_the_netherlands_is_dropped(self):
        rows, _ = build_hap_nl.parse(CSV)
        self.assertNotIn('Huisartsenpost Buiten Beeld', [r[0] for r in rows])

    def test_distance(self):
        self.assertAlmostEqual(build_hap_nl.metres(5.0, 52.0, 5.0, 52.001), 111.2, delta=1)
        self.assertEqual(build_hap_nl.metres(5.0, 52.0, 5.0, 52.0), 0)


class Merge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.rows, _ = build_hap_nl.parse(CSV)

    def run_merge(self, hap):
        national(self.tmp / 'in.sqlite', hap)
        return build_hap_nl.merge(self.tmp / 'in.sqlite', self.tmp / 'out.sqlite', self.rows, 'Wikidata test (CC0 1.0)')

    def test_adds_new_posts_with_the_source_name(self):
        stats = self.run_merge([])
        self.assertEqual((stats['before'], stats['added'], stats['near']), (0, 3, 0))
        db = sqlite3.connect(self.tmp / 'out.sqlite')
        got = db.execute("SELECT name, lon, lat FROM poi WHERE cls='huisartsenpost' ORDER BY name").fetchall()
        self.assertEqual([g[0] for g in got], ['Huisartsenpost Tilburg', 'Huisartsenpost Utrecht, Noord', 'Spoedpost Uden'])
        ids = [r[0] for r in db.execute('SELECT id FROM poi')]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(db.execute("SELECT count(*) FROM poi WHERE cls='pharmacy'").fetchone()[0], 1)     # others untouched

    def test_skips_a_post_near_an_existing_one(self):
        # 100 m from Tilburg, named differently by OpenStreetMap: kept once, with OpenStreetMap's name
        stats = self.run_merge([('HAP Tilburg', 5.0646, 51.5727 + 0.0009)])
        self.assertEqual((stats['before'], stats['added'], stats['near'], stats['after']), (1, 2, 1, 3))
        db = sqlite3.connect(self.tmp / 'out.sqlite')
        self.assertEqual(db.execute("SELECT count(*) FROM poi WHERE name LIKE '%Tilburg'").fetchone()[0], 1)
        self.assertEqual(db.execute("SELECT name FROM poi WHERE name LIKE '%Tilburg'").fetchone()[0], 'HAP Tilburg')

    def test_a_post_300_m_away_is_added(self):
        stats = self.run_merge([('HAP Tilburg', 5.0646, 51.5727 + 0.0027)])
        self.assertEqual(stats['added'], 3)

    def test_meta_records_the_source(self):
        self.run_merge([])
        db = sqlite3.connect(self.tmp / 'out.sqlite')
        meta = dict(db.execute('SELECT key, value FROM meta'))
        self.assertEqual(meta['source'], 'OpenStreetMap contributors')
        self.assertIn('Wikidata test', meta['huisartsenposten'])
        self.assertIn('CC0', meta['huisartsenposten'])

    def test_input_is_not_changed(self):
        self.run_merge([])
        db = sqlite3.connect(self.tmp / 'in.sqlite')
        self.assertEqual(db.execute("SELECT count(*) FROM poi WHERE cls='huisartsenpost'").fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()

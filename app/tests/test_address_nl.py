"""Dutch address search (engine/address_nl.py): postcode + house number, street first, bare postcodes, and its place in
server.places beside the US indexes."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import address_nl, address_search

ROWS = [  # postcode, num, letter, addition, street, city, lat, lon
    ('1012LG', 1, '', '', 'Damrak', 'Amsterdam', 52.3756, 4.8961),
    ('1012LG', 1, 'A', '', 'Damrak', 'Amsterdam', 52.3757, 4.8962),
    ('1016GV', 263, '', '1', 'Prinsengracht', 'Amsterdam', 52.3752, 4.8840),
    ('1015CR', 2, '', '3', 'Keizersgracht', 'Amsterdam', 52.3790, 4.8920),
    ('2514EE', 34, '', '', 'Lange Voorhout', "'s-Gravenhage", 52.0830, 4.3130),
    ('3511AA', 5, '', '', 'Kerkstraat', 'Utrecht', 52.0900, 5.1200),
]


def make_nl_index(path):
    db = sqlite3.connect(path)
    address_nl.create_index(db)
    db.executemany('INSERT INTO nl_addr VALUES (?,?,?,?,?,?,?,?,?,?)',
                   [(pc, n, l, a, st, address_nl.normalize(st), city, address_nl.normalize(city), lat, lon) for pc, n, l, a, st, city, lat, lon in ROWS])
    address_nl.finish_index(db, len(ROWS), 'test fixture')
    db.close()


def make_us_index(path):
    db = sqlite3.connect(path)
    db.executescript('CREATE TABLE addr(num TEXT, street TEXT, norm TEXT, city TEXT, state TEXT, zip TEXT, lat REAL, lon REAL);'
                     'CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);')
    db.execute("INSERT INTO addr VALUES('1600','Pennsylvania Avenue','pennsylvania ave','Washington','DC','20500',38.8977,-77.0365)")
    db.commit()
    db.close()


class DutchAddresses(unittest.TestCase):
    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.geo = self.data / 'derived' / 'geo'
        (self.geo / 'addresses').mkdir(parents=True)
        self.nl = self.geo / 'addresses' / 'NL.sqlite'
        make_nl_index(self.nl)

    def tearDown(self):
        shutil.rmtree(self.data, ignore_errors=True)

    def find(self, q, **kw):
        return address_nl.find(q, [self.nl], **kw)

    def test_parse_postcode_forms(self):
        self.assertEqual(address_nl.parse('1012 AB'), {'postcode': '1012AB', 'number': None, 'suffix': '', 'street': '', 'city': ''})
        self.assertEqual(address_nl.parse('1012ab 12'), {'postcode': '1012AB', 'number': 12, 'suffix': '', 'street': '', 'city': ''})
        self.assertEqual(address_nl.parse('1012AB12-A'), {'postcode': '1012AB', 'number': 12, 'suffix': 'a', 'street': '', 'city': ''})
        self.assertEqual(address_nl.parse('1012 ab 12 a'), {'postcode': '1012AB', 'number': 12, 'suffix': 'a', 'street': '', 'city': ''})

    def test_parse_street_first(self):
        self.assertEqual(address_nl.parse('Damrak 1-A Amsterdam'),
                         {'postcode': '', 'number': 1, 'suffix': 'a', 'street': 'damrak', 'city': 'amsterdam'})
        self.assertEqual(address_nl.parse('Damrak 1, 1012 LG Amsterdam'),
                         {'postcode': '1012LG', 'number': 1, 'suffix': '', 'street': 'damrak', 'city': 'amsterdam'})

    def test_parse_rejects_us(self):
        self.assertIsNone(address_nl.parse('1600 Pennsylvania Ave'))
        self.assertIsNone(address_nl.parse('48375'))
        self.assertIsNone(address_nl.parse('Amsterdam'))

    def test_postcode_and_number(self):
        r = self.find('1012 LG 1')
        self.assertEqual(r[0]['name'], 'Damrak 1')
        self.assertIn('Damrak 1A', [x['name'] for x in r])
        self.assertEqual(r[0]['detail'], '1012 LG Amsterdam')
        self.assertEqual((r[0]['kind'], r[0]['source'], r[0]['onMap']), ('Address', 'Kadaster BAG', True))

    def test_suffix_exact(self):
        self.assertEqual([x['name'] for x in self.find('1012lg 1a')], ['Damrak 1A'])

    def test_roman_addition(self):
        self.assertEqual([x['name'] for x in self.find('Keizersgracht 2-III')], ['Keizersgracht 2-3'])

    def test_street_first_with_city(self):
        self.assertEqual(self.find('Damrak 1 Amsterdam')[0]['name'], 'Damrak 1')

    def test_abbreviation(self):
        self.assertEqual([x['name'] for x in self.find('Kerkstr. 5')], ['Kerkstraat 5'])

    def test_city_alias(self):
        self.assertEqual([x['name'] for x in self.find('Lange Voorhout 34 Den Haag')], ['Lange Voorhout 34'])

    def test_bare_postcode(self):
        r = self.find('1016 GV')
        self.assertEqual([(x['name'], x['kind']) for x in r], [('Prinsengracht', 'Postcode')])
        self.assertIn('263', r[0]['detail'])
        self.assertTrue(r[0]['detail'].startswith('1016 GV Amsterdam'))

    def test_no_guess(self):
        self.assertEqual(self.find('Damrak 1Z'), [])
        self.assertEqual(self.find('Damrak 99'), [])

    def test_near_ranks_before_the_cut(self):
        """A common street (Kerkstraat 5 is in hundreds of towns): the house nearest the map must be found, not cut off by the row
        limit before distance is looked at."""
        db = sqlite3.connect(self.nl)
        rows = [(f'9{i:03d}AA', 5, '', '', 'Kerkstraat', 'kerkstraat', f'Dorp {i}', f'dorp {i}', 53.0 + i / 1000, 6.5) for i in range(300)]
        rows.append(('5611GH', 5, '', '', 'Kerkstraat', 'kerkstraat', 'Eindhoven', 'eindhoven', 51.44, 5.47))
        db.executemany('INSERT INTO nl_addr VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
        db.commit()
        db.close()
        r = self.find('Kerkstraat 5', near=(51.44, 5.47))
        self.assertEqual(r[0]['detail'], '5611 GH Eindhoven')

    def test_indexes_by_style(self):
        make_us_index(self.geo / 'addresses' / 'DC.sqlite')
        self.assertEqual(address_search.indexes(self.geo, 'nl'), [self.nl])
        self.assertEqual(address_search.indexes(self.geo, 'us'), [self.geo / 'addresses' / 'DC.sqlite'])

    def test_us_query_with_nl_index_installed(self):
        import server
        make_us_index(self.geo / 'addresses' / 'DC.sqlite')
        with patch.object(server, 'HERE', self.data):
            us = server.places('1600 Pennsylvania Ave')
            nl = server.places('Damrak 1')
        self.assertEqual(us[0]['detail'], 'Washington, DC, 20500')
        self.assertEqual(nl[0]['name'], 'Damrak 1')

    def test_fallback_to_places(self):
        import server
        place_db = self.data / 'places.sqlite'
        db = sqlite3.connect(place_db)
        db.executescript("CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, detail TEXT, lat REAL, lon REAL, rank INTEGER, source TEXT);"
                         "CREATE VIRTUAL TABLE place_fts USING fts5(name, detail, content='place', content_rowid='id', tokenize='unicode61');"
                         "INSERT INTO place(name,kind,detail,lat,lon,rank,source) VALUES ('ZZ Lighthouse','tower','test',52.0,5.0,4,'OpenStreetMap');"
                         "INSERT INTO place_fts(place_fts) VALUES ('rebuild');")
        db.close()
        with patch.object(server, 'HERE', self.data), patch.object(server, 'PLACEDB', place_db), \
                patch.object(server, 'WATERDB', self.data / 'none.sqlite'):
            r = server.places('1012 ZZ')
        self.assertEqual([x['name'] for x in r], ['ZZ Lighthouse'])


if __name__ == '__main__':
    unittest.main()

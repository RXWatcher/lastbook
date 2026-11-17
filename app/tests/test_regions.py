"""The region registry: US states and the countries Lastbook has a detailed map for (engine/regions.json)."""
import json
import tempfile
import unittest
from pathlib import Path

from engine import address_search, regions


class Regions(unittest.TestCase):
    def test_us_states_match_address_search(self):
        # The lists address search had before the registry, verbatim: the registry must not change them.
        codes = 'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA PR RI SC SD TN TX UT VT VA WA WV WI WY'.split()
        names = ('Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|'
                 'Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|'
                 'Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|'
                 'Oregon|Pennsylvania|Puerto Rico|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|'
                 'Washington|West Virginia|Wisconsin|Wyoming').split('|')
        states = regions.us_states()
        self.assertEqual([r['id'] for r in states], codes)
        self.assertEqual([r['name'] for r in states], names)
        self.assertEqual(address_search.STATE_CODES, codes)
        self.assertEqual(address_search.STATE_NAMES, names)

    def test_nl_entry(self):
        nl = regions.get('NL')
        self.assertEqual(nl['name'], 'Netherlands')
        self.assertEqual(nl['kind'], 'country')
        self.assertEqual(nl['units'], 'metric')
        self.assertEqual(nl['address_style'], 'nl')
        self.assertEqual(nl['box'], [3.2, 50.7, 7.3, 53.7])
        self.assertEqual(nl['attribution'], '© OpenStreetMap contributors · Kadaster BAG · AHN · RVO BRP · Natural Earth')
        self.assertEqual(len(nl['datasets']), 6)

    def test_us_entry_defaults(self):
        ca = regions.get('CA')
        self.assertEqual((ca['kind'], ca['units'], ca['address_style']), ('state', 'imperial', 'us'))
        self.assertIsNone(ca['box'])
        self.assertIsNone(ca['attribution'])
        self.assertIsNone(ca['datasets'])
        self.assertEqual(ca['search_hint'], 'Find an address, town or ZIP')
        self.assertEqual(ca['place_hint'], 'Try a town, county or 5-digit ZIP.')

    def test_region_id_pattern(self):
        for good in ('NL', 'CA', 'DE-BY'):
            self.assertTrue(regions.REGION_ID.fullmatch(good), good)
        for bad in ('nl', 'NLD', '../NL', 'DE-'):
            self.assertFalse(regions.REGION_ID.fullmatch(bad), bad)

    def test_installed_region(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertIsNone(regions.installed_region(d))
            (d / 'pack.json').write_text(json.dumps({'map': 'CA'}))
            self.assertEqual(regions.installed_region(d)['id'], 'CA')
            (d / 'map-set.json').write_text(json.dumps({'name': 'NL'}))
            self.assertEqual(regions.installed_region(d)['id'], 'NL')
            (d / 'map-set.json').write_text(json.dumps({'name': 'base'}))
            self.assertIsNone(regions.installed_region(d))
            (d / 'map-set.json').write_text('{not json')
            self.assertIsNone(regions.installed_region(d))


if __name__ == '__main__':
    unittest.main()

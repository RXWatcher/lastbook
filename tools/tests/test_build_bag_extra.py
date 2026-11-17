"""Secondary addresses (nevenadressen) from the BAG extract (tools/build_bag_extra.py), on small XML fixtures."""
import io
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import tests  # noqa: F401  (puts tools/ on the path)
import build_bag_extra
from engine import address_nl

NS = ('xmlns:Objecten="www.kadaster.nl/schemas/lvbag/imbag/objecten/v20200601" '
      'xmlns:Objecten-ref="www.kadaster.nl/schemas/lvbag/imbag/objecten-ref/v20200601" '
      'xmlns:Historie="www.kadaster.nl/schemas/lvbag/imbag/historie/v20200601" '
      'xmlns:Nummeraanduiding="www.kadaster.nl/schemas/lvbag/imbag/nummeraanduiding/v20200601" '
      'xmlns:gml="http://www.opengis.net/gml/3.2"')


def voorkomen(end=False, inactive=False):
    return ('<Historie:voorkomen><Historie:Voorkomen><Historie:voorkomenidentificatie>1</Historie:voorkomenidentificatie>'
            '<Historie:beginGeldigheid>2010-01-01</Historie:beginGeldigheid>'
            + ('<Historie:eindGeldigheid>2020-01-01</Historie:eindGeldigheid>' if end else '')
            + '<Historie:tijdstipRegistratie>2010-01-02T00:00:00.000</Historie:tijdstipRegistratie>'
            + ('<Historie:tijdstipInactief>2011-01-01T00:00:00.000</Historie:tijdstipInactief>' if inactive else '')
            + '</Historie:Voorkomen></Historie:voorkomen>')


def wrap(body):
    return (f'<?xml version="1.0" encoding="UTF-8"?><sl-bag-extract:bagStand xmlns:sl-bag-extract="x" xmlns:sl="y" {NS}>'
            f'<sl:standBestand><sl:stand><sl-bag-extract:bagObject>{body}</sl-bag-extract:bagObject></sl:stand></sl:standBestand>'
            '</sl-bag-extract:bagStand>')


def refs(tag, ids):
    return ''.join(f'<Objecten:{tag}><Objecten-ref:NummeraanduidingRef domein="NL.IMBAG.Nummeraanduiding">{i}</Objecten-ref:NummeraanduidingRef>'
                   f'</Objecten:{tag}>' for i in ids)


def vbo(ident, status, main, side, x=121400.0, y=487900.0, polygon=False, end=False):
    geo = (f'<gml:Polygon srsName="urn:ogc:def:crs:EPSG::28992"><gml:exterior><gml:LinearRing><gml:posList srsDimension="3">'
           f'{x} {y} 0 {x + 10} {y} 0 {x + 10} {y + 10} 0 {x} {y + 10} 0 {x} {y} 0</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon>'
           if polygon else f'<gml:Point srsName="urn:ogc:def:crs:EPSG::28992" srsDimension="3"><gml:pos>{x} {y} 0.0</gml:pos></gml:Point>')
    return (f'<Objecten:Verblijfsobject><Objecten:identificatie>{ident}</Objecten:identificatie>'
            f'<Objecten:geometrie><Objecten:{"vlak" if polygon else "punt"}>{geo}</Objecten:{"vlak" if polygon else "punt"}></Objecten:geometrie>'
            f'<Objecten:status>{status}</Objecten:status>{refs("heeftAlsHoofdadres", [main])}{refs("heeftAlsNevenadres", side)}'
            f'{voorkomen(end=end)}</Objecten:Verblijfsobject>')


def pitch(kind, ident, side):
    ring = '121500 488000 0 121510 488000 0 121510 488004 0 121500 488000 0'
    return (f'<Objecten:{kind}><Objecten:identificatie>{ident}</Objecten:identificatie><Objecten:geometrie><gml:Polygon>'
            f'<gml:exterior><gml:LinearRing><gml:posList srsDimension="3">{ring}</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon>'
            f'</Objecten:geometrie><Objecten:status>Plaats aangewezen</Objecten:status>{refs("heeftAlsNevenadres", side)}{voorkomen()}'
            f'</Objecten:{kind}>')


def num(ident, nr, pc, opr, wpl=None, letter=None, add=None, status='Naamgeving uitgegeven', end=False):
    return (f'<Objecten:Nummeraanduiding><Objecten:identificatie>{ident}</Objecten:identificatie>'
            f'<Objecten:huisnummer>{nr}</Objecten:huisnummer>'
            + (f'<Objecten:huisletter>{letter}</Objecten:huisletter>' if letter else '')
            + (f'<Objecten:huisnummertoevoeging>{add}</Objecten:huisnummertoevoeging>' if add else '')
            + f'<Objecten:postcode>{pc}</Objecten:postcode><Objecten:status>{status}</Objecten:status>'
            f'<Objecten:ligtAan><Objecten-ref:OpenbareRuimteRef>{opr}</Objecten-ref:OpenbareRuimteRef></Objecten:ligtAan>'
            + (f'<Objecten:ligtIn><Objecten-ref:WoonplaatsRef>{wpl}</Objecten-ref:WoonplaatsRef></Objecten:ligtIn>' if wpl else '')
            + f'{voorkomen(end=end)}</Objecten:Nummeraanduiding>')


def opr(ident, name, wpl, end=False):
    return (f'<Objecten:OpenbareRuimte><Objecten:identificatie>{ident}</Objecten:identificatie><Objecten:naam>{name}</Objecten:naam><Objecten:status>Naamgeving uitgegeven</Objecten:status>'
            f'<Objecten:ligtIn><Objecten-ref:WoonplaatsRef>{wpl}</Objecten-ref:WoonplaatsRef></Objecten:ligtIn>{voorkomen(end=end)}'
            '</Objecten:OpenbareRuimte>')


def wpl(ident, name):
    return (f'<Objecten:Woonplaats><Objecten:identificatie>{ident}</Objecten:identificatie><Objecten:naam>{name}</Objecten:naam><Objecten:status>Woonplaats aangewezen</Objecten:status>'
            f'<Objecten:geometrie><gml:Polygon><gml:exterior><gml:LinearRing><gml:posList>1 1 2 2 3 3 1 1</gml:posList></gml:LinearRing></gml:exterior></gml:Polygon></Objecten:geometrie>'
            f'{voorkomen()}</Objecten:Woonplaats>')


def make_extract(path):
    """Two inner zips per type, as PDOK splits them; the XML wraps each object in bagStand/standBestand/stand/bagObject."""
    def inner(kind, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for n, bodies in enumerate(files, 1):
                z.writestr(f'9999{kind}08112026-{n:06d}.xml', wrap(''.join(bodies)))
        return f'9999{kind}08112026.zip', buf.getvalue()
    parts = [
        inner('VBO', [
            [vbo('V1', 'Verblijfsobject in gebruik', 'N1', ['N2']),                        # corner house: side street address
             vbo('V2', 'Verblijfsobject in gebruik', 'N3', ['N4'], polygon=True, x=121600.0),   # polygon dwelling: its centre
             vbo('V3', 'Verblijfsobject in gebruik', 'N5', ['N6'], end=True)],              # an old version: ignored
            [vbo('V4', 'Verblijfsobject gevormd', 'N7', ['N8']),                           # not built yet: ignored
             vbo('V5', 'Verblijfsobject in gebruik', 'N9', ['N10', 'N11', 'N12'])]]),      # N10 duplicates a main address; N11 withdrawn; N12 no street
        inner('LIG', [[pitch('Ligplaats', 'L1', ['N13'])]]),
        inner('STA', [[pitch('Standplaats', 'S1', ['N14'])]]),
        inner('NUM', [
            [num('N1', 1, '1012LG', 'R1', 'W1'), num('N2', 1, '1012 LH', 'R2', None, letter='A', add='2'), num('N4', 7, '1012LG', 'R1', 'W1'),
             num('N6', 9, '1012LG', 'R1', 'W1'), num('N8', 11, '1012LG', 'R1', 'W1')],
            [num('N10', 1, '1012LG', 'R1', 'W1'), num('N11', 13, '1012LG', 'R1', 'W1', status='Naamgeving ingetrokken'),
             num('N12', 15, '1012LG', 'RX', 'W1'), num('N13', 40, '1012TL', 'R3', None), num('N14', 5, '9999ZZ', 'R4', 'W2')]]),
        inner('OPR', [[opr('R1', 'Damrak', 'W1'), opr('R2', 'Oude Brugsteeg', 'W1'), opr('R3', 'Prins Hendrikkade', 'W1'),
                       opr('R4', 'Kampweg', 'W2'), opr('R2', 'Oude Naam', 'W1', end=True)]]),
        inner('WPL', [[wpl('W1', 'Amsterdam'), wpl('W2', 'Ede')]]),
    ]
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in parts:
            z.writestr(name, data)


def make_main(path):
    db = sqlite3.connect(path)
    address_nl.create_index(db)
    db.execute("INSERT INTO nl_addr VALUES ('1012LG',1,'','','Damrak','damrak','Amsterdam','amsterdam',52.3745,4.8987)")
    address_nl.finish_index(db, 1, 'test')
    db.close()


class Extra(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        make_extract(self.tmp / 'extract.zip')
        make_main(self.tmp / 'main.sqlite')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    jobs = 1

    def build(self):
        counts = build_bag_extra.build(self.tmp / 'extract.zip', self.tmp / 'main.sqlite', self.tmp / 'out' / 'NL.sqlite', jobs=self.jobs)
        return counts, sqlite3.connect(self.tmp / 'out' / 'NL.sqlite')

    def test_counts(self):
        counts, _ = self.build()
        self.assertEqual(counts, {'main': 1, 'added': 4, 'skipped': 1, 'no_street': 1})

    def test_rows(self):
        _, db = self.build()
        rows = {(r[0], r[1], r[2], r[3]): r for r in db.execute('SELECT * FROM nl_addr')}
        self.assertEqual(set(rows), {('1012LG', 1, '', ''), ('1012LH', 1, 'A', '2'), ('1012LG', 7, '', ''),
                                     ('1012TL', 40, '', ''), ('9999ZZ', 5, '', '')})
        side = rows[('1012LH', 1, 'A', '2')]
        self.assertEqual(side[4:8], ('Oude Brugsteeg', 'oude brugsteeg', 'Amsterdam', 'amsterdam'))   # the town, via the street
        self.assertAlmostEqual(side[8], 52.3745, delta=0.01)
        self.assertEqual(rows[('1012LG', 1, '', '')][4], 'Damrak')                                      # the main address is kept as is
        self.assertEqual(rows[('1012TL', 40, '', '')][4:7:2], ('Prins Hendrikkade', 'Amsterdam'))
        self.assertEqual(rows[('9999ZZ', 5, '', '')][6], 'Ede')

    def test_polygon_object_is_placed_at_its_centre(self):
        _, db = self.build()
        lat, lon = db.execute("SELECT lat, lon FROM nl_addr WHERE postcode='1012LG' AND num=7").fetchone()
        from pyproj import Transformer
        want = Transformer.from_crs(28992, 4326, always_xy=True).transform(121605.0, 487905.0)
        self.assertAlmostEqual(lon, want[0], places=5)
        self.assertAlmostEqual(lat, want[1], places=5)

    def test_not_taken(self):
        _, db = self.build()
        numbers = {r[0] for r in db.execute('SELECT num FROM nl_addr')}
        self.assertFalse(numbers & {9, 11, 13, 15})     # old version, not built, withdrawn, no street

    def test_meta_and_search(self):
        _, db = self.build()
        meta = dict(db.execute('SELECT key, value FROM meta'))
        self.assertEqual((meta['style'], meta['count']), ('nl', '5'))
        found = address_nl.find('Oude Brugsteeg 1A-2', [str(self.tmp / 'out' / 'NL.sqlite')])
        self.assertEqual([f['name'] for f in found], ['Oude Brugsteeg 1A-2'])
        self.assertEqual(address_nl.find('1012 LG 7', [str(self.tmp / 'out' / 'NL.sqlite')])[0]['name'], 'Damrak 7')


class ExtraParallel(Extra):
    jobs = 2


if __name__ == '__main__':
    unittest.main()

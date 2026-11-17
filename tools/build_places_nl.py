#!/usr/bin/env python3
"""The place finder for the Netherlands: derived/geo-nl/places.sqlite, in the format tools/build_places.py writes for the US.

  derived/buildenv/bin/python tools/build_places_nl.py derived/geo-nl/national.sqlite derived/sources/nl/bag-light.gpkg \
      derived/geo-nl/admin.sqlite derived/geo-nl/places.sqlite

Reads:
  national.sqlite   named OpenStreetMap places (city, town, village...) and help points (tools/build_map_osm.py; ODbL 1.0)
  bag-light.gpkg    Kadaster BAG's woonplaatsen, the official towns and villages: table woonplaats(geom MULTIPOLYGON in
                    EPSG:28992, status, woonplaats, bronhouder_identificatie = the municipality's code) (CC0 1.0)
  admin.sqlite      municipalities and provinces from OpenStreetMap (tools/build_map_osm.py --admin; ODbL 1.0). Kadaster's
                    own boundaries are CC0 only up to 2021; the current service is CC BY 4.0, so OpenStreetMap's are used.
Writes: place(id, name, kind, detail, lat, lon, rank, source) with place_fts. Ranks as for the US: OpenStreetMap places 1,
municipalities and provinces 2, BAG towns and villages 3, named help points 4. Two cities are known by another name than
BAG's: rows for Den Haag ('s-Gravenhage) and Den Bosch ('s-Hertogenbosch) are added so either name finds them.
"""
import argparse, sqlite3, struct, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from map_schema import gpkg_parts, unpack     # noqa: E402

ALIASES = {"'s-Gravenhage": 'Den Haag', "'s-Hertogenbosch": 'Den Bosch'}
OSM = 'Netherlands (OpenStreetMap)'


def ring_area(r):
    return sum(r[i] * r[i + 3] - r[i + 2] * r[i + 1] for i in range(0, len(r) - 2, 2)) / 2


def centroid(parts):
    """(lat, lon) of the largest ring's area centroid; parts are flat [x, y, ...] lists with x = lon."""
    r = max(parts, key=lambda p: abs(ring_area(p)))
    a = ring_area(r)
    if not a:
        return r[1], r[0]
    cx = sum((r[i] + r[i + 2]) * (r[i] * r[i + 3] - r[i + 2] * r[i + 1]) for i in range(0, len(r) - 2, 2)) / (6 * a)
    cy = sum((r[i + 1] + r[i + 3]) * (r[i] * r[i + 3] - r[i + 2] * r[i + 1]) for i in range(0, len(r) - 2, 2)) / (6 * a)
    return cy, cx


def inside(x, y, parts):
    """Whether the point lies inside the rings (even-odd rule)."""
    hit = False
    for r in parts:
        n = len(r) // 2
        for i in range(n):
            x1, y1, x2, y2 = r[2 * i], r[2 * i + 1], r[2 * ((i + 1) % n)], r[2 * ((i + 1) % n) + 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                hit = not hit
    return hit


def build(national, bag, admin, out):
    from pyproj import Transformer
    to_ll = Transformer.from_crs(28992, 4326, always_xy=True)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.partial')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript('''CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, detail TEXT, lat REAL, lon REAL, rank INTEGER, source TEXT);
      CREATE VIRTUAL TABLE place_fts USING fts5(name, detail, content='place', content_rowid='id', tokenize='unicode61');''')
    ins = 'INSERT INTO place(name,kind,detail,lat,lon,rank,source) VALUES (?,?,?,?,?,?,?)'

    adm = sqlite3.connect(f'file:{admin}?mode=ro', uri=True)
    provinces = [(name, unpack(g), (x0, x1, y0, y1)) for name, x0, x1, y0, y1, g in
                 adm.execute("SELECT name, minx, maxx, miny, maxy, geom FROM admin WHERE kind='province'")]

    def province(lon, lat):
        return next((name for name, parts, (x0, x1, y0, y1) in provinces
                     if x0 <= lon <= x1 and y0 <= lat <= y1 and inside(lon, lat, parts)), '')
    municipalities = {}
    for name, code, g in adm.execute("SELECT name, code, geom FROM admin WHERE kind='municipality'"):
        lat, lon = centroid(unpack(g))
        prov = province(lon, lat)
        db.execute(ins, (name, 'municipality', prov or 'Netherlands', lat, lon, 2, 'OpenStreetMap'))
        if code:
            municipalities[code.strip().upper().removeprefix('GM').zfill(4)] = name
    for name, g in adm.execute("SELECT name, geom FROM admin WHERE kind='province'"):
        lat, lon = centroid(unpack(g))
        db.execute(ins, (name, 'province', 'Netherlands', lat, lon, 2, 'OpenStreetMap'))
    adm.close()

    src = sqlite3.connect(f'file:{bag}?mode=ro', uri=True)
    for g, name, code in src.execute("SELECT geom, woonplaats, bronhouder_identificatie FROM woonplaats "
                                     "WHERE status='Woonplaats aangewezen' AND woonplaats IS NOT NULL"):
        try:
            parts = gpkg_parts(g)
        except Exception:
            continue
        y, x = centroid(parts)
        lon, lat = to_ll.transform(x, y)
        prov = province(lon, lat)
        town = municipalities.get((code or '').strip().zfill(4))
        detail = ', '.join(v for v in (town and f'{town} municipality', prov) if v) or 'Netherlands'
        db.execute(ins, (name, 'town or village', detail, lat, lon, 3, 'Kadaster BAG'))
        if name in ALIASES:
            db.execute(ins, (ALIASES[name], 'town or village', ', '.join(v for v in (f'also called {name}', prov) if v), lat, lon, 3,
                             'Kadaster BAG'))
    src.close()

    nat = sqlite3.connect(f'file:{national}?mode=ro', uri=True)
    for cls, name, g in nat.execute("SELECT cls, name, geom FROM feat WHERE layer='place' AND name IS NOT NULL AND name<>''"):
        _, _, x, y = struct.unpack_from('<iiii', g)
        db.execute(ins, (name, cls, OSM, y / 1e6, x / 1e6, 1, 'OpenStreetMap'))
    for cls, name, lon, lat in nat.execute("SELECT cls, name, lon, lat FROM poi WHERE name IS NOT NULL AND name<>''"):
        db.execute(ins, (name, cls.replace('_', ' '), OSM, lat, lon, 4, 'OpenStreetMap'))
    nat.close()
    db.execute("INSERT INTO place_fts(place_fts) VALUES ('rebuild')")
    n = db.execute('SELECT count(*) FROM place').fetchone()[0]
    db.commit()
    db.close()
    tmp.replace(out)
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('national')
    ap.add_argument('bag')
    ap.add_argument('admin')
    ap.add_argument('out')
    a = ap.parse_args()
    print('places', build(a.national, a.bag, a.admin, a.out))


if __name__ == '__main__':
    main()

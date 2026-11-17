#!/usr/bin/env python3
"""Building outlines and Dutch addresses from Kadaster's BAG (Basisregistratie Adressen en Gebouwen).

  derived/buildenv/bin/python tools/build_bag.py derived/sources/nl/bag-light.gpkg derived/geo-nl [--box W,S,E,N] [--heights heights.sqlite]

Reads: PDOK's BAG GeoPackage without history, https://service.pdok.nl/kadaster/bag/atom/downloads/bag-light.gpkg
(Kadaster, CC0 1.0; about 7.8 GB). Tables used (checked 17 November 2026), all in EPSG:28992 (RD New):
  pand(geom POLYGON, identificatie, status)                          building outlines and their BAG pand number
  verblijfsobject(geom POINT, status, openbare_ruimte_naam, huisnummer, huisletter, toevoeging, postcode, woonplaats_naam)
  ligplaats, standplaats(geom POLYGON, same address columns)         houseboat and mobile-home pitches
Each address object carries its main address (hoofdadres) only; tools/build_bag_extra.py adds the secondary ones.
Writes:
  <out>/buildings.sqlite      bldg(x, y, part, n, data) as tools/build_buildings.py writes it (z14 buckets, zlib int32 records),
                              with empty bldg_socal and bldg_osm (the map reads them) and meta. height_dm is 0 (unknown) unless --heights is given.
  --buildings-only     leave addresses/NL.sqlite alone (redo only buildings.sqlite)
  --heights            tools/fetch_3dbag.py's heights.sqlite (3D BAG, CC BY 4.0): height_dm is the height above ground in decimetres,
                       matched on the BAG pand number; 0 where 3D BAG has none. meta gets with_height, the count of buildings with one.
  <out>/addresses/NL.sqlite   the Dutch address index (engine/address_nl.py: create_index, normalize, finish_index)
Kept: buildings that stand (in use, not measured in, under renovation, out of use, with a demolition permit); addresses in use
or under renovation, and pitches that are designated. Left out: buildings and addresses still to be built.
"""
import argparse, sqlite3, sys, time, zlib
from array import array
from pathlib import Path

import math

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from map_schema import gpkg_parts                    # noqa: E402
from build_buildings import REACH, WORLD             # noqa: E402
from engine import address_nl                        # noqa: E402
import fetch_3dbag                                   # noqa: E402

PAND_OK = ('Pand in gebruik', 'Pand in gebruik (niet ingemeten)', 'Verbouwing pand', 'Pand buiten gebruik', 'Sloopvergunning verleend')
ADDRESS_OK = {'verblijfsobject': ('Verblijfsobject in gebruik', 'Verblijfsobject in gebruik (niet ingemeten)', 'Verbouwing verblijfsobject'),
              'ligplaats': ('Plaats aangewezen',), 'standplaats': ('Plaats aangewezen',)}
BATCH = 100_000
SOURCE = 'Kadaster BAG, PDOK bag-light.gpkg (CC0 1.0)'
SOURCE_HEIGHTS = SOURCE + '; heights from 3D BAG, 3DBAG by tudelft3d and 3DGI (CC BY 4.0)'


def transformer():
    from pyproj import Transformer
    return Transformer.from_crs(28992, 4326, always_xy=True)


def encode_building(ring_lonlat, height_dm):
    """One footprint as tools/build_buildings.py encodes it: the int32 record [npts, height_dm, X0, Y0, dX1, dY1, ...] in global z14
    pixels x 65536, and the z14 buckets it is filed in (its centre's, plus any it reaches more than ~150 m into)."""
    pts = []
    for lon, lat in ring_lonlat:
        s = math.sin(math.radians(max(-85, min(85, lat))))
        pts.append((int((lon + 180) / 360 * WORLD), int((0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * WORLD)))
    cx = sum(p[0] for p in pts) // len(pts); cy = sum(p[1] for p in pts) // len(pts)
    rec = array('i', (len(pts), height_dm, pts[0][0], pts[0][1]))
    lx, ly = pts[0]
    for x, y in pts[1:]:
        rec.extend((x - lx, y - ly)); lx, ly = x, y
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    keys = {(i, j) for i in range((min(xs) + REACH) >> 16, ((max(xs) - REACH) >> 16) + 1)
            for j in range((min(ys) + REACH) >> 16, ((max(ys) - REACH) >> 16) + 1)} | {(cx >> 16, cy >> 16)}
    return rec, keys


def inside(box, lon, lat):
    return box is None or (box[0] <= lon <= box[2] and box[1] <= lat <= box[3])


def _batches(cursor):
    while rows := cursor.fetchmany(BATCH):
        yield rows


def build_addresses(src, out, box, tr, log):
    path = out / 'addresses' / 'NL.sqlite'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.partial')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;')
    address_nl.create_index(db)
    total = 0
    for table, ok in ADDRESS_OK.items():
        marks = ','.join('?' * len(ok))
        cur = src.execute(f'SELECT geom, openbare_ruimte_naam, huisnummer, huisletter, toevoeging, postcode, woonplaats_naam FROM {table} '
                          f'WHERE status IN ({marks}) AND huisnummer IS NOT NULL AND openbare_ruimte_naam IS NOT NULL', ok)
        for rows in _batches(cur):
            xs, ys, keep = [], [], []
            for row in rows:
                try:
                    ring = gpkg_parts(row[0])[0]
                except Exception:
                    continue
                n = len(ring) // 2 if len(ring) <= 2 else len(ring) // 2 - 1      # a polygon's closing point counted once
                xs.append(sum(ring[0:2 * n:2]) / n); ys.append(sum(ring[1:2 * n:2]) / n)
                keep.append(row)
            lons, lats = tr.transform(xs, ys)
            out_rows = []
            for (_, street, num, letter, addition, postcode, city), lon, lat in zip(keep, lons, lats):
                if inside(box, lon, lat):
                    out_rows.append(((postcode or '').replace(' ', '').upper(), int(num), letter or '', addition or '', street,
                                     address_nl.normalize(street), city or '', address_nl.normalize(city or ''), round(lat, 6), round(lon, 6)))
            db.executemany('INSERT INTO nl_addr VALUES (?,?,?,?,?,?,?,?,?,?)', out_rows)
            total += len(out_rows)
            log(f'{table}: {total:,} addresses')
    address_nl.finish_index(db, total, SOURCE)
    db.close()
    tmp.replace(path)
    return total


def build_buildings(src, out, box, tr, log, heights=None):
    path = out / 'buildings.sqlite'
    tmp = path.with_suffix('.partial')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;'
                     'CREATE TABLE bldg(x INT, y INT, part INT, n INT, data BLOB, PRIMARY KEY(x,y,part)) WITHOUT ROWID;'
                     'CREATE TABLE bldg_socal(x INT, y INT, part INT, n INT, data BLOB, PRIMARY KEY(x,y,part)) WITHOUT ROWID;'
                     'CREATE TABLE bldg_osm(x INT, y INT, part INT, n INT, data BLOB, PRIMARY KEY(x,y,part)) WITHOUT ROWID;'
                     'CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);')
    marks = ','.join('?' * len(PAND_OK))
    cur = src.execute(f'SELECT geom, identificatie FROM pand WHERE status IN ({marks})', PAND_OK)
    total = with_height = 0
    for part, rows in enumerate(_batches(cur)):
        rings, ids = [], []
        for g, ident in rows:
            try:
                ring = gpkg_parts(g)[0]
            except Exception:
                continue
            if len(ring) >= 4 and ring[:2] == ring[-2:]:
                ring = ring[:-2]
            if len(ring) >= 6:
                rings.append(ring); ids.append(ident)
        xs = [v for r in rings for v in r[0::2]]
        ys = [v for r in rings for v in r[1::2]]
        lons, lats = tr.transform(xs, ys)
        tiles, at = {}, 0
        for r, ident in zip(rings, ids):
            n = len(r) // 2
            pts = list(zip(lons[at:at + n], lats[at:at + n]))
            at += n
            cx = sum(p[0] for p in pts) / n; cy = sum(p[1] for p in pts) / n
            if not inside(box, cx, cy):
                continue
            h = heights.get(ident) if heights else 0
            with_height += h > 0
            rec, keys = encode_building(pts, h)
            for key in keys:
                a = tiles.get(key)
                if a is None:
                    a = tiles[key] = [array('i'), 0]
                a[0].extend(rec); a[1] += 1
            total += 1
        db.executemany('INSERT INTO bldg VALUES (?,?,?,?,?)', [(x, y, part, c, zlib.compress(buf.tobytes(), 6)) for (x, y), (buf, c) in tiles.items()])
        db.commit()
        log(f'buildings: {total:,}')
    db.executemany('INSERT INTO meta VALUES (?,?)', [('buildings', str(total)), ('built', time.strftime('%Y-%m-%dT%H:%M:%S')), ('source', SOURCE_HEIGHTS if heights else SOURCE),
                                           ('with_height', str(with_height))])
    db.commit()
    db.close()
    tmp.replace(path)
    return total


def build(gpkg, out, box=None, quiet=True, heights=None, addresses=True):
    t0 = time.time()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f'file:{gpkg}?mode=ro', uri=True)
    tr = transformer()
    log = (lambda m: None) if quiet else (lambda m: print(f'{m} ({time.time() - t0:.0f}s)', flush=True))
    a = build_addresses(src, out, box, tr, log) if addresses else 0
    lookup = fetch_3dbag.Heights(heights) if heights else None
    b = build_buildings(src, out, box, tr, log, lookup)
    src.close()
    if lookup:
        lookup.close()
    return a, b


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('gpkg')
    ap.add_argument('out')
    ap.add_argument('--box', help='W,S,E,N in degrees: keep only what lies inside')
    ap.add_argument('--buildings-only', action='store_true', help='skip the address index (to redo only buildings.sqlite)')
    ap.add_argument('--heights', help='heights.sqlite from tools/fetch_3dbag.py: building heights from 3D BAG')
    a = ap.parse_args()
    box = [float(v) for v in a.box.split(',')] if a.box else None
    addresses, buildings = build(a.gpkg, a.out, box, quiet=False, heights=a.heights, addresses=not a.buildings_only)
    print(f'done: {addresses:,} addresses, {buildings:,} buildings', flush=True)


if __name__ == '__main__':
    main()

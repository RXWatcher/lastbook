#!/usr/bin/env python3
"""Food crops that keep producing (orchards, vineyards, soft fruit, asparagus, rhubarb) for the Netherlands, from RVO's BRP.

  derived/buildenv/bin/python tools/build_crops_nl.py derived/sources/nl/brpgewaspercelen_definitief_2025.gpkg \\
      derived/geo-nl/crops.sqlite --box 3.2,50.7,7.3,53.7

Reads: Basisregistratie Gewaspercelen 2025, definitive (RVO via PDOK,
https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2025.gpkg, CC0 1.0): table brp_gewas
(geom POLYGON in EPSG:28992, category, gewas, gewascode, jaar, status), one row per parcel as farmers declared it on 15 May.
Writes: crops.sqlite as tools/build_crops.py writes it for the US: clickable ~600 m cells (`resource` + `spatial`, the main crop
and its hectares) and a colour overlay (`tile`, zoom 7-13). Parcels are drawn onto a 30 m grid in RD New first.
Crops are chosen by BRP code, never by name: Dutch names match too loosely (Aardappelen, potatoes, contains "appel"). Only
codes for a harvest are kept, not nursery stock, seed or propagation beds.
"""
import argparse, json, math, sqlite3, sys, time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from map_schema import gpkg_parts                                            # noqa: E402
from build_crops import raster_cells, raster_tiles, write_tiles, BLOCK      # noqa: E402,F401

YEAR = 2025
S = 30.0                       # metres a pixel
HA_PER_PX = S * S / 10000
# BRP code -> (crop, kind, colour)
CROPS = {1095: ('Apples', 'orchard', (200, 40, 40)), 1096: ('Apples', 'orchard', (200, 40, 40)),
         1097: ('Pears', 'orchard', (170, 190, 60)), 1098: ('Pears', 'orchard', (170, 190, 60)),
         2328: ('Cherries', 'orchard', (190, 30, 60)), 1872: ('Sour cherries', 'orchard', (160, 20, 50)),
         1870: ('Plums', 'orchard', (130, 40, 110)), 2645: ('Nut trees', 'orchard', (150, 100, 50)),
         2628: ('Traditional orchard (mixed fruit trees)', 'orchard', (90, 150, 70)),
         1100: ('Other fruit trees (such as peaches)', 'orchard', (240, 140, 90)),
         1099: ('Wine grapes', 'vineyard', (120, 50, 150)),
         1869: ('Blueberries', 'berries', (60, 70, 180)), 2325: ('Redcurrants', 'berries', (200, 30, 60)),
         1873: ('Blackcurrants', 'berries', (70, 30, 90)), 2326: ('Raspberries', 'berries', (150, 30, 90)),
         2327: ('Blackberries', 'berries', (90, 20, 70)), 1874: ('Other soft fruit (such as gooseberries)', 'berries', (110, 90, 170)),
         1047: ('Cranberries', 'berries', (170, 20, 50)), 2702: ('Strawberries', 'berries', (230, 50, 80)),
         2706: ('Strawberries', 'berries', (230, 50, 80)),
         2710: ('Asparagus', 'perennial_veg', (90, 160, 90)), 2711: ('Asparagus', 'perennial_veg', (90, 160, 90)),
         2755: ('Rhubarb', 'perennial_veg', (180, 90, 110))}
CODES = sorted(CROPS)
PALETTE = np.zeros((len(CODES) + 1, 4), np.uint8)
for _i, _c in enumerate(CODES, 1):
    PALETTE[_i] = (*CROPS[_c][2], 190)


def crop_for(code):
    """(crop in English, map kind) for a BRP crop code, or None for a crop that is not a lasting food source."""
    c = CROPS.get(code)
    return (c[0], c[1]) if c else None


def build(gpkg, out, box=(3.2, 50.7, 7.3, 53.7), log=lambda m: None):
    from PIL import Image, ImageDraw
    from pyproj import Transformer
    to_rd = Transformer.from_crs(4326, 28992, always_xy=True)
    to_ll = Transformer.from_crs(28992, 4326, always_xy=True)
    w, s, e, n = box
    cx, cy = to_rd.transform([w, w, e, e], [s, n, s, n])
    X0, Y0 = math.floor(min(cx) / S) * S, math.ceil(max(cy) / S) * S
    W, H = int(math.ceil((max(cx) - X0) / S)), int(math.ceil((Y0 - min(cy)) / S))
    img = Image.new('L', (W, H), 0)
    draw = ImageDraw.Draw(img)
    src = sqlite3.connect(f'file:{gpkg}?mode=ro', uri=True)
    marks = ','.join('?' * len(CODES))
    parcels = 0
    for g, code in src.execute(f'SELECT geom, gewascode FROM brp_gewas WHERE gewascode IN ({marks})', CODES):
        try:
            rings = gpkg_parts(g)
        except Exception:
            continue
        for i, ring in enumerate(rings):
            pts = [((ring[k] - X0) / S, (Y0 - ring[k + 1]) / S) for k in range(0, len(ring), 2)]
            if len(pts) >= 3:
                draw.polygon(pts, fill=CODES.index(code) + 1 if i == 0 else 0)
        parcels += 1
    src.close()
    log(f'{parcels:,} parcels drawn on a {W} x {H} grid')
    cls = np.asarray(img, dtype=np.uint8)
    inverse = lambda x, y: tuple(np.asarray(v) for v in to_ll.transform(np.asarray(x, float), np.asarray(y, float)))
    forward = lambda lon, lat: tuple(np.asarray(v) for v in to_rd.transform(np.asarray(lon, float), np.asarray(lat, float)))

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.partial')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT);
      CREATE INDEX resource_kind ON resource(kind);
      CREATE VIRTUAL TABLE spatial USING rtree(id, minx, maxx, miny, maxy);
      CREATE TABLE tile(z INT, x INT, y INT, png BLOB, PRIMARY KEY(z,x,y)) WITHOUT ROWID;
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);''')
    rows, cols = np.nonzero(cls)
    npts = 0
    if rows.size:
        cell, ci, cnt, tot, lon, lat = raster_cells(cls, rows, cols, X0, Y0, S, inverse, min_px=5)
        for k, m, t, lo, la, cl in zip(ci, cnt, tot, lon, lat, cell):
            crop, kind = crop_for(CODES[int(k) - 1])
            r = db.execute('INSERT INTO resource(source_id,kind,name,lat,lon,detail,source) VALUES (?,?,?,?,?,?,?)',
                           (f'brp{YEAR}:{int(cl)}', kind, crop, float(la), float(lo),
                            json.dumps({'crop': crop, 'crop_ha': round(float(m) * HA_PER_PX, 1), 'perennial_ha': round(float(t) * HA_PER_PX, 1),
                                        'year': YEAR}),
                            'https://service.pdok.nl/rvo/gewaspercelen/atom/basisregistratie_gewaspercelen_brp.xml'))
            db.execute('INSERT INTO spatial VALUES (?,?,?,?,?)', (r.lastrowid, float(lo), float(lo), float(la), float(la)))
            npts += 1
        tiles = raster_tiles(cls, rows, cols, X0, Y0, S, inverse, forward)
        log(f'{npts:,} cells, {len(tiles):,} detailed tiles')
        write_tiles(db, tiles, PALETTE)
    db.executemany('INSERT INTO meta VALUES (?,?)', [
        ('built', json.dumps({'cells': npts, 'year': YEAR, 'parcels': parcels, 'at': time.strftime('%Y-%m-%dT%H:%M:%S')})),
        ('source', f'RVO Basisregistratie Gewaspercelen {YEAR}, definitive (CC0 1.0)')])
    db.commit()
    db.close()
    tmp.replace(out)
    return npts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('gpkg')
    ap.add_argument('out')
    ap.add_argument('--box', default='3.2,50.7,7.3,53.7', help='W,S,E,N in degrees')
    a = ap.parse_args()
    t0 = time.time()
    n = build(a.gpkg, a.out, [float(v) for v in a.box.split(',')], log=lambda m: print(f'{m} ({time.time() - t0:.0f}s)', flush=True))
    print(f'done: {n:,} clickable cells', flush=True)


if __name__ == '__main__':
    main()

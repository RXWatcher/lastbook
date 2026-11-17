"""Builds derived/geo/crops.sqlite: perennial food crops (orchards, vineyards, berries) from the USDA Cropland Data Layer.

  derived/buildenv/bin/python tools/build_crops.py [STATE_FIPS ...]

Source: library-data/geography/resources/crops/CDL_2025_<fips>.tif (30 m, USA Contiguous Albers / NAD83).
Writes clickable blocks (`resource` + `spatial`, ~600 m cells, dominant crop and acreage) and a colour overlay
(`tile`, RGBA PNG, zoom 7-13) showing where the trees and vines are.
"""
import json, math, re, sqlite3, struct, sys, time, zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import tifffile

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / 'library-data/geography/resources/crops'
OUT = HERE / 'derived/geo/crops.sqlite'
YEAR = 2025
# CDL code -> (crop, kind, RGB)
CROPS = {75: ('Almonds', 'nut', (150, 100, 50)), 76: ('Walnuts', 'nut', (120, 80, 40)), 74: ('Pecans', 'nut', (135, 90, 45)),
         204: ('Pistachios', 'nut', (140, 160, 60)), 66: ('Cherries', 'fruit', (190, 30, 60)), 67: ('Peaches', 'fruit', (240, 140, 90)),
         68: ('Apples', 'fruit', (200, 40, 40)), 77: ('Pears', 'fruit', (170, 190, 60)), 210: ('Prunes', 'fruit', (110, 50, 120)),
         218: ('Nectarines', 'fruit', (240, 120, 70)), 220: ('Plums', 'fruit', (130, 40, 110)), 223: ('Apricots', 'fruit', (245, 160, 50)),
         217: ('Pomegranates', 'fruit', (180, 30, 50)), 215: ('Avocados', 'fruit', (70, 120, 40)), 211: ('Olives', 'fruit', (110, 120, 50)),
         71: ('Other tree crops', 'fruit', (90, 150, 70)), 72: ('Citrus', 'citrus', (250, 160, 20)), 212: ('Oranges', 'citrus', (255, 140, 0)),
         69: ('Grapes', 'vine', (120, 50, 150)), 242: ('Blueberries', 'berry', (60, 70, 180)), 250: ('Cranberries', 'berry', (170, 20, 50)),
         55: ('Caneberries', 'berry', (150, 30, 90)), 207: ('Asparagus', 'veg', (90, 160, 90))}
KIND = {'nut': 'orchard', 'fruit': 'orchard', 'citrus': 'orchard', 'vine': 'vineyard', 'berry': 'berries', 'veg': 'perennial_veg'}
CODES = sorted(CROPS)
LUT = np.zeros(256, np.uint8)
for i, c in enumerate(CODES, 1):
    LUT[c] = i
PALETTE = np.zeros((len(CODES) + 1, 4), np.uint8)
for i, c in enumerate(CODES, 1):
    PALETTE[i] = (*CROPS[c][2], 190)
ACRE_PER_PX = 900 / 4046.86
BLOCK = 20          # 20 x 20 px = 600 m cells for clickable points
MAXZ, MINZ = 13, 7

# --- USA Contiguous Albers Equal Area (EPSG:5070 parameters, GRS80) ---
A, E2 = 6378137.0, 0.0066943800229
E = math.sqrt(E2)
LAT1, LAT2, LAT0, LON0 = map(math.radians, (29.5, 45.5, 23.0, -96.0))


def _q(s):
    return (1 - E2) * (s / (1 - E2 * s * s) - np.log((1 - E * s) / (1 + E * s)) / (2 * E))


def _m(p):
    return math.cos(p) / math.sqrt(1 - E2 * math.sin(p) ** 2)


N_ = (_m(LAT1) ** 2 - _m(LAT2) ** 2) / (_q(math.sin(LAT2)) - _q(math.sin(LAT1)))
C_ = _m(LAT1) ** 2 + N_ * _q(math.sin(LAT1))
RHO0 = A * math.sqrt(C_ - N_ * _q(math.sin(LAT0))) / N_


def forward(lon, lat):
    rho = A * np.sqrt(C_ - N_ * _q(np.sin(np.radians(lat)))) / N_
    th = N_ * (np.radians(lon) - LON0)
    return rho * np.sin(th), RHO0 - rho * np.cos(th)


def inverse(x, y):
    rho = np.hypot(x, RHO0 - y)
    th = np.arctan2(x, RHO0 - y)
    q = (C_ - rho * rho * N_ * N_ / (A * A)) / N_
    p = np.arcsin(np.clip(q / 2, -1, 1))
    for _ in range(6):
        s = np.sin(p)
        p = p + (1 - E2 * s * s) ** 2 / (2 * np.cos(p)) * (q / (1 - E2) - s / (1 - E2 * s * s) + np.log((1 - E * s) / (1 + E * s)) / (2 * E))
    return np.degrees(LON0 + th / N_), np.degrees(p)


def png_rgba(rgba):
    raw = np.hstack([np.zeros((rgba.shape[0], 1), np.uint8), rgba.reshape(rgba.shape[0], -1)]).tobytes()
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', rgba.shape[1], rgba.shape[0], 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def raster_cells(cls, rows, cols, X0, Y0, S, inverse, min_px=20):
    """Clickable cells: the dominant crop class in each BLOCK x BLOCK cell of a class raster (top-left X0, Y0, pixel size S in the
    raster's projection; inverse() turns its x, y into lon, lat). Returns (cell, class, its pixels, all crop pixels, lon, lat)."""
    c = cls[rows, cols]
    br, bc = rows // BLOCK, cols // BLOCK
    key = (br.astype(np.int64) * 100000 + bc) * 32 + c
    u, n = np.unique(key, return_counts=True)
    cell, ci = u // 32, (u % 32).astype(int)
    order = np.lexsort((-n, cell))
    cell, ci, n = cell[order], ci[order], n[order]
    first = np.r_[True, cell[1:] != cell[:-1]]
    tot = np.add.reduceat(n, np.nonzero(first)[0])
    cell, ci, n = cell[first], ci[first], n[first]
    keep = tot >= min_px
    cell, ci, n, tot = cell[keep], ci[keep], n[keep], tot[keep]
    x = X0 + ((cell % 100000) * BLOCK + BLOCK / 2) * S
    y = Y0 - ((cell // 100000) * BLOCK + BLOCK / 2) * S
    lon, lat = inverse(x, y)
    return cell, ci, n, tot, lon, lat


def raster_tiles(cls, rows, cols, X0, Y0, S, inverse, forward):
    """The overlay: every z13 tile touched by a crop pixel, sampled nearest-neighbour from the class raster."""
    plon, plat = inverse(X0 + (cols[::7] + .5) * S, Y0 - (rows[::7] + .5) * S)
    nz = 2 ** MAXZ
    tx = ((plon + 180) / 360 * nz).astype(int)
    ty = ((1 - np.log(np.tan(np.radians(plat)) + 1 / np.cos(np.radians(plat))) / math.pi) / 2 * nz).astype(int)
    tiles = {}
    t = np.arange(256) + 0.5
    for x_, y_ in set(zip(tx.tolist(), ty.tolist())):
        lon_ = (x_ + t / 256) / nz * 360 - 180
        lat_ = np.degrees(np.arctan(np.sinh(math.pi * (1 - 2 * (y_ + t / 256) / nz))))
        LO, LA = np.meshgrid(lon_, lat_)
        ax, ay = forward(LO, LA)
        cc = ((ax - X0) / S).astype(int); rr = ((Y0 - ay) / S).astype(int)
        ok = (rr >= 0) & (rr < cls.shape[0]) & (cc >= 0) & (cc < cls.shape[1])
        v = np.zeros((256, 256), np.uint8)
        v[ok] = cls[rr[ok], cc[ok]]
        if v.any():
            tiles[(x_, y_)] = v
    return tiles


def write_tiles(db, tiles, palette):
    """The overlay at zoom 13, then each zoom down to 7 made from the one above."""
    level = tiles
    for z in range(MAXZ, MINZ - 1, -1):
        for (x, y), v in level.items():
            db.execute('INSERT OR REPLACE INTO tile VALUES (?,?,?,?)', (z, x, y, png_rgba(palette[v])))
        if z > MINZ:
            nxt = {}
            for (x, y) in {(x // 2, y // 2) for x, y in level}:
                q = np.zeros((512, 512), np.uint8)
                for dy in (0, 1):
                    for dx in (0, 1):
                        v = level.get((2 * x + dx, 2 * y + dy))
                        if v is not None:
                            q[dy * 256:(dy + 1) * 256, dx * 256:(dx + 1) * 256] = v
                nxt[(x, y)] = down(q)
            level = nxt
        db.commit()


def state(path):
    """One state's raster -> (points, {(x,y): z13 class tile})."""
    t0 = time.time()
    with tifffile.TiffFile(path) as tf:
        pg = tf.pages[0]
        a = pg.asarray()
        tie, sc = pg.tags['ModelTiepointTag'].value, pg.tags['ModelPixelScaleTag'].value
    X0, Y0, S = tie[3], tie[4], sc[0]
    cls = LUT[a]
    del a
    rows, cols = np.nonzero(cls)
    if not rows.size:
        return [], {}, path.name
    cell, ci, n, tot, lon, lat = raster_cells(cls, rows, cols, X0, Y0, S, inverse)
    pts = [(CODES[k - 1], round(float(m) * ACRE_PER_PX, 1), round(float(t) * ACRE_PER_PX, 1), float(lo), float(la), int(cl))
           for k, m, t, lo, la, cl in zip(ci, n, tot, lon, lat, cell)]
    tiles = raster_tiles(cls, rows, cols, X0, Y0, S, inverse, forward)
    print(f'{path.name}: {len(pts):,} cells, {len(tiles):,} tiles, {time.time() - t0:.0f}s', flush=True)
    return pts, tiles, path.name


def down(q):
    """2x downsample of class codes: keep any crop present (most common non-zero of the four)."""
    s = np.stack([q[0::2, 0::2], q[0::2, 1::2], q[1::2, 0::2], q[1::2, 1::2]])
    out = s.max(axis=0)
    for i in range(4):  # prefer a value that appears in another quadrant pixel
        out = np.where((s[i] > 0) & ((s == s[i]).sum(axis=0) >= 2), s[i], out)
    return out


def main():
    want = sys.argv[1:]
    files = sorted(p for p in SRC.glob(f'CDL_{YEAR}_*.tif') if not want or re.search(r'_(\d+)\.tif$', p.name)[1] in want)
    db = sqlite3.connect(OUT)
    db.executescript('''PRAGMA journal_mode=WAL; DROP TABLE IF EXISTS resource; DROP TABLE IF EXISTS spatial; DROP TABLE IF EXISTS tile;
      CREATE TABLE resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT);
      CREATE INDEX resource_kind ON resource(kind);
      CREATE VIRTUAL TABLE spatial USING rtree(id, minx, maxx, miny, maxy);
      CREATE TABLE tile(z INT, x INT, y INT, png BLOB, PRIMARY KEY(z,x,y)) WITHOUT ROWID;
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);''')
    allt, npts = {}, 0
    with ProcessPoolExecutor(8) as pool:
        for pts, tiles, name in pool.map(state, files):
            for code, acres, total, lon, lat, cell in pts:
                crop, group, _ = CROPS[code]
                cur = db.execute('INSERT INTO resource(source_id,kind,name,lat,lon,detail,source) VALUES (?,?,?,?,?,?,?)',
                                 (f'{name}:{cell}', KIND[group], crop, lat, lon,
                                  json.dumps({'crop': crop, 'crop_acres': acres, 'perennial_acres': total, 'year': YEAR}),
                                  'https://www.nass.usda.gov/Research_and_Science/Cropland/SARS1a.php'))
                db.execute('INSERT INTO spatial VALUES (?,?,?,?,?)', (cur.lastrowid, lon, lon, lat, lat))
            npts += len(pts)
            for k, v in tiles.items():  # states share border tiles: merge
                allt[k] = v if k not in allt else np.where(allt[k] > 0, allt[k], v)
            db.commit()
    write_tiles(db, allt, PALETTE)
    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('built', json.dumps({'cells': npts, 'year': YEAR, 'states': len(files), 'at': time.strftime('%Y-%m-%dT%H:%M:%S')})))
    db.commit()
    print(f'done: {npts:,} clickable cells, {len(allt):,} detailed tiles', flush=True)


if __name__ == '__main__':
    main()

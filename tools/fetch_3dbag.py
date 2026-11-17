#!/usr/bin/env python3
"""Building heights for the Netherlands from 3D BAG, as a small lookup that tools/build_bag.py joins to the BAG buildings.

  derived/buildenv/bin/python tools/fetch_3dbag.py download derived/nl-heights/src
  derived/buildenv/bin/python tools/fetch_3dbag.py heights derived/nl-heights/src/3dbag_nl.gpkg.zip derived/nl-heights/heights.sqlite
  derived/buildenv/bin/python tools/build_bag.py derived/sources/nl/bag-light.gpkg derived/nl-heights --heights derived/nl-heights/heights.sqlite

Reads: the 3D BAG data dump of 3 September 2025 (v20250903), https://3dbag.fsn1.your-objectstorage.com/v20250903/3dbag_nl.gpkg.zip
(3DBAG by the 3D geoinformation research group at TU Delft and 3DGI, CC BY 4.0, https://docs.3dbag.nl/en/copyright/; credit
"© 3DBAG by tudelft3d and 3DGI"). About 19.6 GB as a seek-optimised ZIP of one GeoPackage (111 GB unpacked), which is never
unpacked: the `heights` step reads two layers straight out of the zip with GDAL (the pyogrio wheel brings its own GDAL; build
machine only, see tools/requirements-build-nl.txt) and never asks for a geometry:
  pand.b3_h_maaiveld   ground level of the building, metres above NAP (5th percentile of the AHN ground points around it)
  lod13_2d.b3_h_70p    70th percentile of the roof surface, metres above NAP, one row per building part above ground
Height above ground is the tallest part's b3_h_70p minus b3_h_maaiveld. The 70th percentile sits between eaves and ridge, so
pitched roofs read a little low and flat roofs read true. Buildings with no 3D model (3D BAG leaves out those without usable
AHN points) get no row; neither does one under 1 m, which is a slab, not a building. Both read as 0 = unknown, which the 3D view
draws one storey tall. The `heights` step also accepts a plain .gpkg with those two layers, which is what the tests use.
Writes: heights.sqlite with height(pand INTEGER PRIMARY KEY, dm INT) WITHOUT ROWID, the BAG pand number (the 16-digit
identificatie as an integer) and decimetres above ground, and meta (source, counts). Only buildings with a height get a row.
The download is resumable: a partial file is kept as <name>.part and continued with a Range request.
"""
import argparse, math, sqlite3, sys, time, urllib.error, urllib.request
from pathlib import Path

URL = 'https://3dbag.fsn1.your-objectstorage.com/v20250903/3dbag_nl.gpkg.zip'
SOURCE = '3D BAG v2025.09.03, 3DBAG by tudelft3d and 3DGI (CC BY 4.0), LoD1.3 b3_h_70p minus b3_h_maaiveld'
MIN_DM, MAX_DM = 10, 3000        # under 1 m is a slab; nothing in the Netherlands is over 300 m (the tallest is about 275 m)
CHUNK = 1 << 20


def pand_number(identificatie):
    """The BAG pand number as an integer from 'NL.IMBAG.Pand.0363100012345678' (3D BAG) or '0363100012345678' (BAG light), or None."""
    if not isinstance(identificatie, str):
        return None
    tail = identificatie.rsplit('.', 1)[-1]
    return int(tail) if tail.isdigit() else None


def height_dm(roof, ground):
    """Decimetres above ground from NAP heights of the roof and the ground; 0 where either is unknown or the result is no building."""
    if roof is None or ground is None or math.isnan(roof) or math.isnan(ground):
        return 0
    dm = round((roof - ground) * 10)
    return 0 if dm < MIN_DM else min(dm, MAX_DM)


def _rows(src, layer, columns):
    """Rows (one tuple per feature, no geometry) of a layer in a plain GeoPackage, or in anything GDAL opens (/vsizip/ paths, zips)."""
    src = str(src)
    if src.endswith('.gpkg') and Path(src).is_file():
        db = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
        yield from db.execute(f'SELECT {", ".join(columns)} FROM {layer}')
        db.close()
        return
    try:
        from pyogrio import raw
    except ImportError:
        sys.exit('reading the 3D BAG zip needs pyogrio: derived/buildenv/bin/pip install -r tools/requirements-build-nl.txt')
    path = f'/vsizip/{src}' if src.endswith('.zip') else src
    meta, _, _, data = raw.read(path, layer=layer, columns=list(columns), read_geometry=False)
    by_name = dict(zip(meta['fields'], data))                    # GDAL returns the columns in the layer's order, not the one asked for
    yield from zip(*(by_name[c] for c in columns))


def build_heights(src, out, log=lambda m: None):
    """Reads the two layers of the 3D BAG dump src and writes the height lookup out; returns {'buildings', 'with_height'}."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.partial')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;'
                     'CREATE TABLE ground(pand INTEGER PRIMARY KEY, m REAL) WITHOUT ROWID;'
                     'CREATE TABLE roof(pand INTEGER PRIMARY KEY, m REAL) WITHOUT ROWID;'
                     'CREATE TABLE height(pand INTEGER PRIMARY KEY, dm INT) WITHOUT ROWID;'
                     'CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);')
    db.create_function('height_dm', 2, height_dm, deterministic=True)

    def load(layer, column, merge, keep_null=False):
        n, batch = 0, []
        for ident, value in _rows(src, layer, ('identificatie', column)):
            pand = pand_number(ident)
            known = value is not None and not math.isnan(value)
            if pand is not None and (known or keep_null):
                batch.append((pand, float(value) if known else None))
            if len(batch) >= 200_000:
                db.executemany(merge, batch); n += len(batch); batch = []
                if n % 2_000_000 == 0:
                    log(f'{layer}: {n:,}')
        db.executemany(merge, batch)
        db.commit()
        return n + len(batch)

    load('pand', 'b3_h_maaiveld', 'INSERT OR REPLACE INTO ground VALUES (?,?)', keep_null=True)   # counts every building with a 3D model
    load('lod13_2d', 'b3_h_70p',      # the tallest part of a building
         'INSERT INTO roof VALUES (?,?) ON CONFLICT(pand) DO UPDATE SET m = max(m, excluded.m)')
    db.execute('INSERT INTO height SELECT g.pand, height_dm(r.m, g.m) FROM ground g JOIN roof r USING(pand) WHERE height_dm(r.m, g.m) > 0')
    buildings = db.execute('SELECT count(*) FROM ground').fetchone()[0]
    with_height = db.execute('SELECT count(*) FROM height').fetchone()[0]
    db.executemany('INSERT INTO meta VALUES (?,?)', [('source', SOURCE), ('buildings', str(buildings)), ('with_height', str(with_height)),
                                                     ('built', time.strftime('%Y-%m-%dT%H:%M:%S'))])
    db.executescript('DROP TABLE ground; DROP TABLE roof;')
    db.commit()
    db.execute('VACUUM')
    db.close()
    tmp.replace(out)
    return {'buildings': buildings, 'with_height': with_height}


class Heights:
    """The lookup tools/build_bag.py reads: get(identificatie) is decimetres above ground, 0 where unknown."""

    def __init__(self, path):
        self.db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        self.meta = dict(self.db.execute('SELECT key, value FROM meta'))

    def get(self, identificatie):
        pand = pand_number(identificatie)
        if pand is None:
            return 0
        row = self.db.execute('SELECT dm FROM height WHERE pand=?', (pand,)).fetchone()
        return row[0] if row else 0

    def close(self):
        self.db.close()


def _total(headers, have, status):
    """The whole file's size, from Content-Range (bytes a-b/N or bytes */N) or Content-Length; None when the server gives neither."""
    rng = headers.get('Content-Range') or ''
    if '/' in rng and rng.rsplit('/', 1)[1].isdigit():
        return int(rng.rsplit('/', 1)[1])
    length = headers.get('Content-Length')
    if length and length.isdigit():
        return int(length) + (have if status == 206 else 0)
    return None


def download(url, dest, log=lambda m: None, _again=True):
    """Fetches url to dest, continuing <dest>.part where an earlier run stopped. A finished dest is left alone. The file is called
    finished only at the size the server gives; a .part that does not fit is fetched again, and a cut-off download raises (run again
    to resume)."""
    dest = Path(dest)
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + '.part')
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={'User-Agent': 'lastbook-build-tools', **({'Range': f'bytes={have}-'} if have else {})})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code != 416:
            raise
        total = _total(e.headers, 0, 416)
        if total is not None and total == have:          # the whole file is already in the .part
            part.replace(dest)
            return dest
        part.unlink(missing_ok=True)                      # longer than the file, or of no known size: start again
        if not _again:
            raise
        return download(url, dest, log, _again=False)
    with resp:
        if have and resp.status != 206:                   # the server ignored the Range: start again
            have = 0
        total = _total(resp.headers, have, resp.status)
        with open(part, 'ab' if have else 'wb') as f:
            t0, got, next_log = time.time(), have, have + 256 * CHUNK
            while chunk := resp.read(CHUNK):
                f.write(chunk); got += len(chunk)
                if got >= next_log:
                    next_log += 256 * CHUNK
                    log(f'{got / 1e9:.1f} GB ({(got - have) / 1e6 / max(1, time.time() - t0):.0f} MB/s)')
    if total is not None and got != total:
        raise OSError(f'{dest.name}: the download stopped at {got:,} of {total:,} bytes; run again to resume')
    part.replace(dest)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('download', help='fetch the 3D BAG dump (about 19.6 GB, resumable)')
    d.add_argument('dir')
    d.add_argument('--url', default=URL)
    h = sub.add_parser('heights', help='read the dump into heights.sqlite')
    h.add_argument('src', help='3dbag_nl.gpkg.zip (or a plain .gpkg)')
    h.add_argument('out')
    a = ap.parse_args()
    t0 = time.time()
    log = lambda m: print(f'{m} ({time.time() - t0:.0f}s)', flush=True)
    if a.cmd == 'download':
        print(download(a.url, Path(a.dir) / a.url.rsplit('/', 1)[-1], log))
    else:
        c = build_heights(a.src, a.out, log)
        print(f'done: {c["buildings"]:,} buildings in 3D BAG, {c["with_height"]:,} with a height', flush=True)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Flood defences and flood scenarios for the Netherlands, written into water.sqlite as map features.

  derived/buildenv/bin/python tools/build_floods_nl.py derived/nl-floods/water.sqlite --src derived/nl-floods/src
  derived/buildenv/bin/python tools/build_floods_nl.py water.sqlite --src DIR --scenarios t100,t1000 --fetch-only

Reads (downloads into --src on the first run, and reuses what is there on later ones):
  - NBPW, the national base file of primary flood defences: dike sections as lines in EPSG:28992 (Rijkswaterstaat WFS,
    https://geo.rijkswaterstaat.nl/services/ogc/wvp/nbpw/wfs, layer nbpw:nbpw_dijktrajecten_formeel, 237 sections). Public domain
    (Publiek domein, CC Public Domain Mark 1.0 on data.overheid.nl, dataset 82778).
  - ROR, the EU Floods Directive maps (third cycle) as the provinces publish them: the greatest water depth in a flood, in depth
    classes, for four scenarios (WFS layers ror3:t10_, t100_, t1000_ and t10000_maximale_waterdiepte on
    https://ldo-geoserver.lizard.net/geoserver/wfs, Interprovinciaal Overleg). CC0 1.0 (data.overheid.nl, dataset "Overstromingsrisicokaarten").
    The service holds each scenario as millions of 5 m pieces (4 to 7 million). They are read a page at a time, never kept whole.
Writes: `feat` rows in the water.sqlite you name (layers `flood` and `dike`, origin `floods-nl`; a second run replaces only those rows).
  - `flood`: cls `t100-3` is the scenario and the depth class (1 to 5, see DEPTHS); the shape is one 10 km block of one class.
    Each scenario is read onto a 25 m grid (a cell is flooded when its centre is), then every second cell is taken (50 m), the six
    depth classes become five, and the outlines are traced, simplified (25 m) and left out below 2.5 ha.
  - `dike`: cls `primary`, name the section and its safety standard; lines.
  Coordinates go from EPSG:28992 to WGS84 with pyproj. server.py serves them at /api/map/flood/<z>/<x>/<y>, not in the base tile.
Not used: the CC BY-SA "waterschappen-keringen-imwa" file (Het Waterschapshuis).
Flood scenarios are what could happen if the defences failed, not a forecast.
"""
import argparse, json, math, sqlite3, sys, time, urllib.request, urllib.parse
from collections import namedtuple
from itertools import chain
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from map_schema import pack, bbox                                            # noqa: E402

ORIGIN = 'floods-nl'
FLOOD_MINZ = 8                  # a whole-country view would carry far too many outlines
DIKE_MINZ = 7
CELL = 25.0                     # metres: the grid the scenarios are read onto (kept in src/, and fine enough to redo the rest)
STEP = 2                        # the stored outlines come from every second cell: a 50 m grid
TOL_M = 25.0                    # outline simplification, metres
MIN_AREA_M2 = 25000.0           # outlines (islands and holes alike) smaller than this are left out: 2.5 ha
DIKE_TOL_M = 2.0
BLOCK = 200                     # cells (10 km at 50 m) in one stored shape
PAGE = 50000

ROR_WFS = 'https://ldo-geoserver.lizard.net/geoserver/wfs'
NBPW_WFS = 'https://geo.rijkswaterstaat.nl/services/ogc/wvp/nbpw/wfs'
UA = 'lastbook-build-tool (offline survival library; reads open flood data)'

SCENARIOS = {'t10': 'Large probability: about once in 10 years', 't100': 'Medium probability: about once in 100 years',
             't1000': 'Small probability: about once in 1,000 years', 't10000': 'Very small probability: about once in 10,000 years'}
LEGEND = ['minder dan 0,5 m', 'tussen 0,5 en 1,0 m', 'tussen 1,0 en 1,5 m', 'tussen 1,5 en 2,0 m', 'tussen 2,0 en 5,0 m', 'meer dan 5,0 m']
# The service has six depth classes; the map keeps five (1.0 to 1.5 and 1.5 to 2.0 m become one), which keeps the outlines simple.
DEPTHS = ['less than 0.5 m deep', 'between 0.5 and 1.0 m deep', 'between 1.0 and 2.0 m deep', 'between 2.0 and 5.0 m deep', 'more than 5 m deep']
_MERGE = np.array([0, 1, 2, 3, 3, 4, 5], np.uint8)

Grid = namedtuple('Grid', 'x0 y0 pitch nx ny')      # EPSG:28992 metres; row 0 is the southmost; cell (i, j) spans x0+pitch*i .. +pitch
RD_GRID = Grid(-10000, 280000, CELL, int(320000 / CELL), int(350000 / CELL))   # all of the European Netherlands, with a margin


def depth_class(text):
    """1 to 6 for the service's depth legend ('tussen 0,5 en 1,0 m' is 2). An unknown legend is an error: it means the service changed."""
    try:
        return LEGEND.index(text.strip()) + 1
    except ValueError:
        raise ValueError(f'unknown depth legend {text!r}')


# ---------------------------------------------------------------- reading the 5 m pieces ----
_TOP_BIT = np.zeros(256, np.uint8)
for _v in range(1, 256):
    _TOP_BIT[_v] = _v.bit_length()


def burn_page(diff, feats, grid=RD_GRID):
    """Adds the outlines of feats (GeoJSON features: polygons in RD New metres, legend in properties) to diff.
    diff holds one bit per depth class, set where an outline side crosses the row of cell centres: a running XOR along the row,
    coverage(), then gives the cells whose centre lies inside (holes included). Sides that run along a row are skipped."""
    rings, bits = [], []
    for f in feats:
        props = f['properties']
        bit = 1 << (depth_class(props['legenda'] if 'legenda' in props else props['LEGENDA']) - 1)
        g = f['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for poly in polys:
            rings.extend(poly)
            bits.extend([bit] * len(poly))
    if not rings:
        return
    lens = np.fromiter(map(len, rings), np.int64, len(rings))
    pts = np.fromiter(chain.from_iterable(chain.from_iterable(rings)), np.float64, 2 * int(lens.sum())).reshape(-1, 2)
    ids = np.repeat(np.arange(len(rings)), lens)
    ebits = np.repeat(np.array(bits, np.uint8), lens)[:-1]
    ok = (ids[:-1] == ids[1:]) & (pts[:-1, 1] != pts[1:, 1])
    xa, ya, xb, yb = pts[:-1, 0][ok], pts[:-1, 1][ok], pts[1:, 0][ok], pts[1:, 1][ok]
    ebits = ebits[ok]
    p = grid.pitch
    lo, hi = np.minimum(ya, yb), np.maximum(ya, yb)
    j0 = np.maximum(np.ceil((lo - grid.y0 - p / 2) / p).astype(np.int64), 0)      # rows whose centre is in [lo, hi)
    j1 = np.minimum(np.ceil((hi - grid.y0 - p / 2) / p).astype(np.int64), grid.ny)
    keep = j1 > j0
    xa, ya, xb, yb, j0, j1, ebits = xa[keep], ya[keep], xb[keep], yb[keep], j0[keep], j1[keep], ebits[keep]
    if not j0.size:
        return
    n = j1 - j0
    start = np.cumsum(n) - n
    which = np.repeat(np.arange(len(n)), n)
    rows = j0[which] + (np.arange(int(n.sum())) - start[which])
    yc = grid.y0 + p / 2 + rows * p
    x = xa[which] + (yc - ya[which]) * (xb[which] - xa[which]) / (yb[which] - ya[which])
    col = np.maximum(np.floor((x - grid.x0 - p / 2) / p).astype(np.int64) + 1, 0)   # first cell whose centre is east of the side
    inside = col < grid.nx
    np.bitwise_xor.at(diff, (rows[inside], col[inside]), ebits[which][inside])


def unbalanced_rows(diff):
    """Rows of diff whose outline sides do not pair up. Closed outlines always pair up, so anything but 0 means a page was lost or read twice."""
    return int(np.count_nonzero(np.bitwise_xor.reduce(diff, axis=1)))


def coverage(diff):
    """Depth class (0 none, 1 to 6) of every cell, from the diff array burn_page filled."""
    return _TOP_BIT[np.bitwise_xor.accumulate(diff, axis=1)]


def merge_depths(cls):
    """The service's six depth classes (1 to 6) as the map's five (DEPTHS); 0 stays 0."""
    return _MERGE[cls]


def downsample(cls, grid, step=STEP):
    """Every step-th cell in both directions, with the grid that fits it: the kept cells stay centred on the same points."""
    out = cls[::step, ::step]
    shift = (step - 1) * grid.pitch / 2
    return out, Grid(grid.x0 - shift, grid.y0 - shift, grid.pitch * step, out.shape[1], out.shape[0])


def ring_area(ring):
    """Area of a ring of (x, y) points, whichever way round it runs."""
    a = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


# ---------------------------------------------------------------- outlines ----
def trace(mask):
    """Outlines of a boolean grid as rings of corner points (x = column, y = row), without points on straight runs. Land is on the left of
    every edge, so outer rings run counter-clockwise and holes clockwise: signed areas add up, and an even-odd fill gives the shape."""
    h, w = mask.shape
    m = np.pad(mask, 1)
    inner = m[1:-1, 1:-1]
    K = w + 3
    jj, ii = np.indices((h, w))
    starts, ends = [], []
    for sel, (sx, sy), (ex, ey) in ((inner & ~m[:-2, 1:-1], (0, 0), (1, 0)), (inner & ~m[1:-1, 2:], (1, 0), (1, 1)),
                                    (inner & ~m[2:, 1:-1], (1, 1), (0, 1)), (inner & ~m[1:-1, :-2], (0, 1), (0, 0))):
        i, j = ii[sel], jj[sel]
        starts.append((j + sy) * K + i + sx)
        ends.append((j + ey) * K + i + ex)
    if not starts or not sum(len(s) for s in starts):
        return []
    S, E = np.concatenate(starts).tolist(), np.concatenate(ends).tolist()
    nxt, extra = {}, {}
    for s, e in zip(S, E):
        if s in nxt:
            extra.setdefault(s, []).append(e)       # two edges leave a point where two cells touch at a corner
        else:
            nxt[s] = e
    rings = []
    while nxt:
        s, e = nxt.popitem()
        if s in extra:
            nxt[s] = extra[s].pop()
            if not extra[s]:
                del extra[s]
        first = e - s
        ring, prev, cur = [], first, e
        while cur != s:
            n = nxt.pop(cur)
            if cur in extra:
                nxt[cur] = extra[cur].pop()
                if not extra[cur]:
                    del extra[cur]
            d = n - cur
            if d != prev:
                ring.append(cur)
            prev, cur = d, n
        if first != prev:
            ring.append(s)
        if len(ring) >= 3:
            rings.append([(k % K, k // K) for k in ring])
    return rings


def _dp_keep(a, tol):
    """Douglas-Peucker on an (n, 2) array: a boolean mask of the points to keep (both ends always)."""
    n = len(a)
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        p0, p1, mid = a[i], a[j], a[i + 1:j]
        d = p1 - p0
        norm = math.hypot(d[0], d[1])
        dist = np.hypot(*(mid - p0).T) if norm == 0 else np.abs(d[0] * (mid[:, 1] - p0[1]) - d[1] * (mid[:, 0] - p0[0])) / norm
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return keep


def simplify_line(pts, tol):
    a = np.asarray(pts, float)
    return a[_dp_keep(a, tol)].tolist() if len(a) > 2 and tol > 0 else [list(p) for p in a]


def simplify_ring(pts, tol):
    """Douglas-Peucker for a ring (first point not repeated). Always keeps at least three points."""
    a = np.asarray(pts, float)
    if len(a) <= 3 or tol <= 0:
        return [tuple(p) for p in a.tolist()]
    far = int(np.argmax(np.hypot(*(a - a[0]).T)))
    keep = np.zeros(len(a), bool)
    keep[:far + 1] = _dp_keep(a[:far + 1], tol)
    back = np.vstack([a[far:], a[:1]])
    keep[far:] |= _dp_keep(back, tol)[:-1]
    if keep.sum() < 3:
        d = a[far] - a[0]
        side = np.abs(d[0] * (a[:, 1] - a[0, 1]) - d[1] * (a[:, 0] - a[0, 0]))
        keep[[0, far, int(np.argmax(side))]] = True
    return [tuple(p) for p in a[keep].tolist()]


def _to_lonlat():
    from pyproj import Transformer
    t = Transformer.from_crs(28992, 4326, always_xy=True)

    def convert(rings):
        """rings: lists of (x, y) in metres -> flat [lon, lat, ...] lists, one transform call for all."""
        flat = np.array([p for r in rings for p in r], float)
        if not len(flat):
            return []
        lon, lat = t.transform(flat[:, 0], flat[:, 1])
        out, o = [], 0
        for r in rings:
            n = len(r)
            seg = np.empty(2 * n)
            seg[0::2], seg[1::2] = lon[o:o + n], lat[o:o + n]
            out.append(seg.tolist())
            o += n
        return out
    return convert


def flood_polygons(cls, grid=RD_GRID, block=BLOCK, tol_m=TOL_M, min_area_m2=0):
    """Yields (depth class, parts) for every block of the class grid and every class in it; parts are flat lon/lat rings."""
    convert = _to_lonlat()
    h, w = cls.shape
    for j0 in range(0, h, block):
        for i0 in range(0, w, block):
            sub = cls[j0:j0 + block, i0:i0 + block]
            for c in np.unique(sub):
                if c == 0:
                    continue
                rings = []
                for r in trace(sub == c):
                    metres = [(grid.x0 + grid.pitch * (i0 + x), grid.y0 + grid.pitch * (j0 + y)) for x, y in r]
                    if min_area_m2 and ring_area(metres) < min_area_m2:
                        continue
                    metres = simplify_ring(metres, tol_m)
                    if len(metres) >= 3:
                        rings.append(metres)
                parts = convert(rings)
                if parts:
                    yield int(c), parts


def norm_text(props):
    """'Dike section 14-3 (safety standard: ...)': NORM_OG is the highest chance a year of a flood the section must still hold against."""
    name = f"Dike section {props.get('TRAJECT_ID') or props.get('traject_id') or '?'}"
    og = props.get('NORM_OG') or props.get('norm_og')
    return f'{name} (safety standard: flooding no more likely than 1 in {int(og):,} a year)' if og else name


def dike_rows(gj, tol_m=DIKE_TOL_M):
    """Yields (name, parts) for each dike section of the NBPW GeoJSON (RD New metres); parts are flat lon/lat lines."""
    convert = _to_lonlat()
    for f in gj['features']:
        g = f['geometry']
        lines = g['coordinates'] if g['type'] == 'MultiLineString' else [g['coordinates']]
        lines = [simplify_line([c[:2] for c in line], tol_m) for line in lines]
        parts = [p for p in convert([[tuple(c) for c in line] for line in lines if len(line) >= 2]) if len(p) >= 4]
        if parts:
            yield norm_text(f['properties']), parts


# ---------------------------------------------------------------- the database ----
def write_features(path, floods, dikes, counts, built=None):
    """Replaces this tool's rows (origin floods-nl) in a water.sqlite. floods: (scenario, depth class, parts); dikes: (name, parts)."""
    db = sqlite3.connect(path)
    db.executescript('''CREATE TABLE IF NOT EXISTS feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB, origin TEXT);
      CREATE INDEX IF NOT EXISTS feat_origin ON feat(origin);
      CREATE VIRTUAL TABLE IF NOT EXISTS feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);''')
    db.execute('DELETE FROM feat_idx WHERE id IN (SELECT id FROM feat WHERE origin=?)', (ORIGIN,))
    db.execute('DELETE FROM feat WHERE origin=?', (ORIGIN,))
    n = {'flood': 0, 'dike': 0}

    def add(layer, cls, name, minz, parts):
        cur = db.execute('INSERT INTO feat(layer,cls,name,minz,geom,origin) VALUES (?,?,?,?,?,?)', (layer, cls, name, minz, pack(parts), ORIGIN))
        db.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (cur.lastrowid, *bbox(parts), minz, 30))
        n[layer] += 1
    for scn, c, parts in floods:
        add('flood', f'{scn}-{c}', DEPTHS[c - 1], FLOOD_MINZ, parts)
    for name, parts in dikes:
        add('dike', 'primary', name, DIKE_MINZ, parts)
    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (ORIGIN, json.dumps({**n, 'scenarios': counts, 'cell_m': CELL * STEP,
                                                                                  'built': built or time.strftime('%Y-%m-%dT%H:%M:%S')})))
    db.commit()
    db.close()
    return n


# ---------------------------------------------------------------- downloads ----
def get(url, tries=12):
    """The page at url; the service is rate limited, so a failed request is tried again, a little later each time."""
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=300) as r:
                return r.read()
        except Exception as e:
            if k == tries - 1:
                raise
            print(f'  retry after {e}', flush=True)
            time.sleep(min(60, 5 * (k + 1)))


def wfs(base, layer, **extra):
    q = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': layer, **extra}
    return base + '?' + urllib.parse.urlencode(q, safe=':,')


def fetch_dikes(src):
    path = Path(src) / 'nbpw_dijktrajecten_formeel.json'
    if not path.exists():
        path.write_bytes(get(wfs(NBPW_WFS, 'nbpw:nbpw_dijktrajecten_formeel', outputFormat='application/json')))
    return json.loads(path.read_text())


def fetch_scenario(scn, src, grid=RD_GRID, log=print):
    """Class grid for one scenario, from src/<scn>-classes.npy or the service, a page at a time (src/<scn>-diff.npy resumes a stopped run)."""
    src = Path(src)
    done = src / f'{scn}-classes.npy'
    if done.exists():
        return np.load(done)
    diff_path, state_path = src / f'{scn}-diff.npy', src / f'{scn}-state.json'
    layer = f'ror3:{scn}_maximale_waterdiepte'
    hits = get(wfs(ROR_WFS, layer, resultType='hits')).decode()
    total = int(hits.split('numberMatched="')[1].split('"')[0])
    diff, at = np.zeros((grid.ny, grid.nx), np.uint8), 0
    one = json.loads(get(wfs(ROR_WFS, layer, outputFormat='application/json', count=1)))['features'][0]['properties']
    props = 'geom,' + next(k for k in one if k.lower() == 'legenda')          # the t10000 layer spells it LEGENDA
    if diff_path.exists() and state_path.exists():
        diff, at = np.load(diff_path), json.loads(state_path.read_text())['next']
        log(f'{scn}: resuming at {at:,} of {total:,}')
    t0, pages = time.time(), 0
    while at < total:
        gj = json.loads(get(wfs(ROR_WFS, layer, outputFormat='application/json', count=PAGE, startIndex=at, propertyName=props)))
        feats = gj['features']
        if not feats:
            raise RuntimeError(f'{scn}: the service returned nothing at {at:,} of {total:,}')
        burn_page(diff, feats, grid)
        at += len(feats)
        pages += 1
        if pages % 20 == 0:
            np.save(diff_path, diff)
            state_path.write_text(json.dumps({'next': at}))
            log(f'{scn}: {at:,} of {total:,} pieces ({time.time() - t0:.0f}s)')
    if unbalanced_rows(diff):
        raise RuntimeError(f'{scn}: {unbalanced_rows(diff):,} rows do not balance: a page was lost or read twice. Delete {diff_path.name} and {state_path.name} and run again.')
    cls = coverage(diff)
    np.save(done, cls)
    diff_path.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)
    return cls


def build(water, src, scenarios, fetch_only=False, grid=RD_GRID, log=print):
    src = Path(src)
    src.mkdir(parents=True, exist_ok=True)
    dikes = fetch_dikes(src)
    classes = {s: fetch_scenario(s, src, grid, log) for s in scenarios}
    if fetch_only:
        return None
    floods, counts = [], {}
    for s, cls in classes.items():
        per = {}
        km2 = round(float(np.count_nonzero(cls)) * grid.pitch ** 2 / 1e6)
        coarse, cgrid = downsample(merge_depths(cls), grid)
        for c, parts in flood_polygons(coarse, cgrid, min_area_m2=MIN_AREA_M2):
            floods.append((s, c, parts))
            per[c] = per.get(c, 0) + 1
        counts[s] = {'km2': km2, 'shapes': sum(per.values())}
        log(f'{s}: {counts[s]["km2"]:,} km2 flooded, {counts[s]["shapes"]:,} shapes')
    n = write_features(water, floods, list(dike_rows(dikes)), counts)
    log(f'wrote {n["flood"]:,} flood shapes and {n["dike"]:,} dike sections')
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('water', help='water.sqlite to add the features to (a copy of derived/geo-nl/water.sqlite)')
    ap.add_argument('--src', required=True, help='folder for the downloads (kept between runs)')
    ap.add_argument('--scenarios', default=','.join(SCENARIOS), help='comma list of t10,t100,t1000,t10000')
    ap.add_argument('--fetch-only', action='store_true')
    a = ap.parse_args()
    scn = a.scenarios.split(',')
    if any(s not in SCENARIOS for s in scn):
        sys.exit(f'scenarios are {", ".join(SCENARIOS)}')
    t0 = time.time()
    build(a.water, a.src, scn, a.fetch_only, log=lambda m: print(f'{m} ({time.time() - t0:.0f}s)', flush=True))


if __name__ == '__main__':
    main()

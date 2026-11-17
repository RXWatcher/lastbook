"""Builds derived/geo/water.sqlite: dams (USACE National Inventory of Dams) and lakes/reservoirs/ponds (USGS NHD).

  python tools/build_water.py nid            # dams from derived/geo/sources/nid/nation.csv
  python tools/build_water.py nhd [STATE..]  # waterbodies from derived/geo/sources/nhd/*.zip (all downloaded states by default)
  python tools/build_water.py --geo derived/geo-nl osm   # another map folder: named lakes from its street map only

The `resource` + `spatial` tables mirror the resource atlas so the map's pin code reads both; `feat` + `feat_idx`
mirror the street-map tiles so waterbody outlines draw as water.
"""
import csv, json, math, os, sqlite3, struct, sys, tempfile, time, zipfile
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
GEO = HERE / 'derived/geo'
DB = GEO / 'water.sqlite'


def open_db():
    db = sqlite3.connect(DB)
    db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;
      CREATE TABLE IF NOT EXISTS resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT, origin TEXT);
      CREATE INDEX IF NOT EXISTS resource_kind ON resource(kind);
      CREATE INDEX IF NOT EXISTS resource_origin ON resource(origin);
      CREATE VIRTUAL TABLE IF NOT EXISTS spatial USING rtree(id, minx, maxx, miny, maxy);
      CREATE TABLE IF NOT EXISTS feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB, origin TEXT);
      CREATE INDEX IF NOT EXISTS feat_origin ON feat(origin);
      CREATE VIRTUAL TABLE IF NOT EXISTS feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);
      CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
      CREATE TABLE IF NOT EXISTS nhd_seen(pid TEXT PRIMARY KEY, origin TEXT);''')
    return db


def forget(db, origin):
    """Re-running a source replaces only that source's rows."""
    db.execute('DELETE FROM spatial WHERE id IN (SELECT id FROM resource WHERE origin=?)', (origin,))
    db.execute('DELETE FROM resource WHERE origin=?', (origin,))
    db.execute('DELETE FROM feat_idx WHERE id IN (SELECT id FROM feat WHERE origin=?)', (origin,))
    db.execute('DELETE FROM feat WHERE origin=?', (origin,))
    db.execute('DELETE FROM nhd_seen WHERE origin=?', (origin,))


def add_point(db, origin, source_id, kind, name, lat, lon, detail, source):
    cur = db.execute('INSERT INTO resource(source_id,kind,name,lat,lon,detail,source,origin) VALUES (?,?,?,?,?,?,?,?)',
                     (source_id, kind, name, lat, lon, json.dumps(detail, separators=(',', ':')), source, origin))
    db.execute('INSERT INTO spatial VALUES (?,?,?,?,?)', (cur.lastrowid, lon, lon, lat, lat))


# ------------------------------------------------------------------ NID ----
NID_KEEP = {'Other Names': 'other_names', 'Owner Names': 'owner', 'Primary Purpose': 'purpose', 'Purposes': 'purposes',
            'River or Stream Name': 'river', 'State': 'state', 'County': 'county', 'City': 'city',
            'NID Height (Ft)': 'height_ft', 'Year Completed': 'year', 'Normal Storage (Acre-Ft)': 'normal_storage_af',
            'Max Storage (Acre-Ft)': 'max_storage_af', 'Surface Area (Acres)': 'surface_acres', 'Primary Dam Type': 'dam_type',
            'Hazard Potential Classification': 'hazard', 'Condition Assessment': 'condition', 'Operational Status': 'status'}


def build_nid():
    path = GEO / 'sources/nid/nation.csv'
    with open(path, encoding='utf-8', errors='replace') as f:
        stamp = f.readline().strip().split(',')[-1]
        rows = list(csv.DictReader(f))
    db = open_db()
    forget(db, 'nid')
    n = 0
    for r in rows:
        try:
            lat, lon = float(r['Latitude']), float(r['Longitude'])
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            continue
        d = {k2: r[k].strip() for k, k2 in NID_KEEP.items() if (r.get(k) or '').strip() not in ('', 'None', '-1', '0')}
        nid = r['NID ID']
        add_point(db, 'nid', nid, 'dam', r['Dam Name'].strip() or 'Unnamed dam', lat, lon, d,
                  f'https://nid.sec.usace.army.mil/#/dams/system/{nid}/summary')
        n += 1
    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('nid', json.dumps({'records': n, 'data_last_updated': stamp, 'built': time.strftime('%Y-%m-%dT%H:%M:%S')})))
    db.commit()
    print(f'NID: {n:,} dams (data last updated {stamp})')


# ------------------------------------------------------------------ NHD ----
# NHD waterbody feature types: 390 lake/pond, 436 reservoir, 466 swamp/marsh, 493 estuary, 361 playa, 378 ice mass
NHD_KIND = {390: 'lake', 436: 'reservoir', 493: 'estuary'}
LAYER = {390: ('water', 'water'), 436: ('water', 'reservoir'), 493: ('water', 'water'), 466: ('wet', 'wet'), 361: ('land', 'playa')}
# NHDArea: 445 sea/ocean (gives the coastline outside SoCal), 460 wide rivers, 312 bays and inlets
# reservoir types that hold waste or chemicals: still drawn and listed, but flagged as not water to drink
BAD_RESERVOIR = {43604, 43605, 43606, 43607, 43609, 43610, 43611, 43612, 43623, 43624, 43625, 43626}
SKIP_POINT = {43603, 43608}  # decorative and swimming pools
AREA_LAYER = {445: ('water', 'ocean'), 460: ('water', 'river'), 312: ('water', 'water')}


def wkb_polys(b):
    """GeoPackage geometry blob -> list of polygons, each a list of rings of (lon, lat). Z/M dropped."""
    flags = b[3]
    env = (0, 32, 48, 48, 64)[(flags >> 1) & 7]
    i = 8 + env
    out = []

    def geom(i):
        bo = '<' if b[i] == 1 else '>'
        t = struct.unpack_from(bo + 'I', b, i + 1)[0]
        i += 5
        if t & 0xE0000000:  # EWKB-style Z/M flags
            base, dims = t & 0xFF, 2 + bool(t & 0x80000000) + bool(t & 0x40000000)
        else:  # ISO: 1003 = Z, 2003 = M, 3003 = ZM
            base, dims = t % 1000, 2 + {0: 0, 1: 1, 2: 1, 3: 2}[t // 1000]
        if base == 3:
            nr = struct.unpack_from(bo + 'I', b, i)[0]; i += 4
            rings = []
            for _ in range(nr):
                n = struct.unpack_from(bo + 'I', b, i)[0]; i += 4
                v = struct.unpack_from(bo + str(n * dims) + 'd', b, i); i += n * dims * 8
                rings.append(list(zip(v[0::dims], v[1::dims])))
            out.append(rings)
        elif base == 6:
            n = struct.unpack_from(bo + 'I', b, i)[0]; i += 4
            for _ in range(n):
                i = geom(i)
        return i
    geom(i)
    return out


def simplify(pts, tol):
    """Douglas-Peucker on a ring (degrees)."""
    if len(pts) < 5:
        return pts
    keep = bytearray(len(pts)); keep[0] = keep[-1] = 1
    stack = [(0, len(pts) - 1)]
    while stack:
        a, z = stack.pop()
        ax, ay = pts[a]; zx, zy = pts[z]; dx, dy = zx - ax, zy - ay; L = dx * dx + dy * dy
        best, bi = 0, -1
        for k in range(a + 1, z):
            px, py = pts[k]
            if L:
                t = ((px - ax) * dx + (py - ay) * dy) / L; t = 0 if t < 0 else 1 if t > 1 else t
                ex, ey = ax + t * dx - px, ay + t * dy - py
            else:
                ex, ey = px - ax, py - ay
            d = ex * ex + ey * ey
            if d > best:
                best, bi = d, k
        if best > tol * tol:
            keep[bi] = 1; stack += [(a, bi), (bi, z)]
    return [p for p, k in zip(pts, keep) if k]


def pack(rings):
    a = array('i', [len(rings)])
    for p in rings:
        a.append(len(p)); lx = ly = 0
        for lo, la in p:
            x, y = round(lo * 1e6), round(la * 1e6); a.extend((x - lx, y - ly)); lx, ly = x, y
    return a.tobytes()


def inside_point(ring):
    """A point inside the ring: middle of the widest interior run along a few horizontal scanlines."""
    ys = [y for _, y in ring]; y0, y1 = min(ys), max(ys)
    best = None
    for f in (0.5, 0.35, 0.65, 0.2, 0.8):
        y = y0 + (y1 - y0) * f
        xs = sorted(x1 + (y - ya) * (x2 - x1) / (yb - ya) for (x1, ya), (x2, yb) in zip(ring, ring[1:] + ring[:1])
                    if (ya <= y < yb) or (yb <= y < ya))
        for a, b in zip(xs[0::2], xs[1::2]):
            if best is None or b - a > best[0]:
                best = (b - a, (a + b) / 2, y)
    return (best[1], best[2]) if best else (sum(x for x, _ in ring) / len(ring), sum(ys) / len(ring))


def ring_area_km2(r):
    s = 0
    for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
        s += (x2 - x1) * (y2 + y1)
    lat = sum(y for _, y in r) / len(r)
    return abs(s) / 2 * 111.32 ** 2 * math.cos(math.radians(lat))


def build_nhd(states):
    src = GEO / 'sources/nhd'
    zips = sorted(src.glob('NHD_H_*_State_GPKG.zip'))
    if states:
        zips = [z for z in zips if any(s.lower().replace(' ', '_') in z.name.lower() for s in states)]
    db = open_db()
    for z in zips:
        state = z.name[6:-15].replace('_', ' ')
        origin = 'nhd:' + state
        t0 = time.time()
        with zipfile.ZipFile(z) as zf, tempfile.TemporaryDirectory(dir=src) as tmp:
            member = next(m for m in zf.namelist() if m.endswith('.gpkg'))
            gp = zf.extract(member, tmp)
            g = sqlite3.connect(gp)
            forget(db, origin)
            n = pts = 0
            fdesc = dict(g.execute('SELECT fcode, description FROM NHDFCode'))
            for table, types in (('NHDWaterbody', LAYER), ('NHDArea', AREA_LAYER)):
              cols = {r[1].lower(): r[1] for r in g.execute(f'PRAGMA table_info({table})')}
              geomcol = next(r[0] for r in g.execute("SELECT column_name FROM gpkg_geometry_columns WHERE lower(table_name)=?", (table.lower(),)))
              q = f'SELECT {cols["permanent_identifier"]},{cols.get("gnis_name", "NULL")},{cols["ftype"]},{cols["fcode"]},{cols.get("areasqkm", "0")},{geomcol} FROM {table}'
              for pid, name, ftype, fcode, area, blob in g.execute(q):
                if blob is None or ftype not in types:
                    continue
                # neighbouring state files repeat border features; a lake split by a state line keeps one id
                # but a different clipped shape in each file, so the shape is part of the key
                env = struct.unpack_from('<4d', blob, 8) if blob[3] & 0x0E else (0, 0, 0, 0)
                if db.execute('INSERT OR IGNORE INTO nhd_seen VALUES (?,?)', (f'{pid}:{env[0]:.4f},{env[2]:.4f},{env[1]:.4f},{env[3]:.4f}', origin)).rowcount == 0:
                    continue
                first_piece = db.execute('SELECT count(*) FROM resource WHERE source_id=?', (pid,)).fetchone()[0] == 0
                area = area or 0
                layer, cls = types[ftype]
                # zoom at which an outline appears: roughly when it is a few pixels across
                minz = max(5, min(14, round(14 - math.log2(max(area, 1e-5) ** 0.5 / 0.02))))
                tol = 0.00002 if minz >= 12 else 0.00006 if minz >= 9 else 0.0002
                for poly in wkb_polys(blob):
                    rings = [r2 for r2 in (simplify(r, tol) for r in poly) if len(r2) >= 4]
                    if not rings:
                        continue
                    xs = [x for x, _ in rings[0]]; ys = [y for _, y in rings[0]]
                    cur = db.execute('INSERT INTO feat(layer,cls,name,minz,geom,origin) VALUES (?,?,?,?,?,?)', (layer, cls, name or '', minz, pack(rings), origin))
                    db.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (cur.lastrowid, min(xs), max(xs), min(ys), max(ys), minz, 30))
                    n += 1
                kind = NHD_KIND.get(ftype) if table == 'NHDWaterbody' else None
                # clickable point for named waters and any year-round pond/lake/reservoir of ~1 acre or more
                desc = fdesc.get(fcode) or ''
                perennial = 'Intermittent' not in desc and fcode not in (39000, 43600, 43618, 43619) or 'Perennial' in desc
                if kind and first_piece and fcode not in SKIP_POINT and (name or (perennial and area >= 0.004 and fcode not in BAD_RESERVOIR)):
                    polys = wkb_polys(blob)
                    ring = max((p[0] for p in polys), key=len)
                    lon, lat = inside_point(ring)
                    detail = {'area_acres': round(area * 247.105, 1), 'state': state,
                              'water_type': 'Seasonal (may be dry)' if 'Intermittent' in desc else 'Year-round' if 'Perennial' in desc else ''}
                    if 'Reservoir Type = ' in desc:
                        detail['reservoir_type'] = desc.split('Reservoir Type = ')[1].split(';')[0]
                    if fcode in BAD_RESERVOIR:
                        detail['not_drinking_water'] = True
                    pond = kind == 'lake' and not name and area < 0.04
                    add_point(db, origin, pid, 'pond' if pond else kind, name or '', lat, lon, detail,
                              'https://www.usgs.gov/national-hydrography/national-hydrography-dataset')
                    pts += 1
            g.close()
            os.remove(gp)
        db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (origin, json.dumps({'outlines': n, 'points': pts, 'built': time.strftime('%Y-%m-%dT%H:%M:%S')})))
        db.commit()
        print(f'{state}: {n:,} outlines, {pts:,} points in {time.time() - t0:.0f}s', flush=True)


def unpack(blob):
    a = array('i'); a.frombytes(blob); parts, i = [], 1
    for _ in range(a[0]):
        n = a[i]; i += 1; x = y = 0; pts = []
        for _ in range(n):
            x += a[i]; y += a[i + 1]; i += 2; pts.append((x / 1e6, y / 1e6))
        parts.append(pts)
    return parts


def build_osm():
    """Named lakes and reservoirs from the street-map databases that NHD lacks or leaves unnamed (e.g. Echo Park's 'Echo Lake')."""
    db = open_db()
    forget(db, 'osm')
    named = {}
    for name, lat, lon in db.execute("SELECT lower(name),lat,lon FROM resource WHERE origin LIKE 'nhd:%' AND name!=''"):
        named.setdefault(name, []).append((lat, lon))
    n = 0
    for path in (GEO / 'map.sqlite', GEO / 'national.sqlite'):
        if not path.exists():
            continue
        src = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        for cls, name, blob in src.execute("SELECT cls,name,geom FROM feat WHERE layer='water' AND name!=''"):
            ring = max(unpack(blob), key=len)
            if len(ring) < 4:
                continue
            lon, lat = inside_point(ring)
            if any(abs(lat - y) < 0.03 and abs(lon - x) < 0.03 for y, x in named.get(name.lower(), ())):
                continue  # NHD already has it
            named.setdefault(name.lower(), []).append((lat, lon))
            area = ring_area_km2(ring)
            add_point(db, 'osm', f'osm:{n}', 'reservoir' if cls == 'reservoir' else 'lake', name, lat, lon,
                      {'area_acres': round(area * 247.105, 1), 'source_map': 'OpenStreetMap'}, 'https://www.openstreetmap.org/')
            n += 1
        src.close()
    db.commit()
    print(f'OpenStreetMap: {n:,} named lakes and reservoirs added')


def build_index():
    """Full-text index of named lakes, reservoirs and dams (and a dam's other names, e.g. Echo Dam = Echo Reservoir)."""
    db = open_db()
    db.executescript('DROP TABLE IF EXISTS water_fts; CREATE VIRTUAL TABLE water_fts USING fts5(name, other, tokenize="unicode61");')
    db.execute("INSERT INTO water_fts(rowid,name,other) SELECT id,name,COALESCE(json_extract(detail,'$.other_names'),'') FROM resource "
               "WHERE kind IN ('dam','reservoir','lake') AND name!=''")
    db.commit()
    print('search index:', db.execute('SELECT count(*) FROM water_fts').fetchone()[0], 'named waters and dams')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--geo']:      # build into another map folder (default derived/geo), e.g. a region's derived/geo-nl
        if len(sys.argv) < 3:
            sys.exit(__doc__)
        GEO = Path(sys.argv[2]).resolve()
        DB = GEO / 'water.sqlite'
        del sys.argv[1:3]
    if sys.argv[1:2] == ['nid']:
        build_nid()
    elif sys.argv[1:2] == ['nhd']:
        build_nhd(sys.argv[2:])
        build_index()
    elif sys.argv[1:2] == ['osm']:
        build_osm()
        build_index()
    elif sys.argv[1:2] == ['index']:
        build_index()
    else:
        sys.exit(__doc__)

"""A detailed map for a region outside the US (engine/regions.json), made from the region's own builders' files, checked, zipped
with its address index and listed for setup as a file found on this computer (docs/SETUP-API.md, "Regions outside the US").

  .venv/bin/python packaging/region_maps.py build NL --src derived/geo-nl      # assemble, check, zip
  .venv/bin/python packaging/region_maps.py manifest NL                        # list both zips in derived/release/manifest-v1.json
  .venv/bin/python packaging/region_maps.py manifest NL --entries NL-entries.json   # the same, for zips downloaded from a release
  .venv/bin/python packaging/region_maps.py dev-manifest                       # a setup manifest for running from source

A US state map is cut from the national files (packaging/build_packs.py, state_maps.py). A region outside the US is built whole
by its own tools (for the Netherlands: tools/build_map_osm.py, build_water.py --geo, build_bag.py, build_places_nl.py,
fetch_ahn.py with build_terrain.py, build_crops_nl.py, all writing into derived/geo-nl/), so this assembles those files into
the same eleven-file map set (map_sets.ALLOWED). map.sqlite (the household area map) and atlas.sqlite (US resource records) are
present and empty. Lastbook's site does not host these zips: their manifest entries carry local_only, and setup uses them only
as files already on the computer. The URLs name where they would be if it ever did.
"""
import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / 'packaging', ROOT / 'tools'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from map_sets import ALLOWED, make_zip       # noqa: E402
from map_schema import create_map_tables     # noqa: E402
from engine import regions                   # noqa: E402

OUT = ROOT / 'derived/packs/maps'
ZIPS = ROOT / 'derived/packs/state-zips'
MANIFEST = ROOT / 'derived/release/manifest-v1.json'
DEV_MANIFEST = ROOT / 'derived/release/setup/manifest-v1.json'
REMOTE = 'https://downloads.lastbook.org/manifest-v1.json'
BASE = 'https://downloads.lastbook.org'
BUILT = ('national', 'water', 'terrain', 'buildings', 'crops', 'places')
PROGRESS = ('done', 'done_socal', 'nhd_seen')        # build bookkeeping, never shipped
INCLUDES = 'Streets, buildings, terrain and fruit crops, plus help points, water and place names'


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while b := f.read(1 << 24):
            h.update(b)
    return h.hexdigest()


def _tidy(path):
    """Drop build bookkeeping, settle the journal and compact: what ships is only what the map reads."""
    db = sqlite3.connect(path)
    for t in PROGRESS:
        db.execute(f'DROP TABLE IF EXISTS {t}')
    db.commit()
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('VACUUM')
    db.close()


def assemble(code, src, dest):
    """The eleven map-set files for one region, in dest. Returns map-set.json's content."""
    t0 = time.time()
    src, dest = Path(src), Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    geo = dest / 'derived/geo'
    geo.mkdir(parents=True)
    for name in BUILT:
        shutil.copyfile(src / f'{name}.sqlite', geo / f'{name}.sqlite')
        _tidy(geo / f'{name}.sqlite')
    db = sqlite3.connect(geo / 'national.sqlite')
    features = db.execute('SELECT count(*) FROM feat').fetchone()[0]
    status = {'state': 'complete', 'stage': 'ready', 'features': features}
    db.execute("INSERT OR REPLACE INTO meta VALUES ('status', ?)", (json.dumps(status),))
    db.commit()
    db.close()
    (geo / 'national-status.json').write_text(json.dumps(status), encoding='utf-8')
    (geo / 'socal-cells.json').write_text('[]', encoding='utf-8')
    db = sqlite3.connect(geo / 'map.sqlite')
    create_map_tables(db)
    db.execute('CREATE INDEX poi_cls ON poi(cls, lon, lat)')
    db.commit()
    db.close()
    _tidy(geo / 'map.sqlite')
    atlas = dest / 'library-data/geography/resources/atlas.sqlite'
    atlas.parent.mkdir(parents=True)
    db = sqlite3.connect(atlas)
    db.executescript('CREATE TABLE resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, '
                     'source TEXT, origin TEXT); CREATE VIRTUAL TABLE spatial USING rtree(id, minx, maxx, miny, maxy);'
                     'CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);')
    db.close()
    size = {f.relative_to(dest).as_posix(): f.stat().st_size for f in dest.rglob('*') if f.is_file()}
    info = {'name': code, 'files': size, 'bytes': sum(size.values()), 'seconds': round(time.time() - t0)}
    (dest / 'map-set.json').write_text(json.dumps(info, indent=1), encoding='utf-8')
    return info


def _tile_range(box, z):
    n = 2 ** z

    def y(lat):
        r = math.radians(lat)
        return int((1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n)
    w, s, e, nn = box
    return int((w + 180) / 360 * n), int((e + 180) / 360 * n), y(nn), y(s)


def check(dest, code):
    """What is wrong with a region's map set; an empty list when nothing is."""
    dest = Path(dest)
    fails = []
    rels = {p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()}
    if rels != ALLOWED:
        fails.append(f'files differ from the contract: extra {sorted(rels - ALLOWED)} missing {sorted(ALLOWED - rels)}')
    try:
        info = json.loads((dest / 'map-set.json').read_text(encoding='utf-8'))
        if info.get('name') != code or set(info) - {'name', 'files', 'bytes', 'seconds'}:
            fails.append('map-set.json does not name the region')
    except (OSError, ValueError):
        fails.append('map-set.json missing or unreadable')
    try:
        if json.loads((dest / 'derived/geo/socal-cells.json').read_text()) != []:
            fails.append('socal-cells.json is not empty')
    except (OSError, ValueError):
        fails.append('socal-cells.json missing or unreadable')
    region = regions.get(code)
    if not region or not region.get('box'):
        fails.append(f'{code} is not a region with a box in engine/regions.json')
    for rel in sorted(r for r in rels & ALLOWED if r.endswith('.sqlite')):
        db = sqlite3.connect(f'file:{dest / rel}?immutable=1', uri=True)
        try:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                fails.append(f'{rel}: SQLite check failed')
            if db.execute(f"SELECT 1 FROM sqlite_master WHERE name IN ({','.join('?' * len(PROGRESS))})", PROGRESS).fetchone():
                fails.append(f'{rel}: build progress tables left in')
            if rel.endswith('/map.sqlite') and sum(db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('feat', 'poi', 'meta')):
                fails.append('map.sqlite (the household area map) is not empty')
            if rel.endswith('/buildings.sqlite') and region and region.get('box'):
                x0, x1, y0, y1 = _tile_range(region['box'], 14)
                for t in ('bldg', 'bldg_socal', 'bldg_osm'):
                    if db.execute(f'SELECT count(*) FROM {t} WHERE x NOT BETWEEN ? AND ? OR y NOT BETWEEN ? AND ?',
                                  (x0 - 1, x1 + 1, y0 - 1, y1 + 1)).fetchone()[0]:
                        fails.append(f'{t} rows outside the region box')
        finally:
            db.close()
    return fails


def package(code, dest, addresses, zips=ZIPS, addon=None):
    """Zip the map set and the address index; returns their manifest entries (maps, address_indexes), and, with addon (an add-on zip
    such as tools/build_nl_documents.py makes), a third entry for it: setup installs it with the map (engine/setup/addons.py)."""
    region = regions.get(code)
    zips = Path(zips)
    zips.mkdir(parents=True, exist_ok=True)
    mz = zips / f'Lastbook-Map-{code}.zip'
    make_zip(Path(dest), mz)
    az = zips / f'Lastbook-Addresses-{code}.zip'
    member = f'derived/geo/addresses/{code}.sqlite'
    with zipfile.ZipFile(az.with_suffix('.partial'), 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        z.write(addresses, member)
    az.with_suffix('.partial').replace(az)
    db = sqlite3.connect(f'file:{addresses}?mode=ro', uri=True)
    records = int(dict(db.execute('SELECT key, value FROM meta')).get('count', 0))
    db.close()
    installed = sum((Path(dest) / rel).stat().st_size for rel in ALLOWED)
    kind = region['kind']
    maps = {'id': code, 'title': region['name'], 'title_in_text': region.get('name_in_text') or region['name'], 'kind': kind,
            'includes': INCLUDES, 'local_only': True, 'available': True,
            'installed_bytes': installed,
            'files': [{'name': mz.name, 'url': f'{BASE}/maps/{mz.name}', 'size': mz.stat().st_size, 'sha256': sha_file(mz), 'kind': 'zip'}]}
    addr = {'id': code, 'title': region['name'], 'kind': f'{kind}-addresses', 'local_only': True, 'available': True,
            'installed_bytes': Path(addresses).stat().st_size, 'records': records,
            'files': [{'name': az.name, 'url': f'{BASE}/addresses/{az.name}', 'size': az.stat().st_size, 'sha256': sha_file(az), 'kind': 'zip'}]}
    if not addon:
        return maps, addr
    addon = Path(addon)
    with zipfile.ZipFile(addon) as z:
        name = json.loads(z.read('LastbookData/pack.json'))['name']
        unpacked = sum(i.file_size for i in z.infolist())
    oz = zips / addon.name
    if oz.resolve() != addon.resolve():
        shutil.copyfile(addon, oz)
    extra = {'id': name, 'title': f"{region['name']}: preparedness documents and guides", 'kind': 'addon', 'with_map': code,
             'local_only': True, 'available': True, 'installed_bytes': unpacked,
             'files': [{'name': oz.name, 'url': f'{BASE}/addons/{oz.name}', 'size': oz.stat().st_size, 'sha256': sha_file(oz), 'kind': 'zip'}]}
    return maps, addr, extra


def list_in_manifest(path, maps, addresses, addon=None):
    """Add (or replace) the region's entries in a release manifest, creating it if there is none."""
    path = Path(path)
    m = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1}
    for key, entry in (('maps', maps), ('address_indexes', addresses), ('addons', addon)):
        if entry is None:
            continue
        m[key] = [x for x in m.get(key) or [] if x.get('id') != entry['id']] + [entry]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(m, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def dev_manifest(local=MANIFEST, out=DEV_MANIFEST):
    """For running from source: the published manifest, plus this build's local-only entries, where setup looks for a bundled one."""
    from engine.setup import manifest
    req = urllib.request.Request(REMOTE, headers={'User-Agent': 'lastbook-region-builder'})
    with urllib.request.urlopen(req, timeout=60) as r:
        m = json.loads(r.read().decode('utf-8'))
    mine = json.loads(Path(local).read_text(encoding='utf-8'))
    for key in ('maps', 'address_indexes', 'addons'):
        own = [x for x in mine.get(key) or [] if x.get('local_only')]
        ids = {x['id'] for x in own}
        m[key] = [x for x in m.get(key) or [] if x.get('id') not in ids] + own
    if manifest.validate(m) is None:
        sys.exit('the combined manifest does not validate')
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(m, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    log('wrote', out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='action', required=True)
    b = sub.add_parser('build')
    b.add_argument('code')
    b.add_argument('--src', required=True, help="the region's builders' folder, e.g. derived/geo-nl")
    b.add_argument('--addon', help='an add-on zip to list with the map (tools/build_nl_documents.py --zip)')
    m = sub.add_parser('manifest')
    m.add_argument('code')
    m.add_argument('--entries', help="the entries file from a build or a release (default: this build's derived/packs/maps/<code>-entries.json)")
    sub.add_parser('dev-manifest')
    a = ap.parse_args()
    if a.action == 'build':
        dest = OUT / a.code
        info = assemble(a.code, a.src, dest)
        log(a.code, 'assembled', f"{info['bytes']:,} bytes")
        fails = check(dest, a.code)
        if fails:
            sys.exit('\n'.join(fails))
        entries = package(a.code, dest, Path(a.src) / 'addresses' / f'{a.code}.sqlite', addon=a.addon)
        (OUT / f'{a.code}-entries.json').write_text(json.dumps(entries, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        for e in entries:
            log(e['files'][0]['name'], f"{e['files'][0]['size']:,} bytes", e['files'][0]['sha256'])
    elif a.action == 'manifest':
        entries = json.loads(Path(a.entries or OUT / f'{a.code}-entries.json').read_text(encoding='utf-8'))
        if [e['id'] for e in entries[:2]] != [a.code, a.code] or len(entries) > 3 or (len(entries) == 3 and entries[2].get('with_map') != a.code):
            sys.exit(f'{a.entries} does not hold the {a.code} map and address entries')
        list_in_manifest(MANIFEST, *entries)
        log('listed', a.code, 'in', MANIFEST)
    else:
        dev_manifest()


if __name__ == '__main__':
    main()

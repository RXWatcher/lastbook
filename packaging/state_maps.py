"""Build, check, zip, upload and list one state's detailed map (docs/SETUP-API.md, "State maps").

  derived/app-build/mac-venv/bin/python3 -I -B packaging/state_maps.py CA TX ...   # one state at a time, in this order
  ... packaging/state_maps.py --order                                              # every state, in release order

Each state: build (CA and RI are kept as built), scan, zip to derived/packs/state-zips/, upload to maps/ on the bucket,
check the public SHA-256, list it under "maps" in derived/release/manifest-v1.json and upload that, then delete the zip
and the build copy (CA and RI stay). Results go to derived/packs/state-maps.json and STATE-MAPS.md.
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / 'derived/packs/maps'
ZIPS = ROOT / 'derived/packs/state-zips'
RESULTS = ROOT / 'derived/packs/state-maps.json'
LOCK = ROOT / 'derived/packs/state-maps.lock'      # one writer at a time for the manifest, results and table
CLAIMS = ROOT / 'derived/packs/state-claims'        # a worker owns a state by making its folder here
TABLE = ROOT / 'derived/packs/STATE-MAPS.md'
MANIFEST = ROOT / 'derived/release/manifest-v1.json'
BASE = 'https://downloads.lastbook.org'
KEEP = {'CA', 'RI'}
FIRST = ['CA', 'TX', 'FL', 'NY', 'PA', 'IL', 'OH', 'GA', 'NC', 'MI']
NAMES = dict(AL='Alabama', AK='Alaska', AZ='Arizona', AR='Arkansas', CA='California', CO='Colorado', CT='Connecticut', DE='Delaware',
             DC='District of Columbia', FL='Florida', GA='Georgia', HI='Hawaii', ID='Idaho', IL='Illinois', IN='Indiana', IA='Iowa', KS='Kansas',
             KY='Kentucky', LA='Louisiana', ME='Maine', MD='Maryland', MA='Massachusetts', MI='Michigan', MN='Minnesota', MS='Mississippi',
             MO='Missouri', MT='Montana', NE='Nebraska', NV='Nevada', NH='New Hampshire', NJ='New Jersey', NM='New Mexico', NY='New York',
             NC='North Carolina', ND='North Dakota', OH='Ohio', OK='Oklahoma', OR='Oregon', PA='Pennsylvania', PR='Puerto Rico', RI='Rhode Island',
             SC='South Carolina', SD='South Dakota', TN='Tennessee', TX='Texas', UT='Utah', VT='Vermont', VA='Virginia', WA='Washington',
             WV='West Virginia', WI='Wisconsin', WY='Wyoming')
INCLUDES = 'Local streets, buildings, terrain and crops, plus water, help and resource points'

sys.path.insert(0, str(ROOT / 'packaging'))
sys.path.insert(0, str(ROOT / 'derived/release'))
import scan_pack as S       # noqa: E402
from map_sets import ALLOWED, make_zip   # noqa: E402  (the map-set contract, shared with region_maps.py)
import r2_publish as R      # noqa: E402


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def states():
    db = sqlite3.connect(f'file:{MAPS}/source/profiles.sqlite?immutable=1', uri=True)
    have = sorted({s for (s,) in db.execute('SELECT DISTINCT state FROM zcta') if s and re.fullmatch(r'[A-Z]{2}', s)} | {'CT'})
    return FIRST + [s for s in have if s not in FIRST]


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while b := f.read(1 << 24):
            h.update(b)
    return h.hexdigest()


def scan(d, code):
    """The scan_pack rules that apply to a map set, and the map-set rules: only the listed files, nothing about the household's area."""
    terms = S.read_terms(str(ROOT / 'derived/packs/private-terms.txt'))
    if not terms:
        sys.exit('no private terms')
    sc = S.Scan(d, terms, {}, None)
    sc.done_early = set()
    files = sc.walk()
    rels = [p.relative_to(d).as_posix() for p in files]
    fails = []
    if set(rels) != ALLOWED:
        fails.append(f'files differ from the contract: extra {sorted(set(rels) - ALLOWED)} missing {sorted(ALLOWED - set(rels))}')
    for p, rel in zip(files, rels):
        st = os.lstat(p)
        if rel == 'map-set.json':
            info = sc.load_json(rel, rels, 'map-set')
            if not isinstance(info, dict) or info.get('name') != code or set(info) - {'name', 'files', 'bytes', 'seconds'}:
                fails.append('map-set.json does not name the state')
            continue
        sc.name_rules(rel, st, p.is_symlink())
        if rel.endswith('.json'):
            sc.load_json(rel, rels, 'status')
            data = p.read_bytes()
            if rel.endswith('national-status.json') and set(json.loads(data)) - {'state', 'stage', 'features'}:
                fails.append('status fields')
            if rel.endswith('socal-cells.json') and json.loads(data) != []:
                fails.append('socal-cells.json is not empty')
        else:
            sc.inspect_map(rel, p)
            db = sqlite3.connect(f'file:{p}?immutable=1', uri=True)
            for t in ('meta', 'metadata'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
                    for row in db.execute(f'SELECT * FROM "{t}"'):
                        for x in row:
                            if isinstance(x, str) and (S.HOUSEHOLD.search(x.encode()) or S.USER_PATH.search(x.encode()) or S.LAN.search(x.encode())):
                                fails.append(f'{rel}: {t} names the household, a local path or a LAN address')
            if rel.endswith('/map.sqlite'):
                n = sum(db.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in ('feat', 'poi', 'meta'))
                if n:
                    fails.append('map.sqlite (the household area map) is not empty')
            if rel.endswith('/buildings.sqlite'):     # every footprint table holds only tiles inside this state's box: no area beyond the state rule
                import build_packs as BP
                x0, x1, y0, y1 = BP.tile_range(BP.state_box(MAPS / 'source', code), 14)
                for t in ('bldg', 'bldg_socal', 'bldg_osm'):
                    if db.execute(f'SELECT count(*) FROM {t} WHERE x NOT BETWEEN ? AND ? OR y NOT BETWEEN ? AND ?', (x0, x1, y0, y1)).fetchone()[0]:
                        fails.append(f'{t} rows outside the state box')
            if db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('done','done_socal')").fetchone():
                fails.append(f'{rel}: build progress tables left in')
            db.close()
    for rule, paths in sc.fails.items():
        fails.append(f'{rule}: {paths[:5]}')
    return fails, sc.listed


def web_text(d):
    """Scripts in the text the map shows fail. Web addresses there (a marina's website, a shop's page) are third-party text the Map shows as
    plain words, never as links, as in the Medium pack; they are counted for the report, not removed."""
    fails, notes = [], {}
    for p in d.rglob('*.sqlite'):
        db = sqlite3.connect(f'file:{p}?immutable=1', uri=True)
        virt = [v for (v,) in db.execute("SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL%'")]
        for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql NOT LIKE 'CREATE VIRTUAL%'").fetchall():
            if any(t.startswith(v + '_') for v in virt):
                continue
            for (c, ctype) in [(r[1], (r[2] or '').upper()) for r in db.execute(f'PRAGMA table_info("{t}")')]:
                if 'BLOB' in ctype or c in ('geom', 'data', 'tile', 'img', 'source'):     # source holds citation addresses as text, as in the Medium pack
                    continue
                q = f'SELECT count(*) FROM "{t}" WHERE typeof("{c}")=\'text\' AND '
                n = db.execute(q + f'("{c}" LIKE \'%<script%\' OR "{c}" LIKE \'%javascript:%\')').fetchone()[0]
                if n:
                    fails.append(f'{p.relative_to(d)}: {t}.{c} script {n}')
                n = db.execute(q + f'("{c}" LIKE \'%http:%\' OR "{c}" LIKE \'%https:%\' OR "{c}" LIKE \'%www.%\')').fetchone()[0]
                if n:
                    notes[f'{p.relative_to(d).name}:{t}.{c}'] = n
        db.close()
    return fails, notes


def upload(ctx, path, key):
    """r2_publish.upload_file, with a key under maps/."""
    size = path.stat().st_size
    ctype = 'application/zip'
    if size <= R.MULTIPART_OVER:
        st, _, out = R.s3(ctx, 'PUT', key, body=path.read_bytes(), headers={'content-type': ctype})
        if st != 200:
            sys.exit(f'{key}: HTTP {st} {out[:300]!r}')
        return
    st, _, out = R.s3(ctx, 'POST', key, {'uploads': ''}, headers={'content-type': ctype})
    uid = R.tag(out.decode(), 'UploadId')
    if st != 200 or not uid:
        sys.exit(f'{key}: could not start, HTTP {st}')
    count = (size + R.PART - 1) // R.PART
    import concurrent.futures

    def one(n):
        with open(path, 'rb') as f:
            f.seek((n - 1) * R.PART)
            data = f.read(R.PART)
        s, hd, body = R.s3(ctx, 'PUT', key, {'partNumber': str(n), 'uploadId': uid}, body=data)
        if s != 200:
            raise RuntimeError(f'part {n}: HTTP {s} {body[:200]!r}')
        return n, hd.get('ETag') or hd.get('etag')
    done = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            for n, etag in pool.map(one, range(1, count + 1)):
                done[n] = etag
                if len(done) % 10 == 0 or len(done) == count:
                    log(f'  {key}: part {len(done)}/{count}')
    except Exception:
        R.s3(ctx, 'DELETE', key, {'uploadId': uid})
        raise
    xml = '<CompleteMultipartUpload>' + ''.join(f'<Part><PartNumber>{n}</PartNumber><ETag>{done[n]}</ETag></Part>' for n in sorted(done)) + '</CompleteMultipartUpload>'
    st, _, out = R.s3(ctx, 'POST', key, {'uploadId': uid}, body=xml.encode())
    if st != 200 or b'<Error>' in out:
        sys.exit(f'{key}: could not finish, HTTP {st} {out[:300]!r}')


def public_sha(url):
    h = hashlib.sha256()
    n = 0
    req = urllib.request.Request(url + f'?v={int(time.time())}', headers={'User-Agent': 'curl/8.7.1', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=120) as r:
        while b := r.read(1 << 22):
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def list_in_manifest(ctx, entry):
    m = json.loads(MANIFEST.read_text())
    packs, models = json.dumps(m['packs']), json.dumps(m.get('models'))
    maps = [x for x in m.get('maps', []) if x['id'] != entry['id']] + [entry]
    order = {s: i for i, s in enumerate(states())}
    m['maps'] = sorted(maps, key=lambda x: order.get(x['id'], 999))
    assert json.dumps(m['packs']) == packs and json.dumps(m.get('models')) == models
    tmp = MANIFEST.with_suffix('.maps-tmp')
    tmp.write_text(json.dumps(m, indent=1) + '\n')
    os.replace(tmp, MANIFEST)
    data = MANIFEST.read_bytes()
    st, _, out = R.s3(ctx, 'PUT', 'manifest-v1.json', body=data, headers={'content-type': 'application/json; charset=utf-8'})
    if st != 200:
        sys.exit(f'manifest upload HTTP {st}')
    for _ in range(10):
        got, _n = public_sha(f'{BASE}/manifest-v1.json')
        if got == hashlib.sha256(data).hexdigest():
            return
        time.sleep(3)
    sys.exit('public manifest does not match')


def write_table(res):
    rows = ['# State maps', '', 'One detailed map per state, for first-run setup (docs/SETUP-API.md, "State maps"). Built by `packaging/state_maps.py`;',
            'each zip was scanned, uploaded, checked by its public SHA-256 and then listed under `maps` in `manifest-v1.json`.', '',
            '| State | Zip size | Installed size | SHA-256 | URL |', '|---|---:|---:|---|---|']
    order = {s: i for i, s in enumerate(states())}
    for code in sorted(res, key=lambda c: order.get(c, 999)):
        r = res[code]
        rows.append(f"| {code} {NAMES.get(code, '')} | {r['size'] / 1e9:.2f} GB ({r['size']:,}) | {r['installed_bytes'] / 1e9:.2f} GB ({r['installed_bytes']:,}) | `{r['sha256']}` | {r['url']} |")
    TABLE.write_text('\n'.join(rows) + '\n')


def one_state(ctx, code, res):
    d = MAPS / code
    t0 = time.time()
    if code in KEEP:
        if not (d / 'map-set.json').exists():
            sys.exit(f'{code} should be built already')
    else:
        while shutil.disk_usage(ROOT).free < 35e9:      # other workers' zips are deleted as they finish
            log(code, 'waiting for disk space')
            time.sleep(120)
        log(code, 'building')
        subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'packaging/build_packs.py'), 'map', code], check=True, stdout=subprocess.DEVNULL)
    fails, listed = scan(d, code)
    wf, web = web_text(d)
    fails += wf
    if fails:
        sys.exit(f'{code} scan failed: {fails}')
    log(code, 'scan passed', dict((k, len(v)) for k, v in listed.items()))
    installed = sum((d / rel).stat().st_size for rel in ALLOWED)
    ZIPS.mkdir(exist_ok=True)
    z = ZIPS / f'Lastbook-Map-{code}.zip'
    make_zip(d, z)
    sha, size = sha_file(z), z.stat().st_size
    log(code, 'zipped', size)
    key = f'maps/{z.name}'
    upload(ctx, z, key)
    url = f'{BASE}/{key}'
    got, n = public_sha(url)
    if got != sha or n != size:
        sys.exit(f'{code}: public copy differs ({got} {n})')
    log(code, 'public copy verified')
    entry = {'id': code, 'title': NAMES.get(code, code), 'kind': 'state', 'installed_bytes': installed, 'available': True, 'includes': INCLUDES,
             'files': [{'name': z.name, 'url': url, 'size': size, 'sha256': sha, 'kind': 'zip'}]}
    with open(LOCK, 'a') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        list_in_manifest(ctx, entry)
        res.clear()
        res.update(json.loads(RESULTS.read_text()) if RESULTS.exists() else {})
        res[code] = {'size': size, 'installed_bytes': installed, 'sha256': sha, 'url': url, 'web_address_text': web, 'seconds': round(time.time() - t0)}
        tmp = RESULTS.with_suffix('.tmp')
        tmp.write_text(json.dumps(res, indent=1) + '\n')
        os.replace(tmp, RESULTS)
        write_table(res)
    log(code, 'listed')
    z.unlink()
    if code not in KEEP:
        shutil.rmtree(d)


def main():
    args = sys.argv[1:]
    ctx = R.Context()
    if args[:1] == ['--worker']:
        """Take the next unclaimed state in release order until none is left. A failed state is written down and left claimed, for a person to look at."""
        name = args[1]
        CLAIMS.mkdir(exist_ok=True)
        for code in states():
            res = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
            if code in res:
                continue
            try:
                os.mkdir(CLAIMS / code)
            except FileExistsError:
                continue
            (CLAIMS / code / 'worker').write_text(name)
            log(name, 'took', code)
            try:
                one_state(ctx, code, res)
            except BaseException as e:      # sys.exit and crashes alike
                (CLAIMS / code / 'failed').write_text(f'{e.__class__.__name__}: {e}')
                log(name, code, 'FAILED', e)
                if isinstance(e, KeyboardInterrupt):
                    raise
        log(name, 'no states left')
        return
    todo = states() if args == ['--order'] else args
    res = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    for code in todo:
        if code in res:
            continue
        one_state(ctx, code, res)
    log('done', len(res), 'states')


if __name__ == '__main__':
    main()

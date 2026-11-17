#!/usr/bin/env python3
"""Secondary addresses (BAG nevenadressen) added to the Dutch address index.

  derived/buildenv/bin/python tools/build_bag_extra.py derived/nl-addresses/src/lvbag-extract-nl.zip \
      derived/geo-nl/addresses/NL.sqlite derived/nl-addresses/addresses/NL.sqlite [--jobs N]

Reads:
  - PDOK's full BAG extract with history, https://service.pdok.nl/kadaster/bag/atom/downloads/lvbag-extract-nl.zip (Kadaster,
    CC0 1.0; about 3.7 GB; feed https://service.pdok.nl/kadaster/bag/atom/bag.xml, checked 17 November 2026). It is a zip of one
    zip per object type (9999VBO verblijfsobject, 9999LIG ligplaats, 9999STA standplaats, 9999NUM nummeraanduiding, 9999OPR
    openbare ruimte, 9999WPL woonplaats), each holding many XML files in EPSG:28992. The XML is streamed with iterparse, one
    file at a time, clearing each object as it is read. One inner zip at a time is copied to a temporary file (the largest, the
    dwellings, is 1.2 GB) so that its files can be opened in parallel; nothing else is unpacked.
  - the main-address index that tools/build_bag.py wrote (the second argument).
Writes: a complete address index (the third argument): every main address from the second, plus the secondary addresses, in the
same nl_addr table (engine/address_nl.py: create_index, normalize, finish_index). A secondary address is placed at its object's
point (a polygon's centre for pitches and the few polygon dwellings). One whose postcode, number, letter and addition is already
in the index is skipped, so the index holds each address once.
Kept: objects in use or under renovation, and designated pitches (the same statuses as build_bag.py), in their current version
(a version with an end of validity or registration is history); nummeraanduidingen whose naming is issued ("Naamgeving
uitgegeven") and that have a postcode and number. The street is the openbare ruimte's name, the town the nummeraanduiding's own
woonplaats or else the street's.
Needs pyproj (derived/buildenv). About 15 minutes with 8 jobs, and as much disk as the largest inner zip.
"""
import argparse, multiprocessing, os, shutil, sqlite3, sys, tempfile, time, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from engine import address_nl                        # noqa: E402

OBJECT_OK = {'Verblijfsobject': ('Verblijfsobject in gebruik', 'Verblijfsobject in gebruik (niet ingemeten)', 'Verbouwing verblijfsobject'),
             'Ligplaats': ('Plaats aangewezen',), 'Standplaats': ('Plaats aangewezen',)}
NAME_OK = ('Naamgeving uitgegeven',)
TOWN_OK = ('Woonplaats aangewezen',)
KINDS = {'VBO': 'Verblijfsobject', 'LIG': 'Ligplaats', 'STA': 'Standplaats', 'NUM': 'Nummeraanduiding',
         'OPR': 'OpenbareRuimte', 'WPL': 'Woonplaats'}
RELATIONS = ('heeftAlsNevenadres', 'ligtAan', 'ligtIn')
SOURCE = 'Kadaster BAG, PDOK bag-light.gpkg and lvbag-extract-nl.zip (CC0 1.0)'
_WANT = set()          # nummeraanduiding ids to look up; set before the workers fork


def local(tag):
    return tag.rsplit('}', 1)[-1]


def read(elem):
    """The fields of one BAG object that matter: its simple fields by name, `current` (this version has no end of validity or
    registration), the ids it refers to by relation, and the first coordinate list of its geometry with its dimension."""
    out = {'current': True, 'rel': {}, 'coords': None, 'dim': 3}
    for child in elem:
        name = local(child.tag)
        if name == 'voorkomen':
            out['current'] = not any(local(e.tag) in ('eindGeldigheid', 'eindRegistratie') for e in child.iter())
        elif name in RELATIONS:
            out['rel'].setdefault(name, []).extend((e.text or '').strip() for e in child.iter() if local(e.tag).endswith('Ref'))   # one element per address
        elif name == 'geometrie':
            for e in child.iter():
                if e.get('srsDimension'):
                    out['dim'] = int(e.get('srsDimension'))
                if local(e.tag) in ('pos', 'posList'):
                    out['coords'] = [float(v) for v in (e.text or '').split()]
                    break
        elif name not in out and (child.text or '').strip():
            out[name] = child.text.strip()
    return out


def centre(coords, dim):
    """A point is itself; a ring is the mean of its distinct vertices (the closing vertex counted once)."""
    pts = [(coords[i], coords[i + 1]) for i in range(0, len(coords) - dim + 1, dim)]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def pick(kind, o):
    """What to keep of one object of this type, or None. Small tuples only: they travel between processes."""
    if not o['current'] or 'identificatie' not in o:
        return None
    if kind in ('VBO', 'LIG', 'STA'):
        ids = o['rel'].get('heeftAlsNevenadres')
        if ids and o.get('status') in OBJECT_OK[KINDS[kind]] and o['coords']:
            return ids, centre(o['coords'], o['dim'])
    elif kind == 'NUM':
        if o['identificatie'] in _WANT and o.get('status') in NAME_OK and o.get('huisnummer') and o.get('postcode'):
            return (o['identificatie'], o['postcode'].replace(' ', '').upper(), int(o['huisnummer']), o.get('huisletter', ''),
                    o.get('huisnummertoevoeging', ''), (o['rel'].get('ligtAan') or [''])[0], (o['rel'].get('ligtIn') or [''])[0])
    elif kind == 'OPR':
        if o['identificatie'] in _WANT and o.get('status') in NAME_OK and o.get('naam'):
            return o['identificatie'], o['naam'], (o['rel'].get('ligtIn') or [''])[0]
    elif kind == 'WPL':
        if o.get('status') in TOWN_OK and o.get('naam'):
            return o['identificatie'], o['naam']
    return None


def parse_member(job):
    """All kept objects of one XML file in an inner zip, streamed."""
    path, member, kind = job
    wanted, found = KINDS[kind], []
    with zipfile.ZipFile(path) as z, z.open(member) as fh:
        for _, e in ET.iterparse(fh, events=('end',)):
            if local(e.tag) == wanted:
                got = pick(kind, read(e))
                if got is not None:
                    found.append(got)
                e.clear()
    return found


def members(outer, kind, tmp):
    """The inner zip of this type, copied to a temporary file, and the XML files in it as jobs."""
    with zipfile.ZipFile(outer) as z:
        name = next(n for n in z.namelist() if n.startswith('9999' + kind) and n.lower().endswith('.zip'))
        path = os.path.join(tmp, name)
        with z.open(name) as src, open(path, 'wb') as dst:
            shutil.copyfileobj(src, dst, 1 << 24)
    with zipfile.ZipFile(path) as inner:
        return path, [(path, m, kind) for m in sorted(inner.namelist()) if m.lower().endswith('.xml')]


def stream(outer, kind, jobs, tmp, log):
    path, work = members(outer, kind, tmp)
    try:
        if jobs > 1:
            with multiprocessing.get_context('fork').Pool(jobs) as pool:
                for n, got in enumerate(pool.imap_unordered(parse_member, work), 1):
                    yield from got
                    if n % 200 == 0:
                        log(f'{kind}: {n}/{len(work)} files')
        else:
            for w in work:
                yield from parse_member(w)
    finally:
        os.unlink(path)


def build(extract, main, out, jobs=1, quiet=True, tmpdir=None):
    t0 = time.time()
    log = (lambda m: None) if quiet else (lambda m: print(f'{m} ({time.time() - t0:.0f}s)', flush=True))
    from pyproj import Transformer
    tr = Transformer.from_crs(28992, 4326, always_xy=True)
    global _WANT
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=tmpdir or out.parent)
    try:
        at = {}                                   # nummeraanduiding id -> (x, y) in RD
        _WANT = set()
        for kind in ('VBO', 'LIG', 'STA'):
            for ids, xy in stream(extract, kind, jobs, tmp, log):
                for i in ids:
                    at.setdefault(i, xy)
            log(f'{kind}: {len(at):,} secondary addresses so far')
        _WANT = set(at)
        nums = {n[0]: n[1:] for n in stream(extract, 'NUM', jobs, tmp, log)}
        log(f'NUM: {len(nums):,} usable')
        _WANT = {n[4] for n in nums.values()}
        streets = {s[0]: s[1:] for s in stream(extract, 'OPR', jobs, tmp, log)}
        towns = dict(stream(extract, 'WPL', jobs, tmp, log))
        log(f'OPR/WPL: {len(streets):,} streets, {len(towns):,} towns')
    finally:
        _WANT = set()
        shutil.rmtree(tmp, ignore_errors=True)

    part = out.with_suffix('.partial')
    part.unlink(missing_ok=True)
    db = sqlite3.connect(part)
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;')
    address_nl.create_index(db)
    db.execute('ATTACH DATABASE ? AS main_src', (str(main),))
    db.execute('INSERT INTO nl_addr SELECT * FROM main_src.nl_addr')
    db.execute('CREATE INDEX tmp_key ON nl_addr(postcode, num)')
    mains = db.execute('SELECT count(*) FROM nl_addr').fetchone()[0]
    ids = list(nums)
    added = skipped = nameless = 0
    seen = set()
    for lo in range(0, len(ids), 50_000):
        chunk = ids[lo:lo + 50_000]
        lons, lats = tr.transform([at[i][0] for i in chunk], [at[i][1] for i in chunk])
        for i, lon, lat in zip(chunk, lons, lats):
            postcode, num, letter, addition, opr, wpl = nums[i]
            street, street_town = streets.get(opr, ('', ''))
            if not street:
                nameless += 1
                continue
            key = (postcode, num, letter, addition)
            if key in seen or db.execute('SELECT 1 FROM nl_addr WHERE postcode=? AND num=? AND letter=? AND addition=? LIMIT 1', key).fetchone():
                skipped += 1
                continue
            seen.add(key)
            city = towns.get(wpl) or towns.get(street_town) or ''
            db.execute('INSERT INTO nl_addr VALUES (?,?,?,?,?,?,?,?,?,?)', (postcode, num, letter, addition, street, address_nl.normalize(street),
                                                                          city, address_nl.normalize(city), round(lat, 6), round(lon, 6)))
            added += 1
    db.execute('DROP INDEX tmp_key')
    db.commit()
    db.execute('DETACH DATABASE main_src')
    address_nl.finish_index(db, mains + added, SOURCE)
    db.close()
    part.replace(out)
    return {'main': mains, 'added': added, 'skipped': skipped, 'no_street': nameless}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('extract', help='lvbag-extract-nl.zip')
    ap.add_argument('main', help='the main-address NL.sqlite from tools/build_bag.py')
    ap.add_argument('out', help='the complete NL.sqlite to write')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 2), help='parallel processes (default: cores minus 2)')
    ap.add_argument('--tmp', help='where the temporary inner zip goes (default: next to the output)')
    a = ap.parse_args()
    r = build(a.extract, a.main, a.out, a.jobs, quiet=False, tmpdir=a.tmp)
    print(f'done: {r["main"]:,} main addresses, {r["added"]:,} secondary added, {r["skipped"]:,} duplicates skipped, '
          f'{r["no_street"]:,} without a street name', flush=True)


if __name__ == '__main__':
    main()

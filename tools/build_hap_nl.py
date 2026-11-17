#!/usr/bin/env python3
"""Add the Netherlands' out-of-hours GP posts (huisartsenposten) that OpenStreetMap lacks to a copy of national.sqlite.

  derived/buildenv/bin/python tools/build_hap_nl.py derived/geo-nl/national.sqlite derived/nl-hap/national.sqlite \\
      --csv derived/nl-hap/dl-wikidata/hap.csv --download

Reads:
  national.sqlite   the map database from tools/build_map_osm.py (OpenStreetMap, ODbL 1.0); never changed
  --csv             Wikidata's items for huisartsenposten in the Netherlands (instance of "general practice center", Q2438319,
                    country Netherlands): name, website and coordinates. Wikidata's structured data is CC0 1.0
                    (https://www.wikidata.org/wiki/Wikidata:Licensing). With --download the file is fetched first from the
                    Wikidata Query Service; this is the only network use, and it is a build step, never the app.
                    The items were first entered in 2018 and 2019 from RIVM's VZinfo list, so a post that has since closed or
                    moved can still be in it.
Writes: the output copy of national.sqlite with a poi row of class 'huisartsenpost' for each listed post, and a meta key
'huisartsenposten' that records the source and licence. A post within 150 m of one already in the map (OpenStreetMap's) is
skipped, so OpenStreetMap's name and place stay; items without coordinates or outside the Netherlands' box are skipped.

After this, rebuild places.sqlite (tools/build_places_nl.py), which also lists named help points.
"""
import argparse, csv, io, math, re, shutil, sqlite3, sys, urllib.parse, urllib.request
from pathlib import Path

NEAR_M = 150
BOX = (3.2, 50.7, 7.3, 53.7)        # the Netherlands region's box, as in engine/regions.json
SPARQL = ('SELECT ?i ?name ?c ?web ?located WHERE { ?i wdt:P31 wd:Q2438319 ; wdt:P17 wd:Q55 . ?i rdfs:label ?name . '
          'FILTER(LANG(?name) = "nl") OPTIONAL { ?i wdt:P625 ?c } OPTIONAL { ?i wdt:P856 ?web } OPTIONAL { ?i wdt:P131 ?located } }')
ENDPOINT = 'https://query.wikidata.org/sparql'
POINT = re.compile(r'Point\(\s*([-\d.]+)\s+([-\d.]+)\s*\)')
SOURCE = ('Wikidata (CC0 1.0), https://www.wikidata.org: general practice centers (HAP) in the Netherlands, items first entered '
          'from RIVM VZinfo in 2018 and 2019')


def download(path):
    """Fetch the Wikidata list as CSV into path."""
    url = ENDPOINT + '?' + urllib.parse.urlencode({'query': SPARQL})
    req = urllib.request.Request(url, headers={'Accept': 'text/csv', 'User-Agent': 'lastbook-build-tools/1.0'})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def parse(text):
    """([(name, lon, lat)], number of items without usable coordinates). Points outside the Netherlands' box are dropped."""
    rows, nocoord = [], 0
    for r in csv.DictReader(io.StringIO(text)):
        m = POINT.match(r.get('c') or '')
        if not m:
            nocoord += 1
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        if BOX[0] <= lon <= BOX[2] and BOX[1] <= lat <= BOX[3]:
            rows.append((r['name'].strip(), lon, lat))
    return rows, nocoord


def metres(lon1, lat1, lon2, lat2):
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def merge(src, out, rows, source=SOURCE):
    """Copy src to out and add each (name, lon, lat) not within NEAR_M of a huisartsenpost. Returns the counts."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.partial')
    tmp.unlink(missing_ok=True)
    shutil.copyfile(src, tmp)
    db = sqlite3.connect(tmp)
    have = db.execute("SELECT lon, lat FROM poi WHERE cls='huisartsenpost'").fetchall()
    stats = {'before': len(have), 'added': 0, 'near': 0}
    nid = (db.execute('SELECT max(id) FROM poi').fetchone()[0] or 0) + 1
    for name, lon, lat in rows:
        if any(metres(lon, lat, x, y) < NEAR_M for x, y in have):
            stats['near'] += 1
            continue
        db.execute('INSERT INTO poi VALUES (?,?,?,?,?)', (nid, 'huisartsenpost', name, lon, lat))
        have.append((lon, lat))
        nid += 1
        stats['added'] += 1
    stats['after'] = len(have)
    db.execute("INSERT OR REPLACE INTO meta VALUES ('huisartsenposten', ?)", ('added from ' + source,))
    db.commit()
    db.execute('VACUUM')
    db.close()
    tmp.replace(out)
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('national', help='national.sqlite from tools/build_map_osm.py')
    ap.add_argument('out', help='the new national.sqlite (a changed copy)')
    ap.add_argument('--csv', required=True, help="Wikidata's list (written first when --download is given)")
    ap.add_argument('--download', action='store_true', help='fetch the list from the Wikidata Query Service first')
    a = ap.parse_args()
    if a.download:
        download(a.csv)
    rows, nocoord = parse(Path(a.csv).read_text(encoding='utf-8'))
    stats = merge(a.national, a.out, rows)
    print(f"huisartsenposten: {stats['before']} before, {stats['added']} added, {stats['after']} after "
          f"({stats['near']} within {NEAR_M} m of an existing post, {nocoord} listed without coordinates)")


if __name__ == '__main__':
    sys.exit(main())

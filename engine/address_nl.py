"""Read-only Dutch address lookup in the Netherlands address index (derived/geo/addresses/NL.sqlite, from Kadaster BAG).

People in the Netherlands find an address by postcode and house number ("1012 LG 1", "1012lg1a"), or by street and number,
with or without the town ("Damrak 1", "Damrak 1 Amsterdam", "Damrak 1, 1012 LG Amsterdam"). A postcode alone shows its street.
House number additions are written many ways (12A, 12-A, 12 a, 12-2, 12 hs, 2-III); the index keeps BAG's letter and addition,
and a match must agree on them: like the US lookup, this never guesses a house.

tools/build_bag.py writes the index with create_index(), normalize() and finish_index() from here, so both sides agree.
"""
import math
import re
import sqlite3
import time
import unicodedata

from engine.paths import ro_uri

WORDS = {'str': 'straat', 'ln': 'laan', 'pl': 'plein', 'st': 'sint'}
CITY_ALIASES = {'den haag': 's gravenhage', 'den bosch': 's hertogenbosch'}   # what people say, and BAG's official name
SUFFIX_ALIASES = {'i': '1', 'ii': '2', 'iii': '3', 'iv': '4', 'hs': 'h'}     # floors written in Roman numerals; "hs" for huis

POSTCODE_FIRST = re.compile(
    r'^\s*(?P<pc>\d{4})\s*(?P<pcl>[a-z]{2})'
    r'(?:[\s,]*(?P<num>\d+)(?P<suffix>(?:\s*-\s*|\s*)[a-z0-9]{1,4}(?:[\s-][a-z0-9]{1,4})?)?)?\s*$', re.I)
STREET_FIRST = re.compile(
    r'^\s*(?P<street>(?:\d+e\s+)?[^\d,]*[a-z][^\d,]*?)\s+(?P<num>\d+)'
    r'(?P<suffix>(?:\s*-\s*|\s*)[a-z0-9]{1,4}(?:-[a-z0-9]{1,4})?(?=[\s,]|$))?'
    r'(?:\s*,?\s*(?P<pc>\d{4})\s*(?P<pcl>[a-z]{2})(?=[\s,]|$))?'
    r'(?:\s*,?\s*(?P<city>[^\d,][^\d,]*))?'
    r'(?:\s*,?\s*(?P<pc2>\d{4})\s*(?P<pcl2>[a-z]{2}))?\s*$', re.I)       # the town may come before the postcode, too


def normalize(text):
    """'Kerkstr.' -> 'kerkstraat', "'s-Gravenhage" -> 's gravenhage', 'Sint-Jansstraat' -> 'sint jansstraat'."""
    folded = ''.join(c for c in unicodedata.normalize('NFKD', text or '') if not unicodedata.combining(c)).lower()
    words = re.sub(r'[^a-z0-9]+', ' ', folded).split()
    words = [WORDS.get(w, w) for w in words]
    return ' '.join(w[:-3] + 'straat' if len(w) > 3 and w.endswith('str') else w for w in words)


def _city(text):
    city = normalize(text)
    return CITY_ALIASES.get(city, city)


def _suffix(text):
    return re.sub(r'[^a-z0-9]', '', (text or '').lower())


def _candidates(query):
    """Every reading of the query, most likely first. A short word after the number may be an addition (12 hs) or a town
    (5 Ede), so both are tried."""
    m = POSTCODE_FIRST.match(query or '')
    if m:
        return [{'postcode': (m['pc'] + m['pcl']).upper(), 'number': int(m['num']) if m['num'] else None,
                 'suffix': _suffix(m['suffix']), 'street': '', 'city': ''}]
    m = STREET_FIRST.match(query or '')
    if not m:
        return []
    street = normalize(m['street'])
    if not street:
        return []
    postcode = (m['pc'] + m['pcl']).upper() if m['pc'] else (m['pc2'] + m['pcl2']).upper() if m['pc2'] else ''
    first = {'postcode': postcode, 'number': int(m['num']), 'suffix': _suffix(m['suffix']),
             'street': street, 'city': _city(m['city'] or '')}
    out = [first]
    if first['suffix'] and m['suffix'].strip(' -').isalpha():
        out.append({**first, 'suffix': '', 'city': _city(m['suffix'].strip(' -') + ' ' + (m['city'] or ''))})
    return out


def parse(query):
    """The most likely reading of a Dutch address query, or None when it is not one."""
    found = _candidates(query)
    return found[0] if found else None


def create_index(db):
    db.executescript('CREATE TABLE nl_addr(postcode TEXT, num INTEGER, letter TEXT, addition TEXT, street TEXT, norm TEXT, city TEXT,'
                     ' city_norm TEXT, lat REAL, lon REAL);'
                     'CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);')


def finish_index(db, count, source):
    db.executescript('CREATE INDEX nl_pc ON nl_addr(postcode, num); CREATE INDEX nl_norm ON nl_addr(norm, num);')
    db.executemany('INSERT OR REPLACE INTO meta VALUES (?,?)', [('style', 'nl'), ('region', 'NL'), ('count', str(count)),
                                                               ('source', source), ('built', time.strftime('%Y-%m-%dT%H:%M:%S'))])
    db.commit()


def _pc(postcode):
    return f'{postcode[:4]} {postcode[4:]}' if len(postcode) == 6 else postcode


def _postcode_streets(connections, postcode, limit):
    out = []
    for db in connections:
        try:
            out += db.execute('SELECT street, city, min(num), max(num), avg(lat), avg(lon) FROM nl_addr WHERE postcode=? '
                              'GROUP BY street, city ORDER BY street LIMIT ?', (postcode, limit)).fetchall()
        except sqlite3.Error:
            continue
    return [{'name': street, 'kind': 'Postcode',
             'detail': f'{_pc(postcode)} {city} · number{"s" if lo != hi else ""} {lo}{"–" + str(hi) if lo != hi else ""}',
             'lat': lat, 'lon': lon, 'source': 'Kadaster BAG', 'onMap': True} for street, city, lo, hi, lat, lon in out[:limit]]


def _rows(connections, c, limit, near=None):
    conditions, params = ['num = ?'], [c['number']]
    if c['postcode']:
        conditions.append('postcode = ?')
        params.append(c['postcode'])
    if c['street']:
        conditions += ['norm >= ?', 'norm < ?']
        params += [c['street'], c['street'] + '￿']
    if c['city']:
        conditions.append('city_norm LIKE ?')
        params.append(c['city'] + '%')
    order, extra = 'length(norm), norm', []
    if near:      # a common street (Kerkstraat 5 is in hundreds of towns): the nearest first, before the row limit cuts any off
        k = math.cos(math.radians(near[0]))
        order = 'length(norm), (lat - ?) * (lat - ?) + ((lon - ?) * ?) * ((lon - ?) * ?)'
        extra = [near[0], near[0], near[1], k, near[1], k]
    sql = ('SELECT postcode, num, letter, addition, street, norm, city, lat, lon FROM nl_addr WHERE ' + ' AND '.join(conditions)
           + f' ORDER BY {order} LIMIT ?')
    rows = []
    for db in connections:
        try:
            rows += db.execute(sql, [*params, *extra, limit * 20]).fetchall()
        except sqlite3.Error:
            continue
    return rows


def find(query, paths, limit=8, near=None):
    """Matching addresses from the installed Dutch indexes, never a guessed house."""
    candidates = _candidates(query)
    if not candidates or not paths:
        return []
    connections = []
    try:
        for path in paths:
            try:
                connections.append(sqlite3.connect(ro_uri(path), uri=True))
            except sqlite3.Error:
                continue
        for c in candidates:
            if c['number'] is None:
                hits = _postcode_streets(connections, c['postcode'], limit)
                if hits:
                    return hits
                continue
            rows = _rows(connections, c, limit, near)
            want = c['suffix']
            keyed = [(_suffix((r[2] or '') + (r[3] or '')), r) for r in rows]
            if want:
                same = SUFFIX_ALIASES.get(want, want)     # floors: typed 2-III or 2-3 match a stored 3 or III
                chosen = [r for s, r in keyed if s == want] or [r for s, r in keyed if SUFFIX_ALIASES.get(s, s) == same]
            else:
                chosen = [r for s, r in sorted(keyed, key=lambda k: (k[0] != '', k[0]))]
            if not chosen:
                continue

            def rank(r):
                distance = 0
                if near:
                    distance = (r[7] - near[0]) ** 2 + ((r[8] - near[1]) * math.cos(math.radians(near[0]))) ** 2
                return r[5] != c['street'], len(r[5]), distance
            results, seen = [], set()
            for postcode, num, letter, addition, street, _norm, city, lat, lon in sorted(chosen, key=rank) if c['street'] else chosen:
                key = (postcode, num, letter, addition)
                if key in seen:
                    continue
                seen.add(key)
                results.append({'name': f'{street} {num}{letter or ""}{"-" + addition if addition else ""}', 'kind': 'Address',
                                'detail': f'{_pc(postcode)} {city}', 'lat': lat, 'lon': lon, 'source': 'Kadaster BAG', 'onMap': True})
                if len(results) == limit:
                    break
            return results
        return []
    finally:
        for db in connections:
            db.close()

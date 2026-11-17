#!/usr/bin/env python3
"""Build a street map database (national.sqlite format, tools/map_schema.py) straight from an OpenStreetMap PBF extract.

  derived/buildenv/bin/python tools/build_map_osm.py derived/sources/nl/netherlands-latest.osm.pbf derived/geo-nl/national.sqlite \\
      --box 3.2,50.7,7.3,53.7 --water-polygons derived/sources/nl/water-polygons-split-4326 \\
      --land-polygons derived/sources/nl/land-polygons-split-4326 --admin derived/geo-nl/admin.sqlite

Reads: a Geofabrik country extract (https://download.geofabrik.de/europe/netherlands-latest.osm.pbf), and the coastline
polygons OpenStreetMap publishes (https://osmdata.openstreetmap.de/download/water-polygons-split-4326.zip and
land-polygons-split-4326.zip). All are OpenStreetMap data, © OpenStreetMap contributors, ODbL 1.0.
Writes: feat/feat_idx (roads, water, land use, waterways, rail, places, sea as layer 'ocean', land as layer 'island'), poi
(help points) and meta. Buildings are left out: for the Netherlands they come from Kadaster BAG (tools/build_bag.py).
With --admin, also a build-only admin.sqlite: municipalities (admin_level 8, with ref:gemeentecode) and provinces (admin_level 4),
which tools/build_places_nl.py reads. It never ships.

Classes follow the names of Geofabrik's "free" schema, so map.js draws them as it draws tools/build_map.py's output. Dutch help
points: hospitals with an emergency department (emergency=yes) are 'hospital_seh'; doctors or clinics named huisartsenpost or HAP
are 'huisartsenpost' (out-of-hours GP posts; OpenStreetMap has no tag of its own for them); defibrillators and emergency assembly
points keep their emergency=* value.
"""
import argparse, re, sqlite3, sys, time
from pathlib import Path

from map_schema import ROAD_Z, LANDUSE_KEEP, PLACE_Z, POI_KEEP, simplify, bbox, pack, area_z, create_map_tables, MapWriter

LINES = {'waterway': {'river', 'canal', 'stream', 'drain', 'ditch'}, 'railway': {'rail', 'light_rail', 'subway', 'tram'}}
POI_ALIASES = {('amenity', 'toilets'): 'toilet', ('shop', 'bicycle'): 'bicycle_shop', ('tourism', 'camp_site'): 'camp_site',
               ('leisure', 'park'): None, ('man_made', 'water_tower'): 'water_tower', ('man_made', 'water_works'): 'water_works',
               ('man_made', 'wastewater_plant'): 'wastewater_plant', ('natural', 'spring'): 'spring'}
HAP = re.compile(r'huisartsenpost|\bHAP\b', re.I)
# Only objects with one of these keys reach Python: pyosmium drops the rest after storing node locations (most of the file).
KEYS = ('highway', 'waterway', 'railway', 'natural', 'water', 'landuse', 'leisure', 'boundary', 'place', 'amenity', 'shop',
        'emergency', 'man_made', 'tourism')
ADMIN_LEVELS = {'4': 'province', '8': 'municipality'}


def classify(tags, kind):
    """What one OSM object becomes: [(target, layer or class, class or None)]. kind is 'node', 'way' (lines only: areas arrive
    again as 'area') or 'area'. Points of interest come from nodes and areas, lines from ways."""
    get = tags.get
    if kind == 'way':
        if get('highway') and get('area') != 'yes':
            cls = get('highway')
            if cls == 'track' and (get('tracktype') or '').startswith('grade'):
                cls = 'track_' + get('tracktype')
            return [('feat', 'road', cls)]
        for key, keep in LINES.items():
            if get(key) in keep:
                return [('feat', key if key == 'waterway' else 'rail', get(key))]
        return []
    out = []
    if kind == 'area':
        if get('natural') == 'water' or get('water') or get('landuse') in ('reservoir', 'basin'):
            out.append(('feat', 'water', get('water') or ('reservoir' if get('landuse') == 'reservoir' else 'water')))
        elif get('natural') == 'wetland':
            out.append(('feat', 'wet', 'wetland'))
        elif get('natural') == 'beach':
            out.append(('feat', 'beach', 'beach'))
        elif get('boundary') == 'protected_area' or get('leisure') == 'nature_reserve':
            out.append(('feat', 'land', 'park'))
        else:
            for key in ('landuse', 'leisure', 'natural'):
                if get(key) in LANDUSE_KEEP:
                    out.append(('feat', 'land', LANDUSE_KEEP[get(key)]))
                    break
    elif get('place') and get('name'):
        return [('feat', 'place', get('place'))]
    cls = poi_class(tags)
    if cls:
        out.append(('poi', cls, None))
    return out


def poi_class(tags):
    get = tags.get
    if get('emergency') in ('defibrillator', 'assembly_point'):
        return get('emergency')
    amenity = get('amenity')
    if amenity == 'hospital':
        return 'hospital_seh' if get('emergency') == 'yes' else 'hospital'
    if amenity in ('doctors', 'clinic') and HAP.search(get('name') or ''):
        return 'huisartsenpost'
    for key in ('amenity', 'shop', 'man_made', 'tourism', 'natural', 'leisure'):
        value = get(key)
        if not value:
            continue
        if (key, value) in POI_ALIASES:
            return POI_ALIASES[(key, value)]
        if key in ('amenity', 'shop') and value in POI_KEEP:
            return value
    return None


def overlaps(box, b):
    return box is None or not (b[1] < box[0] or b[0] > box[2] or b[3] < box[1] or b[2] > box[3])


def admin_db(path):
    db = sqlite3.connect(path)
    db.executescript('DROP TABLE IF EXISTS admin; CREATE TABLE admin(kind TEXT, name TEXT, code TEXT, minx REAL, maxx REAL, miny REAL, '
                     'maxy REAL, geom BLOB);')
    return db


def build(pbf, out, box=None, water=None, land=None, admin=None):
    import osmium
    t0 = time.time()
    adm = admin_db(admin) if admin else None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.partial')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    create_map_tables(db)
    w = MapWriter(db)
    seen = {'n': 0}

    def feature(layer, cls, name, parts, tags):
        b = bbox(parts)
        if not overlaps(box, b):
            return
        if layer == 'road':
            w.add('road', cls, name or tags.get('ref'), ROAD_Z.get(cls, 15), parts)
        elif layer in ('water', 'wet'):
            w.add(layer, cls, name, area_z(*b, 7), [simplify(p, 0.00001) for p in parts])
        elif layer == 'beach':
            w.add('beach', cls, name, area_z(*b, 10), parts)
        elif layer == 'land':
            w.add('land', cls, None if cls == 'park' and tags.get('boundary') else name, area_z(*b, 8 if cls == 'park' else 9),
                  [simplify(p, 0.00002 if cls == 'park' else 0.00001) for p in parts])
        elif layer == 'waterway':
            w.add('waterway', cls, name, 10 if cls in ('river', 'canal') else 13, parts)
        elif layer == 'rail':
            w.add('rail', cls, name, 10 if cls == 'rail' else 13, parts)
        elif layer == 'place':
            z = PLACE_Z.get(cls, 14)
            pop = tags.get('population') or ''
            if cls in ('city', 'town') and pop.isdigit() and int(pop) > 300000:
                z = 5
            w.add('place', cls, name, z, parts)

    def handle(tags, kind, parts):
        what = classify(tags, kind)
        if not what:
            return
        name = tags.get('name')
        for target, a, b in what:
            if target == 'feat':
                feature(a, b, name, parts, tags)
            else:
                minx, maxx, miny, maxy = bbox(parts)
                lon, lat = (minx + maxx) / 2, (miny + maxy) / 2
                if overlaps(box, (lon, lon, lat, lat)):
                    w.poi(a, name, lon, lat)
        seen['n'] += 1
        if seen['n'] % 200000 == 0:
            db.commit()
            print(f"{seen['n']:,} objects, {w.fid:,} features, {w.pid:,} points, {time.time() - t0:.0f}s", flush=True)

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if n.tags and n.location.valid():
                tags = dict(n.tags)
                if 'place' in tags or poi_class(tags):
                    handle(tags, 'node', [[n.location.lon, n.location.lat]])

        def way(self, wy):
            if not wy.tags or not ('highway' in wy.tags or 'waterway' in wy.tags or 'railway' in wy.tags):
                return
            try:
                pts = [c for nd in wy.nodes for c in (nd.lon, nd.lat)]
            except osmium.InvalidLocationError:
                return
            if len(pts) >= 4:
                handle(dict(wy.tags), 'way', [pts])

        def area(self, a):
            if not a.tags:
                return
            tags = dict(a.tags)
            kind = ADMIN_LEVELS.get(tags.get('admin_level')) if tags.get('boundary') == 'administrative' else None
            if adm is not None and kind and tags.get('name'):
                rings = []
                try:
                    for outer in a.outer_rings():
                        rings.append([c for nd in outer for c in (nd.lon, nd.lat)])
                except osmium.InvalidLocationError:
                    rings = []
                if rings:
                    b = bbox(rings)
                    adm.execute('INSERT INTO admin VALUES (?,?,?,?,?,?,?,?)', (kind, tags['name'], tags.get('ref:gemeentecode'), *b,
                                                                             pack([simplify(r, 0.0002) for r in rings])))
            if not classify(tags, 'area'):
                return
            parts = []
            try:
                for outer in a.outer_rings():
                    parts.append([c for nd in outer for c in (nd.lon, nd.lat)])
                    for inner in a.inner_rings(outer):
                        parts.append([c for nd in inner for c in (nd.lon, nd.lat)])
            except osmium.InvalidLocationError:
                return
            parts = [p for p in parts if len(p) >= 6]
            if parts:
                handle(tags, 'area', parts)

    Handler().apply_file(str(pbf), locations=True, filters=[osmium.filter.KeyFilter(*KEYS)])
    if adm is not None:
        adm.commit()
        adm.close()
    for folder, layer in ((water, 'ocean'), (land, 'island')):
        if folder:
            n = coast(w, Path(folder), layer, box)
            print(f'{layer}: {n:,} polygons', flush=True)
    as_of = ''
    try:
        as_of = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING).header().get('osmosis_replication_timestamp') or ''
    except Exception:
        pass
    w.finish({'source': f'OpenStreetMap contributors, via Geofabrik {Path(pbf).name} (ODbL 1.0)', 'data_as_of': as_of,
              'bounds': ','.join(str(v) for v in box) if box else '', 'built': time.strftime('%Y-%m-%dT%H:%M:%S')})
    db.close()
    tmp.replace(out)
    print(f'done: {w.fid:,} features, {w.pid:,} points in {time.time() - t0:.0f}s', flush=True)


def coast(w, folder, layer, box):
    """Sea (water polygons) or land (land polygons) from OpenStreetMap's coastline files, the pieces that touch the box."""
    import shapefile
    shp = next(folder.rglob('*.shp'))
    n = 0
    with shapefile.Reader(str(shp)) as r:
        for shape in r.iterShapes():
            x0, y0, x1, y1 = shape.bbox
            if not overlaps(box, (x0, x1, y0, y1)):
                continue
            idx = list(shape.parts) + [len(shape.points)]
            parts = [simplify([c for pt in shape.points[a:b] for c in pt], 0.00005) for a, b in zip(idx, idx[1:])]
            w.add(layer, layer, None, 0, [p for p in parts if len(p) >= 6])
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('pbf')
    ap.add_argument('out')
    ap.add_argument('--box', help='W,S,E,N: leave out what lies wholly outside')
    ap.add_argument('--water-polygons', help='folder with water_polygons.shp (sea)')
    ap.add_argument('--land-polygons', help='folder with land_polygons.shp (land drawn over the sea)')
    ap.add_argument('--admin', help='also write municipalities and provinces to this build-only database')
    a = ap.parse_args()
    box = [float(v) for v in a.box.split(',')] if a.box else None
    build(a.pbf, a.out, box, a.water_polygons, a.land_polygons, a.admin)


if __name__ == '__main__':
    sys.exit(main())

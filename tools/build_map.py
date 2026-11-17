#!/usr/bin/env python3
"""Convert the Geofabrik SoCal GeoPackage (OpenStreetMap, ODbL) into a compact, spatially indexed
map database the app can draw offline.

  python3 tools/build_map.py derived/geo/socal.gpkg derived/geo/map.sqlite

Input is a copy extracted from library-data/geography/openstreetmap/socal-latest-free.gpkg.zip;
the original archive is only read. Output tables:
  feat(id, layer, cls, name, minz, geom)   geom = packed int32 lon/lat * 1e6 (see pack())
  feat_idx (R*Tree on bbox)
  poi(id, cls, name, lon, lat)             help-relevant points (hospitals, pharmacies, water...)
  meta(key, value)
"""
import sqlite3, sys, time

from map_schema import (ROAD_Z, LANDUSE_KEEP, PLACE_Z, POI_KEEP, wkb_parts, gpkg_parts, simplify, pack, bbox,  # noqa: F401
                        area_z)

def main():
    SRC, DST = sys.argv[1], sys.argv[2]
    t0 = time.time()
    src = sqlite3.connect(SRC)
    dst = sqlite3.connect(DST)
    dst.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      DROP TABLE IF EXISTS feat; DROP TABLE IF EXISTS feat_idx; DROP TABLE IF EXISTS poi; DROP TABLE IF EXISTS meta;
      CREATE TABLE feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB);
      CREATE VIRTUAL TABLE feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);
      CREATE TABLE poi(id INTEGER PRIMARY KEY, cls TEXT, name TEXT, lon REAL, lat REAL);
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);''')
    fid = [0]

    def add(layer, cls, name, minz, parts):
        if not parts:
            return
        fid[0] += 1
        bx = bbox(parts)
        dst.execute('INSERT INTO feat VALUES (?,?,?,?,?,?)', (fid[0], layer, cls, name, minz, pack(parts)))
        dst.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (fid[0], *bx, minz, 30))

    def each(table, cols='fclass,name'):
        for row in src.execute(f'SELECT geom,{cols} FROM {table}'):
            if row[0] is None:
                continue
            try:
                yield gpkg_parts(row[0]), row[1:]
            except Exception:
                continue

    # Water bodies
    for parts, (cls, name) in each('gis_osm_water_a_free'):
        layer = 'wet' if cls.startswith('wetland') else 'water'
        b = bbox(parts)
        add(layer, cls, name, area_z(*b, 7), [simplify(p, 0.00001) for p in parts])
    print('water', fid[0], round(time.time() - t0), flush=True)
    for parts, (cls, name) in each('gis_osm_natural_a_free'):
        if cls == 'beach':
            add('beach', cls, name, area_z(*bbox(parts), 10), parts)
    for parts, (cls, name) in each('gis_osm_landuse_a_free'):
        k = LANDUSE_KEEP.get(cls)
        if k:
            add('land', k, name, area_z(*bbox(parts), 9), [simplify(p, 0.00001) for p in parts])
    for parts, (cls,) in each('gis_osm_protected_areas_a_free', 'fclass'):
        add('land', 'park', None, area_z(*bbox(parts), 8), [simplify(p, 0.00002) for p in parts])
    print('land', fid[0], round(time.time() - t0), flush=True)
    for parts, (cls, name) in each('gis_osm_waterways_free'):
        add('waterway', cls, name, 10 if cls == 'river' else 13, parts)
    for parts, (cls, name) in each('gis_osm_railways_free'):
        add('rail', cls, name, 10 if cls == 'rail' else 13, parts)
    print('lines', fid[0], round(time.time() - t0), flush=True)
    for parts, (cls, name, ref) in each('gis_osm_roads_free', 'fclass,name,ref'):
        label = name or ref
        add('road', cls, label, ROAD_Z.get(cls, 15), parts)
    print('roads', fid[0], round(time.time() - t0), flush=True)
    dst.commit()
    for parts, (cls, name) in each('gis_osm_buildings_a_free'):
        add('bldg', cls or '', None, 15, [simplify(parts[0], 0.000002)])
    print('buildings', fid[0], round(time.time() - t0), flush=True)
    dst.commit()
    for parts, (cls, pop, name) in each('gis_osm_places_free', 'fclass,population,name'):
        if name:
            z = PLACE_Z.get(cls, 14)
            if cls in ('city', 'town') and pop and int(pop) > 300000:
                z = 5
            add('place', cls, name, z, parts)
    pid = 0
    for table in ('gis_osm_pois_free', 'gis_osm_pois_a_free', 'gis_osm_natural_free', 'gis_osm_natural_a_free'):
        for parts, (cls, name) in each(table):
            if cls not in POI_KEEP:
                continue
            if table == 'gis_osm_natural_free' and cls not in ('spring',):
                continue
            minx, maxx, miny, maxy = bbox(parts)
            pid += 1
            dst.execute('INSERT INTO poi VALUES (?,?,?,?,?)', (pid, cls, name, (minx + maxx) / 2, (miny + maxy) / 2))
    dst.execute('CREATE INDEX poi_cls ON poi(cls, lon, lat)')
    dst.executemany('INSERT INTO meta VALUES (?,?)', [
        ('source', 'OpenStreetMap contributors, via Geofabrik socal-latest-free.gpkg.zip (ODbL 1.0)'),
        ('data_as_of', '2026-10-25T21:21:21Z'),
        ('bounds', '-121.36,32.50,-114.10,35.89'),
        ('built', time.strftime('%Y-%m-%dT%H:%M:%S')),
    ])
    dst.commit()
    print('done features', fid[0], 'pois', pid, round(time.time() - t0), 's', flush=True)


if __name__ == '__main__':
    main()

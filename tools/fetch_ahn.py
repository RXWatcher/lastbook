#!/usr/bin/env python3
"""Elevation for the Netherlands: AHN's terrain model, as 1° GeoTIFF cells that tools/build_terrain.py reads.

  derived/buildenv/bin/python tools/fetch_ahn.py derived/sources/nl/ahn --box 3.2,50.7,7.3,53.7
  derived/buildenv/bin/python tools/build_terrain.py --src derived/sources/nl/ahn --out derived/geo-nl/terrain.sqlite \\
      --bbox 3.2,50.7,7.3,53.7 --source-label "AHN4 DTM (Rijkswaterstaat, CC0 1.0), 1 arc-second"

Reads: AHN (Actueel Hoogtebestand Nederland), the ground surface without buildings or trees (coverage dtm_05m, 0.5 m), from
PDOK's Web Coverage Service https://service.pdok.nl/rws/ahn/wcs/v1_0 (Rijkswaterstaat, CC0 1.0). The service is asked for
WGS84 (EPSG:4326) at 1 arc-second, the grid of the USGS cells the terrain builder was written for: the map's terrain tiles stop
at zoom 12, about 24 m a pixel at 52° N, so finer data would not show. The full 0.5 m sheets (about 455 GB) are not needed.
Writes: <out>/n53e005/n53e005.tif and so on: float32, 3600 x 3600, top-left tie point and 1/3600° pixel scale, -9999 where
there is no data. Buildings and water are holes in a terrain model; holes up to about a kilometre across are filled from the
ground around them, so a polder does not show false sea-level pits. Larger water stays empty and draws at sea level (0 m).
A cell already written is kept, so an interrupted run resumes.
"""
import argparse, io, math, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import tifffile

WCS = 'https://service.pdok.nl/rws/ahn/wcs/v1_0'
CRS = 'http://www.opengis.net/def/crs/EPSG/0/4326'
PX = 3600            # 1 arc-second
CHUNK = 4            # each cell is asked for in 4 x 4 pieces of 900 x 900 px
NODATA = -9999.0


def cell_name(top, left):
    return f'n{top:02d}e{left:03d}'


def fill_gaps(h, passes=64):
    """NaN cells next to data take the mean of their valid neighbours (8-connected), repeated up to `passes` times."""
    h = h.astype(np.float32, copy=True)
    for _ in range(passes):
        gap = np.isnan(h)
        if not gap.any() or gap.all():
            break
        v = np.where(gap, 0, h)
        n = (~gap).astype(np.float32)
        vp, np_ = np.pad(v, 1), np.pad(n, 1)
        total = np.zeros_like(h)
        count = np.zeros_like(h)
        rows, cols = h.shape
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                if dy == 1 and dx == 1:
                    continue
                total += vp[dy:dy + rows, dx:dx + cols]
                count += np_[dy:dy + rows, dx:dx + cols]
        fill = gap & (count > 0)
        if not fill.any():
            break
        h[fill] = total[fill] / count[fill]
    return h


def write_cell(out, top, left, h):
    """One cell as a GeoTIFF build_terrain.cells() finds and dem() reads: <out>/<name>/<name>.tif."""
    d = Path(out) / cell_name(top, left)
    d.mkdir(parents=True, exist_ok=True)
    data = np.where(np.isnan(h), NODATA, h).astype(np.float32)
    tmp = d / (d.name + '.partial')
    tifffile.imwrite(tmp, data, compression='zlib', extratags=[
        (33550, 'd', 3, (1 / PX, 1 / PX, 0.0), False),               # ModelPixelScaleTag
        (33922, 'd', 6, (0.0, 0.0, 0.0, float(left), float(top), 0.0), False)])   # ModelTiepointTag
    tmp.replace(d / (d.name + '.tif'))


def fetch_piece(lon0, lat0, size, n):
    """Heights for [lon0, lon0+size] x [lat0, lat0+size] as an n x n array (north up), NaN where AHN has none."""
    url = (f'{WCS}?service=WCS&version=2.0.1&request=GetCoverage&coverageId=dtm_05m&format=image/tiff'
           f'&subsettingCrs={CRS}&outputCrs={CRS}&subset=Lat({lat0:.6f},{lat0 + size:.6f})&subset=Long({lon0:.6f},{lon0 + size:.6f})'
           f'&scaleSize=Long({n}),Lat({n})')
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'lastbook-map-builder'})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            with tifffile.TiffFile(io.BytesIO(data)) as t:
                a = t.pages[0].asarray().astype(np.float32)
            if a.shape != (n, n):
                raise ValueError(f'got {a.shape}, asked {n} x {n}')
            a[np.abs(a) > 1e30] = np.nan
            return a
        except Exception as e:      # the service is busy now and then: wait and ask again
            if attempt == 4:
                raise
            print(f'  retry {lon0:.2f},{lat0:.2f}: {e}', flush=True)
            time.sleep(5 * (attempt + 1))


def fetch_cell(top, left, workers=4):
    n, size = PX // CHUNK, 1 / CHUNK
    h = np.full((PX, PX), np.nan, np.float32)
    jobs = [(i, j) for j in range(CHUNK) for i in range(CHUNK)]
    with ThreadPoolExecutor(workers) as pool:
        pieces = pool.map(lambda ij: fetch_piece(left + ij[0] * size, top - (ij[1] + 1) * size, size, n), jobs)
        for (i, j), a in zip(jobs, pieces):
            h[j * n:(j + 1) * n, i * n:(i + 1) * n] = a
    return h


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('out')
    ap.add_argument('--box', default='3.2,50.7,7.3,53.7', help='W,S,E,N in degrees')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    w, s, e, n = map(float, a.box.split(','))
    t0 = time.time()
    for top in range(math.floor(s) + 1, math.ceil(n) + 1):
        for left in range(math.floor(w), math.ceil(e)):
            name = cell_name(top, left)
            if (Path(a.out) / name / (name + '.tif')).exists():
                print(f'{name}: already here', flush=True)
                continue
            h = fetch_cell(top, left, a.workers)
            have = int((~np.isnan(h)).sum())
            if not have:
                print(f'{name}: no AHN data ({time.time() - t0:.0f}s)', flush=True)
                continue
            h = fill_gaps(h)
            write_cell(a.out, top, left, h)
            print(f'{name}: {have / h.size:.0%} of the cell has data ({time.time() - t0:.0f}s)', flush=True)


if __name__ == '__main__':
    sys.exit(main())

"""What a map set zip holds (docs/SETUP-API.md, "State maps"), and how it is zipped: shared by packaging/state_maps.py (US states)
and packaging/region_maps.py (regions outside the US). setup installs only these files (engine/setup/install.py map_member)."""
import os
import sys
import zipfile

ALLOWED = {f'derived/geo/{n}.sqlite' for n in ('national', 'map', 'water', 'terrain', 'buildings', 'crops', 'places')} | {
    'derived/geo/national-status.json', 'derived/geo/socal-cells.json', 'library-data/geography/resources/atlas.sqlite', 'map-set.json'}
STORED = {'derived/geo/terrain.sqlite'}     # tiles are already compressed


def make_zip(d, out):
    tmp = out.with_suffix('.partial')
    with zipfile.ZipFile(tmp, 'w', allowZip64=True) as z:
        for rel in sorted(ALLOWED):
            how = zipfile.ZIP_STORED if rel in STORED else zipfile.ZIP_DEFLATED
            zi = zipfile.ZipInfo(rel, date_time=(2026, 11, 12, 0, 0, 0))
            zi.compress_type = how
            zi.external_attr = 0o644 << 16
            with open(d / rel, 'rb') as src, z.open(zi, 'w', force_zip64=True) as dst:
                while b := src.read(1 << 24):
                    dst.write(b)
    with zipfile.ZipFile(tmp) as z:
        names = {i.filename: i.file_size for i in z.infolist()}
    if names != {rel: (d / rel).stat().st_size for rel in ALLOWED}:
        sys.exit('zip does not hold exactly the set')
    os.replace(tmp, out)

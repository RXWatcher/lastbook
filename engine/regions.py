"""The regions Lastbook has a detailed map for: US states, and countries such as the Netherlands.

engine/regions.json lists them. Each entry says what the region is called, how its addresses are written, which units its
map uses and, for regions outside the US, its box, credits and the datasets its map is built from. Setup, address search,
the map's info and the build tools read it, so a new region is one entry here plus its data, not a change to each of them.
"""
import json
import re
from pathlib import Path

# A US state code (CA), a country (ISO 3166-1 alpha-2: NL), or a subdivision elsewhere (ISO 3166-2: DE-BY, never bare DE,
# which is Delaware).
REGION_ID = re.compile(r'^[A-Z]{2}(-[A-Z0-9]{1,3})?$')

_REGIONS = json.loads((Path(__file__).with_name('regions.json')).read_text(encoding='utf-8'))['regions']
_BY_ID = {r['id']: r for r in _REGIONS}


def all_regions():
    return [dict(r) for r in _REGIONS]


def get(region_id):
    r = _BY_ID.get(region_id) if isinstance(region_id, str) else None
    return dict(r) if r else None


def us_states():
    return [dict(r) for r in _REGIONS if r['country'] == 'US']


def installed_region(data_dir):
    """The region of the detailed map in this data folder: map-set.json's name when there is one, else pack.json's map. None for
    the base map, the whole-US set, or anything unreadable."""
    data_dir = Path(data_dir)
    for name, key in (('map-set.json', 'name'), ('pack.json', 'map')):
        path = data_dir / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding='utf-8')).get(key)
        except (OSError, ValueError, AttributeError):
            return None
        return get(value)
    return None

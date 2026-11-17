# Netherlands Region Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working Netherlands version of Lastbook: the app learns about regions, and a Netherlands map set (streets, help
points, buildings, elevation, water, crops, place finder) with Dutch postcode/street address search installs from a local
zip.

**Architecture:** A region registry (`engine/regions.json` + `engine/regions.py`) replaces the "US state" assumption in
setup, address search, the server's map info and the map screen. Build tools turn Dutch open data (OSM PBF, BAG, AHN, BRP,
BRK) into the existing map-set file formats under `derived/geo-nl/`; a region packager assembles the eleven-file map set,
zips it with its address index, and writes manifest entries marked `local_only`, which setup installs from a file on disk.

**Tech Stack:** Python 3.11 (engine, tools), plain JS (web/), SQLite/FTS5/R*Tree. Build-only Python packages: numpy,
tifffile, pyproj, osmium (pyosmium), Pillow, pyshp.

**Spec:** `docs/superpowers/specs/2026-11-17-netherlands-region-design.md`

## Global Constraints

- The app opens no network connection; nothing is added to `ALLOWED_HOSTS` or `LIBRARY_HOSTS`. Network use is allowed only in build tools under `tools/` and `packaging/`.
- US behaviour is unchanged: the full existing suite passes unchanged (command in Task 0), and US wording/units stay as they are.
- Region ids: US states keep bare two-letter codes; countries use ISO 3166-1 alpha-2 (`NL`); subdivisions elsewhere `XX-YYY`. Pattern: `^[A-Z]{2}(-[A-Z0-9]{1,3})?$`.
- No source under a licence other than ODbL (OSM) or CC0/public domain is shipped. Not the CC BY-SA waterschap-keringen file.
- Everything user-facing stays in English.
- NL attribution line, verbatim: `© OpenStreetMap contributors · Kadaster BAG · AHN · RVO BRP · Natural Earth`.
- Build inputs go in `derived/sources/nl/`, builder outputs in `derived/geo-nl/`, packaged output in `derived/packs/` (all gitignored).
- Tool files carry the header the other tools have: usage line, what they read, what they write, source licence.
- The Netherlands box is `[3.2, 50.7, 7.3, 53.7]` (W, S, E, N).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on branch `netherlands`.

## Review Focus

1. **Amsterdam-style additions** (`Prinsengracht 263-1`, `Keizersgracht 2-III`, `2 hs`): Roman numerals I–IV in a typed addition match a stored `1`–`4` when nothing matches exactly. Test: `test_roman_addition` (Task 3).
2. **Both US and NL address indexes installed**: a US query (`1600 Pennsylvania Ave`) still finds the US address, and a Dutch query never searches the US `addr` table. Test: `test_us_query_with_nl_index_installed` (Task 3).
3. **Common names that differ from BAG's official ones**: `Den Haag` (BAG: `'s-Gravenhage`) and `Den Bosch` (BAG: `'s-Hertogenbosch`) are found by the place finder and accepted as the city in an address. Tests: `test_city_alias` (Task 3), `test_aliases_present` (Task 6).
4. **Gaps in AHN's terrain model** (buildings and water are no-data in a DTM): they are filled from their neighbours, so polders don't show fake sea-level holes, and land below sea level shows as negative metres. Tests: `test_fill_gaps` (Task 8), and the metric `fmtElev` check in Task 12.
5. **The Netherlands chosen in setup without its zip on disk** (or with a wrong one): setup says where to put the file and never tries to download from `downloads.lastbook.org`. Test: `test_local_only_map_without_file` (Task 2).

---

### Task 0: Environment and baseline

**Files:**
- Create: `tools/requirements-build-nl.txt`

- [ ] **Step 1: Make the app venv and record the baseline.**
  Run: `~/.local/bin/python3.11 -m venv .venv && .venv/bin/pip install -r packaging/requirements_macos.txt`
  Then: `.venv/bin/python -B -m unittest app.tests.test_bridge app.tests.test_setup app.tests.test_data_folder app.tests.test_what_ships app.tests.test_update app.tests.test_address_search app.tests.test_topic_search app.tests.test_chat_steps app.tests.test_validate_topics app.tests.test_libq app.tests.test_shell_macos 2>&1 | tail -5`
  Expected: `OK` (possibly with skips). Write the result line into the commit message of Step 3. If anything fails on a clean checkout, record which tests fail. Later tasks must not add failures.
- [ ] **Step 2: Make the build venv.** `tools/requirements-build-nl.txt` pins `numpy`, `tifffile`, `pyproj`, `osmium`, `Pillow` and `pyshp` to current releases. Run: `~/.local/bin/python3.11 -m venv derived/buildenv && derived/buildenv/bin/pip install -r tools/requirements-build-nl.txt && derived/buildenv/bin/python -c "import osmium, pyproj, PIL, shapefile, tifffile, numpy; print('ok')"`. Expected: `ok`.
- [ ] **Step 3: Commit** `tools/requirements-build-nl.txt` with the message "Build tools for the Netherlands: requirements".

### Task 1: Region registry

**Files:**
- Create: `engine/regions.json`, `engine/regions.py`, `app/tests/test_regions.py`
- Modify: `engine/address_search.py:17-27` (STATE_NAMES/STATE_CODES come from the registry, same values and order)

**Interfaces:**
- Produces:
  - `regions.REGION_ID: re.Pattern`, `^[A-Z]{2}(-[A-Z0-9]{1,3})?$`.
  - `regions.all_regions() -> list[dict]`, in the file's order.
  - `regions.get(region_id: str) -> dict | None`.
  - `regions.us_states() -> list[dict]`: entries with `country == 'US'`, in the order of today's `STATE_CODES`.
  - `regions.installed_region(data_dir: Path) -> dict | None`: reads `data_dir/map-set.json` `name`, else `data_dir/pack.json` `map`, then `get()`. Returns `None` for `base`, `us`, a missing file, bad JSON or an unknown id.
  - Entry fields:
    - `id`, `name`, `kind` (`state` or `country`), `country` (`US` or `NL`).
    - `address_style` (`us` or `nl`), `units` (`imperial` or `metric`).
    - `box` (`[W,S,E,N]` or `null`).
    - `attribution` (`str` or `null`), `search_hint`, `place_hint`.
    - `datasets` (`list[{label, status}]` or `null`).
  - US entries have `box`, `attribution` and `datasets` all `null`. Their `search_hint` is `Find an address, town or ZIP`, and their `place_hint` is `Try a town, county or 5-digit ZIP.`
  - The NL entry:
    - `name`: `Netherlands`; `kind`: `country`; `units`: `metric`; `box`: `[3.2, 50.7, 7.3, 53.7]`.
    - `attribution`: the Global Constraints line.
    - `search_hint`: `Find an address, postcode or town`.
    - `place_hint`: `Try a town, municipality or postcode (1234 AB).`
    - `datasets`: the six NL lines in Task 11, Step 3.

- [ ] **Step 1: Write the failing tests** in `app/tests/test_regions.py`:
  - `test_us_states_match_address_search`: `[r['id'] for r in regions.us_states()] == address_search.STATE_CODES`, and the names match `STATE_NAMES` in order. Both lists have 52 entries, including DC and PR.
  - `test_nl_entry`: `get('NL')` has `kind == 'country'`, `units == 'metric'`, `address_style == 'nl'` and `box == [3.2, 50.7, 7.3, 53.7]`.
  - `test_region_id_pattern`: matches `NL`, `CA` and `DE-BY`. Rejects `nl`, `NLD`, `../NL` and `DE-`.
  - `test_installed_region`: in a temp dir, `map-set.json {"name":"NL"}` gives the NL entry, and `{"name":"base"}` gives `None`. With no `map-set.json`, a `pack.json {"map":"CA"}` gives the California entry. Bad JSON gives `None`.
- [ ] **Step 2: Run** `.venv/bin/python -B -m unittest app.tests.test_regions -v`. Expected: FAIL (`No module named 'engine.regions'`).
- [ ] **Step 3: Implement** `engine/regions.json` (52 US entries generated once from the current lists, plus NL) and `engine/regions.py` (loads the JSON once at import from the module's own folder). Then change `address_search.STATE_NAMES` and `STATE_CODES` to be built from `regions.us_states()`.
- [ ] **Step 4: Run** the new tests plus `app.tests.test_address_search`. Expected: PASS.
- [ ] **Step 5: Commit** with the message "Engine: a region registry, with the US states and the Netherlands".

### Task 2: Setup accepts region ids and local-only entries

**Files:**
- Modify:
  - `engine/setup/manifest.py:72-87` (the address-index id check uses `regions.REGION_ID`; keep `local_only: bool` on `maps` and `address_indexes` entries)
  - `engine/setup/install.py:267` (carry-over regex `[A-Z]{2}(-[A-Z0-9]{1,3})?\.(sqlite|json)`)
  - `engine/setup/api.py:450-461` and `_get_file` (local-only rules, and the wording by kind)
- Test: `app/tests/test_setup.py` (new class `RegionMaps(Maps)`, after `AddressIndexes`)

**Interfaces:**
- Consumes: `regions.REGION_ID`.
- Produces:
  - Manifest entries may carry `"local_only": true`, and `validate()` keeps it.
  - `Setup.start` returns `{'error': 'Put <file name> in <folder>, then open setup again.', 'code': 'local_only'}` when a local-only map or address index is asked for and its file is not among the known sources. `<folder>` is `default_parent`.
  - `_get_file` raises `download.Failed('local_only', …)` and never downloads a local-only file.
  - Unavailable-map messages say `country’s` for an entry with `kind == 'country'`, and keep `state’s` otherwise.

- [ ] **Step 1: Write the failing tests** in `RegionMaps`, using the existing `Maps` helpers (`make_map(path, state='NL')` and the class's manifest builder). Give the NL entries `kind: 'country'` and `local_only: True`.
  - `test_manifest_keeps_local_only`: `validate()` output has `maps[0]['local_only'] is True`.
  - `test_region_address_ids`: `DE-BY` and `NL` validate; `de-by` and `../NL` make `validate()` return `None`.
  - `test_local_only_map_without_file`: `start(map_id='NL')` in manage mode with no file gives `code == 'local_only'`, the message contains `Lastbook-Map-NL.zip`, and no download was attempted (patch `download.Download` to fail the test if called).
  - `test_local_only_map_from_file`: put a valid NL map zip in `default_parent`; `found()` lists it with `kind == 'map'` and `id == 'NL'`; `use(path)` then running the job installs it, and `install.map_name(lib) == 'NL'`.
  - `test_nl_address_index_carried_over`: an installed `derived/geo/addresses/NL.sqlite` survives an upgrade, as `CA` does in the existing carry-over test.
- [ ] **Step 2: Run** `.venv/bin/python -B -m unittest app.tests.test_setup.RegionMaps -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the four changes listed under Files.
- [ ] **Step 4: Run** all of `app.tests.test_setup`. Expected: PASS, including every existing US test.
- [ ] **Step 5: Commit** with the message "Setup: region ids and maps installed from a local file".

### Task 3: Dutch address search

**Files:**
- Create: `engine/address_nl.py`, `app/tests/test_address_nl.py`
- Modify:
  - `engine/address_search.py`: add `indexes()`, and have `find_addresses` search only `us`-style indexes.
  - `server.py:1395-1397` (`places()`): add the NL step first.

**Interfaces:**
- Produces:
  - `address_nl.create_index(db: sqlite3.Connection) -> None`. Creates `nl_addr(postcode TEXT, num INTEGER, letter TEXT, addition TEXT, street TEXT, norm TEXT, city TEXT, city_norm TEXT, lat REAL, lon REAL)` and `meta(key TEXT PRIMARY KEY, value TEXT)`. The builder fills them, then calls `finish_index(db, count, source)`, which creates indexes `nl_pc(postcode, num)` and `nl_norm(norm, num)` and writes the meta keys `style='nl'`, `region='NL'`, `count`, `source` and `built`.
  - `address_nl.normalize(text: str) -> str`:
    - ASCII-folds (NFKD, drops combining marks) and lowercases.
    - Turns `'` and other punctuation into spaces and collapses whitespace.
    - Maps whole words: `str`→`straat`, `ln`→`laan`, `pl`→`plein`, `st`→`sint`.
    - Rewrites a trailing `str` on a word to `straat` (`kerkstr` → `kerkstraat`).
    - The builder uses it for `norm` and `city_norm`.
  - `address_nl.CITY_ALIASES = {'den haag': 's gravenhage', 'den bosch': 's hertogenbosch'}`, applied after `normalize`.
  - `address_nl.parse(query: str) -> dict | None`. Keys: `postcode` (`'1012AB'` or `''`), `number` (`int` or `None`), `suffix` (lowercase letters and digits of the letter plus addition, e.g. `'a'`, `'2'`, `'hs'`, `'iii'`, or `''`), `street` (normalized or `''`) and `city` (normalized, aliased or `''`). Returns `None` unless the query is either:
    - postcode-first: `1012 AB`, `1012ab 12`, `1012AB12-A`; or
    - street-first: `Damrak 1`, `Damrak 1-A Amsterdam`, `Damrak 1, 1012 LG Amsterdam`.
  - `address_nl.find(query: str, paths: list[Path], limit: int = 8, near: tuple | None = None) -> list[dict]`.
    - **Suffix matching.** A row's suffix is the lowercase alphanumeric `letter + addition`. Rows whose suffix equals the query suffix come first. If the query suffix is empty, all suffixes are returned, the bare number first. If there is no exact match and the suffix is a Roman numeral `i` to `iv`, match `1` to `4`. Otherwise return no rows; never guess a house.
    - **Address result:** `{'name': '<street> <num><letter>[-<addition>]', 'kind': 'Address', 'detail': '<1012 AB> <city>', 'lat', 'lon', 'source': 'Kadaster BAG', 'onMap': True}`.
    - **Bare postcode:** one result per street in that postcode: `{'name': street, 'kind': 'Postcode', 'detail': '1012 AB <city> · numbers <min>–<max>', …}`, at the mean position.
    - **Sorting:** by distance to `near` when it is given.
  - `address_search.indexes(geo_directory: Path, style: str) -> list[Path]`: installed `addresses/*.sqlite` files whose `meta.style` equals `style`. A missing `style` key counts as `'us'`. Cached by `(path, mtime)`.
  - `server.places(q, …)`:
    - If `address_nl.parse(q)` succeeds and NL indexes exist, run `address_nl.find`. Return its hits if there are any.
    - If it finds nothing and no `us` index exists, skip the US address step and go on to the place finder.
    - Otherwise the existing code runs unchanged.

- [ ] **Step 1: Write the failing tests** in `app/tests/test_address_nl.py`. A fixture builds a temp `addresses/NL.sqlite` with `create_index` and `finish_index` and these rows:
  - Damrak 1, 1012LG, Amsterdam
  - Damrak 1A, 1012LG, Amsterdam
  - Prinsengracht 263-1, 1016GV, Amsterdam
  - Keizersgracht 2-3, 1015CR, Amsterdam
  - Lange Voorhout 34, 2514EE, 's-Gravenhage
  - Kerkstraat 5, 3511AA, Utrecht

  It also builds a US `addresses/CA.sqlite` with the existing schema and one row, `1600 Pennsylvania Ave`.

  Tests:
  - `test_parse_postcode_forms`: `1012 AB`, `1012ab 12`, `1012AB12-A` and `1012 ab 12 a` parse to the expected dicts.
  - `test_parse_rejects_us`: `parse('1600 Pennsylvania Ave') is None` and `parse('48375') is None`.
  - `test_postcode_and_number`: `find('1012 LG 1')` gives `Damrak 1` first, and `Damrak 1A` also appears.
  - `test_suffix_exact`: `find('1012lg 1a')` gives exactly `Damrak 1A`.
  - `test_roman_addition`: `find('Keizersgracht 2-III')` gives `Keizersgracht 2-3`.
  - `test_street_first_with_city`: `find('Damrak 1 Amsterdam')` gives `Damrak 1` first.
  - `test_abbreviation`: `find('Kerkstr. 5')` gives `Kerkstraat 5`.
  - `test_city_alias`: `find('Lange Voorhout 34 Den Haag')` gives one result.
  - `test_bare_postcode`: `find('1016 GV')` gives `[{'name': 'Prinsengracht', 'kind': 'Postcode', …}]`, and its detail contains `263`.
  - `test_no_guess`: `find('Damrak 1Z')` gives `[]`.
  - `test_us_query_with_nl_index_installed`: `server.places('1600 Pennsylvania Ave')` (with `server.HERE` patched to the fixture's data dir) gives the US row; `server.places('Damrak 1')` gives the NL row.
  - `test_fallback_to_places`: with only the NL index, `server.places('1012 ZZ')` does not return `[]` early. Patch `PLACEDB` to a temp place DB holding `1012 ZZ`-free rows, so the result is the place finder's (empty list).
- [ ] **Step 2: Run** `.venv/bin/python -B -m unittest app.tests.test_address_nl -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine/address_nl.py`, `address_search.indexes()`, the `us`-only filter in `find_addresses`, and the NL step in `server.places`.
- [ ] **Step 4: Run** `app.tests.test_address_nl` and `app.tests.test_address_search`. Expected: PASS. In particular, `test_app_route_preserves_address_number` passes unchanged.
- [ ] **Step 5: Commit** with the message "Address search: Dutch postcodes and street-first addresses".

### Task 4: Shared map schema and the OSM PBF builder

**Files:**
- Create:
  - `tools/map_schema.py`: moved out of `build_map.py`, namely `Q`, `ROAD_Z`, `LANDUSE_KEEP`, `PLACE_Z`, `POI_KEEP`, `simplify`, `pack`, `bbox`, `area_z`, and new `create_map_tables(db)` (the four tables) and `class MapWriter`.
  - `tools/build_map_osm.py`.
  - `tools/tests/__init__.py`, `tools/tests/test_build_map_osm.py`.
- Modify: `tools/build_map.py`. It imports from `map_schema` and runs `main()` only under `if __name__ == '__main__'`. Its output is unchanged.

**Interfaces:**
- Produces:
  - `map_schema.MapWriter(db)`:
    - `.add(layer, cls, name, minz, parts)`: same as `build_map.add`.
    - `.poi(cls, name, lon, lat)`.
    - `.finish(meta: dict)`: creates `poi_cls` and writes `meta`.
  - `POI_KEEP` gains `defibrillator`, `assembly_point`, `huisartsenpost` and `hospital_seh`.
  - `build_map_osm.classify(tags: dict, kind: str) -> list[tuple[str, str, str | None]]`.
    - `kind` is `node`, `way` or `area`. It returns `(target, layer_or_cls, extra)` tuples, where `target` is `feat` or `poi`.
    - The classes follow Geofabrik's free-schema names, so the existing `ROAD_Z`, `LANDUSE_KEEP`, `PLACE_Z` and `map.js` styles apply:
      - **Roads:** `highway=*` value. `track` plus `tracktype=gradeN` becomes `track_gradeN`.
      - **Water:** `natural=water`, `water=*` or `landuse=reservoir` becomes layer `water`, cls the `water=` value or `water`.
      - **Wetland:** `natural=wetland` becomes layer `wet`.
      - **Land use:** `landuse`, `leisure` and `natural` values found in `LANDUSE_KEEP` become layer `land`.
      - **Protected areas:** `boundary=protected_area` and `leisure=nature_reserve` become `land/park`.
      - **Waterways:** `river`, `canal`, `stream`, `drain` and `ditch`.
      - **Rail:** `rail`, `light_rail`, `subway` and `tram`.
      - **Places:** `place=*` becomes layer `place`.
      - **Beaches:** `natural=beach` becomes layer `beach`.
      - **POIs:**
        - `amenity`, `shop`, `natural=spring` and `man_made` (`water_tower`, `water_works`) values found in `POI_KEEP`.
        - `emergency=defibrillator` becomes `defibrillator`, and `emergency=assembly_point` becomes `assembly_point`.
        - `amenity=hospital` with `emergency=yes` becomes `hospital_seh`.
        - `amenity=doctors` or `amenity=clinic` with `huisartsenpost` or a whole-word `HAP` in the name (case-insensitive) becomes `huisartsenpost`.
      - **Buildings:** nothing (they come from BAG).
  - CLI: `build_map_osm.py <pbf> <out.sqlite> [--box W,S,E,N] [--water-polygons <dir with water_polygons.shp>]`.
    - Features whose bbox misses `--box` are skipped.
    - Sea polygons from the split-4326 water polygons that touch the box are added as layer `ocean`, cls `ocean`, minz 0.
    - `meta` gets `source = OpenStreetMap contributors, via Geofabrik netherlands-latest.osm.pbf (ODbL 1.0)`, plus `data_as_of` (the PBF header timestamp), `bounds` and `built`.

- [ ] **Step 1: Write the failing tests** in `tools/tests/test_build_map_osm.py`:
  - `test_classify_roads`: `{'highway':'track','tracktype':'grade2'}` gives `[('feat','road','track_grade2')]`.
  - `test_classify_help_points`: covers `emergency=defibrillator`, `amenity=hospital,emergency=yes` becoming `hospital_seh`, `amenity=doctors,name='Huisartsenpost Utrecht'` becoming `huisartsenpost`, and `name='Haptonomie'` *not* becoming `huisartsenpost`.
  - `test_classify_skips_buildings`: `{'building':'yes'}` gives `[]`.
  - `test_build_map_unchanged`: `map_schema.pack` round-trips through `server.unpack` for a two-part geometry.
- [ ] **Step 2: Run** `derived/buildenv/bin/python -B -m unittest tools.tests.test_build_map_osm -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `map_schema.py`, the `build_map.py` import change, and `build_map_osm.py`. The latter uses an `osmium.SimpleHandler` with `node`, `way` and `area` callbacks and `apply_file(pbf, locations=True)`, geometry through `osmium.geom.WKBFactory` parsed with `wkb_parts` (move `wkb_parts` and `gpkg_parts` from `build_map.py` to `map_schema`; later tasks read GeoPackages with `map_schema.gpkg_parts`), and `pyshp` for the water polygons.
- [ ] **Step 4: Run** the tests again. Expected: PASS.
- [ ] **Step 5: Download the sources and run on one city.**
  - Fetch `https://download.geofabrik.de/europe/netherlands-latest.osm.pbf` and `https://osmdata.openstreetmap.de/download/water-polygons-split-4326.zip` into `derived/sources/nl/`, and unzip the latter there.
  - Run `derived/buildenv/bin/python tools/build_map_osm.py derived/sources/nl/netherlands-latest.osm.pbf derived/geo-nl/clip/national.sqlite --box 5.05,52.05,5.17,52.12 --water-polygons derived/sources/nl/water-polygons-split-4326`.
  - Expected: the file exists, `SELECT count(*) FROM poi WHERE cls='defibrillator'` > 0 and `SELECT count(*) FROM feat WHERE layer='road'` > 1000.
- [ ] **Step 6: Commit** with the message "Map tools: shared schema, and a street map builder from an OSM PBF".

### Task 5: Water (named lakes) for a region

**Files:**
- Modify: `tools/build_water.py`. Add `--geo DIR` (default `derived/geo`), used for `DB` and the `osm` mode's sources.

- [ ] **Step 1: Run on the clip** with `derived/buildenv/bin/python tools/build_water.py --geo derived/geo-nl/clip osm && … index`. Expected: `water.sqlite` exists with tables `resource`, `spatial`, `feat`, `feat_idx`, `meta` and `water_fts`, and `SELECT count(*) FROM resource` ≥ 0 without error.
- [ ] **Step 2: Check the US default is unchanged.** `python3 tools/build_water.py --help` shows the default `derived/geo`.
- [ ] **Step 3: Commit** with the message "Water tool: build into another folder".

### Task 6: Place finder for the Netherlands

**Files:**
- Create: `tools/build_places_nl.py`, `tools/tests/test_build_places_nl.py`

**Interfaces:**
- Consumes:
  - `derived/geo-nl/national.sqlite` (Task 4).
  - The BAG GeoPackage `derived/sources/nl/bag-light.gpkg` (downloaded in Task 7, Step 0).
  - The BRK boundaries GeoPackage in `derived/sources/nl/`. Find the current file in the PDOK feed `https://service.pdok.nl/kadaster/brk-bestuurlijke-grenzen/atom/bestuurlijke_grenzen.xml`.
- Produces: `places.sqlite` with the existing schema (`place`, `place_fts`).
  - OSM `place` features: rank 1, source `OpenStreetMap`, detail `Netherlands (OpenStreetMap)`.
  - Named OSM POIs: rank 4.
  - BAG woonplaatsen: kind `town or village`, rank 3, detail `<municipality>, <province>`, source `Kadaster BAG`.
  - Municipalities: kind `municipality`, rank 2, detail the province.
  - Provinces: kind `province`, rank 2, detail `Netherlands`.
  - Alias rows: `Den Haag` for `'s-Gravenhage` and `Den Bosch` for `'s-Hertogenbosch`, same position, detail `also called <official>`.
  - `build_places_nl.centroid(parts) -> (lat, lon)`, the area-weighted centroid of ring parts.

- [ ] **Step 1: Write the failing tests**:
  - `test_aliases_present`: the alias rows exist in a database built from a tiny fixture with one woonplaats, `'s-Gravenhage`.
  - `test_centroid_square`: a unit-square centroid is `(0.5, 0.5)`.
- [ ] **Step 2: Run** `derived/buildenv/bin/python -B -m unittest tools.tests.test_build_places_nl -v`. Expected: FAIL.
- [ ] **Step 3: Inspect the inputs.** Run `sqlite3 <gpkg> "SELECT table_name FROM gpkg_contents"` and `PRAGMA table_info` on the woonplaats, gemeente and provincie tables. Write the table and column names found into the tool header.
- [ ] **Step 4: Implement.** GeoPackage geometry is read with `map_schema.gpkg_parts` (moved there in Task 4) and transformed from EPSG:28992 with `pyproj.Transformer.from_crs(28992, 4326, always_xy=True)`.
- [ ] **Step 5: Run the tests.** Expected: PASS.
- [ ] **Step 6: Commit** with the message "Place finder for the Netherlands".

### Task 7: BAG buildings and the address index

**Files:**
- Create: `tools/build_bag.py`, `tools/tests/test_build_bag.py`

**Interfaces:**
- Consumes:
  - `address_nl.create_index`, `finish_index` and `normalize`.
  - `build_buildings.REACH` and `WORLD`.
  - `map_schema.gpkg_parts`.
- Produces:
  - `build_bag.encode_building(ring_lonlat: list[tuple[float, float]], height_dm: int) -> tuple[array, set[tuple[int, int]]]`. Returns the record and the z14 bucket keys, with exactly `build_buildings.convert`'s encoding and bucket rule.
  - CLI: `build_bag.py <bag-light.gpkg> <out dir> [--box W,S,E,N]`. It writes:
    - `<out>/buildings.sqlite`: tables `bldg`, plus empty `bldg_socal` and `bldg_osm` with the same schema, and `meta` (`buildings`, `built`, and `source = Kadaster BAG (CC0 1.0)`).
    - `<out>/addresses/NL.sqlite`.
  - Buildings are kept only when the pand status is "in use" (in use, not measured in, under renovation). Height is 0.
  - Addresses come from verblijfsobject, ligplaats and standplaats rows whose status is in use. One row per nummeraanduiding, including secondary addresses if the GeoPackage has them.

- [ ] **Step 0: Download** `https://service.pdok.nl/kadaster/bag/atom/downloads/bag-light.gpkg` (7.8 GB) to `derived/sources/nl/`. Inspect `gpkg_contents` and the relevant `PRAGMA table_info`, and write the table, column and status values found into the tool header.
- [ ] **Step 1: Write the failing tests**:
  - `test_encode_matches_build_buildings`: for a fixture ring, the bytes equal those `build_buildings.convert` produces from the same ring in a one-line `.csv.gz` (`socal_only=False`, with `SOCAL` empty).
  - `test_address_rows`: a three-row fixture GeoPackage-shaped SQLite file in the inspected schema gives `NL.sqlite` rows with `postcode='1012LG'`, `num=1` and `letter='A'`.
- [ ] **Step 2: Run** `derived/buildenv/bin/python -B -m unittest tools.tests.test_build_bag -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Stream rows in batches of 100,000 and transform coordinates in batches with pyproj.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Run on the clip.** `--box 5.05,52.05,5.17,52.12` into `derived/geo-nl/clip/`. Expected: `meta.buildings` > 50,000 and `NL.sqlite` has more than 100,000 rows. `address_nl.find('Domplein 9 Utrecht', [path])` returns one result.
- [ ] **Step 6: Commit** with the message "BAG builder: building outlines and Dutch addresses".

### Task 8: Elevation from AHN

**Files:**
- Create: `tools/fetch_ahn.py`, `tools/tests/test_fetch_ahn.py`
- Modify: `tools/build_terrain.py`. Add `--src DIR`, `--out FILE` and `--source-label TEXT`, with the current defaults.

**Interfaces:**
- Produces:
  - `fetch_ahn.fill_gaps(h: np.ndarray, passes: int = 64) -> np.ndarray`. Replaces NaN cells next to valid cells with the mean of their valid 8-neighbours, repeated up to `passes` times. NaN left beyond that stays NaN.
  - `fetch_ahn.cell_name(top: int, left: int) -> str`, e.g. `(53, 5)` gives `'n53e005'`, the name `build_terrain.cells()` parses.
  - CLI: `fetch_ahn.py <out dir> [--box W,S,E,N]`. For each 1° cell touching the box it writes `<out>/<cell>/<cell>.tif`:
    - float32 at 1 arc-second;
    - `ModelTiepointTag (0,0,0,left,top,0)` and `ModelPixelScaleTag (1/3600,1/3600,0)`;
    - values below -1000 stand for no data.
  - The source is PDOK's AHN WCS (`https://service.pdok.nl/rws/ahn/wcs/v1_0`), DTM coverage, requested in EPSG:28992 at 25 m in chunks of at most 2000×2000 px. Gaps are filled, then the data is resampled bilinearly to the WGS84 grid with pyproj.

- [ ] **Step 1: Probe the WCS.** Run `curl -s 'https://service.pdok.nl/rws/ahn/wcs/v1_0?service=WCS&request=GetCapabilities&version=2.0.1' | grep -o '<wcs:CoverageId>[^<]*' ` and record the DTM coverage id. Request one 2000×2000 px chunk at 25 m around Utrecht and confirm a GeoTIFF comes back.
  - **If the WCS cannot serve it:** switch the source to the Copernicus GLO-30 1° tiles (free licence; note that it is a surface model). Write that switch into the tool header and `REGIONS-NL.md`.
- [ ] **Step 2: Write the failing tests**:
  - `test_fill_gaps`: a 5×5 array of `-3.0` with a NaN centre gives `-3.0` at the centre, and an all-NaN array stays all NaN.
  - `test_cell_name`: `cell_name(53, 5) == 'n53e005'`.
  - `test_written_tile_reads_in_build_terrain`: a 10×10 tile written by the tool's `write_cell` reads back through `build_terrain.dem` with the right tie point and scale.
- [ ] **Step 3: Run** `derived/buildenv/bin/python -B -m unittest tools.tests.test_fetch_ahn -v`. Expected: FAIL.
- [ ] **Step 4: Implement** `fetch_ahn.py` and the three `build_terrain.py` arguments.
- [ ] **Step 5: Run the tests.** Expected: PASS.
- [ ] **Step 6: Run on the clip box.** Then run `tools/build_terrain.py --src derived/sources/nl/ahn --out derived/geo-nl/clip/terrain.sqlite --bbox 5.05,52.05,5.17,52.12 --source-label "AHN4 DTM (Rijkswaterstaat, CC0 1.0), 1 arc-second" --workers 8`. Expected: tiles at z12 exist, and decoding one tile's centre pixel gives a height between -10 and 30 m.
- [ ] **Step 7: Commit** with the message "Elevation for the Netherlands from AHN".

### Task 9: Crops from BRP

**Files:**
- Create: `tools/build_crops_nl.py`, `tools/tests/test_build_crops_nl.py`

**Interfaces:**
- Consumes: `build_crops.png_rgba`, `down`, `MAXZ`, `MINZ`, `BLOCK`, `KIND`, and the existing `crops.sqlite` schema.
- Produces:
  - `build_crops_nl.crop_kind(name: str) -> tuple[str, str] | None`. Maps a BRP crop name (Dutch, lowercased) to `(english_crop, kind)` with `kind` in `orchard`, `vineyard`, `berries` or `perennial_veg`, by keyword:
    - `appel`, `peer`, `kers`, `pruim`, `walnoot`, `hazelnoot`, `noten`, `fruit` or `boomgaard` → orchard;
    - `druif` or `wijn` → vineyard;
    - `blauwe bes`, `bes`, `framboos`, `braam`, `aardbei` or `cranberry` → berries;
    - `asperge` or `rabarber` → perennial_veg;
    - anything else → None.
  - CLI: `build_crops_nl.py <brp.gpkg> <out.sqlite> [--box W,S,E,N]`.
    - Parcels are rasterized with Pillow onto a 30 m EPSG:28992 grid, then aggregated into 600 m blocks (resource rows with detail `{crop, crop_ha, perennial_ha}`) and drawn as overlay tiles z7–13.
    - Meta: `source = RVO BRP Gewaspercelen 2025 (CC0 1.0)` and `built = {"year": 2025, "cells": n}`.

- [ ] **Step 0: Download** `https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2025.gpkg` and list the distinct crop names: `SELECT DISTINCT <crop column> …`. Record any perennial crop names the keywords miss, and add them.
- [ ] **Step 1: Write the failing tests**:
  - `test_crop_kind`: `Appelen` → `('Apples', 'orchard')`, `Blauwe bessen` → berries, `Asperges` → perennial_veg, `Wintertarwe` → None.
  - `test_block_resource`: a 2×2-parcel fixture gives one resource with kind `orchard`.
- [ ] **Step 2: Run** `derived/buildenv/bin/python -B -m unittest tools.tests.test_build_crops_nl -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Run on the clip box** (or on a fruit area if the clip has none: `--box 5.2,51.85,5.5,52.0`, the Betuwe). Expected: resource count > 0 and tiles at z13.
- [ ] **Step 6: Commit** with the message "Crops for the Netherlands from BRP".

### Task 10: Region map-set packager

**Files:**
- Create:
  - `packaging/map_sets.py`: `ALLOWED`, `STORED` and `make_zip`, moved out of `state_maps.py`, which imports them.
  - `packaging/region_maps.py`.
  - `packaging/test_region_maps.py`.

**Interfaces:**
- Consumes: `map_schema.create_map_tables`, `address_nl` meta keys, `regions.get`, `manifest.validate`.
- Produces:
  - `region_maps.assemble(code: str, src: Path, dest: Path) -> dict`. Takes the builder outputs in `src` (`national`, `water`, `terrain`, `buildings`, `crops` and `places` `.sqlite`) and writes the eleven `ALLOWED` files to `dest`:
    - an empty `map.sqlite`;
    - an empty `atlas.sqlite` with `resource(id INTEGER PRIMARY KEY, source_id TEXT, kind TEXT, name TEXT, lat REAL, lon REAL, detail TEXT, source TEXT, origin TEXT)`, `spatial` R*Tree `(id,minx,maxx,miny,maxy)` and `metadata(key TEXT PRIMARY KEY, value TEXT)`;
    - `national-status.json` and `socal-cells.json` = `[]`;
    - `map-set.json {name, files, bytes, seconds}`.
    - It drops `done` tables and adds a `status` row to the national meta. It returns `map-set.json`'s content.
  - `region_maps.check(dest: Path, code: str) -> list[str]` returns a list of failures; empty means pass. It fails on:
    - files that differ from `ALLOWED`;
    - a `map-set.json` name other than `code`;
    - a non-empty `map.sqlite`;
    - `socal-cells.json` not equal to `[]`;
    - progress tables left in;
    - any `PRAGMA quick_check` other than `ok`;
    - building tiles outside the region box at z14.
  - `region_maps.package(code) -> list[dict]`. Zips with `make_zip` to `derived/packs/state-zips/Lastbook-Map-<code>.zip`, and zips `Lastbook-Addresses-<code>.zip` with the single member `derived/geo/addresses/<code>.sqlite`. It returns two manifest entries, both with `local_only: True`, `available: True`, `kind: 'country'` and URLs under `https://downloads.lastbook.org/maps/` and `/addresses/`.
  - CLI subcommands:
    - `build <code> --src DIR`: assemble, check, then package.
    - `manifest <code>`: merge the entries into `derived/release/manifest-v1.json`, creating `{"version": 1}` if it is missing.
    - `dev-manifest`: fetch `https://downloads.lastbook.org/manifest-v1.json`, add the local entries, check that `manifest.validate` accepts it, and write `derived/release/setup/manifest-v1.json`.

- [ ] **Step 1: Write the failing tests**:
  - `test_assemble_and_check`: from tiny fixture SQLite files with the right schemas, `assemble` then `check` gives `[]`, and the file set equals `ALLOWED`.
  - `test_check_catches`: a non-empty `map.sqlite` and an extra file each produce a failure.
  - `test_package_entries_validate`: the entries placed in a `{"version": 1, "maps": [...], "address_indexes": [...]}` manifest pass `manifest.validate`, and keep `local_only`.
  - `test_state_maps_still_imports_zip`: `map_sets.ALLOWED` equals the set `state_maps` used, by literal comparison with the eleven paths.
- [ ] **Step 2: Run** `.venv/bin/python -I -B packaging/test_region_maps.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Package the clip** with `build NL --src derived/geo-nl/clip`. Expected: two zips, and `check` reports nothing.
- [ ] **Step 6: Commit** with the message "Packaging: region map sets, zipped with their address index".

### Task 11: Server region awareness

**Files:**
- Modify:
  - `server.py:1045` (`HELP`) and `TILE_POI`.
  - `server.py` `map_info()` and `pack_datasets()`.
  - `server.py` `water_places()`.
  - `server.py` `places()`: kind-based `onMap`.
- Test: `app/tests/test_region_server.py`

**Interfaces:**
- Consumes: `regions.installed_region(HERE)`.
- Produces:
  - `map_info()['region'] = {'id', 'name', 'kind', 'units', 'attribution', 'search_hint', 'place_hint', 'data_as_of'}`. US and no-region libraries get `units: 'imperial'`, `attribution: null`, the US hints and `data_as_of: null`, so `map.js` keeps today's text.
  - `data_as_of` is the national meta `data_as_of`, cut to its date.
  - With an NL region, `pack_datasets()` returns the region's `datasets`.
  - `water_places()` for a metric region gives detail `Netherlands` plus distance as `· <n> km away`.
  - New `HELP` entries:
    - `hospital_seh`: `Hospital with emergency department`
    - `huisartsenpost`: `Out-of-hours GP (huisartsenpost)`
    - `defibrillator`: `Defibrillator (AED)`
    - `assembly_point`: `Emergency assembly point`
  - All four are also added to `TILE_POI`.

- [ ] **Step 1: Write the failing tests** (patch `server.HERE` to a temp data dir with `pack.json` and `map-set.json {"name":"NL"}`, and clear `server._pack` and the `map_contents` cache):
  - `test_region_in_map_info_nl`: `units == 'metric'` and the attribution equals the Global Constraints line.
  - `test_region_in_map_info_us`: with `map-set.json {"name":"CA"}`, `units == 'imperial'` and `attribution is None`.
  - `test_nl_datasets`: labels mention `Kadaster BAG` and `AHN`, and none mention `USGS`.
  - `test_help_labels`: the four new `HELP` keys are present.
- [ ] **Step 2: Run** `.venv/bin/python -B -m unittest app.tests.test_region_server -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** The six NL `datasets` lines in `regions.json` are:
  - Roads, towns, water and help points for the Netherlands (OpenStreetMap)
  - Place names (OpenStreetMap, Kadaster BAG woonplaatsen, Kadaster BRK municipalities and provinces)
  - Elevation (AHN, Rijkswaterstaat)
  - Building outlines (Kadaster BAG)
  - Orchards, fruit, berries and vineyards (RVO BRP 2025)
  - Addresses (Kadaster BAG)

  Each line's status is the short text matching the US lines.
- [ ] **Step 4: Run** the new tests and `app.tests.test_bridge` and `app.tests.test_what_ships`. Expected: PASS.
- [ ] **Step 5: Commit** with the message "Server: map info, help labels and water results follow the region".

### Task 12: Map screen follows the region

**Files:**
- Modify: `web/map.js`, `web/terrain3d.js:284`

**Interfaces:**
- Consumes: `info.region` from Task 11.
- Produces:
  - `st.region`.
  - `metric()`: true when `st.region?.units === 'metric'`.

- [ ] **Step 1: Implement**, all keyed on `metric()` or `st.region`, with US paths unchanged:
  - **`dist`:** metric gives `m` under 1 km, then `x.x km`, then `x km`.
  - **Scale bar:** metric shows km/m only.
  - **`fmtElev`:** metric gives `Math.round(m)` with a ` m` suffix, and adds ` (below sea level)` when below 0, written with a minus sign `−`.
  - **Contours:** metric uses `CONTOUR_M = [[11, 20, 100], [12, 10, 50], [13, 5, 25], [14, 2, 10], [15, 1, 5]]` in metres, with the unit factor 1 instead of 3.28084.
  - **Text:**
    - The attribution line, search label and placeholder come from `region.attribution` and `region.search_hint` when set.
    - The `map-us` button shows the region name.
    - The not-found message uses `region.place_hint`, and the address hint link text becomes `Add address search for your region`.
    - "within about 100 miles" becomes "within about 160 km" when metric.
    - The header's "Shows what was mapped by 25 Oct 2026" uses `region.data_as_of` when set.
  - **Layers:**
    - Add `['aed', 'Defibrillators (AED)', '♥', '#b71c1c', 'defibrillator', 'help']` and `['assembly', 'Emergency assembly points', 'A', '#6a1b9a', 'assembly_point', 'help']`.
    - The hospital layer classes become `hospital,hospital_seh`, and clinic becomes `clinic,doctors,huisartsenpost`.
    - `DEFAULT_LAYERS` gains `aed`. The `Emergency` preset gains `aed` and `assembly`.
  - **Crop caveat:** when metric, the `CAVEAT` for orchard, vineyard, berries and perennial_veg reads `RVO 2025 crop parcels as declared by farmers: right for the parcel, not for every tree. Private farmland — ask first.`
  - **`FIELD`:** add `crop_ha: 'Hectares of it in this ~600 m block'` and `perennial_ha: 'All tree, vine & berry hectares in block'`.
  - **Find-a-place zoom:** `/municipality/i` goes to 11, `/province/i` to 8, `/Postcode/` to 16.
  - **`terrain3d.js`:** "(ocean or outside the US)" becomes "(sea, or outside the map)" when metric. Expose `metric` through `MapView` if `terrain3d.js` needs it.
- [ ] **Step 2: Syntax check.** Run `node --check web/map.js && node --check web/terrain3d.js`. Expected: no output.
- [ ] **Step 3: Run** the full suite (Task 0 command). Expected: the same result as the baseline.
- [ ] **Step 4: Commit** with the message "Map screen: metric units, Dutch help layers and region text".

### Task 13: Setup screen offers the Netherlands

**Files:**
- Modify: `web/setup.js:91-112, 255-300, 365-366`

- [ ] **Step 1: Implement**, all only when `maps().some(m => m.kind && m.kind !== 'state')` (call it `anyCountry`), so a US-only manifest renders exactly as today:
  - **Wording:**
    - The label becomes `Choose your state or country`.
    - The placeholder becomes `Select a state or country`.
    - The hint becomes `Select your state or country to continue.`
    - The button becomes `Choose your state or country to continue`.
    - The lead becomes `Choose your state or country and library.`
    - The manage row becomes `Choose state or country`.
  - **Option groups:** `<optgroup label="Countries">` holds the country entries and `<optgroup label="United States">` the states.
  - **`local_only` entries:**
    - The option says `<title> — from a file on this computer`.
    - When it is selected and `foundFor('map', id)` is empty, the hint says `Put Lastbook-Map-<id>.zip (and Lastbook-Addresses-<id>.zip for address search) in <folder shown in the folder row>, then reopen setup.` and the start button is disabled.
    - When found, the sizes count no download.
  - **Errors:** the `local_only` error code shows its message through the existing error view (add `local_only` to the error-title table with the title `File needed`).
- [ ] **Step 2: Syntax check.** Run `node --check web/setup.js`. Expected: no output.
- [ ] **Step 3: Run** `app.tests.test_setup`. Expected: PASS.
- [ ] **Step 4: Commit** with the message "Setup screen: offer countries, and maps from a local file".

### Task 14: Full Netherlands build and end-to-end check

**Files:** none committed except tool fixes found along the way, each in its own commit.

- [ ] **Step 1: Build the whole country** with `--box 3.2,50.7,7.3,53.7` into `derived/geo-nl/`, in this order:
  - `build_map_osm.py` → `national.sqlite`;
  - `build_water.py --geo derived/geo-nl osm` then `index`;
  - `build_bag.py` → `buildings.sqlite`, `addresses/NL.sqlite`;
  - `build_places_nl.py` → `places.sqlite`;
  - `fetch_ahn.py` and `build_terrain.py` → `terrain.sqlite`;
  - `build_crops_nl.py` → `crops.sqlite`.

  Long steps run in the background. Record each step's row counts and duration for `REGIONS-NL.md`.
- [ ] **Step 2: Package.** Run `.venv/bin/python packaging/region_maps.py build NL --src derived/geo-nl`, then `manifest NL`, then `dev-manifest`. Expected: `check` is empty, and both zips and `derived/release/setup/manifest-v1.json` exist.
- [ ] **Step 3: Install through setup.**
  - Copy both zips into the default parent folder setup shows.
  - Run `.venv/bin/python app/main.py --data /tmp/lastbook-nl/LastbookData` (a fresh, empty folder).
  - In setup, choose Small, and choose Netherlands from the "Countries" group. Use the found zips.
  - Expected: the Small pack downloads from lastbook.org, the NL map installs from the file, and the library opens.
- [ ] **Step 4: Check the Map screen.** Every item must hold; record a failure as a bug and fix it with a test in the owning task's files:
  - The map opens on the Netherlands.
  - Streets, buildings, relief, contours in metres, crop overlay, AEDs, hospitals with emergency departments and supermarkets show.
  - Each search lands on the right building or town: `1012 LG 1`, `Damrak 1`, `Keizersgracht 2-III`, `Den Haag`, `Utrecht`.
  - Distances read in km/m, and the attribution line is the NL one.
  - A Polder spot (e.g. Zuidplaspolder) shows elevation below sea level.
- [ ] **Step 5: Take screenshots** of the Map screen in light and dark mode and save them under `derived/screenshots/`.
- [ ] **Step 6: Run** the full suite (Task 0 command) plus `tools.tests` (build venv) and `packaging/test_region_maps.py`. Expected: all pass.

### Task 15: Docs

**Files:**
- Create: `docs/REGIONS-NL.md`, `docs/regions-nl-proposed.json`
- Modify: `docs/MAPS.md` (add the NL line to the proposals list), `README.md` (a short "Netherlands" section: what it is, how to build the map set with the commands from Task 14, and how to install it from the zip)

- [ ] **Step 1: Write `REGIONS-NL.md`** in the shape of `REGIONS-DE.md`. It covers:
  - what a region is (one, the whole country) and its code;
  - the box;
  - sources layer by layer, with the opened / search only / not checked marks from the research, and the actual sizes and counts from Task 14;
  - help points, including the known gap that OSM has 48 huisartsenposten against about 115;
  - licence notes and attribution;
  - how addresses are written;
  - what is still undecided: flood layers, the Dutch guides and documents, 3D BAG heights, hosting.

  `regions-nl-proposed.json` carries the same data in the shape of `regions-de-proposed.json`.
- [ ] **Step 2: Check** that every source URL in the docs matches the one the tools use: `grep -o 'https://[^ )>"]*' docs/REGIONS-NL.md tools/*nl*.py tools/build_bag.py tools/fetch_ahn.py | sort -u`.
- [ ] **Step 3: Commit** with the message "Docs: the Netherlands region, sources and how to build it".

# Lastbook for the Netherlands: design

Date: 2026-11-17. Fork: `RXWatcher/lastbook`, branch `netherlands`.

## Intent

Lastbook only knows the United States: detailed maps come one US state at a time, from US federal data, and setup,
address search and the place finder all assume US states. There is no Dutch version, and there should be one. This
work makes a working Netherlands version: a person in the Netherlands installs Lastbook, picks "Netherlands" in setup,
and gets an offline map of their country with Dutch help points and Dutch address search. Everything stays in English.

It is built so it can go upstream later: the app learns the general idea of a *region* (a US state is one kind, a
country is another), and the Netherlands is the first non-US region. That also answers upstream issue #23 ("it
shouldn't be US-centric") for future countries.

## Goals

1. **A region registry.** One table of regions that the engine, setup screen and build tools all read: id, name,
   kind (state, country), map box, address style, units, attribution. US states keep working exactly as now.
2. **A Netherlands map set** (`Lastbook-Map-NL.zip`), the same file layout as a US state map, holding:
   - streets, land use, water shapes and place names (OpenStreetMap);
   - help points (OpenStreetMap): hospitals (marking those with an emergency department), GPs and out-of-hours GP posts
     (huisartsenposten), pharmacies, fire stations, police, defibrillators (AEDs), drinking water, emergency assembly
     points, shelters, supermarkets, fuel;
   - building outlines (BAG);
   - elevation shading and contours (AHN), which in the Netherlands shows what lies below sea level;
   - water bodies (OpenStreetMap, through the existing `build_water.py osm` mode);
   - crop fields that keep producing food: orchards, fruit, berries, vineyards (BRP Gewaspercelen);
   - a place finder for woonplaatsen (towns and villages), municipalities and provinces (BAG, BRK/CBS boundaries, OSM).
3. **Dutch address search** (`NL.sqlite` address index from BAG, about 10 million addresses). It understands how
   Dutch addresses are written and looked up:
   - postcode + house number: `1012 AB 12`, `1012AB 12-A`, `1012ab12a`;
   - a bare postcode, `1012 AB`, which shows that postcode's street;
   - street first: `Damrak 1`, `Damrak 1 Amsterdam`, `Damrak 1, 1012 LG Amsterdam`;
   - house number additions written any common way (`12A`, `12-A`, `12 a`, `12-2`, `12 hs`, `12 bis`).
4. **Region-aware app.** For a non-US region, the Map, search and setup screens use the region's words and units:
   "Choose your region", "Find an address, town or postcode", kilometres and metres (contours in metres), the
   region's attribution line, and an opening view on the region. US screens keep their wording and miles/feet.
5. **Installs offline from a local zip.** A person can put `Lastbook-Map-NL.zip` next to the app (or in the data
   folder's parent) and setup finds, checks and installs it, with no download from us. The library pack itself still
   comes from `downloads.lastbook.org` as today.
6. **A proposal document**, `docs/REGIONS-NL.md` and `docs/regions-nl-proposed.json`, in the same shape as the
   existing country proposals (DE, TH, AR, LK), with every source, licence and the "opened / search only / not checked"
   marks, so an upstream PR comes with the discussion they ask for.

## Non-goals (this round)

- Dutch survival guides and Dutch documents in the library (Denk vooruit, NL-Alert, Rode Kruis, overstroomik.nl).
  Next round: Denk vooruit's English PDFs are CC0 for text and can go into a library add-on pack, with guides pointing
  at their pages.
- Flood-risk layers (primary flood defences, flood depth maps). The open sources exist (NBPW, IPO
  overstromingsrisicokaarten, both public domain/CC0) but each needs new map layer kinds. Next round.
- Building heights (3D BAG, CC BY 4.0) and the 3D view for the Netherlands.
- Splitting the Netherlands into provinces; hosting downloads; signed release builds; the iPad app; a Dutch-language
  interface.
- Official supplementary help-point lists (RIVM emergency departments, huisartsenpost directories): OSM's 79 hospitals
  with `emergency=yes` already match RIVM's count of 79; huisartsenposten are thin in OSM (48 of ~115) and are noted as a
  known gap.

## Anti-goals (would make it a failure even if it runs)

- **The app opens a network connection** for the Netherlands, ever. All data comes in through build tools and ships as
  files. Nothing is added to `ALLOWED_HOSTS`.
- **US behaviour changes.** Every existing test still passes unchanged, a US state map built before this change still
  installs and works, and US address queries give the same results.
- **Data under a licence we cannot ship**: no share-alike sources besides OSM's ODbL (so not the CC BY-SA
  waterschap-keringen file), nothing "free for non-commercial use", no scraped directories.
- **Detecting where the person is.** The person chooses the region, as now.

## Constraints from the existing code

- **Map set layout is fixed** (`packaging/state_maps.py` `ALLOWED`, `engine/setup/install.py` `map_member`): seven
  `derived/geo/*.sqlite` files, `national-status.json`, `socal-cells.json` (`[]`), `atlas.sqlite` and `map-set.json`.
  A Netherlands set ships all of them; `map.sqlite` and `atlas.sqlite` are present with the schema and no rows.
- **Formats to produce** (all read by `server.py` as is):
  - `national.sqlite`: `feat`/`feat_idx`/`poi`/`meta`, geometry packed as in `tools/build_map.py` `pack()`.
  - `terrain.sqlite`: 256-px Web Mercator terrain-RGB PNG tiles, z4–12 (negative heights encode fine).
  - `buildings.sqlite`: z14 buckets of zlib int32 records (`tools/build_buildings.py`).
  - `crops.sqlite`, `water.sqlite`, `places.sqlite` as their existing builders write them.
- **No tool here builds `national.sqlite`**, and `tools/build_map.py` expects a Geofabrik "free" GeoPackage, which
  Geofabrik does not publish for the Netherlands (only `.osm.pbf`). A new builder reads the PBF directly.
- **Setup only accepts a local zip that the bundled manifest lists** with the right size and SHA-256
  (`engine/setup/api.py` `found()`/`use()`). So the build writes the Netherlands entries into the bundled
  `setup/manifest-v1.json` (map and address index), and the app built from the fork knows the zip.
- **Map entry URLs must be on `downloads.lastbook.org`** (`manifest.py`). The Netherlands entries carry a URL there
  (the name it would have if upstream hosted it) and are marked so setup only offers them when the file is found
  locally, never tries to download them. How to mark that is the builder's call (e.g. `"available": false` plus a
  found-locally override, or a `"local_only": true` field).
- **Region ids**: US states keep their bare two-letter codes. Countries use their ISO 3166-1 alpha-2 code (`NL`);
  subdivisions elsewhere would use ISO 3166-2 with a hyphen (`DE-BY`, avoiding Delaware). The hardcoded `[A-Z]{2}`
  patterns (`manifest.py`, `install.py`, `build_packs.py`) accept the hyphenated form too. `NL` is not a US code.
- **Address search is US-shaped** (`engine/address_search.py`): it only treats number-first text as an address, and
  a Dutch postcode currently returns nothing and blocks the place finder. Address parsing becomes per address style
  (`us`, `nl`), chosen by the installed index's region, and a query that finds no address falls back to the place
  finder.
- `build_addresses.py`'s normalisation must match `address_search.py`'s; the same holds for the new Dutch style.

## Approaches considered

- **A. Teach the app about regions, add the Netherlands as the first non-US one.** (Chosen.) Most up-front
  work; the only one upstream could accept; the US keeps working.
- B. Replace the US with the Netherlands throughout. Quicker, but loses the US, diverges from upstream, cannot be PR'd.
- C. Data only: a Netherlands zip posing as a "state" `NL`, plus a postcode rule. Fastest to run, but setup still says
  "Choose your state", and the workarounds block a clean PR.

## Sources (researched 2026-11-17)

| Layer | Source | Licence | Size, format |
|---|---|---|---|
| Streets, land, water, places, help points | Geofabrik `netherlands-latest.osm.pbf` | ODbL 1.0 | 1.3 GB PBF |
| Sea and coast | OSM coastline water polygons (osmdata.openstreetmap.de), clipped to the box | ODbL 1.0 | ~1 GB |
| Buildings, addresses, woonplaatsen | PDOK `bag-light.gpkg` (Kadaster) | CC0 1.0 | 7.8 GB GeoPackage, EPSG:28992 |
| Elevation | AHN4 DTM (Rijkswaterstaat/PDOK), used at ~5 m | CC0 1.0 | 0.5 m sheets total 455 GB; use the PDOK WCS at 5 m or the AHN 5 m sheets instead |
| Crops | PDOK BRP Gewaspercelen 2025 definitive (RVO) | CC0 1.0 | 2.9 GB GeoPackage |
| Municipalities, provinces | PDOK Bestuurlijke Gebieden (Kadaster BRK) | CC0 1.0 | GeoPackage |

The terrain tiles stop at zoom 12 (about 24 m per pixel at 52° N), so 5 m elevation is more than enough; the 0.5 m
sheets are not needed. If no working 5 m bulk route exists, Copernicus GLO-30 is the fallback (free licence), noted in
the proposal document.

Attribution line for the Netherlands map: "© OpenStreetMap contributors · Kadaster BAG · AHN · RVO BRP · Natural
Earth".

## How it fits together

1. **Registry** (`engine/regions.py` plus a JSON it reads, shipped with the app): the 51 US entries generated from
   today's `STATE_NAMES`/`STATE_CODES` and `state_maps.NAMES`, plus `NL`. Read by `address_search.py`, `server.py`
   (`map_info`: region, units, attribution, words), `web/setup.js` and `web/map.js` (through `/api/map/info` and
   setup's state), and `packaging/build_packs.py`/`state_maps.py` (names, boxes for non-US regions).
2. **Build tools for the Netherlands** (run on a build machine, never shipped), each with the header the other tools
   have (what it reads, writes, licence):
   - an OSM PBF builder writing a `national.sqlite`-format file for a region box (roads, water, land, rail, places,
     buildings-as-features for z≥15, the help-point classes), plus sea polygons;
   - an AHN builder writing `terrain.sqlite` tiles;
   - a BAG builder writing `buildings.sqlite`, the `NL.sqlite` address index, and the woonplaats rows for `places.sqlite`;
   - a BRP builder writing `crops.sqlite` (a crop-code mapping to the existing crop kinds);
   - a region map-set step (`build_packs.py map NL` or a sibling) that assembles the eleven files, writes
     `map-set.json` (`name: "NL"`), zips `Lastbook-Map-NL.zip` and the address-index zip, and writes their manifest
     entries.
3. **App changes**: registry-driven setup choice (US states and the Netherlands, grouped), Dutch address parsing,
   place-finder fallback, metric units and region words for non-US regions, new map layers for the new help-point
   classes (`defibrillator`, `assembly_point`, out-of-hours GP if kept as its own class), region attribution.
4. **Docs**: `REGIONS-NL.md`, `regions-nl-proposed.json`, and a line in `docs/MAPS.md`.

## Calls made while writing this (builder's, open to correction)

- **Manifest.** The region map-set step writes the Netherlands map and address-index entries into
  `derived/release/manifest-v1.json`, the same source `state_maps.py` appends US states to and
  `packaging/release_manifest.py` turns into the bundled `setup/manifest-v1.json`. For running from source, a small
  dev helper writes `derived/release/setup/manifest-v1.json` from the published manifest plus the local Netherlands
  entries, so the Small pack still downloads from lastbook.org and the Netherlands zip is found locally. These
  manifests are generated, gitignored and never committed (their SHA-256s change with every build).
- **Full-country build is part of this round**, run on this Mac (320 GB free; inputs ~15 GB plus working space). The
  tools are first proven on a one-city clip; the full build follows. If a source turns out unreachable, that layer
  ships empty and the gap is written down, rather than blocking the rest.
- **US-only parts on a Netherlands map are hidden, not branched.** Layers already appear only when the data has
  their class, so the US atlas, dam, fish and boating layers simply do not show. The Southern California dedupe and
  `bldg_socal` are inert with an empty `map.sqlite` and `socal-cells.json` = `[]`. What would show wrong text (the
  attribution line, dataset descriptions in `map_info`, "County"/"mi away" in water results, the "Whole United
  States" button, US caveats) is driven by the region instead.
- **Buildings draw from BAG in `buildings.sqlite`** only; OSM building outlines are left out of `national.sqlite` so
  they are not drawn twice.
- **Natural Earth stays in the attribution**: the world base map (`web/world-context.json`) is Natural Earth.

## Testing and done

- Existing test suite passes unchanged (CONTRIBUTING.md command).
- New unit tests: the registry; Dutch address parsing and lookup against a small fixture index; postcode-only and
  street-first queries; fallback to the place finder; setup installing a `NL` map zip found locally and its address
  index; manifest validation of the new ids; the US paths still pinned.
- Build tools are tested on a small clip (one city) before the full country.
- **Done** means: the full `Lastbook-Map-NL.zip` and `NL` address index are built on this Mac, the app runs from
  source (`app/main.py --data …`) with a Small pack, setup finds and installs the Netherlands map from the local zip,
  and on the Map screen: the map opens on the Netherlands, streets/buildings/terrain/crops/help points show, `1012 AB
  1`-style and `Damrak 1` searches land on the right building, a town name finds the town, distances and contours are
  metric. Screenshots in light and dark mode.

## Left to the builder

- Module layout and names, the registry's exact fields, and how setup groups and labels regions.
- Exact OSM tag-to-class mapping for help points, `minz` thresholds for Dutch roads, and how the coastline is closed.
- The AHN download route (WCS at 5 m vs 5 m sheets) after checking which works, and resampling method.
- How the "found locally only" manifest marking works.
- Which crop codes map to which existing crop kind.
- Contour intervals in metres for a very flat country (likely finer than the US's foot-based steps).

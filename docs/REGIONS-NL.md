# Detailed map for the Netherlands

This document covers the Netherlands for the questions [MAPS.md](MAPS.md) asks before coverage can go beyond the United States.
Those questions are:

- which open source replaces each federal list, and under what licence;
- what a "state" is there;
- how addresses are written.

It follows the shape of [REGIONS.md](REGIONS.md) and [REGIONS-DE.md](REGIONS-DE.md). The machine-readable version is
[regions-nl-proposed.json](regions-nl-proposed.json).

Unlike the other country documents, this one is **built**, not only proposed. This branch has:

- the region in the app (`engine/regions.json`);
- the build tools in `tools/`;
- a packager (`packaging/region_maps.py`);
- a Netherlands map set that setup installs from a file on the computer.

The counts and sizes below come from that build.

**How things were checked.** Research was done on 17 November 2026 by AI research agents reading the publishers' own pages,
and each source was then downloaded and read by the build tools. Each source carries one of three marks:

- **opened:** the dataset or licence page itself was opened and read, and the data was used in the build;
- **search only:** the fact was seen in a search result from the publisher's own site, but the page itself was not opened;
- **not checked:** the page could not be reached or read; the row says what is missing.

## Why the Netherlands is an easy case

Almost every national dataset the map needs is published by the state, for the whole country, as one bulk download under CC0:

- **Kadaster BAG:** every building and address.
- **AHN:** elevation.
- **RVO BRP:** crop parcels.

There is no state-by-state patchwork as in Germany, and no paid national layer as in the US Census-free countries. The one
exception is administrative boundaries; see below.

## What a region is

The whole country is one region, code **`NL`** (ISO 3166-1 alpha-2):

- It is smaller than most US states: about 41,500 km², with about 10 million addresses.
- The national datasets are not split by province.
- People search addresses by postcode, which is national.

Twelve provinces would add nothing a person needs.

- **Code:** `NL` is not one of the 52 US codes in `STATE_CODES`, so a bare code does not collide (unlike `DE`, Delaware). The
  registry's id pattern also accepts ISO 3166-2 subdivisions with a hyphen (`DE-BY`) for countries that need them.
- **Box:** `[3.2, 50.7, 7.3, 53.7]` (W, S, E, N). It covers the European Netherlands:
  - Zeeuws-Vlaanderen at 3.36° E;
  - South Limburg at 50.75° N;
  - the German border at 7.23° E;
  - Rottumeroog at 53.56° N.

  It also takes in strips of Belgium and Germany, which have no detail beyond OpenStreetMap's own roads in the Geofabrik
  extract.
- **Caribbean Netherlands:** Bonaire, Sint Eustatius and Saba are not included. They would be a region of their own; BAG and
  AHN do not cover them.

## Sources, layer by layer

| Layer (file) | US source | Netherlands source | Publisher | Licence | Checked |
|---|---|---|---|---|---|
| Streets, land use, water shapes, rail, place names (`national.sqlite`) | OSM extract | Geofabrik `netherlands-latest.osm.pbf` (about 1.3 GB), read by `tools/build_map_osm.py` | OpenStreetMap contributors | ODbL 1.0 | opened |
| Sea and coast (`national.sqlite`, layers `ocean`, `island`) | OSM coastline, closed westward | OSM water and land polygons, split, EPSG:4326 (osmdata.openstreetmap.de) | OpenStreetMap contributors | ODbL 1.0 | opened |
| Help points (`poi`) | OSM | OSM, with Dutch classes (see Help points) | OpenStreetMap contributors | ODbL 1.0 | opened |
| Buildings (`buildings.sqlite`) | Microsoft footprints | BAG `pand`, from PDOK `bag-light.gpkg` (7.8 GB) | Kadaster | CC0 1.0 | opened |
| Addresses (`addresses/NL.sqlite`) | Overture | BAG `verblijfsobject`, `ligplaats`, `standplaats` from the same file | Kadaster | CC0 1.0 | opened |
| Elevation (`terrain.sqlite`) | USGS 3DEP 1 arc-second | AHN4 terrain model (`dtm_05m`) from PDOK's WCS, asked for at 1 arc-second in EPSG:4326 | Rijkswaterstaat / Het Waterschapshuis | CC0 1.0 (stated in the service's capabilities) | opened |
| Crops (`crops.sqlite`) | USDA Cropland Data Layer | BRP Gewaspercelen 2025, definitive (2.9 GB GeoPackage) | RVO | CC0 1.0 | opened |
| Water (`water.sqlite`) | NID, NHD | named lakes from the OSM street map (`tools/build_water.py --geo derived/geo-nl osm`) | OpenStreetMap contributors | ODbL 1.0 | opened |
| Places (`places.sqlite`) | GNIS, Census | BAG `woonplaats` (towns and villages); OSM municipalities (`admin_level=8`, with `ref:gemeentecode`) and provinces (`admin_level=4`); OSM named places and points | Kadaster; OpenStreetMap contributors | CC0 1.0; ODbL 1.0 | opened |
| Resource atlas (`atlas.sqlite`) | USGS, state records | none: shipped empty | | | |

Notes:

- **Elevation at 1 arc-second, not 0.5 m.**
  - The map's terrain tiles stop at zoom 12, about 24 m a pixel at 52° N. Finer data would not show.
  - The full 0.5 m sheets are about 455 GB (the sum of PDOK's sheet index). The 1 arc-second fetch is 221 MB.
  - A terrain model has holes where buildings and water were. `tools/fetch_ahn.py` fills a hole only when there is ground
    on both sides within 64 cells (about 1.2 km across, 2 km down): buildings, canals and ditches. Polders then show their
    real depth below sea level. Open water and anything wider stays empty and draws at 0 m, so heights are never spread out
    over the sea.
  - The service answers HTTP 400 ("ExtentError") for an area wholly outside AHN; that is read as no data.
- **Municipalities and provinces come from OpenStreetMap, not Kadaster.**
  - Kadaster's boundaries (Bestuurlijke Gebieden) are CC0 as a download only up to 2021; municipalities have merged since.
  - The current PDOK service (api.pdok.nl/kadaster/bestuurlijkegebieden) is **CC BY 4.0** (opened).
  - OSM carries the current boundaries with each municipality's CBS code, under ODbL, which the map already credits.
  - BAG names a town's municipality by its code (`bronhouder_identificatie`), which matches OSM's `ref:gemeentecode`.
- **BAG holds main addresses only** in `bag-light.gpkg`: each address object carries its `hoofdadres`. Secondary addresses
  (`nevenadressen`) are not in this file and are not searchable.
- **What BAG keeps.**
  - Buildings: those that stand ("Pand in gebruik", "Pand in gebruik (niet ingemeten)", "Verbouwing pand", "Pand buiten
    gebruik", "Sloopvergunning verleend").
  - Addresses: those in use or under renovation, and designated houseboat and mobile-home pitches.
  - Left out: what is not built yet.
- **Crops are chosen by BRP code, not by name.** Dutch crop names match too loosely: "Aardappelen" (potatoes) contains
  "appel", and "Kerstbomen" (Christmas trees) contains "kers". The codes kept are listed in `tools/build_crops_nl.py`:
  - apples, pears, cherries, plums, nut trees, traditional orchards, other fruit trees;
  - wine grapes;
  - blueberries, currants, raspberries, blackberries, other soft fruit, cranberries, producing strawberries;
  - asparagus, rhubarb.

  Nursery stock, seed and propagation beds are left out.

## Help points

OpenStreetMap is the source for help points. Classes added for the Netherlands (`tools/build_map_osm.py`):

| Class | From | Layer in the map |
|---|---|---|
| `hospital_seh` | `amenity=hospital` with `emergency=yes` (an emergency department, SEH) | Hospitals |
| `huisartsenpost` | `amenity=doctors` or `clinic` named "Huisartsenpost" or "HAP" (out-of-hours GP post) | Clinics & doctors |
| `defibrillator` | `emergency=defibrillator` | Defibrillators (AED), new |
| `assembly_point` | `emergency=assembly_point` | Emergency assembly points, new |

Coverage, from Overpass counts on 17 November 2026 (search only) and the build:

- **Hospitals with an emergency department.** OSM has 79 hospitals tagged `emergency=yes`, which matches RIVM's count of 79
  SEH locations in its 2026 reachability analysis (opened).
- **Out-of-hours GP posts are thin.** OSM has 48 named huisartsenposten against 111 to 115 in the ZorgkaartNederland and
  Zorgbeurs directories (search only), which are not open data. RIVM's VZinfo publishes a list (search only, licence not
  checked). This is the largest known gap.
- **AEDs.** OSM has about 4,300 defibrillators, a small share of the national AED register. Most public AEDs in the
  Netherlands are in locked cabinets, and the code comes from 112, so a location is a starting point, not a promise.

## Dutch guides and documents

The library gets the Dutch government's own English preparedness guidance, and four short guides that point at its pages the way the
other guides point at library pages. Neither is part of the map set: they are a small **add-on** to the library, the mechanism
`derived/packs/pack-spec.json` already names for extra documents ("addons": the layout of a pack with its own `catalog.json`,
`search.sqlite` and `summary.json`, and no map set).

**Sources.** Denk vooruit (https://english.denkvooruit.nl), the campaign of the National Coordinator for Counterterrorism and Security
(NCTV, Ministry of Justice and Security).

| Document (id) | Original | Pages |
|---|---|---|
| Information booklet, "Prepare for an emergency situation" (`nl-denkvooruit-booklet`) | PDF of 25 November 2025 | 32 |
| "Putting together an emergency kit" (`nl-denkvooruit-kit`) | A4 PDF of 25 November 2025 | 1 |
| "Begin making your emergency plan today" (`nl-denkvooruit-plan`) | PDF form of 6 February 2026 | 3 |
| Nine web pages (`nl-denkvooruit-pages`): NL-Alert, the siren, radio (and its FM frequency table, a second page), the 25 safety regions, flooding, no power, drinking water, extreme weather | English web pages copied on 17 November 2026 | 9 |

**Licence, and what was read.**

- The copyright page (https://english.denkvooruit.nl/service/copyright, opened) says CC0 applies to the site's content unless stated
  otherwise, for example by a copyright notice on a document, and that CC0 does not apply to "photographs, videos, infographics or
  other images". The pages also carry the metadata `DCTERMS.rights: CC0 1.0 Universal` (opened, rights holder Ministry of Justice and
  Security).
- Each PDF was downloaded and read. None has a copyright notice or licence text. All three carry images: the booklet has pictures on
  25 of its 32 pages, the plan form has three, and the kit list is an infographic of icons.
- **Decision: the PDFs are not shipped.** Their images are excluded from CC0 by the copyright page. What is shipped is the wording only:
  a text-only PDF of each, one page for each page of the original, made by `tools/build_nl_documents.py` from text written out by hand in
  `content/nl-documents/`. The booklet's timeline (an infographic) is written out as a list, and the kit list is the text the website
  gives for its infographic. Each page says what it is, where it came from and that it is an unofficial copy (the Rijksoverheid and
  government.nl copyright pages, opened, ask reusers to make clear that the government does not necessarily agree with how its text is
  shown).
- CC0 asks for no credit, so the Netherlands credit line in `engine/regions.json` is unchanged (it is the map's). The publisher, licence
  and source address are in each catalog record and in "About this source".
- Rijksoverheid.nl's copyright page (https://www.rijksoverheid.nl/copyright, opened) also states CC0 for its texts and almost never allows
  images; Dutch only, and nothing from it is used.
- **overstroomik.nl/en** (the flood-risk check; opened: the front page, "about this website", the FAQ, cookies and GDPR): no licence or
  reuse statement was found, and its copyright line is the developer's. **Not used.** The flooding page of Denk vooruit points to it, and
  the guide says so and notes it is in Dutch only.
- **nl-alert.nl** has no English page at /en (404). What the government says about NL-Alert and the siren is on its Denk vooruit pages,
  which are used.

**How the library holds them.** A document in the library is a record in `library-data/catalog.json`, a file under `library-data/documents/`,
its text in `library-data/text/` and one row per page in `library-data/search.sqlite`; the guides cite a catalog id and a PDF file page.
The text-only PDFs are therefore real PDFs, so the app's page view, text view, search, "Ask" and `tools/libq.py` work on them as on any
other, with no change to the app. `packaging/pack_merge.py` (the "pack_merge.py" the pack spec describes, which this repository did not
have) puts the add-on in: it copies the files, joins the catalog by id (never overwriting an id that is not its own), inserts the pages
into the search index, recomputes `summary.json`, notes the add-on in `pack.json` (`add_ons`) and updates `pack-manifest.tsv`, so setup's
repair does not report the library damaged. `remove` undoes it. A zip is checked as setup checks a pack (relative names, no links, only
the add-on's own files).

**Guides.** `content/topics/nl-kit.json`, `nl-alerts.json`, `nl-flood.json` and `nl-outage.json` (72-hour kit and plan; NL-Alert, the
siren, radio and 112; flood, storm and leaving home; long power and water cuts), 77 references (readings and limits) to pages of the four documents.
A guide with `needs_doc` (a new optional field, `content/SCHEMA.md`) is left out of `/api/topics` when that document is not in the
library, so a US library, or a Dutch library without the add-on, does not show them. Everything else about a guide is as before:
`tools/validate_topics.py` checks every id and page against a library with the add-on, and a test (`app.tests.test_nl_documents`) also
checks that each page a guide cites contains the words its note relies on. The publisher "Government of the Netherlands" is labelled
"Government guidance" like the other government sources.

**Setup does not install it.** Setup installs a library, a map and an address index, and replaces the whole library when it upgrades.
The add-on is one extra command (README, "The Dutch guides and documents"), and has to be added again after an upgrade. Teaching setup
a fourth kind of download is left undone.

**Not covered.** Dutch-language material (Rode Kruis, Nederland Veilig, the Dutch booklet), and the pages for fuel, empty shelves, card
payments, wildfire, cyber, earthquake and others on the Denk vooruit risk list; they could be added to `webpages.txt` the same way.

## Licence notes and attribution

- **CC0 1.0** (Kadaster BAG, AHN, RVO BRP): no conditions; credited as a courtesy.
- **ODbL 1.0** (OpenStreetMap): credit, and the map database stays open, as for the US map.

The credit line on the Netherlands map is `© OpenStreetMap contributors · Kadaster BAG · AHN · RVO BRP · Natural Earth`
(`engine/regions.json`). Natural Earth is the world base map every map set draws.

Not used, for licence reasons:

- PDOK's current administrative boundaries (CC BY 4.0).
- Het Waterschapshuis's flood defences (`waterschappen-keringen-imwa`, CC BY-SA 4.0).
- 3D BAG building heights (CC BY 4.0).

The build keeps to ODbL and CC0 so the credit line stays short and the map set carries no share-alike terms beyond
OpenStreetMap's own.

## How addresses are written

- **Postcode.**
  - Four digits and two capital letters: `1012 LG`. BAG stores it without the space.
  - Search accepts `1012 LG`, `1012lg` and `1012 lg`.
  - A postcode alone shows its street, with the house numbers it covers.
- **Order.** Street, house number, then postcode and town: `Damrak 1, 1012 LG Amsterdam`. People search either way:
  - by postcode and number: `1012 LG 1`;
  - by street and number, with or without the town: `Damrak 1`, `Damrak 1 Amsterdam`.
- **House number additions.** BAG has a house letter (`huisletter`, `1A`) and an addition (`huisnummertoevoeging`, `263-1`,
  `2-III`, `9-BS`).
  - People write them in many ways: `12A`, `12-A`, `12 a`, `12-2`, `12 hs`.
  - Search compares the letters and digits only.
  - It treats Roman floor numbers I to IV and digits 1 to 4 as the same: `2-III` finds a stored `2-3`, and `3-2` a stored
    `3-II`.
  - "hs" (huis) matches a stored `H`.
  - A number with an addition that does not exist finds nothing: search never guesses a house.
- **Town names.** BAG uses the official names `'s-Gravenhage` and `'s-Hertogenbosch`. The place finder adds rows for Den Haag
  and Den Bosch, and address search accepts either name as the town.
- **Abbreviations.** `str.` is read as straat, `ln` as laan, `pl` as plein, and `st` as sint. Accents are ignored.

## Building it

```bash
python3.11 -m venv derived/buildenv && derived/buildenv/bin/pip install -r tools/requirements-build-nl.txt
B=derived/buildenv/bin/python; S=derived/sources/nl; G=derived/geo-nl; BOX=3.2,50.7,7.3,53.7
$B tools/build_map_osm.py $S/netherlands-latest.osm.pbf $G/national.sqlite --box $BOX \
   --water-polygons $S/water-polygons-split-4326 --land-polygons $S/land-polygons-split-4326 --admin $G/admin.sqlite
$B tools/build_water.py --geo $G osm
$B tools/build_bag.py $S/bag-light.gpkg $G --box $BOX
$B tools/build_places_nl.py $G/national.sqlite $S/bag-light.gpkg $G/admin.sqlite $G/places.sqlite
$B tools/fetch_ahn.py $S/ahn --box $BOX
$B tools/build_terrain.py --src $S/ahn --out $G/terrain.sqlite --bbox $BOX --source-label "AHN4 DTM (Rijkswaterstaat, CC0 1.0), 1 arc-second"
$B tools/build_crops_nl.py $S/brpgewaspercelen_definitief_2025.gpkg $G/crops.sqlite --box $BOX
.venv/bin/python packaging/region_maps.py build NL --src $G      # derived/packs/state-zips/Lastbook-Map-NL.zip, -Addresses-NL.zip
.venv/bin/python packaging/region_maps.py manifest NL            # list them in derived/release/manifest-v1.json
.venv/bin/python packaging/region_maps.py dev-manifest           # for running from source
```

The sources go in `derived/sources/nl/`:

- `netherlands-latest.osm.pbf`;
- `water-polygons-split-4326/` and `land-polygons-split-4326/`, unzipped;
- `bag-light.gpkg`;
- `brpgewaspercelen_definitief_2025.gpkg`.

The download addresses are in each tool's header.

To install the map, put both zips in the folder setup names, choose the Netherlands under "Countries", and setup uses the
files from the computer.

## Build results

Built on 17 November 2026 on an Apple Silicon Mac (10 cores, 32 GB) from the sources above. OpenStreetMap data was as of
16 November 2026 21:22 UTC; BAG of 1 November 2026; BRP 2025, definitive.

| Step | Result | Time |
|---|---|---|
| `build_map_osm.py` | 5,563,556 map features; 77,924 points; 16 sea and 171 land polygons; 346 municipalities and 12 provinces | 12 min |
| `build_water.py --geo` | 4,750 named lakes and reservoirs | under 1 min |
| `build_bag.py` | 9,706,576 addresses; 11,297,049 buildings | 5.5 min |
| `build_places_nl.py` | 67,160 names; 2,505 BAG towns and villages, all with a province, all but 2 with a municipality | 3 s |
| `fetch_ahn.py` | 15 of 20 one-degree cells have AHN data; 221 MB | 2 min |
| `build_terrain.py` | 1,689 tiles, zoom 4 to 12 | 5 s |
| `build_crops_nl.py` | 16,207 parcels; 6,013 clickable cells | 45 s |
| `region_maps.py build NL` | map set 1,789,935,678 bytes; `Lastbook-Map-NL.zip` 910,079,442 bytes; `Lastbook-Addresses-NL.zip` 384,766,252 bytes | 1.5 min |

Help points in the map, by class:

| Class | Count |
|---|---|
| Defibrillators | 4,363 |
| Supermarkets | 4,867 |
| Fuel stations | 4,061 |
| Drinking water taps | 2,778 |
| Pharmacies | 1,693 |
| Fire stations | 1,013 |
| Police | 463 |
| Emergency assembly points | 156 |
| Hospitals with an emergency department | 75 |
| Other hospitals | 92 |
| Out-of-hours GP posts | 38 |

The Overpass count of hospitals with `emergency=yes` was 79; the map has 75 `hospital_seh` points. The difference was not looked into.

**End to end.** First-run setup was run with the Small library and the Netherlands, all three zips found on the computer.
It checked each against the manifest's size and SHA-256, installed them and switched the library in, with nothing
downloaded. On the library server, the Map screen:

- opens on the Netherlands, with the Dutch credit line and "mapped by 16 Nov 2026";
- shows metric distances, scale and contours;
- shows BAG buildings at street zoom, AEDs, assembly points, SEH hospitals and huisartsenposten;
- reads the Zuidplaspolder at −4.5 m (below sea level).

These searches land on the right building or town:

- `1012 LG 1`
- `Damrak 1`
- `Keizersgracht 6-III`
- `Keizersgracht 2 hs`
- `Kerkstr. 5 Wedde`
- `Lange Voorhout 34 Den Haag`
- `3511 AA`
- `Den Haag`
- `Zuidplas`

Setup's map choice lists the Netherlands under "Countries", above the 52 US states.

## Still undecided

- **Flood layers.** The obvious next layer for this country:
  - the primary flood defences (NBPW, public domain, WFS only; search only);
  - the provinces' flood risk maps (IPO overstromingsrisicokaarten, CC0, opened on data.overheid.nl);
  - LIWO's flood depth scenarios, for which no open bulk download was found.

  Each needs a new kind of map layer.
- **Building heights** for the 3D view (3D BAG, CC BY 4.0).
- **Hosting.** Lastbook's site does not host the Netherlands zips; their manifest entries are marked `local_only`. This
  fork publishes the zips of this build as a GitHub release ([nl-map-2026-11-17](https://github.com/RXWatcher/lastbook/releases/tag/nl-map-2026-11-17)),
  for people who want to install them without building.
- **Caribbean Netherlands**, as its own region.

## What was checked, and what was not

- **Opened, and used in the build:**
  - every dataset in the sources table;
  - the BAG, BRP and AHN licence statements in PDOK's feeds and service capabilities;
  - the PDOK Bestuurlijke Gebieden licence (CC BY 4.0);
  - the Denk vooruit copyright page, its PDFs and the web pages the add-on copies;
  - the Rijksoverheid and government.nl copyright pages;
  - overstroomik.nl/en, which has no licence statement (so not used).
- **Search only:**
  - Overpass counts of help points;
  - the huisartsenpost directories;
  - the NBPW licence.
- **Not checked:**
  - the licence of RIVM's VZinfo huisartsenpost list;
  - whether Geofabrik's extract boundary leaves out any Dutch islands (the Wadden islands are in the build).

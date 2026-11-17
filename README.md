# Lastbook

Lastbook is an offline survival library for Mac, Windows and Linux. It puts manuals, videos, encyclopedias, an offline map and
short practical guides on one computer. After setup, it works offline. The desktop sidebar opens Videos, Map and Chat.
Chat answers questions using the library and links to its sources.

Website: <https://lastbook.org>. Contact: hello@lastbook.org.

> Lastbook’s original code and documentation are licensed under the [MIT License](LICENSE).
> Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

> **This is a fork of [Immortal-Protocols/lastbook](https://github.com/Immortal-Protocols/lastbook) that adds the Netherlands.**
> Everything upstream works as before. On top of it, Lastbook learns about *regions* beyond US states, and the Netherlands is
> the first: a detailed offline map of the whole country with Dutch help points and Dutch address search, in English. See
> [Lastbook for the Netherlands](#lastbook-for-the-netherlands) below. The website, downloads and released apps named in this
> README are upstream's; they do not include the Netherlands.

## Lastbook for the Netherlands

The Netherlands is one region, code `NL`, covering the European Netherlands (box 3.2–7.3° E, 50.7–53.7° N). Choose it in setup
instead of a US state and you get:

| What | From | Licence | In the build of 17 Nov 2026 |
|---|---|---|---|
| Streets, land use, water, rail, place names, coast | OpenStreetMap (Geofabrik `netherlands-latest.osm.pbf`, osmdata coastline polygons) | ODbL 1.0 | 5,563,556 map features |
| Help points: hospitals (marked when they have an emergency department, SEH), out-of-hours GP posts (huisartsenposten), defibrillators (AED), emergency assembly points, pharmacies, fire, police, drinking water, shelters, supermarkets, fuel | OpenStreetMap; huisartsenposten also from Wikidata (CC0 1.0) | ODbL 1.0 | 77,983 points, including 4,363 AEDs, 75 SEH hospitals and 119 huisartsenposten |
| Building outlines | Kadaster BAG (`bag-light.gpkg`, PDOK) | CC0 1.0 | 11,297,049 buildings |
| Building heights for the 3D view | 3D BAG (3DBAG by tudelft3d and 3DGI), joined to BAG on the building number | CC BY 4.0 | 10,695,808 of those buildings; the rest are drawn one storey tall |
| Address search: postcode and house number (`1012 LG 1`), street first (`Damrak 1 Amsterdam`), a postcode alone (`3511 AA`), any house-number addition (`12A`, `12-2`, `2-III`, `2 hs`), and secondary addresses (a corner building's side-street address) | Kadaster BAG | CC0 1.0 | 9,723,320 addresses |
| Elevation, relief, contours in metres, heights below sea level | AHN4 terrain model (Rijkswaterstaat, PDOK WCS), at 1 arc-second | CC0 1.0 | the whole country; the Zuidplaspolder reads −4.5 m |
| Orchards, vineyards, soft fruit, asparagus and rhubarb | RVO BRP Gewaspercelen 2025 | CC0 1.0 | 6,013 map cells from 16,207 parcels |
| Find a town, municipality or province (Den Haag and Den Bosch work as well as BAG's 's-Gravenhage and 's-Hertogenbosch) | BAG towns and villages; OpenStreetMap municipalities and provinces | CC0 1.0; ODbL 1.0 | 67,219 names |
| Named lakes | OpenStreetMap | ODbL 1.0 | 4,750 |
| Flood risk (Layers → Flood risk, from zoom 8): primary flood defences as lines; flood scenarios with water depth for floods of about 1 in 10, 100, 1,000 and 10,000 years. Scenarios, not a forecast | Rijkswaterstaat NBPW; the provinces' flood risk maps (EU Floods Directive, ROR) | Public domain; CC0 1.0 | 237 dike sections; 17,782 km² in the largest scenario |
| Official preparedness documents in English, and four Dutch guides (72-hour kit and plan; warnings, radio and 112; flood, storm and leaving home; long power or water outage) | Government of the Netherlands, Denk vooruit (NCTV): booklet, kit list, plan form, nine web pages | CC0 1.0; text only, pictures not included | 4 documents, 45 pages; an add-on, see [The Dutch guides and documents](#the-dutch-guides-and-documents) |

The map screen follows the region: kilometres and metres, the Dutch credit line
(`© OpenStreetMap contributors · Kadaster BAG · AHN · RVO BRP · 3DBAG by tudelft3d and 3DGI · Natural Earth`), "Find an address, postcode or town", the date the
map data was taken, two new help layers (Defibrillators, Emergency assembly points) and a Flood risk group in the Layers panel
(dikes, and one flood scenario at a time with a water-depth key). Buildings stand at their real height in the 3D view. Setup lists the Netherlands under
"Countries", above the US states. US maps, words and units are unchanged.

Every source, licence and check, and what was left out and why, is in [docs/REGIONS-NL.md](docs/REGIONS-NL.md).

### Getting it running

Lastbook's website does not host the Netherlands map, and the released apps do not know about it, so Lastbook runs from
source. The map files can be downloaded ready-made from this fork's release (the quick way), or built from the open data.

#### The quick way: download the map files

The release [nl-map-2026-11-17-v2](https://github.com/RXWatcher/lastbook/releases/tag/nl-map-2026-11-17-v2) holds the files built on 17 November 2026
(OpenStreetMap data as of 16 November 2026, BAG of 1 November and 8 November 2026, 3D BAG of 3 September 2025, BRP 2025). It has
the map zip (0.9 GB), the address zip (0.4 GB), the manifest entries that let setup check them (`NL-entries.json`), the Dutch
documents add-on (`Lastbook-Addon-NL-Preparedness.zip`, 0.1 MB) and `SHA256SUMS`.

```bash
git clone https://github.com/RXWatcher/lastbook.git && cd lastbook
python3.11 -m venv .venv
.venv/bin/pip install -r packaging/requirements_macos.txt     # Windows: packaging/requirements_app.txt; Linux: packaging/linux/requirements_linux.txt
mkdir -p nl && cd nl
for f in Lastbook-Map-NL.zip Lastbook-Addresses-NL.zip NL-entries.json Lastbook-Addon-NL-Preparedness.zip SHA256SUMS; do
  curl -fLO https://github.com/RXWatcher/lastbook/releases/download/nl-map-2026-11-17-v2/$f
done
shasum -a 256 -c SHA256SUMS
cd ..
.venv/bin/python packaging/region_maps.py manifest NL --entries nl/NL-entries.json
.venv/bin/python packaging/region_maps.py dev-manifest
```

Then do steps 6 and 7 below: move the two zips to the folder setup looks in, and run Lastbook. After setup has made your
library, close Lastbook once and add the Dutch documents and guides (see [The Dutch guides and documents](#the-dutch-guides-and-documents)):

```bash
python3 packaging/pack_merge.py add --data "$HOME/Library/Application Support/Lastbook/LastbookData" nl/Lastbook-Addon-NL-Preparedness.zip
```

#### The full way: build the map files

Build the map files once from the open data. Tested on an Apple Silicon Mac (macOS); the tools are plain Python and should run on
Linux too. Plan on about 37 GB of downloads (40 GB once unpacked; 3D BAG alone is 19.6 GB), about 50 GB of free disk for the sources
and the build, and about 1.5 hours the first time on a recent Mac (the flood download is about 40 minutes and rate limited),
plus the library you choose in setup.

**1. Clone this fork and make the app's Python environment** (Python 3.11):

```bash
git clone https://github.com/RXWatcher/lastbook.git && cd lastbook
python3.11 -m venv .venv
.venv/bin/pip install -r packaging/requirements_macos.txt     # Windows: packaging/requirements_app.txt; Linux: packaging/linux/requirements_linux.txt
```

**2. Make the build environment** (only for building the map; never part of the app):

```bash
python3.11 -m venv derived/buildenv
derived/buildenv/bin/pip install -r tools/requirements-build-nl.txt
```

**3. Download the sources** into `derived/sources/nl/` (all open data; about 13 GB):

```bash
mkdir -p derived/sources/nl && cd derived/sources/nl
curl -fLO https://download.geofabrik.de/europe/netherlands-latest.osm.pbf                          # OpenStreetMap, 1.3 GB
curl -fLO https://osmdata.openstreetmap.de/download/water-polygons-split-4326.zip                  # sea, 0.9 GB
curl -fLO https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip                   # land, 0.8 GB
curl -fLO https://service.pdok.nl/kadaster/bag/atom/downloads/bag-light.gpkg                       # BAG, 7.8 GB
curl -fLO https://service.pdok.nl/kadaster/bag/atom/downloads/lvbag-extract-nl.zip                 # full BAG with secondary addresses, 3.7 GB
curl -fLO https://service.pdok.nl/rvo/gewaspercelen/atom/downloads/brpgewaspercelen_definitief_2025.gpkg   # BRP, 2.9 GB
unzip -q water-polygons-split-4326.zip && unzip -q land-polygons-split-4326.zip
cd ../../..
derived/buildenv/bin/python tools/fetch_3dbag.py download derived/sources/nl/3dbag                 # 3D BAG building heights, 19.6 GB
```

Elevation (AHN, about 220 MB), the flood data and the Wikidata list of GP posts are fetched by their build tools in step 4.

**4. Build the map files** into `derived/geo-nl/`:

```bash
B=derived/buildenv/bin/python; S=derived/sources/nl; G=derived/geo-nl; BOX=3.2,50.7,7.3,53.7
$B tools/build_map_osm.py $S/netherlands-latest.osm.pbf $G/national.sqlite --box $BOX \
   --water-polygons $S/water-polygons-split-4326 --land-polygons $S/land-polygons-split-4326 --admin $G/admin.sqlite   # ~15 min
mkdir -p $S/hap && $B tools/build_hap_nl.py $G/national.sqlite $G/national-hap.sqlite --csv $S/hap/hap.csv --download \
   && mv $G/national-hap.sqlite $G/national.sqlite                              # out-of-hours GP posts from Wikidata
$B tools/build_water.py --geo $G osm                                            # named lakes
$B tools/build_floods_nl.py $G/water.sqlite --src $S/floods                     # dikes and flood scenarios, ~40 min the first time
$B tools/fetch_3dbag.py heights $S/3dbag/3dbag_nl.gpkg.zip $S/3dbag/heights.sqlite                      # ~2 min
$B tools/build_bag.py $S/bag-light.gpkg $G --box $BOX --heights $S/3dbag/heights.sqlite                  # buildings with heights, addresses; ~9 min
$B tools/build_bag_extra.py $S/lvbag-extract-nl.zip $G/addresses/NL.sqlite $G/addresses/NL-full.sqlite \
   && mv $G/addresses/NL-full.sqlite $G/addresses/NL.sqlite                     # secondary addresses; ~6 min
$B tools/build_places_nl.py $G/national.sqlite $S/bag-light.gpkg $G/admin.sqlite $G/places.sqlite
$B tools/fetch_ahn.py $S/ahn --box $BOX
$B tools/build_terrain.py --src $S/ahn --out $G/terrain.sqlite --bbox $BOX --workers 6 \
   --source-label "AHN4 DTM (Rijkswaterstaat, CC0 1.0), 1 arc-second"
$B tools/build_crops_nl.py $S/brpgewaspercelen_definitief_2025.gpkg $G/crops.sqlite --box $BOX
python3 tools/build_nl_documents.py derived/nl-guides/addon --zip derived/packs/state-zips/Lastbook-Addon-NL-Preparedness.zip   # the Dutch documents add-on
```

The order matters in three places: the GP posts go into the street map before the place finder reads it, the flood layers go
into `water.sqlite` after the named lakes, and the secondary addresses are added to the index `build_bag.py` wrote.

**5. Package them and tell setup about them:**

```bash
.venv/bin/python packaging/region_maps.py build NL --src derived/geo-nl   # checks the set, writes the two zips below
.venv/bin/python packaging/region_maps.py manifest NL                     # lists them in derived/release/manifest-v1.json
.venv/bin/python packaging/region_maps.py dev-manifest                    # the setup manifest the app reads when run from source
```

This writes `derived/packs/state-zips/Lastbook-Map-NL.zip` (about 0.9 GB) and `Lastbook-Addresses-NL.zip` (about 0.4 GB). The
manifest holds their size and SHA-256, so setup accepts exactly the files you built; rebuild the manifest whenever you rebuild
the zips. `dev-manifest` also fetches upstream's manifest once, so the library packs still download from lastbook.org.

**6. Put the two zips where setup looks for files:**

| System | Folder |
|---|---|
| macOS | `~/Library/Application Support/Lastbook/` |
| Linux | `~/.local/share/Lastbook/` |
| Windows | `%LOCALAPPDATA%\Lastbook\` |

Setup also names this folder on screen if a zip is missing.

**7. Run Lastbook and choose the Netherlands:**

```bash
.venv/bin/python app/main.py
```

- *First run:* pick a library (Small is 7.7 GB and downloads from lastbook.org), choose **Netherlands** under "Countries",
  and start. The two Netherlands zips are found on the computer, checked and installed; nothing about them is downloaded.
- *An existing library:* Library and local AI → **Choose state or country** → Netherlands.
- *In a browser instead* (the library server): `LASTBOOK_DATA=/path/to/LastbookData .venv/bin/python server.py`, then open
  <http://127.0.0.1:8890/>. Setup is at <http://127.0.0.1:8890/ui/setup.html#manage>.

One map set per library: choosing the Netherlands replaces a US state map, and the other way round.

For your own build of the app (`packaging/build_app_macos.sh` and the Windows and Linux builds), `region_maps.py manifest NL`
adds the Netherlands to `derived/release/manifest-v1.json`, the release manifest the build bundles. That file is upstream's
release material and is not in this repository, so it must also list the library packs. The built app still installs the
Netherlands only from the files.

#### The Dutch guides and documents

The four guides (Netherlands: kit and plan; warnings, radio and 112; flood, storm and leaving home; a long power or water outage) cite
pages of the Dutch government's English preparedness material, which is a small add-on to the library, not part of the map. A library
without the add-on does not show these guides at all; a US library never does.

The add-on holds four text-only documents (45 pages): the 32-page booklet "Prepare for an emergency situation", the one-page emergency
kit list, the emergency plan form, and nine web pages (NL-Alert, the siren, the emergency radio stations with their FM frequencies, the
25 safety regions, flooding, power cuts, drinking water, extreme weather). The government's site puts its text under CC0 1.0 and leaves out
photographs, infographics and other images, and the PDFs are full of pictures, so only the wording is included, with the original's page
numbers: a guide's page number is the page of the original PDF file (for the nine web pages, one page each, and two for the radio page). It is built from the text in `content/nl-documents/`, with no
download and only the standard library:

```bash
python3 tools/build_nl_documents.py derived/nl-guides/addon --zip derived/nl-guides/Lastbook-Addon-NL-Preparedness.zip
# close Lastbook, then put the documents into your library (the folder that holds library-data/; on a Mac by default
# ~/Library/Application Support/Lastbook/LastbookData):
python3 packaging/pack_merge.py add --data "$HOME/Library/Application Support/Lastbook/LastbookData" derived/nl-guides/Lastbook-Addon-NL-Preparedness.zip
```

Open Lastbook and the four guides are in the list; the documents are searchable and open page by page like any PDF. To take them out
again: `python3 packaging/pack_merge.py remove --data <LastbookData> nl-preparedness`. Setting up a different library (an upgrade) replaces
the library, so run the `add` again afterwards. `pack_merge.py` also writes the add-on's files into the library's `pack-manifest.tsv`, so
setup's repair does not call them damaged.

### What is not there yet

- **Out-of-hours GP posts may be out of date.** The map has 119 points: 61 from OpenStreetMap and 58 from Wikidata, whose list
  dates from 2018 and 2019. RIVM counts about 101 today, so a few points may be closed or moved, or doubled. RIVM's own list
  has no licence that allows reuse. Call 112 or your own GP's number. Emergency departments are as tagged in OpenStreetMap
  (75, RIVM counts 79), and a few hospitals with one are not marked.
- **The Dutch guides are an extra step**, and cover only the government's own English material: the 72-hour kit and plan, warnings and
  112, floods and leaving home, long power and water cuts. Upstream's other guides (water, first aid, food, shelter) are US-based but
  mostly general. The documents are text-only (the government's pictures are not CC0), and the radio frequency table and phone numbers are
  as the government published them on 17 November 2026.
- **Building heights are from 3D BAG of September 2025**, so buildings built since have none and are drawn one storey tall, and a
  pitched roof reads a little low (the height is the roof's 70th percentile).
- **Flood scenarios are area-wide**, from the provinces' risk maps, simplified to about 50 m. They show roughly where and how deep, not
  street by street, and not a single dike breach (LIWO's breach scenarios have no open bulk download).
- **No Caribbean Netherlands** (Bonaire, Sint Eustatius, Saba).
- **AEDs**: OpenStreetMap has about 4,400, far fewer than the national register, and most public AEDs are in locked cabinets
  whose code comes from 112.

### How it fits into Lastbook

- `engine/regions.json` and `engine/regions.py`: the regions Lastbook has a detailed map for. These are the 52 US states and the
  Netherlands, each with a name, kind, units, address style, box, credits and dataset list. Setup, address search, the server
  and the build tools read it, so another country is one entry plus its data.
- `engine/address_nl.py`: Dutch address search, used by `server.places` when a Netherlands index is installed.
- Setup accepts region ids (`NL`, `DE-BY`), and manifest entries marked `local_only` that are installed only from a file on the
  computer (`docs/SETUP-API.md`).
- `tools/build_map_osm.py`, `build_hap_nl.py`, `build_bag.py`, `build_bag_extra.py`, `fetch_3dbag.py`, `build_places_nl.py`, `fetch_ahn.py`, `build_crops_nl.py`, `build_floods_nl.py`: the Netherlands
  builders. `tools/map_schema.py` holds the street-map format they share with `tools/build_map.py`.
- `tools/build_nl_documents.py`, `packaging/pack_merge.py`, `content/nl-documents/`, `content/topics/nl-*.json`: the Dutch documents add-on, the tool
  that puts an add-on into a library, the text it is built from, and the four guides. A guide with `needs_doc` shows only where that document is (`content/SCHEMA.md`).
- `packaging/region_maps.py`: assembles, checks and zips a region's map set. `packaging/map_sets.py` holds the map-set
  contract it shares with `packaging/state_maps.py`.
- Design and implementation plan: `docs/superpowers/specs/2026-11-17-netherlands-region-design.md` and
  `docs/superpowers/plans/2026-11-17-netherlands-region.md`. [docs/REGIONS-NL.md](docs/REGIONS-NL.md) is written in the
  same shape as upstream's country proposals, so it can go back upstream with the code.

## Release status

| Platform | Version | Status |
|---|---|---|
| macOS (Apple Silicon, macOS 14 or later) | 1.1.11 | Live on lastbook.org, signed and notarized |
| Windows (64-bit, Windows 10 or later) | 1.1.11 | Live on lastbook.org, Authenticode signed |
| Linux (Ubuntu 24.04 or 26.04 LTS, x86_64) | 1.1.11 | Ubuntu packages; installation instructions below |
| Netherlands map (this fork) | source | Run from source with the map files from release [nl-map-2026-11-17-v2](https://github.com/RXWatcher/lastbook/releases/tag/nl-map-2026-11-17-v2) or built yourself; see [Lastbook for the Netherlands](#lastbook-for-the-netherlands) |

## iPad (development preview, source only)

A native iPad app (Videos, Map and Chat, offline, with optional on-device AI) is in [`mobile/ipad/`](mobile/ipad/).
- It is source for contributors to build and sign themselves.
- There is no App Store, TestFlight or downloadable iPad build.
- See [mobile/ipad/README.md](mobile/ipad/README.md) for what works, the current limitations and how to build it.

## Install on Linux

The Linux packages target **Ubuntu 24.04 LTS and Ubuntu 26.04 LTS on Intel/AMD x86_64 computers**, one package for each. Download
[Lastbook for Ubuntu 24.04](https://downloads.lastbook.org/Lastbook_1.1.11_amd64.deb) (or [for Ubuntu 26.04](https://downloads.lastbook.org/Lastbook_1.1.11_ubuntu26.04_amd64.deb)), then install it with apt so Ubuntu resolves its dependencies.

```bash
sudo apt install ./Lastbook_1.1.11_amd64.deb                  # Ubuntu 24.04
sudo apt install ./Lastbook_1.1.11_ubuntu26.04_amd64.deb      # Ubuntu 26.04
```

Open Lastbook from the application menu. First-run setup downloads your chosen library, state map and optional local AI.
The app uses Ubuntu's GTK, WebKitGTK and media codecs. Its own files install under `/opt/lastbook`, and your library and
settings stay in your home folder. Removing the package leaves those downloaded files and settings in place.

The Linux release was tested on Ubuntu 24.04.5 in WSL2, including installation, setup, video playback, maps, address search,
PDF reading, offline AI with citations, shutdown and uninstall. AI tests used the CPU. Native Linux GPU performance and
other Linux distributions have not been validated for this release.

## What it does

- **Guides first.** Short, curated guides for urgent needs (`content/topics/`), each pointing to real pages in the library
  with page numbers, plus what curators looked for and did not find (`content/gaps.json`).
- **The full library.** Manuals and PDFs (with a whole-PDF view), videos, and offline encyclopedias (ZIM files), with
  keyword search everywhere and meaning-based search on Windows.
- **Offline map.** A base map of the world and the US, plus a detailed map for the state, or the country (this fork: the
  Netherlands), selected during setup: local streets, buildings, terrain, crops, and water, help and resource points.
  Addresses there can be found offline. The person picks the state or country; Lastbook never detects location.
- **Optional local AI.** Ask questions in plain words and get answers that cite library pages, from a model that runs on
  the computer itself (see "The local AI" below). Without it, Chat still finds the right pages.
- **One-download setup.** On first run, setup defaults to Small and selects local AI when the computer can run it.
  The person can choose Small, Medium or All, selects a state map, and starts the checked downloads. A library already on the
  computer (a folder or a pack zip) can be used instead of downloading.
- **Check for updates, only when asked.** About has a Check for updates button (and the Mac menu has Lastbook > Check for
  Updates…). It only says whether a newer version is on the website; nothing is downloaded or installed.

## Privacy and network use

- **No listening port.** The desktop app opens no network port. The window and the engine talk through an in-memory bridge
  (`app/bridge.py`): WKURLSchemeHandler on macOS (`app/shell_macos.py`), WebView2 `WebResourceRequested` on Windows
  (`app/shell_windows.py`), and WebKitGTK `URISchemeRequest` on Linux (`app/shell_linux.py`). The local AI runner speaks JSON lines on standard input and output and opens no socket either.
- **Two uses of the network, both started by the person.** (1) Setup's downloader (`engine/setup/`), when the person
  starts or resumes a download. (2) The update check (`engine/update.py`, `web/update.js`), when the person presses
  the button. Both go through `engine/setup/download.py`, the only module that opens a connection: HTTPS on port 443 only,
  to allow-listed hosts only (`downloads.lastbook.org` for packs, maps, the manifest and update information; Hugging Face's
  download hosts for the AI model; the update check accepts `downloads.lastbook.org` alone), no proxy from the system, and a
  redirect is followed only to another allowed host.
- **Pinned trust.** The downloader trusts only the root certificates in `engine/setup/roots.pem` (11 roots from Mozilla's
  bundle), never the system's trust store. The builds refuse to finish if those roots no longer cover the allowed hosts
  (`packaging/check_tls_roots.py`).
- **Checked files.** Every download is checked against the SHA-256 in the manifest before it is used. Zips are checked
  for unsafe paths, links and sizes before anything is written.
- **Nothing else.** The windows block all web loads, there is no telemetry, no account, and nothing runs on a timer or at
  startup that reaches the network.
- **A working library is never broken.** New data is unpacked beside the old one, checked, and then switched in with a
  single rename. A failure at any step leaves the old library as it was.

The setup contract, including state maps, is in [docs/SETUP-API.md](docs/SETUP-API.md); the engine side is described in
[engine/setup/README.md](engine/setup/README.md).

## What's where

| Path | What it is |
|---|---|
| `app/` | The desktop app: entry point (`main.py`), the no-port bridge, the macOS, Windows and Linux shells, and tests (`app/tests/`). |
| `engine/` | Paths and data-folder lookup, library access, saved pages, offline address search (`address_search.py`, and `address_nl.py` for Dutch addresses), the regions with a detailed map (`regions.json`, `regions.py`), the update check (`update.py`) and first-run setup (`engine/setup/`). `engine/vendor-macos/` holds pypdfium2 for the Mac build. |
| `server.py`, `assistant.py`, `retrieval.py`, `llm_local.py` | The engine: request handler, the assistant and its citation checks, keyword plus meaning-based search, and the local AI (model pins, fit check, runner control). |
| `web/` | The interface, in plain HTML, CSS and JavaScript with no build step and nothing loaded from the web. `setup.*` is the setup screen, `update.js` the update check in About. |
| `content/` | The curated guides (`topics/*.json`) and what curators looked for and did not find (`gaps.json`). Format: `content/SCHEMA.md`. |
| `packaging/` | App builds (macOS, Windows and Linux), the Windows installer and its front (`setup_stub/`), signing helper (`sign_windows.ps1`), icons (`icon/`), pack and state-map builders, the region map-set packager (`region_maps.py`, `map_sets.py`), release manifest, TLS roots tools, package scans, and `packaging/llm/` (the local AI runner). |
| `derived/packs/pack-spec.json` | What goes into each download pack (Small, Medium, All and add-ons) and each state map. Everything else under `derived/` is generated and not kept here. |
| `tools/` | Builders for the offline map, addresses and place finder (US; and for the Netherlands `build_map_osm.py`, `build_bag.py`, `build_bag_extra.py`, `build_places_nl.py`, `fetch_ahn.py`, `build_crops_nl.py`, with their tests in `tools/tests/`), plus curator helpers (`libq.py`, `validate_topics.py`). |
| `website/`, `website-next/` | The earlier website and the current static lastbook.org site, respectively. |
| `docs/` | The setup contract (`SETUP-API.md`), how the offline map is put together (`MAPS.md`), the country proposals (`REGIONS*.md`; `REGIONS-NL.md` is built), notes on the library server version (`LIBRARY-SERVER.md`), and the Netherlands design and plan (`superpowers/`). |

## Run from source

You need Python 3.11 or later and a **data folder**. A data folder holds `library-data/catalog.json` (the library) and gets
a `derived/` folder for indexes, caches and logs. Get one by running the app once and letting setup download a pack, or by
unzipping a pack from lastbook.org.

```bash
python3 -m venv .venv
.venv/bin/pip install -r packaging/requirements_macos.txt     # on Windows: packaging/requirements_app.txt
.venv/bin/python app/main.py --data /path/to/LastbookData
```

Without `--data`, the app checks `LASTBOOK_DATA`, the folder chosen last time, and its own data folder.
Existing libraries elsewhere are accessed when the person chooses them. If no library is available, it opens setup.
The full order is in `app/main.py`. For the Netherlands, see [Getting it running](#getting-it-running).

The **library server** version runs the same engine in a browser and can share with phones on the same Wi-Fi:

```bash
LASTBOOK_DATA=/path/to/LastbookData python3 server.py          # then open http://127.0.0.1:8890/
```

See [docs/LIBRARY-SERVER.md](docs/LIBRARY-SERVER.md). It was written for the household library this project grew out of,
so some of its paths and ports describe that setup. The desktop app does not use this port.

## Build the apps

The builds write into `derived/app-build/` and refuse to finish if the package scan finds something that must not ship:
test code, a network call outside setup's downloader, a web address in our own pages, or a word from the private list
(see below). The builds also run the TLS roots gate.

**macOS (Apple Silicon, needs [uv](https://github.com/astral-sh/uv)):**

```bash
bash packaging/llm/build_llm_macos.sh    # optional: the local AI runner, llama.cpp at a pinned tag, Metal
bash packaging/build_app_macos.sh        # Lastbook.app
```

The build uses CPython 3.11.18 exactly (earlier 3.11 releases lack the block on the compromised eMudhra CA keys). It makes
an ad-hoc signed app. Release copies are then signed with the project's Developer ID in a separate release step; its keys
and settings are not in this repository. The build reads the release manifest from a release folder under
`derived/release/`, which is not in this repository either; see `packaging/release_manifest.py`.

**Windows (64-bit, in Git Bash):**

```bash
TOOLS='C:\path\to\tools' bash packaging/llm/build_llm_windows.sh                 # the runner: llama.cpp with Vulkan, CPU fallbacks
PY=/c/path/to/python.exe OUT='C:\path\to\output' bash packaging/build_app_windows.sh
PY=/c/path/to/python.exe DIST='C:\path\to\output\dist\Lastbook' OUT='C:\path\to\output' bash packaging/build_setup_windows.sh
```

`PY` is CPython 3.14.10 or a later 3.14 (python.org's NuGet package) with `packaging/requirements_app.txt` installed. Each
script header lists the tools it needs, with versions and checksums. The three WebView2 files come from the NuGet package
`Microsoft.Web.WebView2` 1.0.3856.49 and are checked against the hashes in `build_app_windows.sh`. libzim is pinned to
3.13.0 on Windows because Smart App Control refuses 3.13.1's `zim-9.dll`.

`build_setup_windows.sh` makes a per-user installer (no administrator prompt). Its front, `packaging/setup_stub/`, is a
small C program with no C runtime that loads DLLs from System32 only. Its payload reader supports the certificate table
and alignment padding appended by Authenticode signing.

To sign during packaging, set `SIGNTOOL`, `SIGNING_DLIB` and `SIGNING_METADATA` to the Windows paths for SignTool,
the Azure Artifact Signing client DLL and your signing metadata file. `build_setup_windows.sh` calls
`packaging/sign_windows.ps1` for the app folder, uninstaller, inner installer and final installer, in that order.
The helper preserves valid vendor signatures and verifies timestamped signatures after signing. Signing credentials
and account metadata stay in the release environment.

The published Windows 1.1.8 installer passed installation and startup checks, and all 90 installed EXE, DLL and PYD files
had valid signatures. The release is 104,960,408 bytes with SHA-256
`0b31eea87fa05523ca710575e5939754fe10a65eb44ee7d88fe975fbbd161d74`.

**Linux (build on Ubuntu 24.04 or 26.04, x86_64)**

```bash
bash packaging/llm/build_llm_linux.sh
bash packaging/linux/build_app_linux.sh
```

The package uses the system Python and pinned wheels from `packaging/linux/requirements_linux.txt`, built for that Python
only, so each Ubuntu release gets its own package. On 24.04 (Python 3.12) the app build creates
`derived/app-build/linux/<timestamp>/Lastbook_1.1.11_amd64.deb`; on 26.04 (Python 3.14) it creates
`Lastbook_1.1.11_ubuntu26.04_amd64.deb`, with the version `1.1.11+ubuntu26.04`, which apt takes as newer than the 24.04 package.
It bundles the local AI runner when `derived/llm/bin-linux/lastbook-llm` exists. `packaging/linux/smoke_deb.sh` checks
the package in a fresh container of the same Ubuntu release.
Linux integration-test helpers live under `app/tests/linux_*`; set `LASTBOOK_TEST_HOST` to a Windows SSH host with WSL2
before running them. Their disposable test distro is named `LastbookTest`, with files under `C:\LastbookTest`.

## Packs, state maps and the local AI

- **Packs** are data folders: a library plus its catalog, search index and map. `packaging/build_packs.py` builds them
  from a frozen snapshot of a full library according to `derived/packs/pack-spec.json`, and `packaging/verify_packs.py` and
  `packaging/scan_pack.py` check them. The published packs are on `downloads.lastbook.org`. Setup downloads the one the
  person picks and checks it against `setup/manifest-v1.json`, which `packaging/release_manifest.py` writes at build time
  (a newer copy is fetched from `downloads.lastbook.org` when setup opens and used only if it validates).
- **State maps** are one US state's detailed map set, built by `packaging/build_packs.py map <ST>` and published by
  `packaging/state_maps.py`, with per-state address indexes from `packaging/address_indexes.py`. A state map replaces the
  library's map set; it never merges with it. Medium already holds California and All the whole US.
- **Regions outside the US** (`engine/regions.json`) are countries or their subdivisions with a detailed map set of their
  own, built whole from the country's open data by the tools in `tools/` and assembled by `packaging/region_maps.py`. The
  first is **the Netherlands** (`NL`): streets and help points (OpenStreetMap), building outlines and Dutch address search by
  postcode and house number (Kadaster BAG), elevation (AHN) and fruit crops (RVO BRP). Lastbook's site does not host it: its
  manifest entries are `local_only`, and setup installs it from `Lastbook-Map-NL.zip` and `Lastbook-Addresses-NL.zip` placed
  in the folder setup names. How to build it, and every source and licence: [docs/REGIONS-NL.md](docs/REGIONS-NL.md).
- **The local AI** is optional: Gemma 4 26B A4B (Unsloth's `gemma-4-26B-A4B-it-UD-Q4_K_M.gguf`, about 17 GB). The file
  name, size, SHA-256 and Hugging Face revision are pinned in `llm_local.py`. Setup offers it only where the measured fit
  says it fits (about 18 GB of memory for model and context, plus a reserve) and says why in plain words when it does not.
  Setup downloads it directly from Hugging Face. The model is never part of the app or of this repository. The runner,
  `lastbook-llm`, is our own small program (`packaging/llm/lastbook_llm.cpp`) on llama.cpp tag b12032: Metal on a Mac,
  Vulkan with CPU fallbacks on Windows and Linux.
- **Meaning-based search** uses BAAI's bge-small-en-v1.5 (ONNX) through onnxruntime, on Windows only; the Mac build uses
  keyword search.

## What is not in this repository, and why

- **The library** (`library-data/`): hundreds of gigabytes of third-party manuals, videos and encyclopedias, each under
  its own terms. It is distributed as packs, with a Sources and permissions page in each pack.
- **Models and maps** (GGUF, ONNX, map data): large, and published by their makers or built from public data. Setup
  fetches them, and the checksums and pins are here.
- **Generated data** (`derived/`, builds, installers): everything there can be rebuilt with the scripts here.
- **Release and signing material**: signing keys and certificates, notarization and Azure settings, deploy settings and
  the release folders.
- **Private data**: the household's own home area (`web/home-area.json`), the private word lists the scans use, machine
  and user names, keys and internal security-audit notes. The guides here are already in their shipped, general wording.
  To keep your own home-area words out of a build, put them in a local copy of `packaging/ship_edits.json` (`forbidden`)
  and never commit it.

## Tests

```bash
python3 -B -m unittest app.tests.test_bridge app.tests.test_setup app.tests.test_data_folder app.tests.test_what_ships app.tests.test_update app.tests.test_address_search app.tests.test_topic_search app.tests.test_chat_steps app.tests.test_validate_topics app.tests.test_libq app.tests.test_regions app.tests.test_address_nl app.tests.test_region_server app.tests.test_nl_documents
python3 -I -B packaging/test_region_maps.py                                          # the region map-set packager
derived/buildenv/bin/python -B -m unittest discover -s tools/tests -t .              # the Netherlands build tools (build venv)
```

`test_bridge` needs a data folder (`LASTBOOK_DATA`); the others run without a library. `packaging/test_pack_tools.py SAMPLE
WORK` checks the pack tools against a pack sample (`build_packs.py build <pack> --sample N`). The `mac_*` and `win_*`
scripts in `app/tests/` drive a real build against a real data folder, and their paths are placeholders
(`/path/to/lastbook`, `C:\Users\you\app-test`) to set for your own machine.

## Contributing and licence

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Lastbook’s original code and
documentation use the [MIT License](LICENSE), permitting commercial use, modification and redistribution with the
copyright and license notice. Third-party software, models, media and library content retain their own licenses,
listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and each library pack. Distributed app bundles include
GPL-covered components such as python-libzim and libzim and must also meet those components’ license obligations.

## Website maintenance

`website-next/` is the deployed site. Run `python3 -I tools/build.py` from that folder to rebuild the main pages.
The current emergency buying guide is maintained directly in `buying-guide/index.html` and `buying-guide.css`,
with image provenance in `buying-guide/IMAGE-SOURCES.md`. The older `tools/buying_guide.py` and
`data/buying-guide.json` describe the preceding guide and will overwrite the current guide if run.
The current guide contains 17 named products with matching photos. Deployment-specific Amazon Associates tags
are omitted from this repository.

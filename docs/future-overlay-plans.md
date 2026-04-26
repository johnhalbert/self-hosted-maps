# Future Overlay Research And Plans

This document records the consensus findings for future map overlays and concrete implementation plans for the strongest offline-capable candidates.

The main product rule is: offline features must be built from data we are allowed to store and serve locally. Hosted imagery, hosted street view, commercial 3D tiles, or public camera feeds are not offline datasets unless a specific provider contract or product explicitly grants those rights.

## Research Findings

### Satellite And Aerial Imagery

Offline imagery is feasible when the imagery is open, user-provided, or explicitly licensed for local storage and serving. Good candidates are NAIP for U.S. high-resolution aerial imagery, Sentinel/Landsat for lower-resolution global coverage, and sanctioned on-prem products such as MapTiler Server, Mapbox Atlas, Esri export workflows, or direct commercial imagery contracts.

Do not cache or rehost normal Google, Bing, Mapbox, Esri, or similar hosted imagery tiles for offline MapLibre use.

### 3D Map Data

The practical self-hosted path is MapLibre 2.5D: local terrain tiles, hillshade, contours, and building extrusions. True 3D Tiles are possible later through deck.gl or CesiumJS, but that should be a separate viewer mode.

Google Photorealistic 3D Tiles are online-only, billable, attribution-sensitive, and not an offline/self-hosted data source.

### Street View And Panoramic Imagery

Self-hosted Google Street View is not feasible. Google-hosted Street View may only be possible in a separate compliant Google mode, not beside the current MapLibre map, and not cached.

The offline path is owned, locally stored, rights-cleared imagery. Panoramax can be a useful ecosystem or import source, but it is not automatically private or rights-cleared. Every image still needs license, attribution, and privacy review.

### Live Cameras

Approved provider-specific camera snapshots are feasible. Broad arbitrary public camera aggregation is not. DOT/511 sources vary by jurisdiction; Windy, YouTube, EarthCam, and commercial providers all have display, embed, cache, and attribution constraints.

Offline live cameras are impossible. Offline mode can only show stale metadata or previously cached thumbnails if permitted.

### Satellite Positions

Satellite overlays are feasible as estimated orbital overlays from cached orbital elements, not live truth. Positions, ground tracks, passes, and footprints must show source, element epoch, generated time, staleness, and non-operational caveats.

The best source direction is OMM-first CelesTrak GP data, cached locally. Space-Track should remain out of scope until credentials, terms, and redistribution are deliberately handled.

### Other Useful Overlays

Strong candidates include NWS alerts, USGS earthquakes, WFIGS incidents/perimeters, NOAA CO-OPS water/tides, USGS water gauges, NHC/SPC/WPC products, OSM thematic overlays, and terrain/hillshade/contours.

Heavier or keyed candidates include NOAA radar, NASA FIRMS, AirNow/OpenAQ, GTFS realtime, NOAA ENC nautical overlays, and lightning feeds.

## Offline Candidate Plans

Each plan below was run through separate consensus lanes and critique. The status is strong consensus after incorporating final review corrections.

## 1. Offline Raster Imagery Overlays

### Goal

Support locally installed, licensed raster imagery overlays that work without network access after installation.

### Scope

Version 1 supports prebuilt raster MBTiles only. It does not convert COG/GeoTIFF inputs, support PMTiles, scrape provider tiles, or accept arbitrary online tile URL templates.

### Data Model

Add an `imagery` namespace to `/etc/self-hosted-maps/datasets.json`:

```json
{
  "imagery": {
    "schema_version": 1,
    "installed": {},
    "order": [],
    "enabled": []
  }
}
```

Each installed overlay stores:

- `id`, `name`, `format`, `tile_format`, `content_type`
- managed `path` under `/var/lib/self-hosted-maps/imagery/<id>/tiles.mbtiles`
- `bounds`, `minzoom`, `maxzoom`, `tile_size`, `opacity`
- `attribution`, `license.name`, `license.url`, usage notes
- `source.type`, `source.url`, `source.sha256`, `installed_at`, `updated_at`
- offline status: `available`, `bytes`, `sha256`, `checked_at`

State defaults must be added in Python state handling, shell state creation, and `state/datasets.example.json`. Existing installs without `imagery` should be merged with the default shape before mutation.

### API Contract

Use fixed endpoint shapes:

- `GET /api/imagery`: wrapped app JSON listing installed/enabled overlays.
- `GET /api/imagery/{id}.json`: raw TileJSON for MapLibre.
- `GET /api/imagery/{id}/{z}/{x}/{y}.{png|jpg|webp}`: tile bytes.

The TileJSON endpoint should not use the normal `{ ok, data }` wrapper because MapLibre consumes TileJSON directly.

### MBTiles Serving Contract

Use Python `sqlite3` in read-only mode. Open connections per request or per thread; do not share a single unsafe connection across `ThreadingHTTPServer` requests.

Validation rules:

- Imagery ids must match a strict pattern such as `^[a-z0-9][a-z0-9._-]{0,63}$`.
- Resolved paths must remain under `/var/lib/self-hosted-maps/imagery`.
- Required tables: `metadata`, `tiles`.
- Allowed formats: `png`, `jpg`, `jpeg`, `webp`.
- Validate zoom and coordinate bounds.
- Convert browser XYZ to MBTiles TMS row with `tile_row = (1 << z) - 1 - y`.
- Validate extension and content type against registered metadata.
- Check tile magic bytes during install and serve for supported formats.
- Return `400` for invalid coordinates, `404` for unknown overlays or missing tiles.
- Use tile cache headers and ETags based on overlay id, file fingerprint, and tile coordinate.

### Manager Workflow

Add commands:

- `install-imagery-mbtiles.sh`
- `list-imagery-overlays.sh`
- `remove-imagery.sh`

Install flow:

1. Copy a local `.mbtiles` file into a temp directory under the imagery root.
2. Validate schema, metadata, sample tiles, attribution, and license fields.
3. Compute size and SHA-256.
4. Atomically promote into `/var/lib/self-hosted-maps/imagery/<id>/`.
5. Update `datasets.json` under the existing mutation lock.

Removal must only delete managed imagery directories recorded in state.

### Frontend

Load `/api/imagery`, render an imagery section in the layer controls, and add MapLibre raster sources from each overlay TileJSON. Default to one visible imagery overlay at a time. Insert imagery below labels, selected-boundary overlays, and live symbols, with a default opacity such as `0.75` or the overlay metadata value.

Surface attribution through MapLibre source attribution and show license details in the overlay UI.

### Validation

Add `tests/test_imagery_api.py` covering:

- default state merge
- MBTiles metadata parsing
- XYZ-to-TMS conversion
- tile content type and magic-byte checks
- invalid id/path rejection
- missing tile handling
- `/api/imagery` and raw TileJSON output
- install failure leaving no state mutation

## 2. Terrain, Hillshade, And Contours

### Goal

Add offline relief context without coupling terrain to the current OSM vector MBTiles pipeline.

### Scope

First pass should implement terrain/hillshade as separate artifacts and metadata. Contours are planned but should not block the first terrain/hillshade delivery.

### Storage And State

Terrain artifacts live under `/var/lib/self-hosted-maps`, never under `www` or repo assets.

Recommended current artifact layout:

```text
/var/lib/self-hosted-maps/current/
  openmaptiles.mbtiles
  terrain/
    terrain-manifest.json
    dem/{z}/{x}/{y}.png
```

The terrain manifest must include:

- schema version
- source provider/product/license/attribution
- horizontal/vertical datum and units
- terrain bounds and selected dataset bounds
- selected hash and dataset ids
- encoding, tile size, minzoom, maxzoom
- built_at, tool versions, checksums
- contour availability, if any

Terrain is valid only when its `selected_hash` and `dataset_ids` match the current map state.

### Serving Contract

Choose nginx static serving for the first pass:

```nginx
location /terrain/ {
    alias __DATA_ROOT__/current/terrain/;
    try_files $uri =404;
}
```

Wire this through `configure-system.sh` and `update-app.sh --refresh-system-config`. Defer TileServer integration until optional terrain artifacts are proven not to break startup when absent.

### Build And Promotion

Terrain builds must acquire the same mutation lock used for map rebuilds. Use one of these flows:

- Build terrain inside `current.next/terrain` as part of a full rebuild, then promote atomically with the vector artifact.
- Or use a separate terrain staging directory and only promote when metadata matches current `selected_hash` and `dataset_ids`.

On vector rebuild, preserve existing terrain only if it matches the new current state. Otherwise disable/remove terrain metadata cleanly so stale terrain is not displayed over a new vector map.

### Dependencies

Use apt packages for the first implementation:

- `gdal-bin`
- `python3-gdal`
- `python3-numpy`
- `python3-pil`

Avoid global `pip install GDAL`.

### DEM And Encoding

Accept user-provided or configured DEM sources first. A later global source can use Copernicus DEM GLO-30; U.S. installs can use USGS 3DEP. Store source and datum metadata explicitly.

For MapLibre terrain, generate local `raster-dem` PNG tiles using Terrarium or Mapbox Terrain-RGB-compatible encoding. If using Terrain-RGB, document clearly that we generate Mapbox-compatible encoding locally from open DEM data; we are not using Mapbox data.

### Frontend

Extend `/api/state` or the existing overview response with terrain metadata:

- `terrainAvailable`
- `terrainTileTemplate`
- `encoding`
- `rebuiltAt`
- `attribution`
- `minzoom`, `maxzoom`

In `assets/app.js`:

- add a `raster-dem` source when terrain is available
- add a terrain toggle using `map.setTerrain(...)`
- add a hillshade toggle using a `hillshade` layer from the same source
- hide or disable the controls when metadata is absent or stale

### Contours

Defer contours to a follow-up unless terrain generation is stable.

Future options:

- raster contour PNG tiles under `/terrain/contours/{z}/{x}/{y}.png`
- vector contours via `gdal_contour` and a vector tile pipeline

### Validation

Tests should cover:

- terrain manifest parsing
- stale selected hash/dataset id rejection
- capability flags for terrain/hillshade/contours
- missing terrain still leaves base map working
- invalid terrain tile path rejection
- rebuild behavior when terrain is enabled, disabled, failed, or stale

Manual checks:

- rebuild a small region with terrain
- verify `/terrain/dem/...png`
- toggle terrain and hillshade
- change selected datasets and confirm stale terrain disappears until rebuilt

## 3. OSM Thematic Overlays

### Goal

Add useful offline overlays from local OSM data, such as green space, water, roads, buildings, civic POIs, mobility/trails, and selected infrastructure, without adding new providers.

### Key Constraint

The active Tilemaker resources must be audited first. The checked-in `config/tilemaker/process.lua` is minimal, but fresh installs currently copy upstream Tilemaker resources into the install root. The viewer references OpenMapTiles-style layers that the checked-in fallback does not emit.

### Phase 0: Audit

Audit these surfaces:

- `config/tilemaker/config.json`
- `config/tilemaker/process.lua`
- installed `$SHM_INSTALL_ROOT/config/tilemaker/*`
- generated MBTiles `metadata.json.vector_layers`
- all `source-layer` references in `assets/app.js`

The audit should produce a list of available source layers and missing references.

### Phase 1: No-New-Data Toggles

Before expanding tile output, add toggles for verified existing layers:

- green space: `landcover`, optionally `landuse`, `park` when present
- water: `water`, `waterway`, water labels when present
- roads: `transportation`, road labels when present
- buildings: `building`
- boundaries: `boundary` when present

The frontend must gracefully hide or disable toggles for unavailable source layers.

### Phase 2: Repo-Owned Tilemaker Profile

Make `config/tilemaker` repo-owned and deploy it on fresh installs and app updates:

- update `scripts/install-runtime.sh`
- update `bin/update-app.sh`
- document that a map rebuild is required after Tilemaker profile changes

Do not replace OpenMapTiles-compatible layers with the current minimal placeholder. Vendor or derive from the full upstream OpenMapTiles Tilemaker resources, then add thematic layers as additive output.

### Phase 3: Additive Theme Layers

Prefer three shared additive layers rather than one layer per theme:

- `theme_area`
- `theme_line`
- `theme_poi`

Shared attributes:

- `theme`
- `class`
- `subclass`
- `name`
- `brand`
- `operator`
- `network`
- `ref`
- selected accessibility/useful fields such as `access`, `opening_hours`, `wheelchair`

Initial themes:

- `green_space`
- `civic_poi`
- `mobility`
- `food_drink`
- `health`
- `education`
- `public_services`
- `tourism`
- `recreation`

### Tilemaker Rules

Implement node, way, and relation handling deliberately:

- `node_function`: places, POIs, emergency/service points, point infrastructure.
- `way_function`: base layers, trails/cycleways, buildings, landuse, parks, water, line infrastructure.
- `relation_function`: multipolygon water/landuse/park/boundary and selected hiking/cycling route relations.

Use minzoom and attribute budgets to control tile size:

- dense POIs at high zoom only
- no raw tag pass-through
- relation overlays only after benchmarks
- no broad `landuse=*` dump without allowlists

### Frontend

Add an OSM/offline overlay group separate from live provider layers. Persist visibility under a namespaced localStorage key such as `shm.osmThemeLayers.v1`.

Toggles should only affect layer visibility. They should not trigger API calls.

### Validation

Static tests:

- every `assets/app.js` `source-layer` appears in the Tilemaker schema or is handled as optional
- every emitted layer in `process.lua` exists in `config.json`
- overlay groups reference known layer ids

Generated fixture tests:

- run Tilemaker against a tiny fixture when available
- inspect MBTiles `metadata.json.vector_layers`
- verify representative node/way/relation features appear

Benchmarks:

- small city extract
- one state or medium region
- current multi-dataset selection where practical

Record rebuild wall time, MBTiles size, tile count, vector layer list, and viewer load status.

## 4. Local Street Imagery And Panoramas

### Goal

Support offline/local street-level imagery owned or controlled by the operator, with privacy and rights metadata enforced before anything is visible.

### Scope

First pass is local-only and read-focused. No Google, no Mapillary offline cache, no arbitrary folder browsing, and no public upload flow.

Panoramax can be added later as an admin import or clearly labeled remote third-party provider. It should not be the first dependency.

### Storage

Use `SHM_DATA_ROOT`, for example:

```text
${SHM_DATA_ROOT}/imagery/
  catalog.sqlite
  originals/
  redacted/
  thumbnails/
  imports/
```

An even narrower v1 can use an indexed manifest under:

```text
${SHM_DATA_ROOT}/street-imagery/index.json
${SHM_DATA_ROOT}/street-imagery/assets/
```

If the goal includes takedown/redaction workflows in the first implementation, use SQLite. If the goal is just local read-only browsing, use a versioned manifest with documented scale limits.

### Capability And Auth

Add:

- `SHM_STREET_IMAGERY_ENABLED=0`
- `SHM_STREET_IMAGERY_ROOT`
- max bbox area and max results settings

Admin mutations must require an owner-auth gate. In this repo, `SHM_ADMIN_TOKEN` can be blank, so importing, publishing, redacting, or taking down imagery should either require `SHM_ADMIN_TOKEN` to be set or use a separate explicit owner-auth setting.

Public read APIs must remain separate and only expose publishable/redacted records.

### Public API

Suggested routes:

- `GET /api/street-imagery/capabilities`
- `GET /api/street-imagery/local/coverage?bbox=minLon,minLat,maxLon,maxLat&limit=200`
- `GET /api/street-imagery/local/items/{itemId}`
- `GET /api/street-imagery/local/items/{itemId}/thumbnail`
- `GET /api/street-imagery/local/items/{itemId}/image`

No endpoint may accept a filesystem path, URL, glob, or relative filename from the browser.

### Privacy State

The public API may only return images that are:

- approved or publishable
- redacted when redaction is required
- not under active takedown
- not removed, private, or suppressed

Store privacy fields such as:

- face/license plate blur status
- exact location allowed
- EXIF stripped
- owner/source/attribution/license
- review state
- redaction state
- takedown state
- publish state

For image serving, prefer redacted image files. Serving originals should be disabled by default.

### Media Serving

Serve imagery through the Python API initially so privacy checks cannot be bypassed. Consider nginx `X-Accel-Redirect` later for performance, with internal-only aliases.

Path safety:

- resolve by item id through the catalog/index
- verify real paths remain under the configured imagery root
- reject symlinks and traversal
- allowlist MIME types
- cap byte sizes
- never return local absolute paths to the browser

### Frontend

Add a disabled-by-default “Street imagery” control. When enabled:

- fetch coverage for current bbox
- render camera/photo markers and optional heading
- open a side panel on click
- show image, captured date, heading, attribution/license, local/user-provided badge, and sequence prev/next when available

Pannellum should be vendored only when panorama viewing is included. A simpler first pass can show static images and thumbnails.

### Panoramax

Panoramax support should be separate:

- disabled by default
- clearly labeled third-party when remote
- admin import must be SSRF-protected
- bound bbox, count, and byte limits
- preserve source license and attribution
- do not silently rehost third-party imagery unless terms allow it

### Validation

Tests should cover:

- disabled capability defaults
- invalid bbox and limit handling
- no absolute-path leakage
- path traversal and symlink rejection
- publish/redaction/takedown filters
- original-file denial by default
- owner-auth requirement for admin mutations
- Panoramax remote requests disabled by default

## 5. Cached Satellite Orbital Elements

### Goal

Provide offline-capable satellite context from cached orbital elements, with honest “estimated” labeling and staleness metadata.

### Scope

Version 1 should be OMM-first cache/import infrastructure. It should not claim live satellite tracking. Viewer-rendered orbital points require a propagation choice; if that is not selected in the same phase, v1 should expose cache/catalog status only.

### Data Source

Use CelesTrak GP OMM JSON as the default structured source. Support local import of OMM JSON files. Optional TLE import can be compatibility-only and should normalize into the same internal schema.

Space-Track is out of scope for v1.

### Cache Layout

Store under:

```text
${SHM_DATA_ROOT}/cache/satellites/
  manifest.json
  celestrak-gp.json
  previous-celestrak-gp.json
```

Manifest fields:

- schema version
- provider key and label
- source format and URL/file
- groups
- fetched/imported time
- last success time
- record count
- invalid record count
- stale/expired thresholds
- source ETag/Last-Modified when available
- refresh status and error
- dependency/propagation availability

Each normalized element should store:

- `recordKey`
- `noradCatalogNumber`
- `objectName`
- `objectId`
- `epochIso`, `epochMs`
- mean motion, eccentricity, inclination, RAAN, argument of pericenter, mean anomaly
- BSTAR and optional OMM fields
- raw source record
- provenance and staleness

### Refresh And Import

Use an admin refresh/import path that writes cache files atomically:

- download or read into temp files
- validate JSON/schema/fields
- skip invalid records and count them
- preserve previous successful cache on failure
- replace active cache with atomic rename
- viewer GETs must be read-only

If exposed over API, refresh must use the existing admin job pattern and require the admin/owner token.

### API

Phase 1:

- `GET /api/satellites/catalog`
- `GET /api/satellites/elements?group=&limit=`

These return wrapped JSON with provenance, staleness, and capped records. No browser fetches from CelesTrak directly.

Phase 2, after choosing propagation:

- `GET /api/satellites/positions?bbox=&group=&limit=`
- `GET /api/satellites/detail?recordKey=`
- optional pass and footprint endpoints

### Propagation Decision

If implementing positions in v1, choose one path explicitly:

- `sgp4`: smaller dependency, but the repo owns OMM-to-Satrec mapping, TEME-to-WGS84 conversion, footprint math, and pass logic.
- `skyfield`: larger dependency, but safer for geodetic conversion and pass calculations.

Consensus recommendation: implement cache/import first, then make propagation a separate decision. If positions are included immediately, choose lightweight `sgp4` only with explicit tests for OMM mapping and TEME-to-WGS84 conversion.

### Frontend

When positions are implemented, label the button “Orbital estimates,” not “Live satellites.” Popups must show:

- object name
- NORAD/catalog id
- element epoch
- generated time
- source and imported/fetched time
- data age/staleness
- “estimated from cached orbital elements”

Default caps should prevent dense constellations from overwhelming the map.

### Validation

Phase 1 tests:

- OMM validation
- local import and CelesTrak fetch normalization
- atomic cache replacement
- stale/expired classification
- previous-cache preservation on failure
- disabled capability and missing-cache responses
- capped element responses

Phase 2 tests:

- OMM-to-SGP4 mapping
- fixed-time propagation golden cases
- WGS84 longitude/latitude/altitude sanity
- antimeridian ground-track splitting
- footprint closure
- performance caps

## Cross-Cutting Principles

All offline overlays should follow these rules:

- Data lives under `/var/lib/self-hosted-maps` or configured `SHM_DATA_ROOT`, not under app source or `www`.
- Provider credentials remain server-side.
- Public APIs never expose local absolute paths.
- State mutations use the existing mutation lock and atomic file replacement.
- Attribution is visible in the UI, not just stored in metadata.
- Missing or stale optional artifacts must not break the base vector map.
- Each provider/source needs explicit docs covering license, attribution, offline rights, update cadence, storage, and stale behavior.

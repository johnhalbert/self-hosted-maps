# Offline Raster Imagery Overlays

Self Hosted Maps can serve locally installed raster imagery overlays from prebuilt MBTiles files. This v1 path is only for imagery you are licensed to store and serve locally.

## Supported Input

- Prebuilt raster MBTiles only.
- Tile formats: PNG, JPEG, or WebP.
- Required MBTiles tables: `metadata` and `tiles`.
- Required install metadata: attribution and license name.

The installer does not convert COG/GeoTIFF files, read PMTiles, scrape hosted providers, or accept remote tile URL templates.

## Install

```sh
self-hosted-maps-install-imagery naip-la-2024 "NAIP Louisiana 2024" /path/to/naip-la.mbtiles \
  --attribution "Imagery source attribution" \
  --license-name "License or contract name" \
  --license-url "https://example.com/license" \
  --usage-notes "Use only under the operator's offline imagery license."
```

The installer copies the MBTiles into:

```text
/var/lib/self-hosted-maps/imagery/<id>/tiles.mbtiles
```

It validates the SQLite schema, MBTiles metadata, sample tile magic bytes, attribution, license fields, size, and SHA-256 before updating `/etc/self-hosted-maps/datasets.json`. State mutation uses the same mutation lock as dataset operations.

Installing an overlay makes it the enabled imagery overlay by default. Add `--disabled` to install it without making it visible by default.

## List And Remove

```sh
self-hosted-maps-list-imagery
self-hosted-maps-list-imagery --json
self-hosted-maps-remove-imagery naip-la-2024
```

Removal only deletes managed imagery directories recorded in state under the configured imagery root.

## API

- `GET /api/imagery` returns wrapped application JSON with installed imagery overlays, order, and enabled ids.
- `GET /api/imagery/{id}.json` returns raw TileJSON for MapLibre.
- `GET /api/imagery/{id}/{z}/{x}/{y}.{png|jpg|webp}` returns tile bytes.

Tile serving opens MBTiles with Python `sqlite3` in read-only mode per request, validates ids and managed paths, converts browser XYZ coordinates to MBTiles TMS rows, checks tile coordinate ranges, validates file extension/content type, and verifies tile magic bytes before responding.

The public list and TileJSON responses do not expose local filesystem paths.

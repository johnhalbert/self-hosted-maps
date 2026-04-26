# Offline Terrain And Hillshade

Terrain is optional. The base vector map continues to work when no terrain artifact is installed.

Version 1 serves prebuilt local raster-dem PNG tiles from:

```text
/var/lib/self-hosted-maps/current/terrain/
  terrain-manifest.json
  dem/{z}/{x}/{y}.png
```

The local API only advertises terrain when `terrain-manifest.json` matches the current map state's `selected_hash` and `dataset_ids`. Rebuilding a different vector dataset set disables stale terrain metadata instead of displaying it over the wrong map.

## Dependencies

The installer uses Debian apt packages for terrain tooling support:

- `gdal-bin`
- `python3-gdal`
- `python3-numpy`
- `python3-pil`

Do not install GDAL with global `pip install GDAL`. If you build DEM tiles yourself, use the system GDAL packages or an isolated external build environment, then install the resulting raster-dem tiles.

## Building Raster-Dem Tiles

For small regions, build Terrarium or Mapbox Terrain-RGB-compatible PNG tiles from a local DEM with the apt-provided GDAL Python bindings:

```sh
python3 /opt/self-hosted-maps/bin/build-terrain-tiles.py \
  --dem /path/to/source-dem.tif \
  --output /tmp/self-hosted-maps-terrain \
  --bounds -92.0,30.0,-90.0,32.0 \
  --minzoom 0 \
  --maxzoom 12 \
  --encoding terrarium
```

The builder writes `dem/{z}/{x}/{y}.png` under the output directory. Large regions can generate many files, so start with a small `--bounds` and zoom range.

## Installing Raster-Dem Tiles

Build or obtain local raster-dem PNG tiles encoded as Terrarium or Mapbox Terrain-RGB-compatible data. Then install them against the currently served map:

```sh
self-hosted-maps-install-terrain \
  --source /path/to/prebuilt-terrain \
  --encoding terrarium \
  --minzoom 0 \
  --maxzoom 12 \
  --tile-size 256 \
  --bounds -92.0,30.0,-90.0,32.0 \
  --provider "Local DEM" \
  --product "Operator-provided raster-dem" \
  --license-name "Rights-cleared local data" \
  --attribution "Terrain: local DEM"
```

The source directory must contain `dem/{z}/{x}/{y}.png`. The installer copies the tiles under the data root, writes checksums, creates `terrain-manifest.json`, and updates `current.terrain` in `/etc/self-hosted-maps/datasets.json`.

Contours are intentionally disabled in v1. The manifest records `contours.available=false` with reason `deferred`; future contour pipelines can add separate raster or vector contour artifacts.

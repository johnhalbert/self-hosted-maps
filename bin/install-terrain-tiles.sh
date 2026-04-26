#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

usage() {
  cat <<'EOF'
Usage:
  install-terrain-tiles.sh --source DIR --encoding terrarium|mapbox [options]

Installs prebuilt raster-dem PNG tiles from DIR/dem/{z}/{x}/{y}.png into
SHM_DATA_ROOT/current/terrain and stamps a terrain-manifest.json against the
currently served vector map selected_hash and dataset_ids.

Options:
  --minzoom N              Minimum DEM tile zoom. Default: 0
  --maxzoom N              Maximum DEM tile zoom. Required
  --tile-size N            DEM tile size, 256 or 512. Default: 256
  --bounds W,S,E,N         Terrain bounds. Required
  --provider TEXT          Source provider label
  --product TEXT           Source product label
  --license-name TEXT      Source license name
  --license-url URL        Source license URL
  --attribution TEXT       Attribution shown in the map
  --source-url URL         Source URL or local source description
  --horizontal-datum TEXT  Horizontal datum. Default: WGS84
  --vertical-datum TEXT    Vertical datum. Default: source-provided
  --units TEXT             Elevation units. Default: meters
EOF
}

SOURCE_DIR=""
ENCODING=""
MINZOOM="0"
MAXZOOM=""
TILE_SIZE="256"
BOUNDS=""
PROVIDER=""
PRODUCT=""
LICENSE_NAME=""
LICENSE_URL=""
ATTRIBUTION=""
SOURCE_URL=""
HORIZONTAL_DATUM="WGS84"
VERTICAL_DATUM="source-provided"
UNITS="meters"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --source) SOURCE_DIR="${2:-}"; shift 2 ;;
    --encoding) ENCODING="${2:-}"; shift 2 ;;
    --minzoom) MINZOOM="${2:-}"; shift 2 ;;
    --maxzoom) MAXZOOM="${2:-}"; shift 2 ;;
    --tile-size) TILE_SIZE="${2:-}"; shift 2 ;;
    --bounds) BOUNDS="${2:-}"; shift 2 ;;
    --provider) PROVIDER="${2:-}"; shift 2 ;;
    --product) PRODUCT="${2:-}"; shift 2 ;;
    --license-name) LICENSE_NAME="${2:-}"; shift 2 ;;
    --license-url) LICENSE_URL="${2:-}"; shift 2 ;;
    --attribution) ATTRIBUTION="${2:-}"; shift 2 ;;
    --source-url) SOURCE_URL="${2:-}"; shift 2 ;;
    --horizontal-datum) HORIZONTAL_DATUM="${2:-}"; shift 2 ;;
    --vertical-datum) VERTICAL_DATUM="${2:-}"; shift 2 ;;
    --units) UNITS="${2:-}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

require_cmd jq
require_cmd python3
require_cmd sha256sum
ensure_state_file

if [[ -z "$SOURCE_DIR" || -z "$ENCODING" || -z "$MAXZOOM" || -z "$BOUNDS" ]]; then
  usage >&2
  exit 1
fi

case "$ENCODING" in
  terrarium|mapbox|terrain-rgb|mapbox-terrain-rgb) ;;
  *) echo "Unsupported encoding: $ENCODING" >&2; exit 1 ;;
esac

if [[ "$TILE_SIZE" != "256" && "$TILE_SIZE" != "512" ]]; then
  echo "--tile-size must be 256 or 512." >&2
  exit 1
fi

if [[ ! -d "$SOURCE_DIR/dem" ]]; then
  echo "Source directory must contain dem/{z}/{x}/{y}.png tiles." >&2
  exit 1
fi

if [[ -n "$(find "$SOURCE_DIR/dem" -type l -print -quit)" ]]; then
  echo "Terrain tile source must not contain symlinks." >&2
  exit 1
fi

if [[ -z "$(find "$SOURCE_DIR/dem" -type f -name '*.png' -print -quit)" ]]; then
  echo "No PNG terrain tiles found under $SOURCE_DIR/dem." >&2
  exit 1
fi

BOUNDS_JSON="$(python3 - "$BOUNDS" <<'PY'
import json
import sys

try:
    west, south, east, north = [float(part) for part in sys.argv[1].split(",")]
except ValueError:
    raise SystemExit("bounds must be W,S,E,N")
if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
    raise SystemExit("bounds are outside valid longitude/latitude ranges")
print(json.dumps([west, south, east, north]))
PY
)"

acquire_mutation_lock

CURRENT_HASH="$(jq -r '.current.selected_hash // empty' "$SHM_STATE_FILE")"
DATASET_IDS_JSON="$(jq -c '.current.dataset_ids // []' "$SHM_STATE_FILE")"
if [[ -z "$CURRENT_HASH" || "$DATASET_IDS_JSON" == "[]" ]]; then
  echo "No current map build is recorded. Rebuild the selected map before installing terrain." >&2
  exit 1
fi

SELECTED_BOUNDS_JSON="$(jq -c --argjson dataset_ids "$DATASET_IDS_JSON" '
  def valid_bounds($b):
    ($b | type == "array")
    and ($b | length == 4)
    and all($b[]; ((type == "number") or (type == "string")));
  reduce $dataset_ids[] as $id (null;
    (. as $acc
     | (.installed[$id].bounds // null) as $b
     | if valid_bounds($b) then
         ($b | map(tonumber)) as $n
         | if $acc == null then $n
           else [
             ([ $acc[0], $n[0] ] | min),
             ([ $acc[1], $n[1] ] | min),
             ([ $acc[2], $n[2] ] | max),
             ([ $acc[3], $n[3] ] | max)
           ] end
       else $acc end)
  )
' "$SHM_STATE_FILE")"

STAMP="$(date +%Y%m%d-%H%M%S)"
STAGING="${SHM_DATA_ROOT}/tmp/terrain-install.${STAMP}.$$"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$STAGING/terrain/dem" "${SHM_DATA_ROOT}/current" "$SHM_LOG_ROOT"
cp -a "$SOURCE_DIR/dem/." "$STAGING/terrain/dem/"

(
  cd "$STAGING/terrain"
  find dem -type f -name '*.png' -print0 | sort -z | xargs -0 sha256sum > checksums.sha256
)

TILE_COUNT="$(wc -l < "$STAGING/terrain/checksums.sha256" | tr -d '[:space:]')"
BYTES="$(du -sb "$STAGING/terrain/dem" | awk '{print $1}')"
GDAL_VERSION="$(gdalinfo --version 2>/dev/null || true)"
PYTHON_VERSION="$(python3 --version 2>/dev/null || true)"
BUILT_AT="$(date -u +%FT%TZ)"

jq -n \
  --arg selected_hash "$CURRENT_HASH" \
  --argjson dataset_ids "$DATASET_IDS_JSON" \
  --argjson bounds "$BOUNDS_JSON" \
  --argjson selected_bounds "$SELECTED_BOUNDS_JSON" \
  --arg encoding "$ENCODING" \
  --argjson minzoom "$MINZOOM" \
  --argjson maxzoom "$MAXZOOM" \
  --argjson tile_size "$TILE_SIZE" \
  --arg provider "$PROVIDER" \
  --arg product "$PRODUCT" \
  --arg license_name "$LICENSE_NAME" \
  --arg license_url "$LICENSE_URL" \
  --arg attribution "$ATTRIBUTION" \
  --arg source_url "$SOURCE_URL" \
  --arg horizontal_datum "$HORIZONTAL_DATUM" \
  --arg vertical_datum "$VERTICAL_DATUM" \
  --arg units "$UNITS" \
  --arg built_at "$BUILT_AT" \
  --arg gdal_version "$GDAL_VERSION" \
  --arg python_version "$PYTHON_VERSION" \
  --argjson tile_count "$TILE_COUNT" \
  --argjson bytes "$BYTES" \
  '{
    schema_version: 1,
    source: {
      provider: (if $provider == "" then null else $provider end),
      product: (if $product == "" then null else $product end),
      url: (if $source_url == "" then null else $source_url end),
      license: {
        name: (if $license_name == "" then null else $license_name end),
        url: (if $license_url == "" then null else $license_url end)
      },
      attribution: (if $attribution == "" then null else $attribution end)
    },
    attribution: (if $attribution == "" then null else $attribution end),
    horizontal_datum: $horizontal_datum,
    vertical_datum: $vertical_datum,
    units: $units,
    bounds: $bounds,
    selected_bounds: $selected_bounds,
    selected_hash: $selected_hash,
    dataset_ids: $dataset_ids,
    encoding: $encoding,
    tile_size: $tile_size,
    minzoom: $minzoom,
    maxzoom: $maxzoom,
    built_at: $built_at,
    installed_at: $built_at,
    terrain_tile_template: "/terrain/dem/{z}/{x}/{y}.png",
    tool_versions: {
      gdal: (if $gdal_version == "" then null else $gdal_version end),
      python: (if $python_version == "" then null else $python_version end)
    },
    checksums: {
      file: "checksums.sha256",
      tile_count: $tile_count,
      bytes: $bytes
    },
    contours: {
      available: false,
      enabled: false,
      reason: "deferred"
    }
  }' > "$STAGING/terrain/terrain-manifest.json"

rm -rf "${SHM_DATA_ROOT}/current/terrain.prev"
if [[ -d "${SHM_DATA_ROOT}/current/terrain" ]]; then
  mv "${SHM_DATA_ROOT}/current/terrain" "${SHM_DATA_ROOT}/current/terrain.prev"
fi
mv "$STAGING/terrain" "${SHM_DATA_ROOT}/current/terrain"
rm -rf "${SHM_DATA_ROOT}/current/terrain.prev"

STATE_TMP="$(mktemp)"
jq --arg manifest "${SHM_DATA_ROOT}/current/terrain/terrain-manifest.json" \
   --arg encoding "$ENCODING" \
   --arg built_at "$BUILT_AT" '
  .current.terrain = {
    available: true,
    manifest_path: $manifest,
    selected_hash: .current.selected_hash,
    dataset_ids: (.current.dataset_ids // []),
    encoding: $encoding,
    built_at: $built_at,
    contours: {
      available: false,
      enabled: false,
      reason: "deferred"
    }
  }
' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

echo "Installed terrain tiles into ${SHM_DATA_ROOT}/current/terrain"
echo "Manifest: ${SHM_DATA_ROOT}/current/terrain/terrain-manifest.json"

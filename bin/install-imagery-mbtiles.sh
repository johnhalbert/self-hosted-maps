#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
require_cmd sha256sum
require_cmd stat
ensure_imagery_state

PYTHON_BIN="${SHM_PYTHON_BIN:-python3}"

usage() {
  cat >&2 <<'USAGE'
usage: install-imagery-mbtiles.sh <id> <name> <mbtiles-path> --attribution <text> --license-name <name> [options]

Options:
  --license-url <url>    License URL to show in the UI.
  --source-url <url>     Original source URL or local provenance note.
  --usage-notes <text>   Operator notes about allowed use.
  --opacity <0..1>       Default opacity. Defaults to 0.75.
  --disabled             Install without making this the visible imagery overlay.
USAGE
  exit 1
}

if [[ "$#" -lt 3 ]]; then
  usage
fi

OVERLAY_ID="$1"
OVERLAY_NAME="$2"
SOURCE_MBTILES="$3"
shift 3

ATTRIBUTION=""
LICENSE_NAME=""
LICENSE_URL=""
SOURCE_URL=""
USAGE_NOTES=""
OPACITY="0.75"
ENABLE_AFTER=true

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --attribution)
      ATTRIBUTION="${2:?missing attribution value}"
      shift 2
      ;;
    --license-name)
      LICENSE_NAME="${2:?missing license name value}"
      shift 2
      ;;
    --license-url)
      LICENSE_URL="${2:?missing license url value}"
      shift 2
      ;;
    --source-url)
      SOURCE_URL="${2:?missing source url value}"
      shift 2
      ;;
    --usage-notes)
      USAGE_NOTES="${2:?missing usage notes value}"
      shift 2
      ;;
    --opacity)
      OPACITY="${2:?missing opacity value}"
      shift 2
      ;;
    --disabled)
      ENABLE_AFTER=false
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      ;;
  esac
done

if [[ ! "$OVERLAY_ID" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]]; then
  echo "Invalid imagery id. Use lowercase letters, numbers, dots, underscores, and dashes; max 64 chars." >&2
  exit 1
fi
if [[ -z "$ATTRIBUTION" ]]; then
  echo "Imagery attribution is required." >&2
  exit 1
fi
if [[ -z "$LICENSE_NAME" ]]; then
  echo "Imagery license name is required." >&2
  exit 1
fi
if [[ ! -f "$SOURCE_MBTILES" ]]; then
  echo "MBTiles file not found: $SOURCE_MBTILES" >&2
  exit 1
fi

mkdir -p "$SHM_IMAGERY_ROOT"
STAGE_DIR="$(mktemp -d "${SHM_IMAGERY_ROOT}/.install.${OVERLAY_ID}.XXXXXX")"
cleanup() {
  rm -rf "$STAGE_DIR"
}
trap cleanup EXIT

STAGED_PATH="$STAGE_DIR/tiles.mbtiles"
cp "$SOURCE_MBTILES" "$STAGED_PATH"

VALIDATION_JSON="$("$PYTHON_BIN" - "$STAGED_PATH" "$OPACITY" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    opacity = float(sys.argv[2])
except ValueError as exc:
    raise SystemExit("Opacity must be a number.") from exc
if opacity < 0 or opacity > 1:
    raise SystemExit("Opacity must be between 0 and 1.")

content_types = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

def normalize_format(value):
    value = (value or "").strip().lower()
    if value == "jpeg":
        return "jpg"
    if value not in {"png", "jpg", "webp"}:
        raise SystemExit("MBTiles metadata format must be png, jpg/jpeg, or webp.")
    return value

def magic_matches(body, tile_format):
    if tile_format == "png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if tile_format == "jpg":
        return body.startswith(b"\xff\xd8\xff")
    if tile_format == "webp":
        return len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP"
    return False

uri = f"{path.resolve().as_uri()}?mode=ro"
with sqlite3.connect(uri, uri=True) as conn:
    tables = {
        row[0]
        for row in conn.execute(
            "select name from sqlite_master where type = 'table' and name in ('metadata', 'tiles')"
        )
    }
    if tables != {"metadata", "tiles"}:
        raise SystemExit("MBTiles must contain metadata and tiles tables.")
    metadata = {str(k): str(v) for k, v in conn.execute("select name, value from metadata")}
    zoom_min, zoom_max = conn.execute("select min(zoom_level), max(zoom_level) from tiles").fetchone()
    sample = conn.execute("select tile_data from tiles limit 1").fetchone()

if zoom_min is None or zoom_max is None or sample is None:
    raise SystemExit("MBTiles must contain at least one tile.")

tile_format = normalize_format(metadata.get("format"))
if not magic_matches(sample[0], tile_format):
    raise SystemExit("Sample tile bytes do not match MBTiles metadata format.")

def int_metadata(name, fallback):
    value = metadata.get(name)
    if value in (None, ""):
        return int(fallback)
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"MBTiles metadata {name} must be an integer.") from exc

def bounds_metadata():
    value = metadata.get("bounds")
    if not value:
        return [-180, -85.0511, 180, 85.0511]
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise SystemExit("MBTiles metadata bounds must contain four comma-separated values.")
    try:
        bounds = [float(part) for part in parts]
    except ValueError as exc:
        raise SystemExit("MBTiles metadata bounds must be numeric.") from exc
    west, south, east, north = bounds
    if west < -180 or east > 180 or south < -90 or north > 90 or west >= east or south >= north:
        raise SystemExit("MBTiles metadata bounds are invalid.")
    return bounds

tile_size = int_metadata("tile_size", 256)
if tile_size not in {256, 512}:
    raise SystemExit("MBTiles metadata tile_size must be 256 or 512 when present.")

print(json.dumps({
    "format": "mbtiles",
    "tile_format": tile_format,
    "content_type": content_types[tile_format],
    "bounds": bounds_metadata(),
    "minzoom": int_metadata("minzoom", zoom_min),
    "maxzoom": int_metadata("maxzoom", zoom_max),
    "tile_size": tile_size,
    "opacity": opacity,
}, separators=(",", ":")))
PY
)"

BYTES="$(stat -c %s "$STAGED_PATH")"
SHA256="$(sha256sum "$STAGED_PATH" | awk '{print $1}')"
INSTALLED_AT="$(date -u +%FT%TZ)"
DEST_DIR="${SHM_IMAGERY_ROOT}/${OVERLAY_ID}"
DEST_PATH="${DEST_DIR}/tiles.mbtiles"

acquire_mutation_lock
ensure_imagery_state

if [[ -e "$DEST_DIR" ]]; then
  echo "Imagery overlay already exists: $OVERLAY_ID" >&2
  exit 1
fi

META_JSON="$(jq -n \
  --arg id "$OVERLAY_ID" \
  --arg name "$OVERLAY_NAME" \
  --arg path "$DEST_PATH" \
  --arg attribution "$ATTRIBUTION" \
  --arg license_name "$LICENSE_NAME" \
  --arg license_url "$LICENSE_URL" \
  --arg source_url "$SOURCE_URL" \
  --arg source_sha256 "$SHA256" \
  --arg usage_notes "$USAGE_NOTES" \
  --arg installed_at "$INSTALLED_AT" \
  --arg updated_at "$INSTALLED_AT" \
  --arg checked_at "$INSTALLED_AT" \
  --arg sha256 "$SHA256" \
  --argjson bytes "$BYTES" \
  --argjson validated "$VALIDATION_JSON" \
  '{
    id: $id,
    name: $name,
    format: $validated.format,
    tile_format: $validated.tile_format,
    content_type: $validated.content_type,
    path: $path,
    bounds: $validated.bounds,
    minzoom: $validated.minzoom,
    maxzoom: $validated.maxzoom,
    tile_size: $validated.tile_size,
    opacity: $validated.opacity,
    attribution: $attribution,
    license: {
      name: $license_name,
      url: (if ($license_url | length) > 0 then $license_url else null end)
    },
    usage_notes: $usage_notes,
    source: {
      type: "local_mbtiles",
      url: $source_url,
      sha256: $source_sha256
    },
    available: true,
    bytes: $bytes,
    sha256: $sha256,
    checked_at: $checked_at,
    installed_at: $installed_at,
    updated_at: $updated_at
  }')"

mv "$STAGE_DIR" "$DEST_DIR"
trap - EXIT

STATE_TMP="$(mktemp)"
jq \
  --arg id "$OVERLAY_ID" \
  --argjson meta "$META_JSON" \
  --argjson enable "$ENABLE_AFTER" \
  '
    .imagery.installed[$id] = $meta
    | .imagery.order = (((.imagery.order // []) - [$id]) + [$id])
    | if $enable then .imagery.enabled = [$id] else .imagery.enabled = ((.imagery.enabled // []) - [$id]) end
  ' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

log "Installed imagery overlay $OVERLAY_ID ($OVERLAY_NAME)"

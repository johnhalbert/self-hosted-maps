#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
require_cmd osmium
require_cmd sqlite3
ensure_state_file
acquire_mutation_lock

extract_bbox_from_pbf() {
  local pbf_path="$1"
  local bbox

  bbox="$(osmium fileinfo -e "$pbf_path" 2>/dev/null | awk '
    /^Data:/ {in_data=1; next}
    in_data && /Bounding box:/ {
      sub(/^.*Bounding box: \(/, "")
      sub(/\).*$/, "")
      gsub(/[[:space:]]/, "")
      print
      exit
    }
  ')"

  if [[ -z "$bbox" ]]; then
    bbox="$(osmium fileinfo -e "$pbf_path" 2>/dev/null | awk '
      /^Header:/ {in_header=1; next}
      /^Data:/ {in_header=0}
      in_header && /^[[:space:]]+\(/ {
        gsub(/[()[:space:]]/, "")
        print
        exit
      }
    ')"
  fi

  [[ -n "$bbox" ]] || return 1
  printf '%s\n' "$bbox"
}

update_mbtiles_bounds_metadata() {
  local mbtiles_path="$1"
  shift
  local pbf_paths=("$@")
  local min_lon=""
  local min_lat=""
  local max_lon=""
  local max_lat=""
  local bbox bbox_min_lon bbox_min_lat bbox_max_lon bbox_max_lat current_center zoom_level center_lon center_lat bounds_value center_value

  for pbf_path in "${pbf_paths[@]}"; do
    bbox="$(extract_bbox_from_pbf "$pbf_path")" || {
      echo "Unable to determine bounding box for $pbf_path" >&2
      return 1
    }

    IFS=, read -r bbox_min_lon bbox_min_lat bbox_max_lon bbox_max_lat <<< "$bbox"

    if [[ -z "$min_lon" ]]; then
      min_lon="$bbox_min_lon"
      min_lat="$bbox_min_lat"
      max_lon="$bbox_max_lon"
      max_lat="$bbox_max_lat"
      continue
    fi

    min_lon="$(awk -v a="$min_lon" -v b="$bbox_min_lon" 'BEGIN { printf "%.7f", (a < b ? a : b) }')"
    min_lat="$(awk -v a="$min_lat" -v b="$bbox_min_lat" 'BEGIN { printf "%.7f", (a < b ? a : b) }')"
    max_lon="$(awk -v a="$max_lon" -v b="$bbox_max_lon" 'BEGIN { printf "%.7f", (a > b ? a : b) }')"
    max_lat="$(awk -v a="$max_lat" -v b="$bbox_max_lat" 'BEGIN { printf "%.7f", (a > b ? a : b) }')"
  done

  center_lon="$(awk -v a="$min_lon" -v b="$max_lon" 'BEGIN { printf "%.7f", (a + b) / 2 }')"
  center_lat="$(awk -v a="$min_lat" -v b="$max_lat" 'BEGIN { printf "%.7f", (a + b) / 2 }')"

  current_center="$(sqlite3 "$mbtiles_path" "select value from metadata where name='center';")"
  zoom_level="$(printf '%s\n' "$current_center" | awk -F, 'NF >= 3 && $3 ~ /^-?[0-9]+(\.[0-9]+)?$/ { print $3; exit }')"
  [[ -n "$zoom_level" ]] || zoom_level="7"

  bounds_value="${min_lon},${min_lat},${max_lon},${max_lat}"
  center_value="${center_lon},${center_lat},${zoom_level}"

  sqlite3 "$mbtiles_path" <<SQL
DELETE FROM metadata WHERE name IN ('bounds', 'center');
INSERT INTO metadata(name, value) VALUES ('bounds', '$bounds_value');
INSERT INTO metadata(name, value) VALUES ('center', '$center_value');
SQL

  echo "Updated MBTiles metadata bounds to $bounds_value"
  echo "Updated MBTiles metadata center to $center_value"
}

TILEMAKER_BIN="/usr/local/bin/tilemaker"
if [[ ! -x "$TILEMAKER_BIN" ]]; then
  TILEMAKER_BIN="$(command -v tilemaker)"
fi

if [[ -z "${TILEMAKER_BIN:-}" ]]; then
  echo "tilemaker not found" >&2
  exit 1
fi

mapfile -t DATASET_IDS < <(printf '%s\n' "$@" | sed '/^$/d' | sort -u)
if [[ "${#DATASET_IDS[@]}" -eq 0 ]]; then
  echo "No dataset ids supplied." >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BUILD_DIR="$SHM_SELECTED_BUILD_DIR/$STAMP"
TMP_DIR="${SHM_DATA_ROOT}/current.next"
LOG_FILE="${SHM_LOG_ROOT}/rebuild-selected.log"
mkdir -p "$BUILD_DIR" "$TMP_DIR" "$SHM_LOG_ROOT"
exec >> "$LOG_FILE" 2>&1

echo "[$(date '+%F %T')] rebuilding dataset set"
echo "Dataset ids: ${DATASET_IDS[*]}"

PBF_PATHS=()
for dataset_id in "${DATASET_IDS[@]}"; do
  pbf_path="$(jq -r --arg id "$dataset_id" '.installed[$id].pbf_path // empty' "$SHM_STATE_FILE")"
  if [[ -z "$pbf_path" || ! -f "$pbf_path" ]]; then
    echo "Missing PBF for dataset $dataset_id" >&2
    exit 1
  fi
  PBF_PATHS+=("$pbf_path")
done

INPUT_PBF="${PBF_PATHS[0]}"
if [[ "${#PBF_PATHS[@]}" -gt 1 ]]; then
  INPUT_PBF="$BUILD_DIR/merged.osm.pbf"
  osmium merge --overwrite -o "$INPUT_PBF" "${PBF_PATHS[@]}"
fi

"$TILEMAKER_BIN" \
  --input "$INPUT_PBF" \
  --output "$BUILD_DIR/openmaptiles.mbtiles" \
  --config "${SHM_INSTALL_ROOT}/config/tilemaker/config.json" \
  --process "${SHM_INSTALL_ROOT}/config/tilemaker/process.lua"

sqlite3 "$BUILD_DIR/openmaptiles.mbtiles" "select count(*) from tiles;" | grep -Eq '^[1-9][0-9]*$'
update_mbtiles_bounds_metadata "$BUILD_DIR/openmaptiles.mbtiles" "${PBF_PATHS[@]}"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
cp "$BUILD_DIR/openmaptiles.mbtiles" "$TMP_DIR/openmaptiles.mbtiles"
rm -rf "${SHM_DATA_ROOT}/current.prev"
mv "${SHM_DATA_ROOT}/current" "${SHM_DATA_ROOT}/current.prev" 2>/dev/null || true
mv "$TMP_DIR" "${SHM_DATA_ROOT}/current"
rm -rf "${SHM_DATA_ROOT}/current.prev"

DATASET_IDS_JSON="$(printf '%s\n' "${DATASET_IDS[@]}" | jq -Rsc 'split("\n")[:-1]')"
CURRENT_HASH="$(printf '%s\n' "${DATASET_IDS[@]}" | sha256sum | awk '{print $1}')"

STATE_TMP="$(mktemp)"
jq --arg hash "$CURRENT_HASH" \
   --arg artifact "${SHM_DATA_ROOT}/current/openmaptiles.mbtiles" \
   --arg rebuilt_at "$(date -u +%FT%TZ)" \
   --argjson dataset_ids "$DATASET_IDS_JSON" '
  .current.selected_hash = $hash
  | .current.artifact_path = $artifact
  | .current.rebuilt_at = $rebuilt_at
  | .current.dataset_ids = $dataset_ids
' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

systemctl restart self-hosted-maps-tileserver.service

echo "[$(date '+%F %T')] dataset rebuild complete"

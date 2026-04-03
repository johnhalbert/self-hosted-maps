#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
require_cmd osmium
require_cmd sqlite3
ensure_state_file

TILEMAKER_BIN="/usr/local/bin/tilemaker"
if [[ ! -x "$TILEMAKER_BIN" ]]; then
  TILEMAKER_BIN="$(command -v tilemaker)"
fi

if [[ -z "${TILEMAKER_BIN:-}" ]]; then
  echo "tilemaker not found" >&2
  exit 1
fi

mapfile -t SELECTED_IDS < <(jq -r '.selected[]?' "$SHM_STATE_FILE")
if [[ "${#SELECTED_IDS[@]}" -eq 0 ]]; then
  echo "No datasets selected. Use select-datasets.sh or map-manager.sh first." >&2
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BUILD_DIR="$SHM_SELECTED_BUILD_DIR/$STAMP"
TMP_DIR="${SHM_DATA_ROOT}/current.next"
LOG_FILE="${SHM_LOG_ROOT}/rebuild-selected.log"
mkdir -p "$BUILD_DIR" "$TMP_DIR" "$SHM_LOG_ROOT"
exec >> "$LOG_FILE" 2>&1

echo "[$(date '+%F %T')] rebuilding selected datasets"
echo "Selected datasets: ${SELECTED_IDS[*]}"

PBF_PATHS=()
for dataset_id in "${SELECTED_IDS[@]}"; do
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

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
cp "$BUILD_DIR/openmaptiles.mbtiles" "$TMP_DIR/openmaptiles.mbtiles"
rm -rf "${SHM_DATA_ROOT}/current.prev"
mv "${SHM_DATA_ROOT}/current" "${SHM_DATA_ROOT}/current.prev" 2>/dev/null || true
mv "$TMP_DIR" "${SHM_DATA_ROOT}/current"
rm -rf "${SHM_DATA_ROOT}/current.prev"

mapfile -t SORTED_IDS < <(printf '%s\n' "${SELECTED_IDS[@]}" | sort -u)
DATASET_IDS_JSON="$(printf '%s\n' "${SORTED_IDS[@]}" | jq -Rsc 'split("\n")[:-1]')"
SELECTED_HASH="$(printf '%s\n' "${SORTED_IDS[@]}" | sha256sum | awk '{print $1}')"

STATE_TMP="$(mktemp)"
jq --arg hash "$SELECTED_HASH" \
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

echo "[$(date '+%F %T')] selected rebuild complete"

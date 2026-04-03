#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd curl
require_cmd jq
ensure_state_file

if [[ "$#" -lt 1 ]]; then
  echo "usage: install-dataset.sh <dataset-id> [--select] [--rebuild]" >&2
  exit 1
fi

DATASET_ID="$1"
shift
SELECT_AFTER=false
REBUILD_AFTER=false

for arg in "$@"; do
  case "$arg" in
    --select) SELECT_AFTER=true ;;
    --rebuild) REBUILD_AFTER=true ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

DATASET_JSON="$($SHM_BIN_DIR/find-dataset.sh "$DATASET_ID")"
NAME="$(jq -r '.name' <<<"$DATASET_JSON")"
PARENT="$(jq -r '.parent' <<<"$DATASET_JSON")"
URL="$(jq -r '.download_url' <<<"$DATASET_JSON")"
BOUNDS_JSON="$(jq -c '.bounds // []' <<<"$DATASET_JSON")"
DATASET_DIR="$(dataset_dir_for_id "$DATASET_ID")"
PBF_PATH="$DATASET_DIR/source.osm.pbf"
INSTALLED_AT="$(date -u +%FT%TZ)"

mkdir -p "$DATASET_DIR"

if [[ ! -f "$PBF_PATH" ]]; then
  log "Downloading dataset $DATASET_ID"
  curl -L --fail --retry 5 -o "$PBF_PATH" "$URL"
else
  log "Dataset $DATASET_ID already downloaded"
fi

META_JSON="$(jq -n \
  --arg id "$DATASET_ID" \
  --arg name "$NAME" \
  --arg provider "geofabrik" \
  --arg parent "$PARENT" \
  --arg url "$URL" \
  --arg pbf "$PBF_PATH" \
  --arg dir "$DATASET_DIR" \
  --arg installed_at "$INSTALLED_AT" \
  --argjson bounds "$BOUNDS_JSON" \
  '{
    id: $id,
    name: $name,
    provider: $provider,
    parent: $parent,
    download_url: $url,
    pbf_path: $pbf,
    dataset_dir: $dir,
    installed_at: $installed_at,
    bounds: $bounds
  }')"

printf '%s\n' "$META_JSON" > "$DATASET_DIR/metadata.json"

STATE_TMP="$(mktemp)"
jq --arg id "$DATASET_ID" --argjson meta "$META_JSON" '.installed[$id] = $meta' "$SHM_STATE_FILE" > "$STATE_TMP"

if $SELECT_AFTER; then
  STATE_TMP2="$(mktemp)"
  jq --arg id "$DATASET_ID" '.selected = ((.selected // []) + [$id] | unique)' "$STATE_TMP" > "$STATE_TMP2"
  mv "$STATE_TMP2" "$STATE_TMP"
fi

mv "$STATE_TMP" "$SHM_STATE_FILE"

if $REBUILD_AFTER; then
  "$SHM_BIN_DIR/rebuild-selected.sh"
fi

log "Installed dataset $DATASET_ID ($NAME)"

#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd curl
require_cmd jq
ensure_state_file
acquire_mutation_lock

if [[ "$#" -lt 3 ]]; then
  echo "usage: install-dataset-url.sh <dataset-id> <dataset-name> <pbf-url> [--provider <provider>] [--select] [--rebuild]" >&2
  exit 1
fi

DATASET_ID="$1"
DATASET_NAME="$2"
PBF_URL="$3"
shift 3
PROVIDER="custom"
SELECT_AFTER=false
REBUILD_AFTER=false

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --provider)
      PROVIDER="${2:?missing provider value}"
      shift 2
      ;;
    --select)
      SELECT_AFTER=true
      shift
      ;;
    --rebuild)
      REBUILD_AFTER=true
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

DATASET_DIR="$(dataset_dir_for_id "$DATASET_ID")"
PBF_PATH="$DATASET_DIR/source.osm.pbf"
INSTALLED_AT="$(date -u +%FT%TZ)"
mkdir -p "$DATASET_DIR"

if [[ ! -f "$PBF_PATH" ]]; then
  log "Downloading dataset $DATASET_ID from $PBF_URL"
  curl -L --fail --retry 5 -o "$PBF_PATH" "$PBF_URL"
else
  log "Dataset $DATASET_ID already downloaded"
fi

META_JSON="$(jq -n \
  --arg id "$DATASET_ID" \
  --arg name "$DATASET_NAME" \
  --arg provider "$PROVIDER" \
  --arg url "$PBF_URL" \
  --arg pbf "$PBF_PATH" \
  --arg dir "$DATASET_DIR" \
  --arg installed_at "$INSTALLED_AT" \
  '{
    id: $id,
    name: $name,
    provider: $provider,
    parent: "",
    download_url: $url,
    pbf_path: $pbf,
    dataset_dir: $dir,
    installed_at: $installed_at,
    bounds: []
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
  bash "$SHM_BIN_DIR/rebuild-selected.sh"
fi

log "Installed dataset $DATASET_ID ($DATASET_NAME)"

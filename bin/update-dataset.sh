#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd curl
require_cmd jq
ensure_state_file

if [[ "$#" -lt 1 ]]; then
  echo "usage: update-dataset.sh <dataset-id> [--rebuild] [--refresh-catalog]" >&2
  exit 1
fi

DATASET_ID="$1"
shift
REBUILD_AFTER=false
REFRESH_CATALOG=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild)
      REBUILD_AFTER=true
      shift
      ;;
    --refresh-catalog)
      REFRESH_CATALOG=true
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if ! jq -e --arg id "$DATASET_ID" '.installed[$id] != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
  echo "Unknown dataset: $DATASET_ID" >&2
  exit 1
fi

provider="$(jq -r --arg id "$DATASET_ID" '.installed[$id].provider // "unknown"' "$SHM_STATE_FILE")"
name="$(jq -r --arg id "$DATASET_ID" '.installed[$id].name // $id' "$SHM_STATE_FILE")"
old_url="$(jq -r --arg id "$DATASET_ID" '.installed[$id].download_url // ""' "$SHM_STATE_FILE")"
dataset_dir="$(jq -r --arg id "$DATASET_ID" '.installed[$id].dataset_dir // empty' "$SHM_STATE_FILE")"
pbf_path="$(jq -r --arg id "$DATASET_ID" '.installed[$id].pbf_path // empty' "$SHM_STATE_FILE")"
old_bounds="$(jq -c --arg id "$DATASET_ID" '.installed[$id].bounds // []' "$SHM_STATE_FILE")"
old_installed_at="$(jq -r --arg id "$DATASET_ID" '.installed[$id].installed_at // ""' "$SHM_STATE_FILE")"
old_size=0
if [[ -n "$pbf_path" && -f "$pbf_path" ]]; then
  old_size="$(stat -c %s "$pbf_path")"
fi

if $REFRESH_CATALOG || [[ ! -f "$SHM_GEOFABRIK_CATALOG" ]]; then
  "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
fi

new_url="$old_url"
new_bounds="$old_bounds"
new_parent="$(jq -r --arg id "$DATASET_ID" '.installed[$id].parent // ""' "$SHM_STATE_FILE")"

if [[ "$provider" == "geofabrik" ]]; then
  dataset_json="$($SHM_BIN_DIR/find-dataset.sh "$DATASET_ID")"
  new_url="$(jq -r '.download_url' <<<"$dataset_json")"
  new_bounds="$(jq -c '.bounds // []' <<<"$dataset_json")"
  new_parent="$(jq -r '.parent // ""' <<<"$dataset_json")"
fi

mkdir -p "$dataset_dir"
TMP_PBF="$dataset_dir/source.osm.pbf.new"
trap 'rm -f "$TMP_PBF"' EXIT

log "Updating dataset $DATASET_ID"
curl -L --fail --retry 5 -o "$TMP_PBF" "$new_url"
new_size="$(stat -c %s "$TMP_PBF")"
mv "$TMP_PBF" "$pbf_path"
trap - EXIT

updated_at="$(date -u +%FT%TZ)"
existing_history="$(jq -c --arg id "$DATASET_ID" '.installed[$id].update_history // []' "$SHM_STATE_FILE")"
META_JSON="$(jq -n \
  --arg id "$DATASET_ID" \
  --arg name "$name" \
  --arg provider "$provider" \
  --arg parent "$new_parent" \
  --arg url "$new_url" \
  --arg pbf "$pbf_path" \
  --arg dir "$dataset_dir" \
  --arg installed_at "$updated_at" \
  --argjson bounds "$new_bounds" \
  --argjson update_history "$existing_history" \
  '{
    id: $id,
    name: $name,
    provider: $provider,
    parent: $parent,
    download_url: $url,
    pbf_path: $pbf,
    dataset_dir: $dir,
    installed_at: $installed_at,
    bounds: $bounds,
    update_history: $update_history
  }')"

printf '%s\n' "$META_JSON" > "$dataset_dir/metadata.json"

STATE_TMP="$(mktemp)"
jq --arg id "$DATASET_ID" \
   --argjson meta "$META_JSON" \
   --arg previous_installed_at "$old_installed_at" \
   --arg updated_at "$updated_at" \
   --argjson previous_size_bytes "$old_size" \
   --argjson new_size_bytes "$new_size" '
  .installed[$id] = $meta
  | .installed[$id].update_history = ((.installed[$id].update_history // []) + [{
      previous_installed_at: $previous_installed_at,
      updated_at: $updated_at,
      previous_size_bytes: $previous_size_bytes,
      new_size_bytes: $new_size_bytes
    }])
' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

if $REBUILD_AFTER && jq -e --arg id "$DATASET_ID" '(.selected // []) | index($id) != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
  "$SHM_BIN_DIR/rebuild-selected.sh"
fi

log "Updated dataset $DATASET_ID ($name)"

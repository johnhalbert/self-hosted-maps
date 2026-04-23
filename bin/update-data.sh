#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file
acquire_mutation_lock

LOG_FILE="${SHM_LOG_ROOT}/pipeline.log"
mkdir -p "$SHM_LOG_ROOT"
exec >> "$LOG_FILE" 2>&1

echo "[$(date '+%F %T')] starting scheduled dataset refresh"

mapfile -t DATASET_IDS < <(jq -r '.current.dataset_ids[]?' "$SHM_STATE_FILE")
DATASET_SCOPE="current"
if [[ "${#DATASET_IDS[@]}" -eq 0 ]]; then
  mapfile -t DATASET_IDS < <(jq -r '.selected[]?' "$SHM_STATE_FILE")
  DATASET_SCOPE="selected"
fi

if [[ "${#DATASET_IDS[@]}" -eq 0 ]]; then
  echo "[$(date '+%F %T')] no datasets available for scheduled refresh"
  exit 0
fi

echo "Refreshing ${DATASET_SCOPE} dataset set: ${DATASET_IDS[*]}"

if bash "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null; then
  echo "Catalog refreshed before scheduled dataset update"
else
  echo "Catalog refresh failed; continuing with cached or installed metadata"
fi

UPDATED_ANY=false
CURRENT_ARTIFACT_MISSING=false
if [[ ! -f "${SHM_DATA_ROOT}/current/openmaptiles.mbtiles" ]]; then
  CURRENT_ARTIFACT_MISSING=true
  echo "Current MBTiles artifact is missing; a rebuild will be forced"
fi

for dataset_id in "${DATASET_IDS[@]}"; do
  update_status="unknown"
  if update_json="$(bash "$SHM_BIN_DIR/check-dataset-updates.sh" "$dataset_id" --json 2>/dev/null)"; then
    update_status="$(jq -r '.[0].update_status // "unknown"' <<<"$update_json")"
  fi

  case "$update_status" in
    up-to-date)
      echo "Dataset $dataset_id is up to date"
      ;;
    *)
      echo "Updating dataset $dataset_id (status: $update_status)"
      bash "$SHM_BIN_DIR/update-dataset.sh" "$dataset_id" >/dev/null
      UPDATED_ANY=true
      ;;
  esac
done

if [[ "$UPDATED_ANY" == "true" || "$CURRENT_ARTIFACT_MISSING" == "true" ]]; then
  echo "Rebuilding current artifact for dataset set: ${DATASET_IDS[*]}"
  bash "$SHM_BIN_DIR/rebuild-dataset-set.sh" "${DATASET_IDS[@]}"
else
  echo "No dataset changes detected; skipping rebuild"
fi

echo "[$(date '+%F %T')] scheduled dataset refresh complete"

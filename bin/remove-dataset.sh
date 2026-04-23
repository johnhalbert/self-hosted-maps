#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file
acquire_mutation_lock

DATASET_ID="${1:?usage: remove-dataset.sh <dataset-id>}"
DATASET_DIR="$(jq -r --arg id "$DATASET_ID" '.installed[$id].dataset_dir // empty' "$SHM_STATE_FILE")"

if [[ -n "$DATASET_DIR" && -d "$DATASET_DIR" ]]; then
  rm -rf "$DATASET_DIR"
fi

STATE_TMP="$(mktemp)"
jq --arg id "$DATASET_ID" 'del(.installed[$id]) | .selected = ((.selected // []) - [$id])' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

log "Removed dataset $DATASET_ID"

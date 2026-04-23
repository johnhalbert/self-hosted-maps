#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

mapfile -t SELECTED_IDS < <(jq -r '.selected[]?' "$SHM_STATE_FILE")
if [[ "${#SELECTED_IDS[@]}" -eq 0 ]]; then
  echo "No datasets selected. Use select-datasets.sh or map-manager.sh first." >&2
  exit 1
fi

exec bash "$SHM_BIN_DIR/rebuild-dataset-set.sh" "${SELECTED_IDS[@]}"

#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

DATASET_ID="${1:?usage: find-dataset.sh <dataset-id>}"

if [[ ! -f "$SHM_NORMALIZED_CATALOG" ]]; then
  "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
fi

jq -e --arg id "$DATASET_ID" '
  .[]
  | select(.id == $id)
' "$SHM_NORMALIZED_CATALOG"

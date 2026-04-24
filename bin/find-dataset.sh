#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

MODE="catalog"
if [[ "${1:-}" == "--installed" ]]; then
  MODE="installed"
  shift
fi

DATASET_ID="${1:?usage: find-dataset.sh [--installed] <dataset-id>}"

if [[ ! -f "$SHM_NORMALIZED_CATALOG" ]]; then
  bash "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
fi

if [[ "$MODE" == "installed" ]]; then
  find_catalog_entry_for_installed_dataset "$DATASET_ID" "$SHM_NORMALIZED_CATALOG"
else
  catalog_entry_by_id "$DATASET_ID" "$SHM_NORMALIZED_CATALOG"
fi

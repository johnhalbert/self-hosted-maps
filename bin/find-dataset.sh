#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

DATASET_ID="${1:?usage: find-dataset.sh <dataset-id>}"

if [[ ! -f "$SHM_GEOFABRIK_CATALOG" ]]; then
  "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
fi

jq -e --arg id "$DATASET_ID" '
  .features[]
  | select(.properties.id == $id)
  | .properties as $p
  | select($p.urls.pbf != null)
  | {
      id: $p.id,
      name: $p.name,
      parent: ($p.parent // ""),
      provider: "geofabrik",
      download_url: $p.urls.pbf,
      bounds: (.bbox // [])
    }
' "$SHM_GEOFABRIK_CATALOG"

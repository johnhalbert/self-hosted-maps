#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd curl
require_cmd jq
ensure_state_file

CATALOG_URL="https://download.geofabrik.de/index-v1-nogeom.json"
TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

log "Fetching Geofabrik catalog"
curl -fsSL "$CATALOG_URL" -o "$TMP_FILE"
jq empty "$TMP_FILE" >/dev/null
mv "$TMP_FILE" "$SHM_GEOFABRIK_CATALOG"
trap - EXIT

STATE_TMP="$(mktemp)"
jq --arg ts "$(date -u +%FT%TZ)" --arg cache "$SHM_GEOFABRIK_CATALOG" '
  .catalog.provider = "geofabrik"
  | .catalog.fetched_at = $ts
  | .catalog.cache_path = $cache
' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

echo "$SHM_GEOFABRIK_CATALOG"

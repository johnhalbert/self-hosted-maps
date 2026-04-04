#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd curl
require_cmd jq
require_cmd grep
require_cmd sed
ensure_state_file

GEOFABRIK_URL="https://download.geofabrik.de/index-v1-nogeom.json"
BBBIKE_INDEX_URL="https://download.bbbike.org/osm/bbbike/"

TMP_GEOFABRIK="$(mktemp)"
TMP_BBBIKE="$(mktemp)"
TMP_COMBINED="$(mktemp)"
trap 'rm -f "$TMP_GEOFABRIK" "$TMP_BBBIKE" "$TMP_COMBINED"' EXIT

log "Fetching Geofabrik catalog"
curl -fsSL "$GEOFABRIK_URL" -o "$TMP_GEOFABRIK"
jq empty "$TMP_GEOFABRIK" >/dev/null
mv "$TMP_GEOFABRIK" "$SHM_GEOFABRIK_CATALOG"

log "Fetching BBBike catalog"
curl -fsSL "$BBBIKE_INDEX_URL" -o "$TMP_BBBIKE"
mv "$TMP_BBBIKE" "$SHM_BBBIKE_INDEX_HTML"

jq '[
  .features[]
  | .properties as $p
  | select($p.urls.pbf != null)
  | {
      id: $p.id,
      source_id: $p.id,
      name: $p.name,
      provider: "geofabrik",
      parent: ($p.parent // ""),
      download_url: $p.urls.pbf,
      bounds: (.bbox // [])
    }
]' "$SHM_GEOFABRIK_CATALOG" > "$TMP_GEOFABRIK"

grep -oE 'href="[A-Za-z0-9._-]+/"' "$SHM_BBBIKE_INDEX_HTML" \
  | sed -E 's/^href="//; s/"$//; s/\/$//' \
  | sort -u \
  | jq -Rsc '[
      split("\n")[:-1]
      | map(select(. != "" and . != ".."))
      | .[]
      | {
          id: (("bbbike-" + .) | ascii_downcase),
          source_id: .,
          name: .,
          provider: "bbbike",
          parent: "bbbike",
          download_url: ("https://download.bbbike.org/osm/bbbike/" + . + "/" + . + ".osm.pbf"),
          bounds: []
        }
    ]' > "$TMP_BBBIKE"

jq -s 'add | sort_by(.provider, .name)' "$TMP_GEOFABRIK" "$TMP_BBBIKE" > "$TMP_COMBINED"
mv "$TMP_COMBINED" "$SHM_NORMALIZED_CATALOG"

STATE_TMP="$(mktemp)"
jq --arg ts "$(date -u +%FT%TZ)" \
   --arg cache "$SHM_NORMALIZED_CATALOG" \
   --arg geofabrik_cache "$SHM_GEOFABRIK_CATALOG" \
   --arg bbbike_cache "$SHM_BBBIKE_INDEX_HTML" '
  .catalog.provider = "multi"
  | .catalog.providers = ["geofabrik", "bbbike"]
  | .catalog.fetched_at = $ts
  | .catalog.cache_path = $cache
  | .catalog.sources = {
      geofabrik: {cache_path: $geofabrik_cache},
      bbbike: {cache_path: $bbbike_cache}
    }
' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

echo "$SHM_NORMALIZED_CATALOG"

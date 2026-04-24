#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd curl
require_cmd jq
require_cmd grep
require_cmd sed
ensure_state_file
acquire_mutation_lock

GEOFABRIK_URL="https://download.geofabrik.de/index-v1.json"
BBBIKE_INDEX_URL="https://download.bbbike.org/osm/bbbike/"

TMP_GEOFABRIK_RAW="$(mktemp)"
TMP_GEOFABRIK_CATALOG="$(mktemp)"
TMP_GEOFABRIK_BOUNDARIES="$(mktemp)"
TMP_BBBIKE_RAW="$(mktemp)"
TMP_BBBIKE_CATALOG="$(mktemp)"
TMP_COMBINED="$(mktemp)"
STATE_TMP="$(mktemp)"
trap 'rm -f "$TMP_GEOFABRIK_RAW" "$TMP_GEOFABRIK_CATALOG" "$TMP_GEOFABRIK_BOUNDARIES" "$TMP_BBBIKE_RAW" "$TMP_BBBIKE_CATALOG" "$TMP_COMBINED" "$STATE_TMP"' EXIT

log "Fetching Geofabrik catalog"
curl -fsSL "$GEOFABRIK_URL" -o "$TMP_GEOFABRIK_RAW"
jq empty "$TMP_GEOFABRIK_RAW" >/dev/null

log "Fetching BBBike catalog"
curl -fsSL "$BBBIKE_INDEX_URL" -o "$TMP_BBBIKE_RAW"

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
      bounds: (.bbox // []),
      boundary_available: (
        (.geometry != null)
        and ((.geometry.type // "") == "Polygon" or (.geometry.type // "") == "MultiPolygon")
      )
    }
]' "$TMP_GEOFABRIK_RAW" > "$TMP_GEOFABRIK_CATALOG"

jq --arg ts "$(date -u +%FT%TZ)" '
  {
    generated_at: $ts,
    provider: "geofabrik",
    items: (
      [
        .features[]
        | .properties as $p
        | select($p.urls.pbf != null)
        | select(
            (.geometry != null)
            and ((.geometry.type // "") == "Polygon" or (.geometry.type // "") == "MultiPolygon")
          )
        | {
            key: $p.id,
            value: {
              id: $p.id,
              source_id: $p.id,
              name: $p.name,
              provider: "geofabrik",
              parent: ($p.parent // ""),
              geometry: .geometry
            }
          }
      ]
      | from_entries
    )
  }
' "$TMP_GEOFABRIK_RAW" > "$TMP_GEOFABRIK_BOUNDARIES"

grep -oE 'href="[A-Za-z0-9._-]+/"' "$TMP_BBBIKE_RAW" \
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
          bounds: [],
          boundary_available: false
        }
    ]' > "$TMP_BBBIKE_CATALOG"

jq -s 'add | sort_by(.provider, .name)' "$TMP_GEOFABRIK_CATALOG" "$TMP_BBBIKE_CATALOG" > "$TMP_COMBINED"

mv "$TMP_GEOFABRIK_RAW" "$SHM_GEOFABRIK_CATALOG"
mv "$TMP_GEOFABRIK_BOUNDARIES" "$SHM_CATALOG_BOUNDARY_INDEX"
mv "$TMP_BBBIKE_RAW" "$SHM_BBBIKE_INDEX_HTML"
mv "$TMP_COMBINED" "$SHM_NORMALIZED_CATALOG"

jq --arg ts "$(date -u +%FT%TZ)" \
   --arg cache "$SHM_NORMALIZED_CATALOG" \
   --arg geofabrik_cache "$SHM_GEOFABRIK_CATALOG" \
   --arg boundary_index "$SHM_CATALOG_BOUNDARY_INDEX" \
   --arg bbbike_cache "$SHM_BBBIKE_INDEX_HTML" '
  .catalog.provider = "multi"
  | .catalog.providers = ["geofabrik", "bbbike"]
  | .catalog.fetched_at = $ts
  | .catalog.cache_path = $cache
  | .catalog.sources = {
      geofabrik: {
        cache_path: $geofabrik_cache,
        boundary_index_path: $boundary_index
      },
      bbbike: {cache_path: $bbbike_cache}
    }
' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

echo "$SHM_NORMALIZED_CATALOG"

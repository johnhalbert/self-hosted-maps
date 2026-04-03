#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

if [[ ! -f "$SHM_GEOFABRIK_CATALOG" ]]; then
  "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
fi

QUERY="${1:-}"
QUERY_LOWER="$(printf '%s' "$QUERY" | tr '[:upper:]' '[:lower:]')"

jq -r --arg q "$QUERY_LOWER" '
  .features[]
  | .properties as $p
  | select($p.urls.pbf != null)
  | select(
      $q == ""
      or (($p.name // "" | ascii_downcase) | contains($q))
      or (($p.id // "" | ascii_downcase) | contains($q))
      or (($p.parent // "" | ascii_downcase) | contains($q))
    )
  | [$p.id, $p.name, ($p.parent // ""), $p.urls.pbf]
  | @tsv
' "$SHM_GEOFABRIK_CATALOG" | sort -t$'\t' -k2,2

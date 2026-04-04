#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

if [[ ! -f "$SHM_NORMALIZED_CATALOG" ]]; then
  bash "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
fi

QUERY="${1:-}"
QUERY_LOWER="$(printf '%s' "$QUERY" | tr '[:upper:]' '[:lower:]')"

jq -r --arg q "$QUERY_LOWER" '
  .[]
  | select(
      $q == ""
      or ((.name // "" | ascii_downcase) | contains($q))
      or ((.id // "" | ascii_downcase) | contains($q))
      or ((.provider // "" | ascii_downcase) | contains($q))
      or ((.parent // "" | ascii_downcase) | contains($q))
    )
  | [
      .id,
      .name,
      (if (.parent // "") == "" then .provider else (.provider + ":" + .parent) end),
      .download_url
    ]
  | @tsv
' "$SHM_NORMALIZED_CATALOG" | sort -t$'\t' -k2,2

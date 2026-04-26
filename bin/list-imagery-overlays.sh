#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_imagery_state

human_size() {
  local bytes="$1"
  if [[ -z "$bytes" || "$bytes" == "0" ]]; then
    printf '0B\n'
    return 0
  fi
  numfmt --to=iec-i --suffix=B "$bytes" 2>/dev/null || printf '%sB\n' "$bytes"
}

if [[ "${1:-}" == "--json" ]]; then
  jq '.imagery' "$SHM_STATE_FILE"
  exit 0
fi

jq -r '
  (.imagery.order // []) as $order
  | (.imagery.installed // {}) as $installed
  | (($order | map(select($installed[.] != null))) + (($installed | keys | sort) - $order))[]
' "$SHM_STATE_FILE" | while IFS= read -r overlay_id; do
  metadata="$(jq -c --arg id "$overlay_id" '.imagery.installed[$id]' "$SHM_STATE_FILE")"
  name="$(jq -r '.name // empty' <<<"$metadata")"
  tile_format="$(jq -r '.tile_format // empty' <<<"$metadata")"
  content_type="$(jq -r '.content_type // empty' <<<"$metadata")"
  bytes="$(jq -r '.bytes // 0' <<<"$metadata")"
  installed_at="$(jq -r '.installed_at // ""' <<<"$metadata")"
  available="$(jq -r '.available // false' <<<"$metadata")"
  if jq -e --arg id "$overlay_id" '(.imagery.enabled // []) | index($id) != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
    status="enabled"
  else
    status="installed"
  fi
  if [[ "$available" != "true" ]]; then
    status="${status},unavailable"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$overlay_id" \
    "${name:-$overlay_id}" \
    "$tile_format" \
    "$content_type" \
    "$status" \
    "$(human_size "$bytes")" \
    "$installed_at"
done

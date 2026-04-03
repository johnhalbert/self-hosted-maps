#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

human_size() {
  local bytes="$1"
  if [[ -z "$bytes" || "$bytes" == "0" ]]; then
    printf '0B\n'
    return 0
  fi
  numfmt --to=iec-i --suffix=B "$bytes" 2>/dev/null || printf '%sB\n' "$bytes"
}

state_json="$(cat "$SHM_STATE_FILE")"
current_ready=false
if jq -e '.current.rebuilt_at != null and .current.artifact_path != null' <<<"$state_json" >/dev/null 2>&1; then
  current_ready=true
fi

jq -r '.installed | keys[]?' "$SHM_STATE_FILE" | while IFS= read -r dataset_id; do
  name="$(jq -r --arg id "$dataset_id" '.installed[$id].name // $id' "$SHM_STATE_FILE")"
  provider="$(jq -r --arg id "$dataset_id" '.installed[$id].provider // "unknown"' "$SHM_STATE_FILE")"
  pbf_path="$(jq -r --arg id "$dataset_id" '.installed[$id].pbf_path // ""' "$SHM_STATE_FILE")"
  dataset_dir="$(jq -r --arg id "$dataset_id" '.installed[$id].dataset_dir // ""' "$SHM_STATE_FILE")"
  installed_at="$(jq -r --arg id "$dataset_id" '.installed[$id].installed_at // ""' "$SHM_STATE_FILE")"

  status_parts=()
  if jq -e --arg id "$dataset_id" '(.selected // []) | index($id) != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
    status_parts+=(selected)
    if $current_ready; then
      status_parts+=(current)
    fi
  else
    status_parts+=(installed)
  fi
  if jq -e --arg id "$dataset_id" '.bootstrap.dataset_id? == $id' "$SHM_STATE_FILE" >/dev/null 2>&1; then
    status_parts+=(bootstrap)
  fi

  pbf_bytes=0
  if [[ -n "$pbf_path" && -f "$pbf_path" ]]; then
    pbf_bytes="$(stat -c %s "$pbf_path")"
  fi

  dataset_bytes=0
  if [[ -n "$dataset_dir" && -d "$dataset_dir" ]]; then
    dataset_bytes="$(du -sb "$dataset_dir" | awk '{print $1}')"
  fi

  status_csv="$(IFS=, ; echo "${status_parts[*]}")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$dataset_id" \
    "$name" \
    "$provider" \
    "$status_csv" \
    "$(human_size "$pbf_bytes")" \
    "$(human_size "$dataset_bytes")" \
    "$installed_at"
done

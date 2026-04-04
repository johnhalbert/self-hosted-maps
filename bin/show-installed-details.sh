#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

DATASET_ID="${1:?usage: show-installed-details.sh <dataset-id>}"

human_size() {
  local bytes="$1"
  if [[ -z "$bytes" || "$bytes" == "0" ]]; then
    printf '0B\n'
    return 0
  fi
  numfmt --to=iec-i --suffix=B "$bytes" 2>/dev/null || printf '%sB\n' "$bytes"
}

metadata="$(jq -c --arg id "$DATASET_ID" '.installed[$id]' "$SHM_STATE_FILE")"
if [[ -z "$metadata" || "$metadata" == "null" ]]; then
  echo "Unknown dataset: $DATASET_ID" >&2
  exit 1
fi

name="$(jq -r '.name // empty' <<<"$metadata")"
provider="$(jq -r '.provider // "unknown"' <<<"$metadata")"
pbf_path="$(jq -r '.pbf_path // ""' <<<"$metadata")"
dataset_dir="$(jq -r '.dataset_dir // ""' <<<"$metadata")"
installed_at="$(jq -r '.installed_at // ""' <<<"$metadata")"
selected=false
part_of_current=false
bootstrap=false

if jq -e --arg id "$DATASET_ID" '(.selected // []) | index($id) != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
  selected=true
fi
if jq -e --arg id "$DATASET_ID" '(.current.dataset_ids // []) | index($id) != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
  part_of_current=true
fi
if jq -e --arg id "$DATASET_ID" '.bootstrap.dataset_id? == $id' "$SHM_STATE_FILE" >/dev/null 2>&1; then
  bootstrap=true
fi

pbf_size_bytes=0
if [[ -n "$pbf_path" && -f "$pbf_path" ]]; then
  pbf_size_bytes="$(stat -c %s "$pbf_path")"
fi

dataset_size_bytes=0
if [[ -n "$dataset_dir" && -d "$dataset_dir" ]]; then
  dataset_size_bytes="$(du -sb "$dataset_dir" | awk '{print $1}')"
fi

update_json="$(bash "$SHM_BIN_DIR/check-dataset-updates.sh" "$DATASET_ID" --json | jq '.[0]')"

jq -n \
  --arg id "$DATASET_ID" \
  --arg name "$name" \
  --arg provider "$provider" \
  --arg installed_at "$installed_at" \
  --arg pbf_path "$pbf_path" \
  --arg dataset_dir "$dataset_dir" \
  --arg pbf_size_human "$(human_size "$pbf_size_bytes")" \
  --arg dataset_size_human "$(human_size "$dataset_size_bytes")" \
  --argjson pbf_size_bytes "$pbf_size_bytes" \
  --argjson dataset_size_bytes "$dataset_size_bytes" \
  --argjson selected "$selected" \
  --argjson part_of_current "$part_of_current" \
  --argjson bootstrap "$bootstrap" \
  --argjson metadata "$metadata" \
  --argjson update "$update_json" \
  '{
    id: $id,
    name: $name,
    provider: $provider,
    installed_at: $installed_at,
    selected: $selected,
    part_of_current_build: $part_of_current,
    bootstrap_dataset: $bootstrap,
    pbf_path: $pbf_path,
    dataset_dir: $dataset_dir,
    pbf_size_bytes: $pbf_size_bytes,
    pbf_size_human: $pbf_size_human,
    dataset_size_bytes: $dataset_size_bytes,
    dataset_size_human: $dataset_size_human,
    metadata: $metadata,
    update_check: $update
  }'

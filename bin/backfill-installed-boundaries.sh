#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file
acquire_mutation_lock

BACKFILL_VERSION=1

if jq -e --argjson version "$BACKFILL_VERSION" '
  (.catalog.installed_boundary_backfill.version // 0) == $version
' "$SHM_STATE_FILE" >/dev/null 2>&1; then
  log "Installed boundary metadata backfill already completed"
  exit 0
fi

if [[ ! -f "$SHM_NORMALIZED_CATALOG" ]]; then
  echo "Missing catalog cache: $SHM_NORMALIZED_CATALOG" >&2
  exit 1
fi

WORK_STATE="$(mktemp)"
NEXT_STATE="$(mktemp)"
trap 'rm -f "$WORK_STATE" "$NEXT_STATE"' EXIT
cp "$SHM_STATE_FILE" "$WORK_STATE"

CATALOG_FETCHED_AT="$(jq -r '.catalog.fetched_at // ""' "$WORK_STATE")"
changed_ids=()

mapfile -t DATASET_IDS < <(jq -r '.installed | keys[]?' "$WORK_STATE")

for dataset_id in "${DATASET_IDS[@]}"; do
  source_id="$(jq -r --arg id "$dataset_id" '.installed[$id].source_id // ""' "$WORK_STATE")"
  provider="$(jq -r --arg id "$dataset_id" '.installed[$id].provider // "unknown"' "$WORK_STATE")"
  has_source_id_field=false
  if jq -e --arg id "$dataset_id" '
    .installed[$id] | has("source_id")
  ' "$WORK_STATE" >/dev/null 2>&1; then
    has_source_id_field=true
  fi
  has_boundary_available=false
  if jq -e --arg id "$dataset_id" '
    .installed[$id].boundary.available? | type == "boolean"
  ' "$WORK_STATE" >/dev/null 2>&1; then
    has_boundary_available=true
  fi

  if [[ "$has_source_id_field" == "true" && "$has_boundary_available" == "true" ]]; then
    continue
  fi

  next_source_id="$source_id"
  next_bounds="$(jq -c --arg id "$dataset_id" '.installed[$id].bounds // []' "$WORK_STATE")"
  boundary_json=""

  if catalog_json="$(find_catalog_entry_for_installed_dataset "$dataset_id" "$SHM_NORMALIZED_CATALOG" "$WORK_STATE" 2>/dev/null)"; then
    if [[ -z "$next_source_id" ]]; then
      next_source_id="$(jq -r '.source_id // ""' <<<"$catalog_json")"
    fi
    boundary_provider="$(jq -r '.provider // "unknown"' <<<"$catalog_json")"
    boundary_available="$(jq -r 'if (.boundary_available // false) then "true" else "false" end' <<<"$catalog_json")"
    boundary_reason=""
    if [[ "$boundary_available" != "true" ]]; then
      boundary_reason="$(default_boundary_reason_for_provider "$boundary_provider")"
    fi
    boundary_json="$(build_boundary_metadata_json "$boundary_available" "catalog" "$CATALOG_FETCHED_AT" "$boundary_reason")"
    if [[ "$(jq -r 'length' <<<"$next_bounds")" == "0" ]]; then
      next_bounds="$(jq -c '.bounds // []' <<<"$catalog_json")"
    fi
  else
    boundary_reason="$(default_boundary_reason_for_provider "$provider")"
    boundary_json="$(build_boundary_metadata_json false "none" "$CATALOG_FETCHED_AT" "$boundary_reason")"
  fi

  jq --arg id "$dataset_id" \
     --arg source_id "$next_source_id" \
     --argjson boundary "$boundary_json" \
     --argjson bounds "$next_bounds" '
    .installed[$id].source_id = (
      if (.installed[$id] | has("source_id")) then
        .installed[$id].source_id
      else
        $source_id
      end
    )
    | .installed[$id].boundary = ((.installed[$id].boundary // {}) + $boundary)
    | if ((.installed[$id].bounds // []) | length) == 0 and (($bounds | length) == 4)
      then .installed[$id].bounds = $bounds
      else .
      end
  ' "$WORK_STATE" > "$NEXT_STATE"
  mv "$NEXT_STATE" "$WORK_STATE"
  changed_ids+=("$dataset_id")
done

jq --arg ts "$(date -u +%FT%TZ)" --argjson version "$BACKFILL_VERSION" '
  .catalog.installed_boundary_backfill = {
    version: $version,
    completed_at: $ts
  }
' "$WORK_STATE" > "$NEXT_STATE"
mv "$NEXT_STATE" "$WORK_STATE"
mv "$WORK_STATE" "$SHM_STATE_FILE"

for dataset_id in "${changed_ids[@]}"; do
  dataset_dir="$(jq -r --arg id "$dataset_id" '.installed[$id].dataset_dir // ""' "$SHM_STATE_FILE")"
  if [[ -z "$dataset_dir" ]]; then
    continue
  fi
  mkdir -p "$dataset_dir"
  jq -c --arg id "$dataset_id" '.installed[$id]' "$SHM_STATE_FILE" > "$dataset_dir/metadata.json"
done

log "Backfilled installed boundary metadata for ${#changed_ids[@]} datasets"

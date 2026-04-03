#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
require_cmd curl
ensure_state_file

DATASET_ID=""
OUTPUT_JSON=false
REFRESH_CATALOG=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      OUTPUT_JSON=true
      shift
      ;;
    --refresh-catalog)
      REFRESH_CATALOG=true
      shift
      ;;
    *)
      if [[ -z "$DATASET_ID" ]]; then
        DATASET_ID="$1"
        shift
      else
        echo "Unknown argument: $1" >&2
        exit 1
      fi
      ;;
  esac
done

if $REFRESH_CATALOG || [[ ! -f "$SHM_NORMALIZED_CATALOG" ]]; then
  "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
fi

human_size() {
  local bytes="$1"
  if [[ -z "$bytes" || "$bytes" == "0" ]]; then
    printf '0B\n'
    return 0
  fi
  numfmt --to=iec-i --suffix=B "$bytes" 2>/dev/null || printf '%sB\n' "$bytes"
}

to_epoch() {
  local value="$1"
  if [[ -z "$value" || "$value" == "null" ]]; then
    printf '0\n'
    return 0
  fi
  date -u -d "$value" +%s 2>/dev/null || printf '0\n'
}

parse_header_value() {
  local header_name="$1"
  awk -v name="$header_name" 'BEGIN{IGNORECASE=1} $0 ~ "^" name ":" {sub(/^[^:]+:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit}'
}

build_record() {
  local id="$1"
  local name provider url installed_at pbf_path local_size catalog_url head_response remote_last_modified_raw remote_last_modified_iso remote_content_length update_status note
  name="$(jq -r --arg id "$id" '.installed[$id].name // $id' "$SHM_STATE_FILE")"
  provider="$(jq -r --arg id "$id" '.installed[$id].provider // "unknown"' "$SHM_STATE_FILE")"
  url="$(jq -r --arg id "$id" '.installed[$id].download_url // ""' "$SHM_STATE_FILE")"
  installed_at="$(jq -r --arg id "$id" '.installed[$id].installed_at // ""' "$SHM_STATE_FILE")"
  pbf_path="$(jq -r --arg id "$id" '.installed[$id].pbf_path // ""' "$SHM_STATE_FILE")"

  local_size=0
  if [[ -n "$pbf_path" && -f "$pbf_path" ]]; then
    local_size="$(stat -c %s "$pbf_path")"
  fi

  catalog_url=""
  if [[ -f "$SHM_NORMALIZED_CATALOG" ]]; then
    catalog_url="$(jq -r --arg id "$id" '.[] | select(.id == $id) | .download_url // empty' "$SHM_NORMALIZED_CATALOG" | head -1)"
  fi

  if [[ -n "$catalog_url" ]]; then
    url="$catalog_url"
  fi

  head_response=""
  if [[ -n "$url" ]]; then
    head_response="$(curl -fsSI -L "$url" 2>/dev/null || true)"
  fi

  remote_last_modified_raw=""
  remote_last_modified_iso=""
  remote_content_length=""
  update_status="unknown"
  note=""

  if [[ -n "$head_response" ]]; then
    remote_last_modified_raw="$(printf '%s\n' "$head_response" | parse_header_value 'Last-Modified')"
    remote_content_length="$(printf '%s\n' "$head_response" | parse_header_value 'Content-Length')"
    if [[ -n "$remote_last_modified_raw" ]]; then
      remote_last_modified_iso="$(date -u -d "$remote_last_modified_raw" +%FT%TZ 2>/dev/null || true)"
    fi

    remote_epoch="$(to_epoch "$remote_last_modified_iso")"
    installed_epoch="$(to_epoch "$installed_at")"

    if [[ "$remote_epoch" -gt 0 && "$installed_epoch" -gt 0 && "$remote_epoch" -gt "$installed_epoch" ]]; then
      update_status="update-available"
      note="remote Last-Modified is newer than installed_at"
    elif [[ -n "$remote_content_length" && "$local_size" -gt 0 && "$remote_content_length" != "$local_size" ]]; then
      update_status="update-available"
      note="remote Content-Length differs from local file size"
    else
      update_status="up-to-date"
    fi
  elif [[ -n "$url" ]]; then
    note="HEAD request failed"
  else
    note="no known download URL"
  fi

  jq -n \
    --arg id "$id" \
    --arg name "$name" \
    --arg provider "$provider" \
    --arg url "$url" \
    --arg installed_at "$installed_at" \
    --arg remote_last_modified "$remote_last_modified_iso" \
    --arg update_status "$update_status" \
    --arg note "$note" \
    --arg local_size_human "$(human_size "$local_size")" \
    --arg remote_size_human "$(human_size "${remote_content_length:-0}")" \
    --argjson local_size_bytes "$local_size" \
    --argjson remote_size_bytes "${remote_content_length:-0}" \
    '{
      id: $id,
      name: $name,
      provider: $provider,
      download_url: $url,
      installed_at: $installed_at,
      remote_last_modified: $remote_last_modified,
      local_size_bytes: $local_size_bytes,
      local_size_human: $local_size_human,
      remote_size_bytes: $remote_size_bytes,
      remote_size_human: $remote_size_human,
      update_status: $update_status,
      note: $note
    }'
}

records=()
if [[ -n "$DATASET_ID" ]]; then
  records+=("$(build_record "$DATASET_ID")")
else
  while IFS= read -r id; do
    records+=("$(build_record "$id")")
  done < <(jq -r '.installed | keys[]?' "$SHM_STATE_FILE")
fi

if $OUTPUT_JSON; then
  printf '%s\n' "${records[@]}" | jq -s .
else
  for record in "${records[@]}"; do
    jq -r '[.id, .name, .update_status, .remote_last_modified, .local_size_human, .remote_size_human, .note] | @tsv' <<<"$record"
  done
fi

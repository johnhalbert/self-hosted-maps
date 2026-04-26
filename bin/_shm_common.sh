#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

if [[ -f /etc/self-hosted-maps/self-hosted-maps.conf ]]; then
  # shellcheck disable=SC1091
  source /etc/self-hosted-maps/self-hosted-maps.conf
fi

: "${SHM_INSTALL_ROOT:=/opt/self-hosted-maps}"
: "${SHM_DATA_ROOT:=/var/lib/self-hosted-maps}"
: "${SHM_CONFIG_ROOT:=/etc/self-hosted-maps}"
: "${SHM_LOG_ROOT:=/var/log/self-hosted-maps}"
: "${SHM_RUNTIME_CONFIG_FILE:=${SHM_CONFIG_ROOT}/self-hosted-maps.runtime.conf}"

if [[ -f "$SHM_RUNTIME_CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$SHM_RUNTIME_CONFIG_FILE"
fi

SHM_COMMON_SOURCE="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
  SHM_COMMON_SOURCE="$(readlink -f "$SHM_COMMON_SOURCE" 2>/dev/null || printf '%s' "$SHM_COMMON_SOURCE")"
fi

SHM_BIN_DIR="$(cd "$(dirname "$SHM_COMMON_SOURCE")" && pwd)"
SHM_STATE_FILE="${SHM_STATE_FILE:-${SHM_CONFIG_ROOT}/datasets.json}"
SHM_CATALOG_DIR="${SHM_CATALOG_DIR:-${SHM_DATA_ROOT}/cache/catalog}"
SHM_GEOFABRIK_CATALOG="${SHM_GEOFABRIK_CATALOG:-${SHM_CATALOG_DIR}/geofabrik-index-v1.json}"
SHM_BBBIKE_INDEX_HTML="${SHM_BBBIKE_INDEX_HTML:-${SHM_CATALOG_DIR}/bbbike-index.html}"
SHM_NORMALIZED_CATALOG="${SHM_NORMALIZED_CATALOG:-${SHM_CATALOG_DIR}/catalog.json}"
SHM_CATALOG_BOUNDARY_INDEX="${SHM_CATALOG_BOUNDARY_INDEX:-${SHM_CATALOG_DIR}/geofabrik-boundary-index.json}"
SHM_DATASETS_DIR="${SHM_DATASETS_DIR:-${SHM_DATA_ROOT}/datasets}"
SHM_IMAGERY_ROOT="${SHM_IMAGERY_ROOT:-${SHM_DATA_ROOT}/imagery}"
SHM_SELECTED_BUILD_DIR="${SHM_SELECTED_BUILD_DIR:-${SHM_DATA_ROOT}/builds/selected}"
SHM_LOCK_DIR="${SHM_LOCK_DIR:-${SHM_DATA_ROOT}/locks}"
SHM_MUTATION_LOCK_FILE="${SHM_MUTATION_LOCK_FILE:-${SHM_LOCK_DIR}/mutation.lock}"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

ensure_state_file() {
  mkdir -p "$SHM_CONFIG_ROOT" "$SHM_CATALOG_DIR" "$SHM_DATASETS_DIR" "$SHM_IMAGERY_ROOT" "$SHM_SELECTED_BUILD_DIR" "$SHM_LOG_ROOT" "$SHM_LOCK_DIR"
  if [[ ! -f "$SHM_STATE_FILE" ]]; then
    cat > "$SHM_STATE_FILE" <<'JSON'
{
  "catalog": {
    "provider": "multi",
    "providers": [],
    "fetched_at": null,
    "cache_path": null,
    "sources": {},
    "installed_boundary_backfill": null
  },
  "installed": {},
  "selected": [],
  "imagery": {
    "schema_version": 1,
    "installed": {},
    "order": [],
    "enabled": []
  },
  "current": {
    "selected_hash": null,
    "artifact_path": null,
    "rebuilt_at": null,
    "dataset_ids": []
  },
  "bootstrap": {}
}
JSON
  fi
}

ensure_imagery_state() {
  require_cmd jq
  ensure_state_file
  local state_tmp
  state_tmp="$(mktemp)"
  jq '
    .imagery = ({
      schema_version: 1,
      installed: {},
      order: [],
      enabled: []
    } + (.imagery // {}))
    | if (.imagery.installed | type) != "object" then .imagery.installed = {} else . end
    | if (.imagery.order | type) != "array" then .imagery.order = [] else . end
    | if (.imagery.enabled | type) != "array" then .imagery.enabled = [] else . end
  ' "$SHM_STATE_FILE" > "$state_tmp"
  mv "$state_tmp" "$SHM_STATE_FILE"
}

acquire_mutation_lock() {
  if [[ "${SHM_MUTATION_LOCK_HELD:-0}" == "1" ]]; then
    return 0
  fi
  command -v flock >/dev/null 2>&1 || {
    echo "Missing required command: flock" >&2
    exit 1
  }
  mkdir -p "$SHM_LOCK_DIR"
  exec 9>"$SHM_MUTATION_LOCK_FILE"
  flock 9
  export SHM_MUTATION_LOCK_HELD=1
}

dataset_dir_for_id() {
  local dataset_id="$1"
  printf '%s/%s' "$SHM_DATASETS_DIR" "$dataset_id"
}

json_compact_array_from_args() {
  if [[ "$#" -eq 0 ]]; then
    printf '[]\n'
    return 0
  fi
  printf '%s\n' "$@" | jq -Rsc 'split("\n")[:-1] | unique'
}

catalog_entry_by_id() {
  local dataset_id="$1"
  local catalog_path="${2:-$SHM_NORMALIZED_CATALOG}"
  jq -ce --arg id "$dataset_id" '
    first(.[] | select((.id // "") == $id))
  ' "$catalog_path"
}

find_catalog_entry_for_installed_dataset() {
  local dataset_id="$1"
  local catalog_path="${2:-$SHM_NORMALIZED_CATALOG}"
  local state_path="${3:-$SHM_STATE_FILE}"
  local source_id download_url result

  source_id="$(jq -r --arg id "$dataset_id" '.installed[$id].source_id // ""' "$state_path")"
  download_url="$(jq -r --arg id "$dataset_id" '.installed[$id].download_url // ""' "$state_path")"
  result=""

  if [[ -n "$source_id" ]]; then
    result="$(jq -ce --arg source_id "$source_id" '
      first(.[] | select((.source_id // "") == $source_id))
    ' "$catalog_path" 2>/dev/null || true)"
  fi

  if [[ -z "$result" || "$result" == "null" ]]; then
    result="$(catalog_entry_by_id "$dataset_id" "$catalog_path" 2>/dev/null || true)"
  fi

  if [[ ( -z "$result" || "$result" == "null" ) && -n "$download_url" ]]; then
    result="$(jq -ce --arg download_url "$download_url" '
      first(.[] | select((.download_url // "") == $download_url))
    ' "$catalog_path" 2>/dev/null || true)"
  fi

  if [[ -z "$result" || "$result" == "null" ]]; then
    return 1
  fi

  printf '%s\n' "$result"
}

default_boundary_reason_for_provider() {
  local provider="$1"
  case "$provider" in
    bbbike)
      printf 'provider_boundary_unavailable\n'
      ;;
    custom|osm)
      printf 'non_catalog_dataset\n'
      ;;
    geofabrik)
      printf 'catalog_boundary_missing\n'
      ;;
    *)
      printf 'boundary_unavailable\n'
      ;;
  esac
}

build_boundary_metadata_json() {
  local available="${1:-false}"
  local source="${2:-none}"
  local catalog_fetched_at="${3:-}"
  local reason="${4:-}"
  jq -cn \
    --argjson available "$available" \
    --arg source "$source" \
    --arg catalog_fetched_at "$catalog_fetched_at" \
    --arg reason "$reason" '
      {
        available: $available,
        source: $source,
        catalog_fetched_at: $catalog_fetched_at,
        reason: $reason
      }
    '
}

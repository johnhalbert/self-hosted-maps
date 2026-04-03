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

SHM_BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHM_STATE_FILE="${SHM_STATE_FILE:-${SHM_CONFIG_ROOT}/datasets.json}"
SHM_CATALOG_DIR="${SHM_CATALOG_DIR:-${SHM_DATA_ROOT}/cache/catalog}"
SHM_GEOFABRIK_CATALOG="${SHM_GEOFABRIK_CATALOG:-${SHM_CATALOG_DIR}/geofabrik-index-v1-nogeom.json}"
SHM_BBBIKE_INDEX_HTML="${SHM_BBBIKE_INDEX_HTML:-${SHM_CATALOG_DIR}/bbbike-index.html}"
SHM_NORMALIZED_CATALOG="${SHM_NORMALIZED_CATALOG:-${SHM_CATALOG_DIR}/catalog.json}"
SHM_DATASETS_DIR="${SHM_DATASETS_DIR:-${SHM_DATA_ROOT}/datasets}"
SHM_SELECTED_BUILD_DIR="${SHM_SELECTED_BUILD_DIR:-${SHM_DATA_ROOT}/builds/selected}"

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
  mkdir -p "$SHM_CONFIG_ROOT" "$SHM_CATALOG_DIR" "$SHM_DATASETS_DIR" "$SHM_SELECTED_BUILD_DIR" "$SHM_LOG_ROOT"
  if [[ ! -f "$SHM_STATE_FILE" ]]; then
    cat > "$SHM_STATE_FILE" <<'JSON'
{
  "catalog": {
    "provider": "multi",
    "providers": [],
    "fetched_at": null,
    "cache_path": null
  },
  "installed": {},
  "selected": [],
  "current": {
    "selected_hash": null,
    "artifact_path": null,
    "rebuilt_at": null,
    "dataset_ids": []
  }
}
JSON
  fi
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

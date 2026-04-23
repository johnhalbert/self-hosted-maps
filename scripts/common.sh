#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

ensure_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root." >&2
    exit 1
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

detect_platform() {
  source /etc/os-release
  if [[ "${ID:-}" != "debian" ]]; then
    echo "This installer targets Debian." >&2
  fi
}

write_env_file() {
  local cfg_dir="$1"
  mkdir -p "$cfg_dir"
  cat > "$cfg_dir/self-hosted-maps.conf" <<CFG
SHM_INSTALL_ROOT="${SHM_INSTALL_ROOT}"
SHM_DATA_ROOT="${SHM_DATA_ROOT}"
SHM_CONFIG_ROOT="${SHM_CONFIG_ROOT}"
SHM_LOG_ROOT="${SHM_LOG_ROOT}"
SHM_BOOTSTRAP_MODE="${SHM_BOOTSTRAP_MODE:-${SHM_REGION_MODE:-}}"
SHM_PBF_URL="${SHM_PBF_URL}"
SHM_UPDATE_SCHEDULE="${SHM_UPDATE_SCHEDULE}"
SHM_INSTALL_USER="${SHM_INSTALL_USER}"
SHM_TIMEZONE="${SHM_TIMEZONE}"
SHM_RUNTIME_CONFIG_FILE="${cfg_dir}/self-hosted-maps.runtime.conf"
CFG
}

write_runtime_env_file_if_missing() {
  local cfg_dir="$1"
  local runtime_file="$cfg_dir/self-hosted-maps.runtime.conf"
  if [[ -f "$runtime_file" ]]; then
    return 0
  fi
  cat > "$runtime_file" <<'CFG'
# Optional runtime settings for the web viewer and local API.
# Leave SHM_ADMIN_TOKEN blank to allow local admin actions without a token.
SHM_ADDRESS_SEARCH_ENABLED="1"
SHM_GEOCODER_URL="https://nominatim.openstreetmap.org/search"
SHM_GEOCODER_USER_AGENT="self-hosted-maps/1.0"
SHM_OPENSKY_ENABLED="1"
SHM_OPENSKY_API_BASE_URL="https://opensky-network.org/api"
SHM_OPENSKY_CLIENT_ID=""
SHM_OPENSKY_CLIENT_SECRET=""
SHM_ADSBEXCHANGE_ENABLED="0"
SHM_ADSBEXCHANGE_API_BASE_URL="https://adsbexchange.com/api"
SHM_ADSBEXCHANGE_API_KEY=""
SHM_ADMIN_TOKEN=""
CFG
  chmod 0600 "$runtime_file"
}

safe_mkdirs() {
  mkdir -p "$SHM_INSTALL_ROOT" "$SHM_DATA_ROOT" "$SHM_CONFIG_ROOT" "$SHM_LOG_ROOT"
  mkdir -p "$SHM_DATA_ROOT"/{incoming,builds,current,cache,tmp}
}

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
SHM_REGION_MODE="${SHM_REGION_MODE}"
SHM_PBF_URL="${SHM_PBF_URL}"
SHM_UPDATE_SCHEDULE="${SHM_UPDATE_SCHEDULE}"
SHM_INSTALL_USER="${SHM_INSTALL_USER}"
SHM_TIMEZONE="${SHM_TIMEZONE}"
CFG
}

safe_mkdirs() {
  mkdir -p "$SHM_INSTALL_ROOT" "$SHM_DATA_ROOT" "$SHM_CONFIG_ROOT" "$SHM_LOG_ROOT"
  mkdir -p "$SHM_DATA_ROOT"/{incoming,builds,current,cache,tmp}
}

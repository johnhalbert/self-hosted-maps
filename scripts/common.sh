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
SHM_APP_SOURCE_ROOT="${SHM_REPO_ROOT:-}"
SHM_APP_MANIFEST_FILE="${cfg_dir}/app-manifest.json"
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
SHM_OPENSKY_TOKEN_URL="https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
SHM_OPENSKY_CLIENT_ID=""
SHM_OPENSKY_CLIENT_SECRET=""
SHM_ADSBEXCHANGE_ENABLED="0"
SHM_ADSBEXCHANGE_API_BASE_URL="https://adsbexchange.com/api"
SHM_ADSBEXCHANGE_API_KEY=""
SHM_ADMIN_TOKEN=""
CFG
  chmod 0600 "$runtime_file"
}

write_initial_app_manifest() {
  local cfg_dir="$1"
  local source_root="$2"
  local manifest_file="$cfg_dir/app-manifest.json"
  local tmp_file commit branch describe remote_url status dirty untracked_count

  command -v jq >/dev/null 2>&1 || return 0

  commit=""
  branch=""
  describe=""
  remote_url=""
  dirty=false
  untracked_count=0

  if command -v git >/dev/null 2>&1 && git -C "$source_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    commit="$(git -C "$source_root" rev-parse HEAD 2>/dev/null || true)"
    branch="$(git -C "$source_root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    describe="$(git -C "$source_root" describe --tags --always --dirty 2>/dev/null || true)"
    remote_url="$(git -C "$source_root" config --get remote.origin.url 2>/dev/null || true)"
    status="$(git -C "$source_root" status --porcelain 2>/dev/null || true)"
    [[ -z "$status" ]] || dirty=true
    untracked_count="$(printf '%s\n' "$status" | awk '/^\?\?/ {count++} END {print count+0}')"
  fi

  tmp_file="${manifest_file}.tmp"
  jq -n \
    --arg updated_at "$(date -u +%FT%TZ)" \
    --arg source_root "$source_root" \
    --arg install_root "$SHM_INSTALL_ROOT" \
    --arg config_root "$SHM_CONFIG_ROOT" \
    --arg data_root "$SHM_DATA_ROOT" \
    --arg commit "$commit" \
    --arg branch "$branch" \
    --arg describe "$describe" \
    --arg remote_url "$remote_url" \
    --argjson dirty "$dirty" \
    --argjson untracked_count "$untracked_count" \
    '{
      manifest_version: 1,
      updater_version: "install",
      updated_at: $updated_at,
      source: {
        path: $source_root,
        git: {
          available: ($commit | length > 0),
          commit: ($commit | select(length > 0) // null),
          branch: ($branch | select(length > 0) // null),
          describe: ($describe | select(length > 0) // null),
          dirty: $dirty,
          untracked_count: $untracked_count,
          remote_url: ($remote_url | select(length > 0) // null)
        }
      },
      installed: {
        install_root: $install_root,
        config_root: $config_root,
        data_root: $data_root
      },
      update: {
        refresh_system_config: true,
        surfaces: {
          runtime: ["install_root/bin", "install_root/www", "config_root/manager-usage.txt", "/usr/local/bin/self-hosted-maps-* symlinks"],
          preserved: ["config_root/self-hosted-maps.runtime.conf", "config_root/datasets.json", "data_root/datasets", "data_root/current", "install_root/www/vendor"]
        }
      }
    }' > "$tmp_file"
  mv "$tmp_file" "$manifest_file"
  chmod 0644 "$manifest_file"
}

safe_mkdirs() {
  mkdir -p "$SHM_INSTALL_ROOT" "$SHM_DATA_ROOT" "$SHM_CONFIG_ROOT" "$SHM_LOG_ROOT"
  mkdir -p "$SHM_DATA_ROOT"/{incoming,builds,current,cache,tmp}
}

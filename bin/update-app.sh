#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_DIR="${SHM_UPDATE_APP_BIN_DIR:-$SCRIPT_DIR}"

# shellcheck disable=SC1091
source "$COMMON_DIR/_shm_common.sh"

APP_MANIFEST_FILE="${SHM_APP_MANIFEST_FILE:-${SHM_CONFIG_ROOT}/app-manifest.json}"
APP_BACKUP_ROOT="${SHM_APP_BACKUP_ROOT:-${SHM_DATA_ROOT}/backups/app-update}"
APP_TMP_ROOT="${SHM_APP_TMP_ROOT:-${SHM_DATA_ROOT}/tmp/app-update}"
APP_LOG_FILE="${SHM_APP_UPDATE_LOG_FILE:-${SHM_LOG_ROOT}/update-app.log}"
APP_UPDATER_VERSION="1"

ACTION="preview"
SOURCE_ROOT="${SHM_APP_SOURCE_ROOT:-}"
OUTPUT_JSON=0
ASSUME_YES=0
REFRESH_SYSTEM_CONFIG=0

usage() {
  cat <<'EOF'
Usage:
  update-app.sh --source PATH --preview [--json]
  update-app.sh --source PATH --apply [--yes] [--refresh-system-config]

Updates installed Self Hosted Maps app files from a local checkout. This does
not pull from git, update datasets, rebuild maps, or change runtime secrets.
EOF
}

log_msg() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

ensure_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "Run as root." >&2
    exit 1
  fi
}

resolve_path() {
  local path="$1"
  if command -v readlink >/dev/null 2>&1; then
    readlink -f "$path" 2>/dev/null || printf '%s\n' "$path"
  else
    printf '%s\n' "$path"
  fi
}

json_string_or_null() {
  local value="${1:-}"
  if [[ -z "$value" ]]; then
    printf 'null'
  else
    jq -Rn --arg value "$value" '$value'
  fi
}

parse_args() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --source)
        SOURCE_ROOT="${2:-}"
        shift 2
        ;;
      --preview|--dry-run|--preview-json)
        ACTION="preview"
        if [[ "$1" == "--preview-json" ]]; then
          OUTPUT_JSON=1
        fi
        shift
        ;;
      --apply)
        ACTION="apply"
        shift
        ;;
      --json)
        OUTPUT_JSON=1
        shift
        ;;
      --yes|-y)
        ASSUME_YES=1
        shift
        ;;
      --refresh-system-config|--system-config|--include-system-config)
        REFRESH_SYSTEM_CONFIG=1
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
  done
}

source_path_from_manifest() {
  if [[ -f "$APP_MANIFEST_FILE" ]]; then
    jq -r '.source.path // empty' "$APP_MANIFEST_FILE" 2>/dev/null || true
  fi
}

validate_source() {
  local source="$1"
  local required=(
    "install.sh"
    "bin/_shm_common.sh"
    "bin/map-manager.sh"
    "bin/web-api.py"
    "scripts/install-runtime.sh"
    "scripts/configure-system.sh"
    "assets/index.html"
    "assets/app.js"
    "docs/manager-usage.txt"
  )
  local missing=()
  local rel
  for rel in "${required[@]}"; do
    if [[ ! -e "$source/$rel" ]]; then
      missing+=("$rel")
    fi
  done
  if [[ "${#missing[@]}" -gt 0 ]]; then
    printf 'Invalid source checkout: missing %s\n' "${missing[*]}" >&2
    return 1
  fi
}

collect_git_metadata_json() {
  local source="$1"
  if ! command -v git >/dev/null 2>&1 || ! git -C "$source" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    jq -cn '{available:false, commit:null, branch:null, describe:null, dirty:null, untracked_count:null, remote_url:null}'
    return
  fi

  local commit branch describe status untracked_count remote_url dirty
  commit="$(git -C "$source" rev-parse HEAD 2>/dev/null || true)"
  branch="$(git -C "$source" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  describe="$(git -C "$source" describe --tags --always --dirty 2>/dev/null || true)"
  status="$(git -C "$source" status --porcelain 2>/dev/null || true)"
  untracked_count="$(printf '%s\n' "$status" | awk '/^\?\?/ {count++} END {print count+0}')"
  remote_url="$(git -C "$source" config --get remote.origin.url 2>/dev/null || true)"
  dirty=false
  [[ -z "$status" ]] || dirty=true

  jq -cn \
    --arg commit "$commit" \
    --arg branch "$branch" \
    --arg describe "$describe" \
    --arg remote_url "$remote_url" \
    --argjson dirty "$dirty" \
    --argjson untracked_count "$untracked_count" \
    '{
      available: true,
      commit: ($commit | select(length > 0) // null),
      branch: ($branch | select(length > 0) // null),
      describe: ($describe | select(length > 0) // null),
      dirty: $dirty,
      untracked_count: $untracked_count,
      remote_url: ($remote_url | select(length > 0) // null)
    }'
}

manifest_json() {
  if [[ -f "$APP_MANIFEST_FILE" ]]; then
    jq -c . "$APP_MANIFEST_FILE" 2>/dev/null || jq -cn '{manifest_unreadable:true}'
  else
    jq -cn '{legacy_install:true, manifest_present:false}'
  fi
}

surfaces_json() {
  jq -cn --argjson system_config "$REFRESH_SYSTEM_CONFIG" '{
    runtime: [
      "install_root/bin",
      "install_root/www (preserving www/vendor)",
      "config_root/manager-usage.txt",
      "/usr/local/bin/self-hosted-maps-* symlinks"
    ],
    preserved: [
      "config_root/self-hosted-maps.conf",
      "config_root/self-hosted-maps.runtime.conf",
      "config_root/datasets.json",
      "data_root/datasets",
      "data_root/current",
      "data_root/cache",
      "install_root/www/vendor"
    ],
    system_config: (
      if $system_config == 1 then [
        "/etc/systemd/system/self-hosted-maps-api.service",
        "/etc/systemd/system/self-hosted-maps-tileserver.service",
        "config_root/tileserver-config.json",
        "/etc/nginx/sites-available/self-hosted-maps-viewer",
        "/etc/nginx/sites-enabled/self-hosted-maps-viewer"
      ] else [] end
    )
  }'
}

service_actions_json() {
  jq -cn --argjson system_config "$REFRESH_SYSTEM_CONFIG" '{
    default: ["restart self-hosted-maps-api.service", "reload nginx"],
    system_config: (
      if $system_config == 1 then [
        "systemctl daemon-reload",
        "restart self-hosted-maps-api.service if API unit changed",
        "restart self-hosted-maps-tileserver.service if tileserver unit/config changed",
        "nginx -t then reload nginx if nginx config changed"
      ] else [] end
    )
  }'
}

build_preview_json() {
  local source="$1"
  local stamp="$2"
  local git_json manifest surfaces services
  git_json="$(collect_git_metadata_json "$source")"
  manifest="$(manifest_json)"
  surfaces="$(surfaces_json)"
  services="$(service_actions_json)"

  jq -cn \
    --arg action "$ACTION" \
    --arg source "$source" \
    --arg install_root "$SHM_INSTALL_ROOT" \
    --arg config_root "$SHM_CONFIG_ROOT" \
    --arg data_root "$SHM_DATA_ROOT" \
    --arg log_root "$SHM_LOG_ROOT" \
    --arg manifest_path "$APP_MANIFEST_FILE" \
    --arg backup_path "$APP_BACKUP_ROOT/$stamp" \
    --arg staging_path "$APP_TMP_ROOT/$stamp" \
    --argjson git "$git_json" \
    --argjson manifest "$manifest" \
    --argjson surfaces "$surfaces" \
    --argjson services "$services" \
    --argjson refresh_system_config "$REFRESH_SYSTEM_CONFIG" \
    '{
      action: $action,
      source: { path: $source, git: $git },
      installed: {
        install_root: $install_root,
        config_root: $config_root,
        data_root: $data_root,
        log_root: $log_root,
        manifest_path: $manifest_path,
        manifest: $manifest
      },
      update: {
        backup_path: $backup_path,
        staging_path: $staging_path,
        refresh_system_config: $refresh_system_config,
        surfaces: $surfaces,
        service_actions: $services
      }
    }'
}

print_preview() {
  local preview="$1"
  if [[ "$OUTPUT_JSON" == "1" ]]; then
    jq . <<<"$preview"
    return
  fi
  jq -r '
    "Source: \(.source.path)",
    "Git: \(
      if .source.git.available then
        ((.source.git.describe // .source.git.commit // "unknown") + (if .source.git.dirty then " (dirty)" else "" end))
      else
        "not a git checkout"
      end
    )",
    "Install root: \(.installed.install_root)",
    "Config root: \(.installed.config_root)",
    "Data root: \(.installed.data_root)",
    "Manifest: \(.installed.manifest_path)",
    "Backup: \(.update.backup_path)",
    "System config refresh: \(.update.refresh_system_config)",
    "",
    "Updated surfaces:",
    (.update.surfaces.runtime[] | "  - \(.)"),
    "",
    "Preserved surfaces:",
    (.update.surfaces.preserved[] | "  - \(.)"),
    "",
    "Service actions:",
    (.update.service_actions.default[] | "  - \(.)"),
    (.update.service_actions.system_config[]? | "  - \(.)")
  ' <<<"$preview"
}

confirm_apply() {
  local preview="$1"
  if [[ "$ASSUME_YES" == "1" ]]; then
    return 0
  fi
  print_preview "$preview"
  printf '\nApply this app update? [y/N] '
  local answer
  read -r answer
  [[ "$answer" == "y" || "$answer" == "Y" || "$answer" == "yes" || "$answer" == "YES" ]]
}

run_from_temp_copy_if_needed() {
  if [[ "$ACTION" != "apply" || "${SHM_UPDATE_APP_REEXECED:-0}" == "1" ]]; then
    return
  fi
  mkdir -p "$APP_TMP_ROOT/runner"
  local runner="$APP_TMP_ROOT/runner/update-app.$$.sh"
  cp "$SCRIPT_DIR/update-app.sh" "$runner"
  chmod +x "$runner"
  export SHM_UPDATE_APP_REEXECED=1
  export SHM_UPDATE_APP_BIN_DIR="$SCRIPT_DIR"
  exec bash "$runner" "$@"
}

stage_runtime_files() {
  local source="$1"
  local stage="$2"
  mkdir -p "$stage/install/bin" "$stage/install/www" "$stage/config"
  cp -a "$source/bin/." "$stage/install/bin/"
  chmod +x "$stage/install/bin/"*.sh

  cp -a "$source/assets/." "$stage/install/www/"
  if [[ -d "$SHM_INSTALL_ROOT/www/vendor" ]]; then
    mkdir -p "$stage/install/www/vendor"
    cp -a "$SHM_INSTALL_ROOT/www/vendor/." "$stage/install/www/vendor/"
  fi

  cp "$source/docs/manager-usage.txt" "$stage/config/manager-usage.txt"
}

validate_staged_runtime() {
  local stage="$1"
  bash -n "$stage/install/bin/"*.sh
  if command -v python3 >/dev/null 2>&1; then
    python3 -m py_compile "$stage/install/bin/web-api.py"
  fi
}

copy_if_exists() {
  local source="$1"
  local destination="$2"
  if [[ -e "$source" || -L "$source" ]]; then
    mkdir -p "$(dirname "$destination")"
    cp -a "$source" "$destination"
  fi
}

backup_surfaces() {
  local backup="$1"
  mkdir -p "$backup"
  copy_if_exists "$SHM_INSTALL_ROOT/bin" "$backup/install/bin"
  copy_if_exists "$SHM_INSTALL_ROOT/www" "$backup/install/www"
  copy_if_exists "$SHM_CONFIG_ROOT/manager-usage.txt" "$backup/config/manager-usage.txt"
  mkdir -p "$backup/usr-local-bin"
  local link
  for link in \
    /usr/local/bin/self-hosted-maps-manager \
    /usr/local/bin/self-hosted-maps-rebuild \
    /usr/local/bin/self-hosted-maps-refresh-catalog \
    /usr/local/bin/self-hosted-maps-list-installed \
    /usr/local/bin/self-hosted-maps-update-app; do
    if [[ -e "$link" || -L "$link" ]]; then
      cp -a "$link" "$backup/usr-local-bin/"
    fi
  done

  if [[ "$REFRESH_SYSTEM_CONFIG" == "1" ]]; then
    copy_if_exists /etc/systemd/system/self-hosted-maps-api.service "$backup/systemd/self-hosted-maps-api.service"
    copy_if_exists /etc/systemd/system/self-hosted-maps-tileserver.service "$backup/systemd/self-hosted-maps-tileserver.service"
    copy_if_exists "$SHM_CONFIG_ROOT/tileserver-config.json" "$backup/config/tileserver-config.json"
    copy_if_exists /etc/nginx/sites-available/self-hosted-maps-viewer "$backup/nginx/self-hosted-maps-viewer"
    copy_if_exists /etc/nginx/sites-enabled/self-hosted-maps-viewer "$backup/nginx/self-hosted-maps-viewer.enabled"
  fi
}

install_runtime_files() {
  local stage="$1"
  install -d -m 0755 "$SHM_INSTALL_ROOT/bin" "$SHM_INSTALL_ROOT/www" "$SHM_CONFIG_ROOT" /usr/local/bin
  cp -a "$stage/install/bin/." "$SHM_INSTALL_ROOT/bin/"
  cp -a "$stage/install/www/." "$SHM_INSTALL_ROOT/www/"
  install -m 0644 "$stage/config/manager-usage.txt" "$SHM_CONFIG_ROOT/manager-usage.txt"

  ln -sf "$SHM_INSTALL_ROOT/bin/_shm_common.sh" /usr/local/bin/_shm_common.sh
  ln -sf "$SHM_INSTALL_ROOT/bin/map-manager.sh" /usr/local/bin/self-hosted-maps-manager
  ln -sf "$SHM_INSTALL_ROOT/bin/rebuild-selected.sh" /usr/local/bin/self-hosted-maps-rebuild
  ln -sf "$SHM_INSTALL_ROOT/bin/refresh-catalog.sh" /usr/local/bin/self-hosted-maps-refresh-catalog
  ln -sf "$SHM_INSTALL_ROOT/bin/list-installed.sh" /usr/local/bin/self-hosted-maps-list-installed
  ln -sf "$SHM_INSTALL_ROOT/bin/update-app.sh" /usr/local/bin/self-hosted-maps-update-app
}

render_template() {
  local source="$1"
  local destination="$2"
  shift 2
  cp "$source" "$destination"
  while [[ "$#" -gt 0 ]]; do
    local placeholder="$1"
    local value="$2"
    shift 2
    sed -i "s|${placeholder}|${value}|g" "$destination"
  done
}

fonts_root() {
  local root=""
  if command -v npm >/dev/null 2>&1; then
    root="$(npm root -g 2>/dev/null)/tileserver-gl-light/node_modules/tileserver-gl-styles/fonts"
  fi
  if [[ ! -d "$root" && -d "/usr/local/lib/node_modules/tileserver-gl-light/node_modules/tileserver-gl-styles/fonts" ]]; then
    root="/usr/local/lib/node_modules/tileserver-gl-light/node_modules/tileserver-gl-styles/fonts"
  fi
  [[ -d "$root" ]] || {
    echo "Unable to locate TileServer fonts directory." >&2
    return 1
  }
  printf '%s\n' "$root"
}

install_if_changed() {
  local mode="$1"
  local source="$2"
  local destination="$3"
  if [[ -f "$destination" ]] && cmp -s "$source" "$destination"; then
    return 1
  fi
  install -m "$mode" "$source" "$destination"
  return 0
}

refresh_system_config() {
  local source="$1"
  local stage="$2"
  local changed_api=0 changed_tileserver=0 changed_nginx=0 fonts
  mkdir -p "$stage/systemd" "$stage/config" "$stage/nginx"

  render_template "$source/systemd/self-hosted-maps-api.service" "$stage/systemd/self-hosted-maps-api.service" \
    "__CONFIG_ROOT__" "$SHM_CONFIG_ROOT" \
    "__INSTALL_ROOT__" "$SHM_INSTALL_ROOT"

  render_template "$source/systemd/self-hosted-maps-tileserver.service" "$stage/systemd/self-hosted-maps-tileserver.service" \
    "__CONFIG_ROOT__" "$SHM_CONFIG_ROOT" \
    "__DATA_ROOT__" "$SHM_DATA_ROOT"

  fonts="$(fonts_root)"
  render_template "$source/config/tileserver-config.json" "$stage/config/tileserver-config.json" \
    "__FONTS_ROOT__" "$fonts"

  render_template "$source/config/nginx-viewer.conf" "$stage/nginx/self-hosted-maps-viewer" \
    "__INSTALL_ROOT__" "$SHM_INSTALL_ROOT"

  install -d -m 0755 /etc/systemd/system "$SHM_CONFIG_ROOT" /etc/nginx/sites-available /etc/nginx/sites-enabled
  if install_if_changed 0644 "$stage/systemd/self-hosted-maps-api.service" /etc/systemd/system/self-hosted-maps-api.service; then
    changed_api=1
  fi
  if install_if_changed 0644 "$stage/systemd/self-hosted-maps-tileserver.service" /etc/systemd/system/self-hosted-maps-tileserver.service; then
    changed_tileserver=1
  fi
  if install_if_changed 0644 "$stage/config/tileserver-config.json" "$SHM_CONFIG_ROOT/tileserver-config.json"; then
    changed_tileserver=1
  fi
  if install_if_changed 0644 "$stage/nginx/self-hosted-maps-viewer" /etc/nginx/sites-available/self-hosted-maps-viewer; then
    changed_nginx=1
  fi
  ln -sf /etc/nginx/sites-available/self-hosted-maps-viewer /etc/nginx/sites-enabled/self-hosted-maps-viewer

  if [[ "$changed_api" == "1" || "$changed_tileserver" == "1" ]]; then
    systemctl daemon-reload
  fi
  if [[ "$changed_nginx" == "1" ]]; then
    nginx -t
  fi

  printf '%s %s %s\n' "$changed_api" "$changed_tileserver" "$changed_nginx" > "$stage/system-config-changes"
}

restart_services() {
  local stage="$1"
  local changed_api=0 changed_tileserver=0 changed_nginx=0
  if [[ -f "$stage/system-config-changes" ]]; then
    read -r changed_api changed_tileserver changed_nginx < "$stage/system-config-changes"
  fi

  systemctl restart self-hosted-maps-api.service
  if [[ "$changed_tileserver" == "1" ]]; then
    systemctl restart self-hosted-maps-tileserver.service
  fi
  if [[ "$changed_nginx" == "1" ]]; then
    systemctl reload nginx || systemctl restart nginx
  else
    systemctl reload nginx >/dev/null 2>&1 || true
  fi
}

write_manifest() {
  local preview="$1"
  local backup="$2"
  local tmp_manifest="${APP_MANIFEST_FILE}.tmp"
  mkdir -p "$SHM_CONFIG_ROOT"
  jq \
    --arg updated_at "$(date -u +%FT%TZ)" \
    --arg backup_path "$backup" \
    --arg updater_version "$APP_UPDATER_VERSION" \
    '. + {
      manifest_version: 1,
      updater_version: $updater_version,
      updated_at: $updated_at,
      backup_path: $backup_path
    }' <<<"$preview" > "$tmp_manifest"
  mv "$tmp_manifest" "$APP_MANIFEST_FILE"
}

apply_update() {
  local source="$1"
  local stamp="$2"
  local preview="$3"
  local stage="$APP_TMP_ROOT/$stamp"
  local backup="$APP_BACKUP_ROOT/$stamp"

  ensure_root
  require_cmd jq
  acquire_mutation_lock
  mkdir -p "$APP_TMP_ROOT" "$APP_BACKUP_ROOT" "$SHM_LOG_ROOT"

  {
    log_msg "Starting app update from $source"
    log_msg "Backup path: $backup"
    log_msg "Staging path: $stage"
  } >> "$APP_LOG_FILE"

  rm -rf "$stage"
  mkdir -p "$stage"
  stage_runtime_files "$source" "$stage"
  validate_staged_runtime "$stage"
  backup_surfaces "$backup"
  if [[ "$REFRESH_SYSTEM_CONFIG" == "1" ]]; then
    refresh_system_config "$source" "$stage"
  fi
  install_runtime_files "$stage"
  restart_services "$stage"
  write_manifest "$preview" "$backup"

  log_msg "App update complete. Manifest: $APP_MANIFEST_FILE" >> "$APP_LOG_FILE"
}

main() {
  parse_args "$@"

  if [[ -z "$SOURCE_ROOT" ]]; then
    SOURCE_ROOT="$(source_path_from_manifest)"
  fi
  if [[ -z "$SOURCE_ROOT" ]]; then
    echo "No source checkout provided. Use --source PATH." >&2
    exit 1
  fi
  SOURCE_ROOT="$(resolve_path "$SOURCE_ROOT")"
  validate_source "$SOURCE_ROOT"

  local stamp preview
  stamp="$(date +%Y%m%d-%H%M%S)"
  preview="$(build_preview_json "$SOURCE_ROOT" "$stamp")"

  if [[ "$ACTION" == "preview" ]]; then
    print_preview "$preview"
    return
  fi

  run_from_temp_copy_if_needed "$@"
  if ! confirm_apply "$preview"; then
    echo "App update cancelled." >&2
    exit 1
  fi
  apply_update "$SOURCE_ROOT" "$stamp" "$preview"
  if [[ "$OUTPUT_JSON" == "1" ]]; then
    jq . "$APP_MANIFEST_FILE"
  else
    echo "App update complete."
    echo "Manifest: $APP_MANIFEST_FILE"
    echo "Backup: $APP_BACKUP_ROOT/$stamp"
  fi
}

main "$@"

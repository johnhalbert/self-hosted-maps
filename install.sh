#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$REPO_ROOT/scripts/common.sh"
source "$REPO_ROOT/installer/lib/ui.sh"

ensure_root
require_cmd bash

detect_platform
ensure_ui_backend
welcome_screen

install_root="/opt/self-hosted-maps"
data_root="/var/lib/self-hosted-maps"
config_root="/etc/self-hosted-maps"
log_root="/var/log/self-hosted-maps"
install_user="root"
timezone_str="$(cat /etc/timezone 2>/dev/null || true)"

region_mode="$(choose_region_mode)"
case "$region_mode" in
  world) pbf_url="https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf" ;;
  *) pbf_url="$(choose_region_url)" ;;
esac

update_schedule="$(choose_update_schedule)"
check_resources_or_warn "$region_mode"

if ! confirm_summary "$install_root" "$data_root" "$config_root" "$log_root" "$region_mode" "$pbf_url" "$update_schedule"; then
  info_box "Installation cancelled."
  exit 1
fi

export SHM_INSTALL_ROOT="$install_root"
export SHM_DATA_ROOT="$data_root"
export SHM_CONFIG_ROOT="$config_root"
export SHM_LOG_ROOT="$log_root"
export SHM_REGION_MODE="$region_mode"
export SHM_PBF_URL="$pbf_url"
export SHM_UPDATE_SCHEDULE="$update_schedule"
export SHM_INSTALL_USER="$install_user"
export SHM_TIMEZONE="${timezone_str:-UTC}"
export SHM_REPO_ROOT="$REPO_ROOT"

bash "$REPO_ROOT/scripts/bootstrap-system.sh"
bash "$REPO_ROOT/scripts/install-node.sh"
bash "$REPO_ROOT/scripts/install-tilemaker.sh"
bash "$REPO_ROOT/scripts/install-runtime.sh"
bash "$REPO_ROOT/scripts/configure-system.sh"
bash "$REPO_ROOT/scripts/initial-build.sh"
bash "$REPO_ROOT/scripts/register-cron.sh"

viewer_ip="$(hostname -I | awk '{print $1}')"
success_box "Installation complete.\n\nViewer: http://${viewer_ip}/\nTiles JSON: http://${viewer_ip}/tiles/data/openmaptiles.json\nConfig: ${config_root}/self-hosted-maps.conf"

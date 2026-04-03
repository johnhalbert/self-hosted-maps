#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$REPO_ROOT/scripts/common.sh"
source "$REPO_ROOT/installer/lib/ui.sh"
source "$REPO_ROOT/installer/lib/catalog-ui.sh"

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

export SHM_INSTALL_ROOT="$install_root"
export SHM_DATA_ROOT="$data_root"
export SHM_CONFIG_ROOT="$config_root"
export SHM_LOG_ROOT="$log_root"
export SHM_INSTALL_USER="$install_user"
export SHM_TIMEZONE="${timezone_str:-UTC}"
export SHM_REPO_ROOT="$REPO_ROOT"

bootstrap_mode="$(choose_bootstrap_mode)"
summary_scope=""
case "$bootstrap_mode" in
  world)
    pbf_url="https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf"
    bootstrap_dataset_id="world"
    bootstrap_dataset_name="World"
    bootstrap_provider="osm"
    summary_scope="world"
    ;;
  catalog)
    bootstrap_dataset_id="$(choose_catalog_dataset_id "$REPO_ROOT")"
    dataset_json="$($REPO_ROOT/bin/find-dataset.sh "$bootstrap_dataset_id")"
    pbf_url="$(jq -r '.download_url' <<<"$dataset_json")"
    bootstrap_dataset_name="$(jq -r '.name' <<<"$dataset_json")"
    bootstrap_provider="$(jq -r '.provider' <<<"$dataset_json")"
    summary_scope="catalog: $bootstrap_dataset_name ($bootstrap_dataset_id)"
    ;;
  custom)
    pbf_url="$(choose_custom_pbf_url)"
    bootstrap_dataset_name="$(choose_custom_dataset_name)"
    bootstrap_dataset_id="$(printf '%s' "$bootstrap_dataset_name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
    [[ -n "$bootstrap_dataset_id" ]] || bootstrap_dataset_id="custom-bootstrap"
    bootstrap_provider="custom"
    summary_scope="custom: $bootstrap_dataset_name"
    ;;
  *)
    echo "Unknown bootstrap mode: $bootstrap_mode" >&2
    exit 1
    ;;
esac

update_schedule="$(choose_update_schedule)"
check_resources_or_warn "$bootstrap_mode"

if ! confirm_summary "$install_root" "$data_root" "$config_root" "$log_root" "$summary_scope" "$pbf_url" "$update_schedule"; then
  info_box "Installation cancelled."
  exit 1
fi

export SHM_BOOTSTRAP_MODE="$bootstrap_mode"
export SHM_BOOTSTRAP_DATASET_ID="$bootstrap_dataset_id"
export SHM_BOOTSTRAP_DATASET_NAME="$bootstrap_dataset_name"
export SHM_BOOTSTRAP_PROVIDER="$bootstrap_provider"
export SHM_PBF_URL="$pbf_url"
export SHM_UPDATE_SCHEDULE="$update_schedule"

bash "$REPO_ROOT/scripts/bootstrap-system.sh"
bash "$REPO_ROOT/scripts/install-node.sh"
bash "$REPO_ROOT/scripts/install-tilemaker.sh"
bash "$REPO_ROOT/scripts/install-runtime.sh"
bash "$REPO_ROOT/scripts/configure-system.sh"
bash "$REPO_ROOT/scripts/bootstrap-selection-v5.sh"
bash "$REPO_ROOT/scripts/register-cron.sh"
bash "$REPO_ROOT/scripts/post-install-discoverability.sh"

viewer_ip="$(hostname -I | awk '{print $1}')"
success_box "Installation complete.\n\nViewer: http://${viewer_ip}/\nTiles JSON: http://${viewer_ip}/data/openmaptiles.json\nManager command: self-hosted-maps-manager\nManager path: ${install_root}/bin/map-manager.sh\nUsage guide: ${config_root}/manager-usage.txt\nConfig: ${config_root}/self-hosted-maps.conf"

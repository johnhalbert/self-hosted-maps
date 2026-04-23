#!/usr/bin/env bash
set -euo pipefail

INSTALLER_UI_TITLE="Self Hosted Maps"

ensure_ui_backend() {
  local missing=()
  command -v whiptail >/dev/null 2>&1 || missing+=(whiptail)
  command -v dialog  >/dev/null 2>&1 || missing+=(dialog)
  if (( ${#missing[@]} > 0 )); then
    apt-get update
    apt-get install -y "${missing[@]}"
  fi
}

welcome_screen() {
  whiptail --title "$INSTALLER_UI_TITLE" --msgbox "This installer sets up a native map stack on Debian.\n\nV2 adds stronger preflight guidance and a cleaner viewer/tile split." 12 72
}

info_box() {
  whiptail --title "$INSTALLER_UI_TITLE" --msgbox "$1" 12 72
}

success_box() {
  whiptail --title "Installation Complete" --msgbox "$1" 14 72
}

choose_region_mode() {
  whiptail --title "Dataset Scope" --menu "Choose the initial dataset scope:" 15 72 5 \
    world "Use the full OSM planet PBF" \
    region "Use a specific region PBF" 3>&1 1>&2 2>&3
}

choose_region_url() {
  local choice
  choice=$(whiptail --title "Region Source" --menu "Choose a region source or custom URL:" 18 80 8 \
    louisiana "Geofabrik Louisiana extract" \
    texas "Geofabrik Texas extract" \
    usa "Geofabrik US extract" \
    north-america "Geofabrik North America extract" \
    custom "Enter a custom .osm.pbf URL" 3>&1 1>&2 2>&3)
  case "$choice" in
    louisiana) echo "https://download.geofabrik.de/north-america/us/louisiana-latest.osm.pbf" ;;
    texas) echo "https://download.geofabrik.de/north-america/us/texas-latest.osm.pbf" ;;
    usa) echo "https://download.geofabrik.de/north-america/us-latest.osm.pbf" ;;
    north-america) echo "https://download.geofabrik.de/north-america-latest.osm.pbf" ;;
    custom) whiptail --title "Custom PBF URL" --inputbox "Enter the full URL to a .osm.pbf file:" 10 80 3>&1 1>&2 2>&3 ;;
  esac
}

choose_update_schedule() {
  local choice
  choice=$(whiptail --title "Update Schedule" --menu "Choose how often to refresh map data:" 18 80 8 \
    daily "Every day at 03:00" \
    weekly "Every Sunday at 03:00" \
    monthly "First day of month at 03:00" \
    custom "Enter a custom cron expression" 3>&1 1>&2 2>&3)
  case "$choice" in
    daily) echo "0 3 * * *" ;;
    weekly) echo "0 3 * * 0" ;;
    monthly) echo "0 3 1 * *" ;;
    custom) whiptail --title "Custom Cron" --inputbox "Enter a cron expression for the maintenance job:" 10 80 "0 3 * * 0" 3>&1 1>&2 2>&3 ;;
  esac
}

check_resources_or_warn() {
  local mode="$1"
  local mem_mb disk_gb
  mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  disk_gb=$(df -BG / | awk 'NR==2 {gsub(/G/, "", $4); print $4}')
  if [[ "$mode" == "world" ]]; then
    if (( mem_mb < 16000 )) || (( disk_gb < 250 )); then
      whiptail --title "Resource Warning" --yesno "World imports are heavy.\n\nDetected memory: ${mem_mb} MB\nFree disk on /: ${disk_gb} GB\n\nRecommended starting point is a region extract unless you know this LXC is sized appropriately.\n\nContinue anyway?" 16 78 || exit 1
    fi
  fi
}

confirm_summary() {
  local install_root="$1"
  local data_root="$2"
  local config_root="$3"
  local log_root="$4"
  local region_mode="$5"
  local pbf_url="$6"
  local update_schedule="$7"
  whiptail --title "Confirm Installation" --yesno "Install root: ${install_root}\nData root: ${data_root}\nConfig root: ${config_root}\nLog root: ${log_root}\nScope: ${region_mode}\nPBF URL: ${pbf_url}\nSchedule: ${update_schedule}\n\nProceed?" 18 90
}

show_step_failure() {
  local step_title="$1"
  local log_file="$2"
  local display_file="$log_file"

  if [[ ! -s "$display_file" ]]; then
    display_file="$(mktemp)"
    cat > "$display_file" <<EOF
Step failed: $step_title

No log output was captured for this step.
EOF
  fi

  whiptail --title "Install Step Failed" --msgbox "Step failed: ${step_title}\n\nThe step log will be shown next." 12 78 || true
  whiptail --title "Failure Log" --textbox "$display_file" 28 100 || true

  if [[ "$display_file" != "$log_file" ]]; then
    rm -f "$display_file"
  fi
}

run_install_step() {
  local step_index="$1"
  local total_steps="$2"
  local step_title="$3"
  local log_file="$4"
  shift 4

  mkdir -p "$(dirname "$log_file")"
  : > "$log_file"

  local rc_file prompt
  rc_file="$(mktemp)"
  echo "1" > "$rc_file"
  prompt="Step ${step_index} of ${total_steps} — ${step_title}\n\nStreaming live output from the current installer phase.\nLog: ${log_file}"

  local dialog_rc=0
  set +e
  (
    set +e
    set -o pipefail
    trap '' SIGPIPE
    "$@" 2>&1 | tee "$log_file"
    printf '%s' "${PIPESTATUS[0]}" > "$rc_file"
  ) | dialog --title "$INSTALLER_UI_TITLE Installer" --progressbox "$prompt" 22 100
  dialog_rc=$?
  set -e

  local rc=1
  if [[ -f "$rc_file" ]]; then
    rc="$(cat "$rc_file")"
    rc="${rc:-1}"
    rm -f "$rc_file"
  fi

  if (( dialog_rc != 0 )); then
    rc="$dialog_rc"
  fi

  if (( rc != 0 )); then
    show_step_failure "$step_title" "$log_file"
  fi

  return "$rc"
}

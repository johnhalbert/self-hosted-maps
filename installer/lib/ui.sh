#!/usr/bin/env bash
set -euo pipefail

INSTALLER_UI_TITLE="Self Hosted Maps"

ensure_ui_backend() {
  if ! command -v whiptail >/dev/null 2>&1; then
    apt-get update
    apt-get install -y whiptail dialog
  fi
}

welcome_screen() {
  whiptail --title "$INSTALLER_UI_TITLE" --msgbox "This installer sets up a native map stack on Debian.\n\nV2 adds stronger preflight guidance and a cleaner viewer/tile split." 12 72
}

info_box() {
  whiptail --title "$INSTALLER_UI_TITLE" --msgbox "$1" 12 72
}

success_box() {
  whiptail --title "Installation Complete" --msgbox "$1" 20 78
}

choose_update_schedule() {
  local choice
  choice=$(whiptail --title "Update Schedule" --menu "Choose how often to rebuild tiles:" 18 80 8 \
    daily "Every day at 03:00" \
    weekly "Every Sunday at 03:00" \
    monthly "First day of month at 03:00" \
    custom "Enter a custom cron expression" 3>&1 1>&2 2>&3)
  case "$choice" in
    daily) echo "0 3 * * *" ;;
    weekly) echo "0 3 * * 0" ;;
    monthly) echo "0 3 1 * *" ;;
    custom) whiptail --title "Custom Cron" --inputbox "Enter a cron expression for the rebuild job:" 10 80 "0 3 * * 0" 3>&1 1>&2 2>&3 ;;
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
  local tmp_created=0

  if [[ ! -s "$display_file" ]]; then
    display_file="$(mktemp)"
    tmp_created=1
    cat > "$display_file" <<EOF
Step failed: $step_title

No log output was captured for this step.
EOF
  fi

  whiptail --title "Install Step Failed" --msgbox "Step failed: ${step_title}\n\nThe step log will be shown next." 12 78
  whiptail --title "Failure Log" --textbox "$display_file" 28 100 || true

  if (( tmp_created )); then
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

  local rc_file
  rc_file="$(mktemp)"
  echo "1" > "$rc_file"

  (
    set +e
    trap '' SIGPIPE

    "$@" > "$log_file" 2>&1 &
    local cmd_pid=$!
    local start_ts elapsed mins secs start_pct end_pct span tick pct rc final_pct

    start_ts=$(date +%s)
    start_pct=$(( (step_index - 1) * 100 / total_steps ))
    end_pct=$(( step_index * 100 / total_steps ))
    span=$(( end_pct - start_pct - 1 ))
    if (( span < 1 )); then
      span=1
    fi

    tick=0
    while kill -0 "$cmd_pid" 2>/dev/null; do
      elapsed=$(( $(date +%s) - start_ts ))
      mins=$(( elapsed / 60 ))
      secs=$(( elapsed % 60 ))
      pct=$(( start_pct + 1 + (tick % span) ))
      if (( pct >= end_pct )); then
        pct=$(( end_pct - 1 ))
      fi
      if (( pct < start_pct )); then
        pct=$start_pct
      fi

      echo "XXX"
      echo "$pct"
      printf "Step %d of %d\n%s\n\nThis step is still running.\nElapsed: %02d:%02d\nLog: %s\n" "$step_index" "$total_steps" "$step_title" "$mins" "$secs" "$log_file"
      echo "XXX"

      tick=$(( tick + 1 ))
      sleep 1
    done

    wait "$cmd_pid"
    rc=$?
    printf '%s' "$rc" > "$rc_file"

    final_pct=$end_pct
    if (( rc != 0 )); then
      final_pct=$start_pct
    fi

    echo "XXX"
    echo "$final_pct"
    if (( rc == 0 )); then
      printf "Step %d of %d\n%s\n\nCompleted successfully.\nLog: %s\n" "$step_index" "$total_steps" "$step_title" "$log_file"
    else
      printf "Step %d of %d\n%s\n\nFailed.\nLog: %s\n" "$step_index" "$total_steps" "$step_title" "$log_file"
    fi
    echo "XXX"
    sleep 1
  ) | whiptail --title "$INSTALLER_UI_TITLE Installer" --gauge "Preparing ${step_title}" 14 78 0

  local rc=1
  if [[ -f "$rc_file" ]]; then
    rc="$(cat "$rc_file")"
    rm -f "$rc_file"
  fi

  if (( rc != 0 )); then
    show_step_failure "$step_title" "$log_file"
  fi

  return "$rc"
}

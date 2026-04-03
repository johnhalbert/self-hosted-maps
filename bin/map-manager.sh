#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

ensure_state_file
require_cmd whiptail
require_cmd jq

choose_catalog_dataset() {
  local query rows row id name parent url args choice
  query="$(whiptail --title "Catalog Search" --inputbox "Filter datasets by name, id, or parent. Leave blank to browse." 10 80 3>&1 1>&2 2>&3)" || return 1
  mapfile -t rows < <("$SHM_BIN_DIR/list-catalog.sh" "$query" | head -200)
  if [[ "${#rows[@]}" -eq 0 ]]; then
    whiptail --title "Catalog" --msgbox "No datasets matched your query." 10 60
    return 1
  fi
  args=()
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r id name parent url <<<"$row"
    args+=("$id" "$name")
  done
  choice="$(whiptail --title "Catalog" --menu "Choose a dataset to inspect or install" 25 100 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 1
  printf '%s\n' "$choice"
}

show_installed() {
  local tmp
  tmp="$(mktemp)"
  {
    printf 'ID\tNAME\tPROVIDER\tSTATUS\tPBF\n'
    "$SHM_BIN_DIR/list-installed.sh"
  } | column -ts $'\t' > "$tmp"
  whiptail --title "Installed Datasets" --textbox "$tmp" 25 120
  rm -f "$tmp"
}

select_active() {
  local rows row id name provider status pbf args state output cleaned selected
  mapfile -t rows < <("$SHM_BIN_DIR/list-installed.sh")
  if [[ "${#rows[@]}" -eq 0 ]]; then
    whiptail --title "Select Active" --msgbox "No datasets are installed yet." 10 60
    return 0
  fi
  args=()
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r id name provider status pbf <<<"$row"
    state=OFF
    [[ "$status" == "selected" ]] && state=ON
    args+=("$id" "$name" "$state")
  done
  output="$(whiptail --title "Select Active Datasets" --checklist "Choose which installed datasets participate in the current merged map" 25 100 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 0
  cleaned="$(printf '%s' "$output" | tr ' ' '\n' | tr -d '"' | sed '/^$/d')"
  mapfile -t selected < <(printf '%s\n' "$cleaned")
  "$SHM_BIN_DIR/select-datasets.sh" "${selected[@]}" >/dev/null
  whiptail --title "Select Active" --msgbox "Updated selected dataset set." 10 60
}

remove_dataset_ui() {
  local rows row id name provider status pbf args choice
  mapfile -t rows < <("$SHM_BIN_DIR/list-installed.sh")
  if [[ "${#rows[@]}" -eq 0 ]]; then
    whiptail --title "Remove Dataset" --msgbox "No datasets are installed yet." 10 60
    return 0
  fi
  args=()
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r id name provider status pbf <<<"$row"
    args+=("$id" "$name")
  done
  choice="$(whiptail --title "Remove Dataset" --menu "Choose a dataset to remove" 25 100 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 0
  if whiptail --title "Confirm Remove" --yesno "Remove dataset '$choice' from local storage?" 10 70; then
    "$SHM_BIN_DIR/remove-dataset.sh" "$choice" >/dev/null
    whiptail --title "Remove Dataset" --msgbox "Removed dataset '$choice'." 10 60
  fi
}

install_dataset_ui() {
  local dataset_id
  dataset_id="$(choose_catalog_dataset)" || return 0
  "$SHM_BIN_DIR/install-dataset.sh" "$dataset_id" >/dev/null
  if whiptail --title "Install Dataset" --yesno "Dataset '$dataset_id' installed. Add it to the selected set now?" 10 70; then
    mapfile -t current_selected < <(jq -r '.selected[]?' "$SHM_STATE_FILE")
    "$SHM_BIN_DIR/select-datasets.sh" "${current_selected[@]}" "$dataset_id" >/dev/null
  fi
  if whiptail --title "Rebuild Current Map" --yesno "Rebuild the current merged map now?" 10 70; then
    "$SHM_BIN_DIR/rebuild-selected.sh"
    whiptail --title "Rebuild Current Map" --msgbox "Rebuild finished. Check ${SHM_LOG_ROOT}/rebuild-selected.log for details." 10 80
  fi
}

browse_catalog_ui() {
  local dataset_id tmp
  dataset_id="$(choose_catalog_dataset)" || return 0
  tmp="$(mktemp)"
  "$SHM_BIN_DIR/find-dataset.sh" "$dataset_id" | jq . > "$tmp"
  whiptail --title "Dataset Details" --textbox "$tmp" 25 100
  rm -f "$tmp"
}

refresh_catalog_ui() {
  "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
  whiptail --title "Refresh Catalog" --msgbox "Catalog refreshed from Geofabrik." 10 60
}

rebuild_ui() {
  "$SHM_BIN_DIR/rebuild-selected.sh"
  whiptail --title "Rebuild Current Map" --msgbox "Rebuild finished. Check ${SHM_LOG_ROOT}/rebuild-selected.log for details." 10 80
}

while true; do
  choice="$(whiptail --title "Self Hosted Maps Manager" --menu "Choose an action" 20 78 10 \
    1 "Browse catalog" \
    2 "Install dataset" \
    3 "Show installed datasets" \
    4 "Select active datasets" \
    5 "Rebuild current map" \
    6 "Remove dataset" \
    7 "Refresh catalog" \
    8 "Exit" 3>&1 1>&2 2>&3)" || exit 0
  case "$choice" in
    1) browse_catalog_ui ;;
    2) install_dataset_ui ;;
    3) show_installed ;;
    4) select_active ;;
    5) rebuild_ui ;;
    6) remove_dataset_ui ;;
    7) refresh_catalog_ui ;;
    8) exit 0 ;;
  esac
done

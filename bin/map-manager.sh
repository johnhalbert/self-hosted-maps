#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

ensure_state_file
require_cmd whiptail
require_cmd jq
require_cmd column

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
    if [[ -n "$parent" ]]; then
      args+=("$id" "$name [$parent]")
    else
      args+=("$id" "$name")
    fi
  done
  choice="$(whiptail --title "Catalog" --menu "Choose a dataset to inspect or install" 25 110 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 1
  printf '%s\n' "$choice"
}

choose_installed_dataset() {
  local rows row id name provider status pbf_size dataset_size installed_at args choice
  mapfile -t rows < <("$SHM_BIN_DIR/list-installed.sh")
  if [[ "${#rows[@]}" -eq 0 ]]; then
    whiptail --title "Installed Datasets" --msgbox "No datasets are installed yet." 10 60
    return 1
  fi
  args=()
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r id name provider status pbf_size dataset_size installed_at <<<"$row"
    args+=("$id" "$name [$status, $dataset_size]")
  done
  choice="$(whiptail --title "Installed Datasets" --menu "Choose a dataset" 25 110 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 1
  printf '%s\n' "$choice"
}

show_installed() {
  local tmp selected_summary rebuilt_at
  tmp="$(mktemp)"
  selected_summary="$(jq -r '(.selected // []) | if length == 0 then "(none)" else join(", ") end' "$SHM_STATE_FILE")"
  rebuilt_at="$(jq -r '.current.rebuilt_at // "(never)"' "$SHM_STATE_FILE")"
  {
    printf 'Selected datasets: %s\n' "$selected_summary"
    printf 'Current map rebuilt at: %s\n\n' "$rebuilt_at"
    printf 'ID\tNAME\tPROVIDER\tSTATUS\tPBF_SIZE\tDATASET_SIZE\tINSTALLED_AT\n'
    "$SHM_BIN_DIR/list-installed.sh"
  } | column -ts $'\t' > "$tmp"
  whiptail --title "Installed Datasets" --textbox "$tmp" 28 140
  rm -f "$tmp"
}

show_installed_details_ui() {
  local dataset_id tmp
  dataset_id="$(choose_installed_dataset)" || return 0
  tmp="$(mktemp)"
  "$SHM_BIN_DIR/show-installed-details.sh" "$dataset_id" | jq . > "$tmp"
  whiptail --title "Installed Dataset Details" --textbox "$tmp" 28 120
  rm -f "$tmp"
}

select_active() {
  local rows row id name provider status pbf_size dataset_size installed_at args state output cleaned selected
  mapfile -t rows < <("$SHM_BIN_DIR/list-installed.sh")
  if [[ "${#rows[@]}" -eq 0 ]]; then
    whiptail --title "Select Active" --msgbox "No datasets are installed yet." 10 60
    return 0
  fi
  args=()
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r id name provider status pbf_size dataset_size installed_at <<<"$row"
    state=OFF
    if [[ ",$status," == *,selected,* ]]; then
      state=ON
    fi
    args+=("$id" "$name [$dataset_size]" "$state")
  done
  output="$(whiptail --title "Select Active Datasets" --checklist "Choose which installed datasets participate in the current merged map" 25 110 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 0
  cleaned="$(printf '%s' "$output" | tr ' ' '\n' | tr -d '"' | sed '/^$/d')"
  mapfile -t selected < <(printf '%s\n' "$cleaned")
  "$SHM_BIN_DIR/select-datasets.sh" "${selected[@]}" >/dev/null
  whiptail --title "Select Active" --msgbox "Updated selected dataset set." 10 60
}

remove_dataset_ui() {
  local dataset_id
  dataset_id="$(choose_installed_dataset)" || return 0
  if whiptail --title "Confirm Remove" --yesno "Remove dataset '$dataset_id' from local storage?" 10 70; then
    "$SHM_BIN_DIR/remove-dataset.sh" "$dataset_id" >/dev/null
    whiptail --title "Remove Dataset" --msgbox "Removed dataset '$dataset_id'." 10 60
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
  whiptail --title "Catalog Dataset Details" --textbox "$tmp" 25 110
  rm -f "$tmp"
}

refresh_catalog_ui() {
  "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
  whiptail --title "Refresh Catalog" --msgbox "Catalog refreshed from Geofabrik." 10 60
}

check_updates_ui() {
  local tmp
  tmp="$(mktemp)"
  {
    printf 'ID\tNAME\tUPDATE\tREMOTE_LAST_MODIFIED\tLOCAL_SIZE\tREMOTE_SIZE\tNOTE\n'
    "$SHM_BIN_DIR/check-dataset-updates.sh" --refresh-catalog
  } | column -ts $'\t' > "$tmp"
  whiptail --title "Dataset Update Check" --textbox "$tmp" 28 140
  rm -f "$tmp"
}

rebuild_ui() {
  "$SHM_BIN_DIR/rebuild-selected.sh"
  whiptail --title "Rebuild Current Map" --msgbox "Rebuild finished. Check ${SHM_LOG_ROOT}/rebuild-selected.log for details." 10 80
}

while true; do
  choice="$(whiptail --title "Self Hosted Maps Manager" --menu "Choose an action" 22 84 12 \
    1 "Browse catalog" \
    2 "Install dataset" \
    3 "Show installed datasets" \
    4 "Show installed dataset details" \
    5 "Select active datasets" \
    6 "Check dataset updates" \
    7 "Rebuild current map" \
    8 "Remove dataset" \
    9 "Refresh catalog" \
    10 "Exit" 3>&1 1>&2 2>&3)" || exit 0
  case "$choice" in
    1) browse_catalog_ui ;;
    2) install_dataset_ui ;;
    3) show_installed ;;
    4) show_installed_details_ui ;;
    5) select_active ;;
    6) check_updates_ui ;;
    7) rebuild_ui ;;
    8) remove_dataset_ui ;;
    9) refresh_catalog_ui ;;
    10) exit 0 ;;
  esac
done

#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

ensure_state_file
require_cmd whiptail
require_cmd jq
require_cmd column

humanize_catalog_name() {
  local value="$1"
  printf '%s' "$value" \
    | sed -E 's/[_-]+/ /g; s/([[:lower:][:digit:]])([[:upper:]])/\1 \2/g; s/([[:upper:]])([[:upper:]][[:lower:]])/\1 \2/g; s/[[:space:]]+/ /g; s/^ //; s/ $//'
}

choose_catalog_dataset() {
  local query rows row id name parent url args choice human_name tag suffix n
  declare -A tag_to_id=()
  query="$(whiptail --title "Catalog Search" --inputbox "Filter datasets by name, id, or parent. Leave blank to browse." 10 80 3>&1 1>&2 2>&3)" || return 1
  mapfile -t rows < <(bash "$SHM_BIN_DIR/list-catalog.sh" "$query")
  if [[ "${#rows[@]}" -eq 0 ]]; then
    whiptail --title "Catalog" --msgbox "No datasets matched your query." 10 60
    return 1
  fi
  args=()
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r id name parent url <<<"$row"
    human_name="$(humanize_catalog_name "$name")"
    tag="$human_name"
    if [[ -n "${tag_to_id[$tag]+x}" ]]; then
      suffix="$id"
      tag="${human_name} [$suffix]"
      n=2
      while [[ -n "${tag_to_id[$tag]+x}" ]]; do
        tag="${human_name} [$suffix $n]"
        ((n++))
      done
    fi
    tag_to_id["$tag"]="$id"
    args+=("$tag" "${url:-$human_name}")
  done
  choice="$(whiptail --title "Catalog" --menu "Choose a dataset to inspect or install" 25 140 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 1
  printf '%s\n' "${tag_to_id[$choice]}"
}

choose_installed_dataset() {
  local title rows filtered_rows row id name provider status pbf_size dataset_size installed_at args choice filter_query filter_lower
  title="${1:-Installed Datasets}"
  filter_query="$(whiptail --title "$title" --inputbox "Filter installed datasets by id, name, provider, or status. Leave blank to browse all." 10 90 3>&1 1>&2 2>&3)" || return 1
  filter_lower="$(printf '%s' "$filter_query" | tr '[:upper:]' '[:lower:]')"
  mapfile -t rows < <(bash "$SHM_BIN_DIR/list-installed.sh")
  if [[ "${#rows[@]}" -eq 0 ]]; then
    whiptail --title "$title" --msgbox "No datasets are installed yet." 10 60
    return 1
  fi
  filtered_rows=()
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r id name provider status pbf_size dataset_size installed_at <<<"$row"
    haystack="$(printf '%s %s %s %s' "$id" "$name" "$provider" "$status" | tr '[:upper:]' '[:lower:]')"
    if [[ -z "$filter_lower" || "$haystack" == *"$filter_lower"* ]]; then
      filtered_rows+=("$row")
    fi
  done
  if [[ "${#filtered_rows[@]}" -eq 0 ]]; then
    whiptail --title "$title" --msgbox "No installed datasets matched your filter." 10 70
    return 1
  fi
  args=()
  for row in "${filtered_rows[@]}"; do
    IFS=$'\t' read -r id name provider status pbf_size dataset_size installed_at <<<"$row"
    args+=("$id" "$name [$status, $dataset_size]")
  done
  choice="$(whiptail --title "$title" --menu "Choose a dataset" 25 110 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 1
  printf '%s\n' "$choice"
}

show_first_run_hint_if_needed() {
  local installed_count bootstrap_id bootstrap_name bootstrap_provider state_tmp
  if jq -e '.ui.first_run_hint_shown_at? != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
    return 0
  fi
  installed_count="$(jq -r '(.installed // {}) | length' "$SHM_STATE_FILE")"
  bootstrap_id="$(jq -r '.bootstrap.dataset_id // ""' "$SHM_STATE_FILE")"
  bootstrap_name="$(jq -r '.bootstrap.dataset_name // ""' "$SHM_STATE_FILE")"
  bootstrap_provider="$(jq -r '.bootstrap.provider // ""' "$SHM_STATE_FILE")"
  if [[ "$installed_count" == "1" && -n "$bootstrap_id" ]]; then
    whiptail --title "Welcome to Self Hosted Maps" --msgbox "Your first dataset is installed and ready.\n\nBootstrap dataset: ${bootstrap_name:-$bootstrap_id}\nDataset ID: $bootstrap_id\nProvider: ${bootstrap_provider:-unknown}\n\nUse this manager to install more datasets, change the selected set, check for updates, and rebuild the served map." 16 78
    state_tmp="$(mktemp)"
    jq --arg ts "$(date -u +%FT%TZ)" '.ui.first_run_hint_shown_at = $ts' "$SHM_STATE_FILE" > "$state_tmp"
    mv "$state_tmp" "$SHM_STATE_FILE"
  fi
}

show_installed() {
  local tmp selected_summary rebuilt_at current_summary
  tmp="$(mktemp)"
  selected_summary="$(jq -r '(.selected // []) | if length == 0 then "(none)" else join(", ") end' "$SHM_STATE_FILE")"
  current_summary="$(jq -r '(.current.dataset_ids // []) | if length == 0 then "(none)" else join(", ") end' "$SHM_STATE_FILE")"
  rebuilt_at="$(jq -r '.current.rebuilt_at // "(never)"' "$SHM_STATE_FILE")"
  {
    printf 'Selected datasets: %s\n' "$selected_summary"
    printf 'Current served datasets: %s\n' "$current_summary"
    printf 'Current map rebuilt at: %s\n\n' "$rebuilt_at"
    printf 'ID\tNAME\tPROVIDER\tSTATUS\tPBF_SIZE\tDATASET_SIZE\tINSTALLED_AT\n'
    bash "$SHM_BIN_DIR/list-installed.sh"
  } | column -ts $'\t' > "$tmp"
  whiptail --title "Installed Datasets" --textbox "$tmp" 28 140
  rm -f "$tmp"
}

show_installed_details_ui() {
  local dataset_id tmp
  dataset_id="$(choose_installed_dataset "Installed Dataset Details")" || return 0
  tmp="$(mktemp)"
  bash "$SHM_BIN_DIR/show-installed-details.sh" "$dataset_id" | jq . > "$tmp"
  whiptail --title "Installed Dataset Details" --textbox "$tmp" 28 120
  rm -f "$tmp"
}

select_active() {
  local rows row id name provider status pbf_size dataset_size installed_at args state output cleaned selected
  mapfile -t rows < <(bash "$SHM_BIN_DIR/list-installed.sh")
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
  output="$(whiptail --title "Select Active Datasets" --checklist "Choose which installed datasets participate in the next rebuild" 25 110 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 0
  cleaned="$(printf '%s' "$output" | tr ' ' '\n' | tr -d '"' | sed '/^$/d')"
  mapfile -t selected < <(printf '%s\n' "$cleaned")
  bash "$SHM_BIN_DIR/select-datasets.sh" "${selected[@]}" >/dev/null
  whiptail --title "Select Active" --msgbox "Updated selected dataset set." 10 60
}

remove_dataset_ui() {
  local dataset_id
  dataset_id="$(choose_installed_dataset "Remove Dataset")" || return 0
  if whiptail --title "Confirm Remove" --yesno "Remove dataset '$dataset_id' from local storage?" 10 70; then
    bash "$SHM_BIN_DIR/remove-dataset.sh" "$dataset_id" >/dev/null
    whiptail --title "Remove Dataset" --msgbox "Removed dataset '$dataset_id'." 10 60
  fi
}

install_dataset_ui() {
  local dataset_id
  dataset_id="$(choose_catalog_dataset)" || return 0
  bash "$SHM_BIN_DIR/install-dataset.sh" "$dataset_id" >/dev/null
  if whiptail --title "Install Dataset" --yesno "Dataset '$dataset_id' installed. Add it to the selected set now?" 10 70; then
    mapfile -t current_selected < <(jq -r '.selected[]?' "$SHM_STATE_FILE")
    bash "$SHM_BIN_DIR/select-datasets.sh" "${current_selected[@]}" "$dataset_id" >/dev/null
  fi
  if confirm_rebuild_summary; then
    bash "$SHM_BIN_DIR/rebuild-selected.sh"
    whiptail --title "Rebuild Current Map" --msgbox "Rebuild finished. Check ${SHM_LOG_ROOT}/rebuild-selected.log for details." 10 80
  fi
}

browse_catalog_ui() {
  local dataset_id tmp
  dataset_id="$(choose_catalog_dataset)" || return 0
  tmp="$(mktemp)"
  bash "$SHM_BIN_DIR/find-dataset.sh" "$dataset_id" | jq . > "$tmp"
  whiptail --title "Catalog Dataset Details" --textbox "$tmp" 25 110
  rm -f "$tmp"
}

refresh_catalog_ui() {
  bash "$SHM_BIN_DIR/refresh-catalog.sh" >/dev/null
  whiptail --title "Refresh Catalog" --msgbox "Catalog refreshed from Geofabrik. Legacy boundary metadata was backfilled if needed." 10 78
}

check_updates_ui() {
  local tmp
  tmp="$(mktemp)"
  {
    printf 'ID\tNAME\tUPDATE\tREMOTE_LAST_MODIFIED\tLOCAL_SIZE\tREMOTE_SIZE\tNOTE\n'
    bash "$SHM_BIN_DIR/check-dataset-updates.sh" --refresh-catalog
  } | column -ts $'\t' > "$tmp"
  whiptail --title "Dataset Update Check" --textbox "$tmp" 28 140
  rm -f "$tmp"
}

update_dataset_ui() {
  local dataset_id tmp status note rebuild_args update_json
  dataset_id="$(choose_installed_dataset "Update Dataset")" || return 0
  update_json="$(bash "$SHM_BIN_DIR/check-dataset-updates.sh" "$dataset_id" --json --refresh-catalog | jq '.[0]')"
  status="$(jq -r '.update_status // "unknown"' <<<"$update_json")"
  note="$(jq -r '.note // ""' <<<"$update_json")"
  tmp="$(mktemp)"
  jq . <<<"$update_json" > "$tmp"
  whiptail --title "Update Preview" --textbox "$tmp" 22 110
  rm -f "$tmp"
  if [[ "$status" == "up-to-date" ]]; then
    if ! whiptail --title "Update Dataset" --yesno "Dataset '$dataset_id' appears up to date. Redownload it anyway?" 10 70; then
      return 0
    fi
  else
    if ! whiptail --title "Update Dataset" --yesno "Update dataset '$dataset_id' now?\n\nStatus: $status\nNote: $note" 12 80; then
      return 0
    fi
  fi
  rebuild_args=()
  if jq -e --arg id "$dataset_id" '(.selected // []) | index($id) != null' "$SHM_STATE_FILE" >/dev/null 2>&1; then
    if whiptail --title "Update Dataset" --yesno "Dataset '$dataset_id' is selected. Rebuild the current map after updating?" 10 75; then
      rebuild_args+=(--rebuild)
    fi
  fi
  bash "$SHM_BIN_DIR/update-dataset.sh" "$dataset_id" --refresh-catalog "${rebuild_args[@]}"
  whiptail --title "Update Dataset" --msgbox "Updated dataset '$dataset_id'." 10 60
}

confirm_rebuild_summary() {
  local selected_count summary rebuilt_at message
  selected_count="$(jq -r '(.selected // []) | length' "$SHM_STATE_FILE")"
  if [[ "$selected_count" == "0" ]]; then
    whiptail --title "Rebuild Current Map" --msgbox "No datasets are currently selected." 10 60
    return 1
  fi
  summary="$(jq -r '(.selected // []) | join(", ")' "$SHM_STATE_FILE")"
  rebuilt_at="$(jq -r '.current.rebuilt_at // "(never)"' "$SHM_STATE_FILE")"
  message="Selected datasets: $summary\n\nSelected count: $selected_count\nCurrent map rebuilt at: $rebuilt_at\n\nProceed with rebuild?"
  whiptail --title "Rebuild Current Map" --yesno "$message" 15 90
}

rebuild_ui() {
  if ! confirm_rebuild_summary; then
    return 0
  fi
  bash "$SHM_BIN_DIR/rebuild-selected.sh"
  whiptail --title "Rebuild Current Map" --msgbox "Rebuild finished. Check ${SHM_LOG_ROOT}/rebuild-selected.log for details." 10 80
}

show_first_run_hint_if_needed

while true; do
  choice="$(whiptail --title "Self Hosted Maps Manager" --menu "Choose an action" 23 86 13 \
    1 "Browse catalog" \
    2 "Install dataset" \
    3 "Show installed datasets" \
    4 "Show installed dataset details" \
    5 "Select active datasets" \
    6 "Check dataset updates" \
    7 "Update dataset" \
    8 "Rebuild current map" \
    9 "Remove dataset" \
    10 "Refresh catalog" \
    11 "Exit" 3>&1 1>&2 2>&3)" || exit 0
  case "$choice" in
    1) browse_catalog_ui ;;
    2) install_dataset_ui ;;
    3) show_installed ;;
    4) show_installed_details_ui ;;
    5) select_active ;;
    6) check_updates_ui ;;
    7) update_dataset_ui ;;
    8) rebuild_ui ;;
    9) remove_dataset_ui ;;
    10) refresh_catalog_ui ;;
    11) exit 0 ;;
  esac
done

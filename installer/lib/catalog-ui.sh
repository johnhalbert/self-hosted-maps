#!/usr/bin/env bash
set -euo pipefail

ensure_catalog_deps() {
  local missing=()
  command -v curl >/dev/null 2>&1 || missing+=(curl)
  command -v jq >/dev/null 2>&1 || missing+=(jq)
  if [[ "${#missing[@]}" -gt 0 ]]; then
    apt-get update
    apt-get install -y "${missing[@]}"
  fi
}

choose_bootstrap_mode() {
  whiptail --title "Initial Dataset" --menu "Choose how to bootstrap the initial map:" 18 90 8 \
    world "Use the full OSM planet PBF" \
    catalog "Browse the live dataset catalog" \
    custom "Enter a custom .osm.pbf URL" 3>&1 1>&2 2>&3
}

choose_catalog_dataset_id() {
  local repo_root="$1"
  local query rows row id name parent url args choice

  ensure_catalog_deps
  bash "$repo_root/bin/fetch-catalog.sh" >/dev/null

  query="$(whiptail --title "Catalog Search" --inputbox "Filter datasets by name, id, or parent. Leave blank to browse." 10 80 3>&1 1>&2 2>&3)" || return 1
  mapfile -t rows < <(bash "$repo_root/bin/list-catalog.sh" "$query" | head -200)
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

  choice="$(whiptail --title "Catalog" --menu "Choose a dataset to install first" 25 110 15 "${args[@]}" 3>&1 1>&2 2>&3)" || return 1
  printf '%s\n' "$choice"
}

choose_custom_dataset_name() {
  whiptail --title "Custom Dataset Name" --inputbox "Enter a short name for this custom dataset:" 10 70 "custom-bootstrap" 3>&1 1>&2 2>&3
}

choose_custom_pbf_url() {
  whiptail --title "Custom PBF URL" --inputbox "Enter the full URL to a .osm.pbf file:" 10 90 3>&1 1>&2 2>&3
}

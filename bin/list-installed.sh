#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file

jq -r '
  . as $root
  | ($root.installed | to_entries[]?)
  | [
      .key,
      .value.name,
      .value.provider,
      (if (($root.selected // []) | index(.key)) then "selected" else "installed" end),
      .value.pbf_path
    ]
  | @tsv
' "$SHM_STATE_FILE"

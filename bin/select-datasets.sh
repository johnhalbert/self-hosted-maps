#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_state_file
acquire_mutation_lock

SELECTED_JSON="$(json_compact_array_from_args "$@")"
STATE_TMP="$(mktemp)"
jq --argjson selected "$SELECTED_JSON" '.selected = ($selected | unique)' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

log "Updated selected dataset set"

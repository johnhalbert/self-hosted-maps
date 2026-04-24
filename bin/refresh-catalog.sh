#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

ensure_state_file
acquire_mutation_lock

bash "$SHM_BIN_DIR/fetch-catalog.sh" >/dev/null
bash "$SHM_BIN_DIR/backfill-installed-boundaries.sh" >/dev/null

echo "$SHM_NORMALIZED_CATALOG"

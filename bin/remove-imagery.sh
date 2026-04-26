#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_shm_common.sh"

require_cmd jq
ensure_imagery_state

PYTHON_BIN="${SHM_PYTHON_BIN:-python3}"
OVERLAY_ID="${1:?usage: remove-imagery.sh <imagery-id>}"

if [[ ! "$OVERLAY_ID" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]]; then
  echo "Invalid imagery id." >&2
  exit 1
fi

acquire_mutation_lock
ensure_imagery_state

metadata="$(jq -c --arg id "$OVERLAY_ID" '.imagery.installed[$id]' "$SHM_STATE_FILE")"
if [[ -z "$metadata" || "$metadata" == "null" ]]; then
  echo "Unknown imagery overlay: $OVERLAY_ID" >&2
  exit 1
fi

mbtiles_path="$(jq -r '.path // ""' <<<"$metadata")"
managed_dir="$("$PYTHON_BIN" - "$SHM_IMAGERY_ROOT" "$OVERLAY_ID" "$mbtiles_path" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=False)
overlay_id = sys.argv[2]
path = Path(sys.argv[3]).resolve(strict=False)
expected_dir = (root / overlay_id).resolve(strict=False)

try:
    path.relative_to(root)
except ValueError as exc:
    raise SystemExit("Recorded imagery path is outside the managed imagery root.") from exc

if path.name != "tiles.mbtiles" or path.parent != expected_dir:
    raise SystemExit("Recorded imagery path is not a managed imagery MBTiles path.")

print(expected_dir)
PY
)"

STATE_TMP="$(mktemp)"
jq --arg id "$OVERLAY_ID" '
  del(.imagery.installed[$id])
  | .imagery.order = ((.imagery.order // []) - [$id])
  | .imagery.enabled = ((.imagery.enabled // []) - [$id])
' "$SHM_STATE_FILE" > "$STATE_TMP"
mv "$STATE_TMP" "$SHM_STATE_FILE"

if [[ -d "$managed_dir" ]]; then
  rm -rf "$managed_dir"
fi

log "Removed imagery overlay $OVERLAY_ID"

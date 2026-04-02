#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root

if [[ -f "${SHM_DATA_ROOT}/current/openmaptiles.mbtiles" ]]; then
  log "MBTiles already exists, skipping initial build"
else
  log "No MBTiles found, running initial build"
  "${SHM_INSTALL_ROOT}/bin/update-data.sh"
fi

log "Starting tile server"
systemctl restart self-hosted-maps-tileserver.service

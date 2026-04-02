#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
log "Running initial tile build"
"${SHM_INSTALL_ROOT}/bin/update-data.sh"
log "Starting tile server"
systemctl restart self-hosted-maps-tileserver.service

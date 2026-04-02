#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
if ! command -v node >/dev/null 2>&1; then
  log "Installing Node.js and npm from Debian"
  apt-get install -y nodejs npm
fi

log "Installing tileserver-gl-light globally"
npm install -g tileserver-gl-light

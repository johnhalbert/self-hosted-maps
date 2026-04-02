#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
if ! command -v node >/dev/null 2>&1; then
  log "Installing Node.js and npm from Debian"
  apt-get install -y nodejs npm python3-setuptools
fi

if command -v tileserver-gl >/dev/null 2>&1; then
  log "tileserver-gl already installed"
else
  log "Installing tileserver-gl globally"
  npm install -g tileserver-gl-light
fi

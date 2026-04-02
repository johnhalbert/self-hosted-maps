#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
if command -v tilemaker >/dev/null 2>&1; then
  log "tilemaker already installed"
  exit 0
fi

WORKDIR="/usr/local/src/tilemaker"
rm -rf "$WORKDIR"
git clone https://github.com/systemed/tilemaker.git "$WORKDIR"
cd "$WORKDIR"
mkdir -p build
cd build
cmake ..
make -j"$(nproc)"
make install

#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
if [[ -x /usr/local/bin/tilemaker ]] || command -v tilemaker >/dev/null 2>&1; then
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
make -j1
make install

hash -r
if [[ -x /usr/local/bin/tilemaker ]]; then
  log "tilemaker installed at /usr/local/bin/tilemaker"
elif command -v tilemaker >/dev/null 2>&1; then
  log "tilemaker installed at $(command -v tilemaker)"
else
  echo "tilemaker install completed but binary not found on PATH" >&2
  exit 1
fi

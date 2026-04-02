#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
safe_mkdirs
write_env_file "$SHM_CONFIG_ROOT"

install -d -m 0755 "$SHM_INSTALL_ROOT/bin" "$SHM_INSTALL_ROOT/www" "$SHM_INSTALL_ROOT/config/tilemaker"
cp "${SHM_REPO_ROOT}/bin/"* "$SHM_INSTALL_ROOT/bin/"
cp "${SHM_REPO_ROOT}/config/tilemaker/config.json" "$SHM_INSTALL_ROOT/config/tilemaker/config.json"
cp "${SHM_REPO_ROOT}/config/tilemaker/process.lua" "$SHM_INSTALL_ROOT/config/tilemaker/process.lua"
cp "${SHM_REPO_ROOT}/assets/index-v2.html" "$SHM_INSTALL_ROOT/www/index.html"
mkdir -p "$SHM_INSTALL_ROOT/www/vendor"
curl -L --fail --retry 5 -o "$SHM_INSTALL_ROOT/www/vendor/maplibre-gl.js" https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.js
curl -L --fail --retry 5 -o "$SHM_INSTALL_ROOT/www/vendor/maplibre-gl.css" https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.css
chmod +x "$SHM_INSTALL_ROOT/bin/"*.sh

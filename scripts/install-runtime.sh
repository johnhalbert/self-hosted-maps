#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
safe_mkdirs
write_env_file "$SHM_CONFIG_ROOT"
write_runtime_env_file_if_missing "$SHM_CONFIG_ROOT"

install -d -m 0755 "$SHM_INSTALL_ROOT/bin" "$SHM_INSTALL_ROOT/www" "$SHM_INSTALL_ROOT/config/tilemaker"
cp "${SHM_REPO_ROOT}/bin/"* "$SHM_INSTALL_ROOT/bin/"

TILEMAKER_RESOURCES="/usr/local/src/tilemaker/resources"

if [[ -f "${TILEMAKER_RESOURCES}/config-openmaptiles.json" && -f "${TILEMAKER_RESOURCES}/process-openmaptiles.lua" ]]; then
  cp "${TILEMAKER_RESOURCES}/config-openmaptiles.json" "$SHM_INSTALL_ROOT/config/tilemaker/config.json"
  cp "${TILEMAKER_RESOURCES}/process-openmaptiles.lua" "$SHM_INSTALL_ROOT/config/tilemaker/process.lua"
else
  echo "Known-good tilemaker resources not found in ${TILEMAKER_RESOURCES}" >&2
  exit 1
fi
cp -R "${SHM_REPO_ROOT}/assets/." "$SHM_INSTALL_ROOT/www/"
mkdir -p "$SHM_INSTALL_ROOT/www/vendor"
curl -L --fail --retry 5 -o "$SHM_INSTALL_ROOT/www/vendor/maplibre-gl.js" https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.js
curl -L --fail --retry 5 -o "$SHM_INSTALL_ROOT/www/vendor/maplibre-gl.css" https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.css
chmod +x "$SHM_INSTALL_ROOT/bin/"*.sh

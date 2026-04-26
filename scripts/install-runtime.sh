#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
safe_mkdirs
write_env_file "$SHM_CONFIG_ROOT"
write_runtime_env_file_if_missing "$SHM_CONFIG_ROOT"

install -d -m 0755 "$SHM_INSTALL_ROOT/bin" "$SHM_INSTALL_ROOT/www" "$SHM_INSTALL_ROOT/config/tilemaker"
cp "${SHM_REPO_ROOT}/bin/"* "$SHM_INSTALL_ROOT/bin/"

if [[ ! -f "${SHM_REPO_ROOT}/config/tilemaker/config.json" || ! -f "${SHM_REPO_ROOT}/config/tilemaker/process.lua" ]]; then
  echo "Repo-owned tilemaker profile is incomplete under ${SHM_REPO_ROOT}/config/tilemaker" >&2
  exit 1
fi
cp -R "${SHM_REPO_ROOT}/config/tilemaker/." "$SHM_INSTALL_ROOT/config/tilemaker/"
cp -R "${SHM_REPO_ROOT}/assets/." "$SHM_INSTALL_ROOT/www/"
mkdir -p "$SHM_INSTALL_ROOT/www/vendor"
curl -L --fail --retry 5 -o "$SHM_INSTALL_ROOT/www/vendor/maplibre-gl.js" https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.js
curl -L --fail --retry 5 -o "$SHM_INSTALL_ROOT/www/vendor/maplibre-gl.css" https://unpkg.com/maplibre-gl@5.6.2/dist/maplibre-gl.css
chmod +x "$SHM_INSTALL_ROOT/bin/"*.sh
chmod +x "$SHM_INSTALL_ROOT/bin/"*.py 2>/dev/null || true
write_initial_app_manifest "$SHM_CONFIG_ROOT" "$SHM_REPO_ROOT"

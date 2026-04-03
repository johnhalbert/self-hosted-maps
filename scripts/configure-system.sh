#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root

install -m 0644 "${SHM_REPO_ROOT}/systemd/self-hosted-maps-tileserver.service" /etc/systemd/system/self-hosted-maps-tileserver.service
sed -i "s|__CONFIG_ROOT__|${SHM_CONFIG_ROOT}|g" /etc/systemd/system/self-hosted-maps-tileserver.service
sed -i "s|__DATA_ROOT__|${SHM_DATA_ROOT}|g" /etc/systemd/system/self-hosted-maps-tileserver.service

FONTS_ROOT="$(npm root -g 2>/dev/null)/tileserver-gl-light/node_modules/tileserver-gl-styles/fonts"
ALT_FONTS_ROOT="/usr/local/lib/node_modules/tileserver-gl-light/node_modules/tileserver-gl-styles/fonts"

if [[ ! -d "$FONTS_ROOT" && -d "$ALT_FONTS_ROOT" ]]; then
  FONTS_ROOT="$ALT_FONTS_ROOT"
fi

if [[ ! -d "$FONTS_ROOT" ]]; then
  echo "Unable to locate TileServer fonts directory. Checked: $FONTS_ROOT and $ALT_FONTS_ROOT" >&2
  exit 1
fi

install -m 0644 "${SHM_REPO_ROOT}/config/tileserver-config.json" "${SHM_CONFIG_ROOT}/tileserver-config.json"
sed -i "s|__FONTS_ROOT__|${FONTS_ROOT}|g" "${SHM_CONFIG_ROOT}/tileserver-config.json"

install -m 0644 "${SHM_REPO_ROOT}/config/nginx-viewer.conf" /etc/nginx/sites-available/self-hosted-maps-viewer
sed -i "s|__INSTALL_ROOT__|${SHM_INSTALL_ROOT}|g" /etc/nginx/sites-available/self-hosted-maps-viewer

ln -sf /etc/nginx/sites-available/self-hosted-maps-viewer /etc/nginx/sites-enabled/self-hosted-maps-viewer
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable self-hosted-maps-tileserver.service
systemctl enable nginx
systemctl restart nginx

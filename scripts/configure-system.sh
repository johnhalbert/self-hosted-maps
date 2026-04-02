#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root

install -m 0644 "${SHM_REPO_ROOT}/systemd/self-hosted-maps-tileserver.service" /etc/systemd/system/self-hosted-maps-tileserver.service
sed -i "s|__INSTALL_ROOT__|${SHM_INSTALL_ROOT}|g" /etc/systemd/system/self-hosted-maps-tileserver.service
sed -i "s|__DATA_ROOT__|${SHM_DATA_ROOT}|g" /etc/systemd/system/self-hosted-maps-tileserver.service
sed -i "s|__CONFIG_ROOT__|${SHM_CONFIG_ROOT}|g" /etc/systemd/system/self-hosted-maps-tileserver.service

install -m 0644 "${SHM_REPO_ROOT}/config/tileserver-config.json" "${SHM_CONFIG_ROOT}/tileserver-config.json"
install -m 0644 "${SHM_REPO_ROOT}/config/nginx-viewer.conf" /etc/nginx/sites-available/self-hosted-maps-viewer
sed -i "s|__INSTALL_ROOT__|${SHM_INSTALL_ROOT}|g" /etc/nginx/sites-available/self-hosted-maps-viewer

ln -sf /etc/nginx/sites-available/self-hosted-maps-viewer /etc/nginx/sites-enabled/self-hosted-maps-viewer
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable self-hosted-maps-tileserver.service
systemctl enable nginx
systemctl restart nginx

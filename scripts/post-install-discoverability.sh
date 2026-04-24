#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root

install -d -m 0755 /usr/local/bin
ln -sf "${SHM_INSTALL_ROOT}/bin/_shm_common.sh" /usr/local/bin/_shm_common.sh
ln -sf "${SHM_INSTALL_ROOT}/bin/map-manager.sh" /usr/local/bin/self-hosted-maps-manager
ln -sf "${SHM_INSTALL_ROOT}/bin/rebuild-selected.sh" /usr/local/bin/self-hosted-maps-rebuild
ln -sf "${SHM_INSTALL_ROOT}/bin/refresh-catalog.sh" /usr/local/bin/self-hosted-maps-refresh-catalog
ln -sf "${SHM_INSTALL_ROOT}/bin/list-installed.sh" /usr/local/bin/self-hosted-maps-list-installed

install -m 0644 "${SHM_REPO_ROOT}/docs/manager-usage.txt" "${SHM_CONFIG_ROOT}/manager-usage.txt"

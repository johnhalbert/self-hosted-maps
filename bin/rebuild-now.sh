#!/usr/bin/env bash
set -euo pipefail
source /etc/self-hosted-maps/self-hosted-maps.conf
exec bash "${SHM_INSTALL_ROOT}/bin/update-data.sh"

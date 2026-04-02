#!/usr/bin/env bash
set -euo pipefail
source /etc/self-hosted-maps/self-hosted-maps.conf
exec "${SHM_INSTALL_ROOT}/bin/update-data.sh"

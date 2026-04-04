#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
CRON_FILE="/etc/cron.d/self-hosted-maps"
cat > "$CRON_FILE" <<CRON
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${SHM_UPDATE_SCHEDULE} root bash ${SHM_INSTALL_ROOT}/bin/update-data.sh
CRON
chmod 0644 "$CRON_FILE"
systemctl restart cron

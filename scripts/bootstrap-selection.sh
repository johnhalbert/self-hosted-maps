#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root

BOOTSTRAP_MODE="${SHM_BOOTSTRAP_MODE:?SHM_BOOTSTRAP_MODE is required}"
BOOTSTRAP_URL="${SHM_PBF_URL:?SHM_PBF_URL is required}"
BOOTSTRAP_ID="${SHM_BOOTSTRAP_DATASET_ID:-}"
BOOTSTRAP_NAME="${SHM_BOOTSTRAP_DATASET_NAME:-}"
BOOTSTRAP_PROVIDER="${SHM_BOOTSTRAP_PROVIDER:-custom}"

case "$BOOTSTRAP_MODE" in
  catalog)
    if [[ -z "$BOOTSTRAP_ID" ]]; then
      echo "Catalog bootstrap requires SHM_BOOTSTRAP_DATASET_ID" >&2
      exit 1
    fi
    "${SHM_INSTALL_ROOT}/bin/install-dataset.sh" "$BOOTSTRAP_ID" --select --rebuild
    ;;
  custom|world)
    if [[ -z "$BOOTSTRAP_ID" || -z "$BOOTSTRAP_NAME" ]]; then
      echo "$BOOTSTRAP_MODE bootstrap requires SHM_BOOTSTRAP_DATASET_ID and SHM_BOOTSTRAP_DATASET_NAME" >&2
      exit 1
    fi
    "${SHM_INSTALL_ROOT}/bin/install-dataset-url.sh" "$BOOTSTRAP_ID" "$BOOTSTRAP_NAME" "$BOOTSTRAP_URL" --provider "$BOOTSTRAP_PROVIDER" --select --rebuild
    ;;
  *)
    echo "Unknown bootstrap mode: $BOOTSTRAP_MODE" >&2
    exit 1
    ;;
 esac

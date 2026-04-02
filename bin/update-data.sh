#!/usr/bin/env bash
set -euo pipefail

source /etc/self-hosted-maps/self-hosted-maps.conf

STAMP="$(date +%Y%m%d-%H%M%S)"
INCOMING_DIR="${SHM_DATA_ROOT}/incoming/${STAMP}"
BUILD_DIR="${SHM_DATA_ROOT}/builds/${STAMP}"
TMP_DIR="${SHM_DATA_ROOT}/current.next"
LOG_FILE="${SHM_LOG_ROOT}/pipeline.log"

mkdir -p "$INCOMING_DIR" "$BUILD_DIR" "$TMP_DIR" "$SHM_LOG_ROOT"
exec >> "$LOG_FILE" 2>&1

echo "[$(date '+%F %T')] starting update"
curl -L --fail --retry 5 -o "$INCOMING_DIR/source.osm.pbf" "$SHM_PBF_URL"

tilemaker \
  --input "$INCOMING_DIR/source.osm.pbf" \
  --output "$BUILD_DIR/openmaptiles.mbtiles" \
  --config "${SHM_INSTALL_ROOT}/config/tilemaker/config.json" \
  --process "${SHM_INSTALL_ROOT}/config/tilemaker/process.lua"

sqlite3 "$BUILD_DIR/openmaptiles.mbtiles" "select count(*) from tiles;" | grep -Eq '^[1-9][0-9]*$'

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
cp "$BUILD_DIR/openmaptiles.mbtiles" "$TMP_DIR/openmaptiles.mbtiles"
rm -rf "${SHM_DATA_ROOT}/current.prev"
mv "${SHM_DATA_ROOT}/current" "${SHM_DATA_ROOT}/current.prev" 2>/dev/null || true
mv "$TMP_DIR" "${SHM_DATA_ROOT}/current"
rm -rf "${SHM_DATA_ROOT}/current.prev"

systemctl restart self-hosted-maps-tileserver.service

echo "[$(date '+%F %T')] update complete"

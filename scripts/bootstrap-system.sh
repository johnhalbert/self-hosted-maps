#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

ensure_root
log "Updating apt metadata"
export DEBIAN_FRONTEND=noninteractive
apt-get update
log "Upgrading installed packages"
apt-get -y upgrade
log "Installing base dependencies"
apt-get install -y \
  ca-certificates \
  curl \
  wget \
  git \
  jq \
  unzip \
  tar \
  cron \
  whiptail \
  dialog \
  build-essential \
  cmake \
  pkg-config \
  zlib1g-dev \
  libboost-all-dev \
  liblua5.3-dev \
  lua5.3 \
  libsqlite3-dev \
  sqlite3 \
  osmium-tool \
  python3 \
  python3-venv \
  python3-pip \
  python3-setuptools \
  nginx
systemctl enable cron
systemctl restart cron

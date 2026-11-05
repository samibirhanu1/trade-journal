#!/usr/bin/env bash
# init-server.sh: prepare a fresh Ubuntu server for the trade-journal app.
# Safe to run more than once.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="${APP_DIR:-/opt/trade-journal}"
ENABLE_FIREWALL="${ENABLE_FIREWALL:-true}"

log() { echo "[init] $*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root (or with sudo)." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

log "Installing base packages"
apt-get update
apt-get install -y curl git ca-certificates sudo ufw

if id "$DEPLOY_USER" >/dev/null 2>&1; then
  log "User $DEPLOY_USER already exists"
else
  log "Creating user $DEPLOY_USER"
  useradd -m -s /bin/bash "$DEPLOY_USER"
fi
usermod -aG sudo "$DEPLOY_USER"

log "Preparing $APP_DIR"
mkdir -p "$APP_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

if command -v docker >/dev/null 2>&1; then
  log "Docker already installed"
else
  log "Installing Docker"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

usermod -aG docker "$DEPLOY_USER"

if [ -d /run/systemd/system ]; then
  systemctl enable --now docker
else
  log "No systemd here (probably a container), skipping Docker service start"
fi

if [ "$ENABLE_FIREWALL" = "true" ]; then
  log "Configuring firewall"
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
else
  log "Firewall step skipped (ENABLE_FIREWALL=$ENABLE_FIREWALL)"
fi

log "Done."
docker --version
docker compose version
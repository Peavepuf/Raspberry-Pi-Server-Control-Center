#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/Peavepuf/Raspberry-Pi-Server-Control-Center.git"
WORK_DIR="$(mktemp -d /tmp/rpi-server-control-center-update-XXXXXX)"

cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

echo "[1/4] Downloading latest project files"
git clone --depth 1 "${REPO_URL}" "${WORK_DIR}"

echo "[2/4] Entering update workspace"
cd "${WORK_DIR}"

echo "[3/4] Running Raspberry Pi installer/update"
chmod +x install_pi.sh
./install_pi.sh

echo "[4/4] Update completed"
echo
echo "If the GUI is already open, close it and start it again."
echo "A reboot is recommended after major updates:"
echo "  sudo reboot"

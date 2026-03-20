#!/usr/bin/env bash
set -euo pipefail

APP_NAME="raspberry-pi-server-control-center"
TARGET_DIR="/opt/${APP_NAME}"
PI_USER="${SUDO_USER:-pi}"
PI_HOME="$(eval echo "~${PI_USER}")"
AUTOSTART_DIR="${PI_HOME}/.config/autostart"
DESKTOP_FILE="${AUTOSTART_DIR}/${APP_NAME}.desktop"
START_SCRIPT="${TARGET_DIR}/start_dashboard.sh"
SERVICE_NAME="server-monitor.service"

echo "[1/8] Preparing target directory: ${TARGET_DIR}"
sudo mkdir -p "${TARGET_DIR}"
sudo rsync -a --delete ./ "${TARGET_DIR}/" \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude "*.pyc"

echo "[2/8] Installing required packages"
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-tk python3-rpi.gpio iputils-ping rsync

echo "[3/8] Creating Python virtual environment"
sudo python3 -m venv --system-site-packages "${TARGET_DIR}/.venv"

echo "[4/8] Writing launcher script"
sudo tee "${START_SCRIPT}" > /dev/null <<EOF
#!/usr/bin/env bash
cd "${TARGET_DIR}"
exec "${TARGET_DIR}/.venv/bin/python" "${TARGET_DIR}/main.py"
EOF
sudo chmod +x "${START_SCRIPT}"

echo "[5/8] Applying file permissions"
sudo mkdir -p "${TARGET_DIR}/data"
sudo chown -R "${PI_USER}:${PI_USER}" "${TARGET_DIR}"
sudo usermod -aG gpio "${PI_USER}" || true

echo "[6/8] Configuring desktop auto-start"
sudo -u "${PI_USER}" mkdir -p "${AUTOSTART_DIR}"
sudo -u "${PI_USER}" tee "${DESKTOP_FILE}" > /dev/null <<EOF
[Desktop Entry]
Type=Application
Name=Raspberry Pi Server Control Center
Comment=Server monitoring dashboard
Exec=${START_SCRIPT}
Path=${TARGET_DIR}
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "[7/8] Disabling old headless service if present"
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}"; then
  sudo systemctl disable --now "${SERVICE_NAME}" || true
fi

echo "[8/8] Installation completed"
echo
echo "The Tkinter dashboard will open automatically when the desktop session starts."
echo "Manual start command:"
echo "  ${START_SCRIPT}"
echo
echo "Headless mode command:"
echo "  cd ${TARGET_DIR} && ${TARGET_DIR}/.venv/bin/python main.py --headless"

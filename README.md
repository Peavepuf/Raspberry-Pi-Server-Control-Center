# Raspberry Pi Server Control Center

Raspberry Pi Server Control Center is a desktop and background monitoring application for Raspberry Pi devices. It checks server availability, stores results in SQLite, sends Telegram notifications, and controls a cooling fan through GPIO.

## Features

- Hourly connectivity checks
- HTTP/HTTPS status checks
- SSL expiry warnings
- Daily and weekly summary reports
- Telegram notifications and alerts
- Telegram test message button in the GUI
- Tkinter desktop interface
- SQLite-based local storage
- Target management from the interface
- Telegram settings management from the interface
- Relay-based fan control with separate start/stop thresholds

## What the Application Monitors

- Domains
- URLs
- IP addresses

Each tracked target includes:

- **Name**
- **Address / URL / IP**
- **Enabled / disabled state**

These values are stored in the database and used consistently in:

- the Tkinter dashboard
- Telegram reports
- daily and weekly summaries

## HTTP and SSL Monitoring

- If you enter a full `http://` or `https://` URL, that exact URL is tested.
- If you enter a domain or IP without a scheme, the application tries `https://` first and then `http://`.
- HTTP status results are stored in SQLite for every hourly check.
- SSL expiry checks are performed for HTTPS endpoints when available.
- SSL warning messages are sent through Telegram when expiry thresholds are reached.

## Fan Control

The relay fan controller uses two temperature points:

- **Fan Start Temperature**: the fan turns on
- **Fan Stop Temperature**: the fan turns off

This creates a hysteresis window so the relay does not switch on and off continuously. For example, you can set the fan to start at `55C` and stop at `50C`.

Relay mode can also be configured:

- **Active LOW**: the relay turns on when the GPIO output goes LOW
- **Active HIGH**: the relay turns on when the GPIO output goes HIGH

Default values:

- GPIO pin: `23`
- fan stop temperature: `50C`
- fan start temperature: `55C`
- relay mode: `active LOW`

## Graphical Interface

Start the application with the GUI:

```bash
python main.py
```

The interface includes:

- current target status list
- target names and addresses
- latency values
- HTTP/HTTPS result overview
- SSL status overview
- 24-hour, 7-day, and overall uptime
- error details
- CPU temperature
- current fan on/off state
- upcoming scheduled jobs
- settings page

## Settings Page

The settings page allows you to manage:

- tracked target name
- tracked target address / URL / IP
- target enabled state
- GPIO pin
- fan stop temperature
- fan start temperature
- relay active-low mode
- fan polling interval
- Telegram bot token
- Telegram chat / user ID list
- Telegram test message button

When a full URL is entered, the application automatically extracts the hostname required for ping checks while keeping the original address in the database.

## Command Line Usage

### Start with GUI

```bash
python main.py
```

### Start without GUI

```bash
python main.py --headless
```

### Run a single check

```bash
python main.py --run-once
```

### Generate daily summary

```bash
python main.py --run-daily
```

### Generate weekly summary

```bash
python main.py --run-weekly
```

### Test without Telegram notifications

```bash
python main.py --run-once --no-notify
```

## Telegram Commands

- `/start`
- `/help`
- `/status`
- `/uptime`
- `/servers`
- `/daily`
- `/weekly`

## Fresh Raspberry Pi Installation

For a clean install on a new Raspberry Pi:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/Peavepuf/Raspberry-Pi-Server-Control-Center.git
cd Raspberry-Pi-Server-Control-Center
chmod +x install_pi.sh
sudo ./install_pi.sh
```

After installation:

- the GUI starts automatically when the desktop session opens
- the application is installed under `/opt/raspberry-pi-server-control-center`
- local data is kept in `/opt/raspberry-pi-server-control-center/data`

Manual start commands:

```bash
/opt/raspberry-pi-server-control-center/start_dashboard.sh
```

```bash
cd /opt/raspberry-pi-server-control-center
.venv/bin/python main.py --headless
```

The install script:

- installs required packages
- copies the application to the target directory
- creates a Python virtual environment
- configures GUI auto-start

## Update Existing Raspberry Pi Installation

If you already have a local copy of the project:

```bash
cd Raspberry-Pi-Server-Control-Center
chmod +x updater.sh
./updater.sh
```

If you only want a quick update flow from scratch again:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/Peavepuf/Raspberry-Pi-Server-Control-Center.git
cd Raspberry-Pi-Server-Control-Center
chmod +x updater.sh
./updater.sh
```

The updater downloads the latest version from GitHub and runs the Raspberry Pi installer again while keeping your local database folder in place.

## Headless Service

To run the application as a background service:

```bash
sudo cp systemd/server-monitor.service /etc/systemd/system/server-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now server-monitor.service
```

## Storage

Local data is stored in:

```text
data/monitor.db
```

## Project Structure

- `main.py` - application entry point
- `monitor/` - application modules
- `config/servers.json` - optional initial seed targets
- `data/monitor.db` - local database
- `install_pi.sh` - Raspberry Pi installation script
- `updater.sh` - update script for Raspberry Pi

## Security

- Telegram credentials are not hardcoded in source files
- Settings are stored locally in SQLite
- Database files are ignored by Git

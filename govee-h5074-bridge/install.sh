#!/bin/sh
# Install (or re-install after firmware update) the Govee H5074 bridge.
# Idempotent.
set -eu

ROOT=/data/govee-h5074-bridge

chmod +x "$ROOT/service/run" "$ROOT/service/log/run"

# Pull in vedbus/settingsdevice/ve_utils from Venus so we don't ship our own.
VELIB=/opt/victronenergy/dbus-pump/ext/velib_python
for f in vedbus.py settingsdevice.py ve_utils.py; do
    if [ ! -e "$ROOT/$f" ] && [ -f "$VELIB/$f" ]; then
        cp "$VELIB/$f" "$ROOT/$f"
    fi
done

ln -sf "$ROOT/service" /service/govee-h5074-bridge

# Venus OS uses daemontools (svscan); it picks up new /service entries
# automatically within a few seconds.
svc -u /service/govee-h5074-bridge 2>/dev/null || true

echo "govee-h5074-bridge installed at /service/govee-h5074-bridge"

#!/bin/sh
# Install (or re-install after firmware update) the Govee H5074 bridge.
# Idempotent.
set -eu

ROOT=/data/govee-h5074-bridge
RC_LOCAL=/data/rc.local
REINSTALL_LOG=/var/log/govee-h5074-bridge-reinstall.log
HOOK_LINE="$ROOT/install.sh >$REINSTALL_LOG 2>&1"

if [ ! -d /opt/victronenergy ] || [ ! -d /service ] || [ ! -d /data ]; then
    echo "ERROR: unsupported host. This installer is only for Venus OS on a Cerbo GX." >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: install.sh must be run as root on the Cerbo (Venus OS)." >&2
    exit 1
fi

chmod +x "$ROOT/service/run" "$ROOT/service/log/run"

# Pull in vedbus/settingsdevice/ve_utils from Venus so we don't ship our own.
VELIB=/opt/victronenergy/dbus-pump/ext/velib_python
for f in vedbus.py settingsdevice.py ve_utils.py; do
    if [ ! -e "$ROOT/$f" ] && [ -f "$VELIB/$f" ]; then
        cp "$VELIB/$f" "$ROOT/$f"
    fi
done

ln -sf "$ROOT/service" /service/govee-h5074-bridge

# Ensure the bridge self-reinstalls on every boot/update.
if [ ! -f "$RC_LOCAL" ]; then
    printf '#!/bin/sh\n' >"$RC_LOCAL"
fi

if ! grep -Fqx "$HOOK_LINE" "$RC_LOCAL"; then
    printf '\n%s\n' "$HOOK_LINE" >>"$RC_LOCAL"
fi

chmod +x "$RC_LOCAL"

# Venus OS uses daemontools (svscan); it picks up new /service entries
# automatically within a few seconds.
svc -u /service/govee-h5074-bridge 2>/dev/null || true

echo "govee-h5074-bridge installed at /service/govee-h5074-bridge"

# Govee H5074/H5075 → Cerbo GX bridge

Listens for Govee H5074/H5075 BLE advertisements on the Cerbo GX MK2's
on-board BLE radio and registers each sensor as a
`com.victronenergy.temperature.*` D-Bus service, so it appears under
**Settings → I/O → Sensors** in Remote Console.

## Layout

```
/data/govee-h5074-bridge/
├── bridge.py           # main service
├── install.sh          # idempotent installer
├── service/run         # daemontools start script
├── service/log/run     # multilog logger
└── vedbus.py + ve_utils.py + settingsdevice.py  # copied from /opt by install.sh
```

## Install

```sh
ssh root@cerbo
cd /data/govee-h5074-bridge
./install.sh
```

`install.sh` symlinks `service/` into `/service/govee-h5074-bridge`
(daemontools' `svscan` picks it up within ~5 seconds), copies the
velib_python helpers, and idempotently ensures `/data/rc.local` contains
the reinstall hook:

```sh
/data/govee-h5074-bridge/install.sh >/var/log/govee-h5074-bridge-reinstall.log 2>&1
```

This makes the bridge self-heal across reboots and firmware updates.
The installer also exits early unless it detects a Venus OS host and is
run as root.

## Logs

```sh
tail -F /var/log/govee-h5074-bridge/current
```

## Automatic stale cleanup

Sensors are marked disconnected after 10 minutes without advertisements.
By default, they are then pruned (D-Bus service removed and localsettings
branch deleted) after 48 hours without advertisements.

Set an override before service start if you want a different prune window:

```sh
export GOVEE_PRUNE_AFTER_S=21600   # 6 hours
```

Set to `0` or a negative value to disable auto-prune.

If BlueZ is slow to come up at boot, the bridge retries hci0 init before
failing. Defaults are 30 attempts with a 2-second delay:

```sh
export GOVEE_BLUEZ_INIT_RETRIES=30
export GOVEE_BLUEZ_INIT_DELAY_S=2
```

## Model support

The bridge supports both H5074 and H5075 models.

H5074 decode uses `int16`/`uint16` little-endian fields for temperature
and humidity (both scaled by 100), plus battery percent.

H5075 decode uses a 24-bit big-endian combined field where:

* `combined // 1000` = temperature in tenths of °C
* `combined % 1000` = humidity in tenths of %

and a trailing battery percent byte.

To override which models are onboarded:

```sh
export GOVEE_SUPPORTED_MODEL_TOKENS=H5074,H5075
```

## Removing a sensor

If you replace a sensor or want to drop a stale one, remove its D-Bus
instance via localsettings:

```sh
dbus -y com.victronenergy.settings /Settings/Devices/govee_<slug> RemoveSettings
svc -t /service/govee-h5074-bridge
```

# Govee H5074 → Cerbo GX bridge

Listens for Govee H5074 BLE advertisements on the Cerbo GX MK2's
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
(daemontools' `svscan` picks it up within ~5 seconds) and copies the
velib_python helpers.

To survive firmware updates, ensure `/data/rc.local` contains:

```sh
ln -sf /data/govee-h5074-bridge/service /service/govee-h5074-bridge
/data/govee-h5074-bridge/install.sh >/var/log/govee-h5074-bridge-reinstall.log 2>&1
```

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

The bridge now supports both H5074 and H5075 models. The H5075 decoder is still being
reverse-engineered; it tries both little-endian and big-endian interpretations of
the manufacturer-data payload and picks the one that produces physically plausible values
(temperature −50 to 100°C, humidity 0 to 200%).

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

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

## Removing a sensor

If you replace a sensor or want to drop a stale one, remove its D-Bus
instance via localsettings:

```sh
dbus -y com.victronenergy.settings /Settings/Devices/govee_<slug> RemoveSettings
svc -t /service/govee-h5074-bridge
```

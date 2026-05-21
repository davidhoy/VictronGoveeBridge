# VictronGoveeBridge

Bridge that surfaces **Govee H5074** Bluetooth temperature/humidity
sensors on a **Victron Cerbo GX MK2**, so they appear natively in
Remote Console under **Settings → I/O → Sensors** and flow through
the rest of the Victron stack (VRM, MQTT, Modbus-TCP, alarms, etc.)
just like a built-in sensor.

No pairing, no app, no cloud — the H5074 broadcasts its readings as
unconnectable BLE advertisements roughly once per second, and the
Cerbo GX MK2's on-board BLE radio is already in range to hear them.

![Three Govee H5074 sensors — Cockpit, Owner hull, Saloon — on the
Cerbo GX Environment tab](docs/environment-tab.png)

## Why

The H5074 is a cheap, battery-powered, multi-year temperature/humidity
sensor. Stock Venus OS knows how to decode a handful of BLE sensors
(Ruuvi, Mopeka, etc.) via its `dbus-ble-sensors` service — but not
Govee. This project plugs that gap without modifying anything Victron
ships.

## How

```
  Govee H5074  ──BLE advert (mfg id 0xEC88)──▶  BlueZ on the Cerbo
                                                       │
                                                       │ org.bluez signals
                                                       ▼
                                                 bridge.py
                                          (one VeDbusService per sensor)
                                                       │
                                                       │ com.victronenergy.temperature.govee_<mac>
                                                       ▼
                                       dbus-systemcalc-py picks it up
                                                       │
                                                       ▼
                              Remote Console → Settings → I/O → Sensors
                              VRM, MQTT, Modbus-TCP, Node-RED, ...
```

The bridge:

1. Subscribes to BlueZ's `InterfacesAdded` and `PropertiesChanged`
   D-Bus signals to receive every BLE advert seen by `hci0`.
2. Filters for Govee's manufacturer-specific data (company ID `0xEC88`)
   and decodes the 7-byte H5074 payload (`int16` temp ×100, `uint16`
   humidity ×100, `uint8` battery %).
3. The first time it sees a new MAC, it registers a
   `com.victronenergy.temperature.govee_<macslug>` D-Bus service via
   velib_python's `VeDbusService`, with `/Temperature`, `/Humidity`,
   `/BatteryVoltage`, `/CustomName`, `/TemperatureType`. Each sensor
   gets its own private system-bus connection (a single connection
   can only own the root path `/` once).
4. DeviceInstance, CustomName and TemperatureType are persisted via
   `com.victronenergy.settings` (localsettings), so renaming a sensor
   "Saloon" in the GUI or changing its type from Generic to Room
   sticks across restarts and firmware updates.

## Repo layout

```
.
├── README.md                          ← you are here
├── scan_govee_h5074.py                ← standalone PoC scanner (Bleak on a Mac)
├── requirements.txt                   ← bleak, for the PoC only
└── govee-h5074-bridge/                ← the actual bridge (deployed to the Cerbo)
    ├── bridge.py                      ← the service
    ├── install.sh                     ← idempotent installer
    ├── service/run                    ← daemontools start script
    ├── service/log/run                ← multilog logger
    └── README.md                      ← operational notes
```

## Installing on a Cerbo GX MK2

Requires root SSH enabled on the Cerbo (Settings → General → Root
password / Access level). From a workstation:

```sh
rsync -avz govee-h5074-bridge/ root@<cerbo-ip>:/data/govee-h5074-bridge/
ssh root@<cerbo-ip> '/data/govee-h5074-bridge/install.sh'
```

`install.sh` is idempotent — it copies `vedbus.py`, `settingsdevice.py`
and `ve_utils.py` from `/opt/victronenergy/dbus-pump/ext/velib_python/`,
then symlinks `service/` into `/service/govee-h5074-bridge`. The
daemontools supervisor (`svscan`) picks it up within a few seconds.

To survive firmware updates (which wipe `/service` but preserve
`/data`), add one line to `/data/rc.local`:

```sh
/data/govee-h5074-bridge/install.sh >/var/log/govee-h5074-bridge-reinstall.log 2>&1
```

## Verifying

```sh
ssh root@<cerbo-ip>

# is the service running?
svstat /service/govee-h5074-bridge /service/govee-h5074-bridge/log

# what does it see?
tail -F /var/log/govee-h5074-bridge/current

# what's on D-Bus?
dbus-send --system --print-reply --dest=org.freedesktop.DBus \
  /org/freedesktop/DBus org.freedesktop.DBus.ListNames | grep govee

# live values for one sensor
dbus -y com.victronenergy.temperature.govee_<macslug> /Temperature GetValue
```

In Remote Console the sensors appear under **Settings → I/O → Sensors**.
Click into a sensor to rename it or change its TemperatureType
(Generic / Battery / Fridge / Room / Outdoor / Water heater).

## Removing a sensor

If you retire a sensor, drop its persisted settings and restart:

```sh
dbus -y com.victronenergy.settings /Settings/Devices/govee_<slug> RemoveSettings
svc -t /service/govee-h5074-bridge
```

## Operating notes

* Service supervisor on Venus OS is **daemontools**, not runit —
  commands are `svc -u/-d/-t`, `svstat`, `svok`; the logger is
  `multilog`.
* The Cerbo GX MK2 (`einstein`) has on-board BLE. The **original**
  Cerbo GX does not — that hardware can't host this bridge.
* The bridge does not pair or connect to the H5074; it only listens
  to broadcast advertisements. Range is line-of-sight ~10 m.
* `/BatteryVoltage` is synthesised from the broadcast battery
  percentage (`pct × 0.03 V`) so the GUI has something to show; the
  H5074 itself only reports a percentage.

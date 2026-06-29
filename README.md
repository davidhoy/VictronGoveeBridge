# VictronGoveeBridge

Bridge that surfaces **Govee H5074 and H5075** Bluetooth
temperature/humidity sensors on a **Victron Cerbo GX MK2**, so they
appear natively in
Remote Console under **Settings → I/O → Sensors** and flow through
the rest of the Victron stack (VRM, MQTT, Modbus-TCP, alarms, etc.)
just like a built-in sensor.

No pairing, no app, no cloud. Both models broadcast readings as
unconnectable BLE advertisements, and the Cerbo GX MK2's on-board BLE
radio can passively receive them.

![Three Govee H5074 sensors — Cockpit, Owner hull, Saloon — on the
Cerbo GX Environment tab](docs/environment-tab.png)

## Why

The H5074/H5075 family is a cheap, battery-powered, multi-year
temperature/humidity
sensor. Stock Venus OS knows how to decode a handful of BLE sensors
(Ruuvi, Mopeka, etc.) via its `dbus-ble-sensors` service — but not
Govee. This project plugs that gap without modifying anything Victron
ships.

## How

```
  Govee H5074/H5075  ──BLE advert (mfg id 0xEC88)──▶  BlueZ on the Cerbo
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
   and decodes payloads for supported models:
   * H5074: `int16` temp ×100 (LE), `uint16` humidity ×100 (LE),
     `uint8` battery %.
   * H5075: 24-bit combined field (BE), where `combined // 1000`
     is temperature in tenths of °C and `combined % 1000` is humidity
     in tenths of %; plus `uint8` battery %.
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
├── scan_govee_h5074.py                ← standalone PoC scanner (H5074 format; Bleak on a Mac)
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
then symlinks `service/` into `/service/govee-h5074-bridge`. It also
idempotently ensures `/data/rc.local` contains a reinstall hook, so the
bridge re-attaches itself after reboots and firmware updates (which wipe
`/service` but preserve `/data`). The daemontools supervisor (`svscan`)
picks it up within a few seconds.

The installer includes host-safety checks and exits unless it is run as
root on a Venus OS layout (`/opt/victronenergy`, `/service`, `/data`).

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

## Configuration

The bridge supports a few optional environment variables, read on
service start:

* `GOVEE_SUPPORTED_MODEL_TOKENS` (default: `H5074,H5075`):
  comma-separated case-insensitive tokens that must appear in the BLE
  device name before onboarding.
* `GOVEE_PRUNE_AFTER_S` (default: `172800`, 48h): remove a stale
  sensor's D-Bus service and persisted settings after this many seconds
  without advertisements. Set `0` or a negative value to disable prune.
* `GOVEE_BLUEZ_INIT_RETRIES` (default: `30`): number of startup retries
  while waiting for BlueZ `hci0`.
* `GOVEE_BLUEZ_INIT_DELAY_S` (default: `2`): delay between BlueZ init
  retries.

Independent of prune, a sensor is marked disconnected after 10 minutes
without advertisements.

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
* The bridge does not pair or connect to the sensors; it only listens
  to broadcast advertisements. Range is line-of-sight ~10 m.
* `/BatteryVoltage` is synthesised from the broadcast battery
  percentage (`pct × 0.03 V`) so the GUI has something to show; H5074
  and H5075 broadcasts only provide a percentage.

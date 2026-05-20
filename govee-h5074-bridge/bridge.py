#!/usr/bin/env python3
"""
Govee H5074 → Victron Cerbo GX D-Bus bridge.

Listens for Govee H5074 BLE advertisements via BlueZ and registers each
unique sensor as a `com.victronenergy.temperature.govee_<mac>` D-Bus
service, so it appears under Settings → I/O → Sensors in the GUI.

Designed to run as a long-lived runit service on Venus OS.
"""

import logging
import os
import struct
import sys
import time
from typing import Dict, Optional

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

# vedbus + settingsdevice live next to this file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vedbus import VeDbusService
from settingsdevice import SettingsDevice


GOVEE_COMPANY_ID = 0xEC88
PRODUCT_ID = 0xB034  # arbitrary, only used for /ProductId
PROCESS_VERSION = "0.1.0"
STALE_AFTER_S = 600  # mark /Connected=0 if no ad for 10 min

log = logging.getLogger("govee-bridge")


def decode_h5074(payload: bytes):
    """Decode a Govee H5074 manufacturer-data payload.

    Layout after the 0xEC88 company ID:
      [0]   prefix (0x00)
      [1:3] temperature * 100, int16 LE (°C)
      [3:5] humidity    * 100, uint16 LE (%)
      [5]   battery percent
    Returns (temp_c, humidity, battery) or None.
    """
    if len(payload) < 6:
        return None
    temp_raw, hum_raw, battery = struct.unpack_from("<hHB", payload, 1)
    return temp_raw / 100.0, hum_raw / 100.0, battery


def mac_to_slug(mac: str) -> str:
    return mac.replace(":", "").lower()


def instance_seed(mac: str) -> int:
    """Stable default DeviceInstance in [40, 250) derived from the MAC.

    localsettings will dedupe collisions, but seeding deterministically
    means a given sensor lands on the same instance run-to-run when free.
    """
    s = mac_to_slug(mac)
    return 40 + (int(s[-6:], 16) % 210)


class GoveeSensor:
    def __init__(self, mac: str, friendly_name: str, bus: dbus.SystemBus) -> None:
        self.mac = mac
        self.slug = mac_to_slug(mac)
        self.last_seen: float = 0.0

        seed = instance_seed(mac)
        settings_root = f"/Settings/Devices/govee_{self.slug}"
        self.settings = SettingsDevice(
            bus=bus,
            supportedSettings={
                "instance": [
                    f"{settings_root}/ClassAndVrmInstance",
                    f"temperature:{seed}",
                    0,
                    0,
                ],
                "customname": [
                    f"{settings_root}/CustomName",
                    friendly_name,
                    0,
                    0,
                ],
            },
            eventCallback=self._on_setting_changed,
        )

        _, instance_str = self.settings["instance"].split(":")
        self.device_instance = int(instance_str)

        service_name = f"com.victronenergy.temperature.govee_{self.slug}"
        self.svc = VeDbusService(service_name, bus=bus, register=False)

        self.svc.add_path("/DeviceInstance", self.device_instance)
        self.svc.add_path("/ProductId", PRODUCT_ID)
        self.svc.add_path("/ProductName", "Govee H5074")
        self.svc.add_path("/FirmwareVersion", "n/a")
        self.svc.add_path("/HardwareVersion", "1")
        self.svc.add_path("/Connected", 1)
        self.svc.add_path("/Mgmt/ProcessName", os.path.basename(__file__))
        self.svc.add_path("/Mgmt/ProcessVersion", PROCESS_VERSION)
        self.svc.add_path("/Mgmt/Connection", f"BLE {mac}")
        self.svc.add_path("/Status", 0)

        self.svc.add_path("/Temperature", None)
        self.svc.add_path("/Humidity", None)
        self.svc.add_path("/TemperatureType", 2)  # 2 = generic
        self.svc.add_path("/BatteryVoltage", None)

        # writeable from the GUI; we mirror back into localsettings on change
        self.svc.add_path(
            "/CustomName",
            self.settings["customname"],
            writeable=True,
            onchangecallback=self._on_customname_changed,
        )

        self.svc.register()
        log.info("registered %s as DeviceInstance %d (seed %d)",
                 service_name, self.device_instance, seed)

    def _on_setting_changed(self, setting, oldvalue, newvalue):
        if setting == "customname":
            try:
                self.svc["/CustomName"] = newvalue
            except Exception:
                pass

    def _on_customname_changed(self, path, newvalue):
        self.settings["customname"] = newvalue
        return True

    def update(self, temp_c: float, humidity: float, battery_pct: int) -> None:
        self.last_seen = time.monotonic()
        self.svc["/Temperature"] = round(temp_c, 2)
        self.svc["/Humidity"] = round(humidity, 2)
        # H5074 reports % only; expose a synthetic voltage so the GUI shows
        # something useful (1% ≈ 0.03V, full scale ≈ 3.0V CR2477).
        self.svc["/BatteryVoltage"] = round(battery_pct * 0.03, 2)
        if self.svc["/Connected"] != 1:
            self.svc["/Connected"] = 1
            self.svc["/Status"] = 0

    def check_stale(self, now: float) -> None:
        if self.last_seen and now - self.last_seen > STALE_AFTER_S:
            if self.svc["/Connected"] != 0:
                log.info("%s stale (no ad for %ds), marking disconnected",
                         self.mac, int(now - self.last_seen))
                self.svc["/Connected"] = 0
                self.svc["/Status"] = 10  # 10 = "not connected"


class GoveeBridge:
    def __init__(self) -> None:
        self.bus = dbus.SystemBus()
        self.sensors: Dict[str, GoveeSensor] = {}

        self.adapter = dbus.Interface(
            self.bus.get_object("org.bluez", "/org/bluez/hci0"),
            "org.bluez.Adapter1",
        )
        self.om = dbus.Interface(
            self.bus.get_object("org.bluez", "/"),
            "org.freedesktop.DBus.ObjectManager",
        )

    def start(self) -> None:
        try:
            self.adapter.SetDiscoveryFilter(
                {
                    "Transport": "le",
                    "DuplicateData": True,
                    "RSSI": dbus.Int16(-127),
                }
            )
        except dbus.exceptions.DBusException as exc:
            log.warning("SetDiscoveryFilter failed: %s", exc)

        try:
            self.adapter.StartDiscovery()
        except dbus.exceptions.DBusException as exc:
            # someone else may already have discovery running; that's fine
            log.warning("StartDiscovery: %s", exc)

        self.bus.add_signal_receiver(
            self._on_iface_added,
            dbus_interface="org.freedesktop.DBus.ObjectManager",
            signal_name="InterfacesAdded",
        )
        self.bus.add_signal_receiver(
            self._on_props_changed,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged",
            path_keyword="path",
            arg0="org.bluez.Device1",
        )

        # pick up devices BlueZ already knows about
        try:
            for path, ifaces in self.om.GetManagedObjects().items():
                self._on_iface_added(path, ifaces)
        except dbus.exceptions.DBusException as exc:
            log.warning("GetManagedObjects: %s", exc)

        GLib.timeout_add_seconds(60, self._stale_check)

    def _stale_check(self) -> bool:
        now = time.monotonic()
        for s in self.sensors.values():
            s.check_stale(now)
        return True

    def _path_to_mac(self, path: str) -> Optional[str]:
        # /org/bluez/hci0/dev_A4_C1_38_20_60_85
        leaf = path.rsplit("/", 1)[-1]
        if not leaf.startswith("dev_"):
            return None
        return leaf[4:].replace("_", ":")

    def _on_iface_added(self, path, ifaces):
        dev = ifaces.get("org.bluez.Device1")
        if not dev:
            return
        mfg = dev.get("ManufacturerData") or {}
        self._handle(
            dev.get("Address", "") or self._path_to_mac(path),
            str(dev.get("Name", "")),
            mfg,
        )

    def _on_props_changed(self, iface, changed, invalid, path=None):
        if iface != "org.bluez.Device1":
            return
        mfg = changed.get("ManufacturerData")
        if not mfg:
            return
        mac = self._path_to_mac(path) if path else None
        if not mac:
            return
        self._handle(mac, str(changed.get("Name", "")), mfg)

    def _handle(self, mac: str, name: str, mfg) -> None:
        if not mac:
            return
        try:
            payload = mfg[dbus.UInt16(GOVEE_COMPANY_ID)]
        except (KeyError, TypeError):
            payload = None
            for k, v in mfg.items():
                if int(k) == GOVEE_COMPANY_ID:
                    payload = v
                    break
        if payload is None:
            return
        raw = bytes(payload)
        decoded = decode_h5074(raw)
        if decoded is None:
            return
        temp_c, humidity, battery = decoded

        sensor = self.sensors.get(mac.upper())
        if sensor is None:
            friendly = name or f"Govee H5074 {mac[-5:]}"
            try:
                sensor = GoveeSensor(mac.upper(), friendly, self.bus)
            except Exception:
                log.exception("failed to register sensor %s", mac)
                return
            self.sensors[mac.upper()] = sensor
            log.info("discovered new H5074 %s (%s)", mac, friendly)

        sensor.update(temp_c, humidity, battery)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bridge = GoveeBridge()
    bridge.start()

    loop = GLib.MainLoop()
    log.info("Govee H5074 bridge started; waiting for advertisements")
    try:
        loop.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
PoC: capture Govee H5074 BLE advertisements.

The H5074 is a passive BLE broadcaster — it advertises temperature,
humidity, and battery roughly once per second. We listen for ads
containing Govee's manufacturer-specific data (company ID 0xEC88)
and decode them. No pairing required.
"""
import asyncio
import struct
from datetime import datetime

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

GOVEE_COMPANY_ID = 0xEC88


def decode_h5074(payload: bytes):
    # 7-byte payload after the company ID:
    #   [0]    prefix (0x00)
    #   [1:3]  temp * 100,  int16 LE (°C)
    #   [3:5]  humidity * 100, uint16 LE (%)
    #   [5]    battery %
    #   [6]    pad (0x00)
    if len(payload) < 6:
        return None
    temp_raw, hum_raw, battery = struct.unpack_from("<hHB", payload, 1)
    return temp_raw / 100.0, hum_raw / 100.0, battery


def on_advertisement(device: BLEDevice, adv: AdvertisementData) -> None:
    payload = adv.manufacturer_data.get(GOVEE_COMPANY_ID)
    if payload is None:
        return
    decoded = decode_h5074(payload)
    if decoded is None:
        return
    temp_c, humidity, battery = decoded
    name = adv.local_name or device.name or "?"
    ts = datetime.now().strftime("%H:%M:%S")
    print(
        f"[{ts}] {device.address}  {name:18s}  "
        f"T={temp_c:6.2f}°C  H={humidity:5.2f}%  "
        f"Batt={battery:3d}%  RSSI={adv.rssi}dBm  "
        f"raw={payload.hex()}"
    )


async def main() -> None:
    print("Scanning for Govee H5074 advertisements — Ctrl-C to stop.")
    scanner = BleakScanner(detection_callback=on_advertisement)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await scanner.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

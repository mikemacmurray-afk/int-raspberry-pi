"""
SunSynk / Solarman V5 Diagnostic Probe Tool.
Quickly tests connection to the inverter Wi-Fi stick from your laptop.

Usage:
  python tools/probe_sunsynk.py --host 192.168.1.60 --serial 2300000000
"""

import argparse
import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectors.sunsynk.client import SunSynkClient

async def main():
    parser = argparse.ArgumentParser(description="Probe SunSynk 8kW Inverter via Wi-Fi logger")
    parser.add_argument("--host", type=str, required=True, help="IP address of SunSynk Wi-Fi stick")
    parser.add_argument("--serial", type=int, required=True, help="Serial number printed on Wi-Fi stick (e.g. 2300000000)")
    parser.add_argument("--port", type=int, default=8899, help="Solarman port (default 8899)")
    parser.add_argument("--slave", type=int, default=1, help="Modbus Slave ID (default 1)")
    args = parser.parse_args()

    print(f"\n⚡ Probing SunSynk Inverter at {args.host}:{args.port} (Logger S/N: {args.serial}, Slave ID: {args.slave})...")
    client = SunSynkClient(host=args.host, serial_number=args.serial, port=args.port, slave_id=args.slave, timeout=5.0)

    try:
        data = await client.read_telemetry(allow_mock=False)
        print("\n✅ Successfully connected to SunSynk Inverter!")
        print("-" * 50)
        solar = data.get("solar", {})
        battery = data.get("battery", {})
        grid = data.get("grid", {})
        load = data.get("load", {})

        print(f"☀️  Solar PV Generation : {solar.get('total_watts')} W (PV1: {solar.get('pv1_watts')}W, PV2: {solar.get('pv2_watts')}W)")
        print(f"🔋 Battery Status       : {battery.get('soc_percent')}% | {battery.get('voltage')}V | {battery.get('watts')}W | {battery.get('temperature_c')}°C")
        print(f"🏠 House Essential Load : {load.get('total_watts')} W")
        print(f"🌐 Grid Power Flow      : {grid.get('watts')} W ({grid.get('voltage')}V @ {grid.get('frequency_hz')}Hz)")
        print(f"🌡️  Inverter Temp        : {data.get('inverter', {}).get('temperature_c')}°C")
        print("-" * 50)

        print("\nReading System Mode Configuration...")
        mode = await client.read_system_mode(allow_mock=False)
        print(f"Work Mode               : {mode.get('work_mode_str')}")
        print(f"Priority                : {mode.get('priority_str')}")
        print(f"Battery Shutdown / Restart: {mode.get('battery_shutdown_soc')}% / {mode.get('battery_restart_soc')}%")
        print(f"TOU Master Enabled      : {mode.get('tou_enabled')}")
        print("\nTOU Slots:")
        for s in mode.get("tou_slots", []):
            print(f"  Slot {s['slot']}: Time {s['time']} | Max {s['power']}W | Target {s['soc']}% | Grid Charge: {s['grid_charge']}")

    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        print("\nTroubleshooting tips:")
        print(" 1. Verify your laptop is on the same 2.4GHz Wi-Fi network as the SunSynk logger.")
        print(" 2. Confirm the IP address of the logger in your Wi-Fi router's DHCP list.")
        print(" 3. Verify the Logger Serial Number matches the barcode on the Wi-Fi stick.")

if __name__ == "__main__":
    asyncio.run(main())

"""
SunSynk Connect Cloud API Probe Tool.
Tests authenticating with the Sunsynk Cloud API and fetching live inverter telemetry.

Usage:
  python tools/probe_sunsynk_cloud.py --username user@example.com --password mysecret
"""

import sys
import argparse
import asyncio
from pathlib import Path

# Force UTF-8 stdout encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectors.sunsynk.cloud_client import SunsynkCloudClient

async def main():
    parser = argparse.ArgumentParser(description="Probe SunSynk Cloud API")
    parser.add_argument("--username", type=str, required=True, help="Sunsynk Connect account email/username")
    parser.add_argument("--password", type=str, required=True, help="Sunsynk Connect account password")
    parser.add_argument("--sn", type=str, default="", help="Optional: inverter serial number")
    args = parser.parse_args()

    print(f"\n⚡ Authenticating with SunSynk Connect API for user '{args.username}'...")
    client = SunsynkCloudClient(username=args.username, password=args.password, inverter_sn=args.sn)

    try:
        data = await client.read_telemetry(allow_mock=False)
        print("\n✅ Successfully connected to SunSynk Cloud API!")
        print("-" * 55)
        print(f"Inverter Serial Number : {client.inverter_sn}")
        solar = data.get("solar", {})
        battery = data.get("battery", {})
        grid = data.get("grid", {})
        load = data.get("load", {})

        print(f"☀️  Solar Generation    : {solar.get('total_watts')} W")
        print(f"🔋 Battery Storage     : {battery.get('soc_percent')}% ({battery.get('watts')} W)")
        print(f"🏠 House Load          : {load.get('total_watts')} W")
        print(f"🌐 Grid Power Flow     : {grid.get('watts')} W")
        print("-" * 55)

        print("\nFetching Inverter System Mode & TOU Settings...")
        mode = await client.read_system_mode(allow_mock=False)
        print(f"Work Mode              : {mode.get('work_mode_str')}")
        print(f"Priority               : {mode.get('priority_str')}")
        print(f"Battery Cutoffs        : Low {mode.get('battery_low_soc')}% | Restart {mode.get('battery_restart_soc')}% | Shutdown {mode.get('battery_shutdown_soc')}%")
        print("\nTime of Use (TOU) 6 Slots:")
        for s in mode.get("tou_slots", []):
            print(f"  Slot {s['slot']}: Time {s['time']} | Max {s['power']}W | Target {s['soc']}% | Grid Charge: {s['grid_charge']}")

    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        print("\nTroubleshooting tips:")
        print(" 1. Verify your Sunsynk Connect email and password.")
        print(" 2. Confirm your account works in the official Sunsynk mobile app or at https://www.sunsynk.net.")

if __name__ == "__main__":
    asyncio.run(main())

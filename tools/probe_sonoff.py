"""
Sonoff eWeLink LAN Diagnostic Probe Tool.
Tests connectivity to Sonoff Geyser / DB Switch over Wi-Fi LAN without internet cloud.

Usage:
  python tools/probe_sonoff.py --host 192.168.1.70
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectors.sonoff.ewelink_lan import SonoffDevice

async def main():
    parser = argparse.ArgumentParser(description="Probe Sonoff Wi-Fi Device")
    parser.add_argument("--host", type=str, required=True, help="IP address of Sonoff switch")
    parser.add_argument("--port", type=int, default=8081, help="Sonoff LAN port (default 8081)")
    args = parser.parse_args()

    print(f"\n⚡ Probing Sonoff Device at {args.host}:{args.port}...")
    dev = SonoffDevice(name="Probe Device", host=args.host, port=args.port, has_temp_sensor=True)

    info = await dev.get_device_info()
    if info:
        print("\n✅ Successfully connected to Sonoff device over LAN!")
        print("-" * 50)
        print(f"Switch State    : {info.get('switch', 'unknown').upper()}")
        if "temperature" in info:
            print(f"Temperature     : {info.get('temperature')} °C")
        if "humidity" in info:
            print(f"Humidity        : {info.get('humidity')} %")
        if "power" in info:
            print(f"Active Power    : {info.get('power')} W")
        if "voltage" in info:
            print(f"Voltage         : {info.get('voltage')} V")
        if "current" in info:
            print(f"Current         : {info.get('current')} A")
        print(f"Raw LAN Info    : {info}")
        print("-" * 50)
    else:
        print("\n❌ Failed to communicate with Sonoff on port 8081.")
        print("Troubleshooting tips:")
        print(" 1. Make sure 'LAN Control' is enabled in the eWeLink app for this device.")
        print(" 2. Confirm your laptop is on the same local subnet as the Sonoff switch.")

if __name__ == "__main__":
    asyncio.run(main())

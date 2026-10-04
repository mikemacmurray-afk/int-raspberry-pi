"""
Network Discovery Scanner.
Scans the local subnet for SunSynk Wi-Fi Dongles (port 8899) and Sonoff devices (port 8081).
Helps automatically locate device IP addresses on your home Wi-Fi.

Usage:
  python tools/scan_network.py
"""

import socket
import asyncio
import ipaddress
import sys
from pathlib import Path

def get_local_ip() -> str:
    """Detect local IP address of laptop."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually connect externally, just determines routing interface
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

async def check_port(ip: str, port: int, timeout: float = 0.5) -> bool:
    try:
        conn = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def scan_host(ip: str):
    sunsynk_found = await check_port(ip, 8899)
    sonoff_found = await check_port(ip, 8081)
    
    if sunsynk_found:
        print(f"  🔍 [Found SunSynk Logger] -> IP: {ip} (Port 8899 OPEN)")
    if sonoff_found:
        print(f"  🔍 [Found Sonoff Device]  -> IP: {ip} (Port 8081 OPEN)")

async def main():
    local_ip = get_local_ip()
    print(f"\nScanning local Wi-Fi subnet around your laptop ({local_ip})...")
    
    if local_ip.startswith("127."):
        print("Could not detect active Wi-Fi interface. Ensure Wi-Fi is connected.")
        return

    # Scan /24 subnet
    network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
    print(f"Probing {network.num_addresses - 2} host addresses for ports 8899 (SunSynk) and 8081 (Sonoff)...")
    print("-" * 65)

    batch_size = 40
    hosts = [str(h) for h in network.hosts()]
    for i in range(0, len(hosts), batch_size):
        batch = hosts[i:i + batch_size]
        await asyncio.gather(*(scan_host(h) for h in batch))

    print("-" * 65)
    print("Scan complete. Use the discovered IPs in config/config.yaml.\n")

if __name__ == "__main__":
    asyncio.run(main())

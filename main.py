"""
Home Energy Management System - Entry Point.
Runs on your Windows Laptop (Development & Emulation Mode) and Raspberry Pi 5 (Edge Host).

Usage:
  python main.py
"""

import uvicorn
import logging
from config.settings import load_config

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )

def main():
    setup_logging()
    cfg = load_config()

    print("=" * 65)
    print(" ⚡ SunSynk 8kW + Sonoff Home Energy Conductor")
    print(f" 🖥️  Host Runtime    : Laptop / Pi 5 Unified Harness")
    print(f" 🌐 Web Dashboard   : http://localhost:{cfg.web.port}")
    print(f" 📡 SunSynk Wi-Fi   : {cfg.sunsynk.host}:{cfg.sunsynk.port} (SN: {cfg.sunsynk.serial_number})")
    print(f" ♨️  Geyser (Sonoff) : {cfg.sonoff_geyser.host} (Temp Probe: {cfg.sonoff_geyser.has_temp_sensor})")
    print(f" 🏊 Pool DB Switch  : {cfg.sonoff_pool_pump.host}")
    print(f" ⚡ Backup DB Switch: {cfg.sonoff_geyser_backup.host}")
    print("=" * 65)

    uvicorn.run(
        "web.server:app",
        host=cfg.web.host,
        port=cfg.web.port,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()

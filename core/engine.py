"""
Core Orchestration & Polling Engine.
Coordinates device pollers, logging, automations, and live state broadcasts.
Works interchangeably on Windows laptop (emulation/development) and Raspberry Pi 5.
"""

import asyncio
import logging
import platform
import psutil
import time
from typing import Dict, Any, Optional
from config.settings import AppConfig
from connectors.sunsynk.client import SunSynkClient
from connectors.sunsynk.cloud_client import SunsynkCloudClient
from connectors.sonoff.client import SonoffFleet
from connectors.rainpoint.client import RainPointClient
from core.database import Database

logger = logging.getLogger("CoreEngine")

class SystemHarness:
    """Provides system diagnostics (identifies whether running on Pi 5 or Laptop)."""
    @staticmethod
    def get_system_stats() -> Dict[str, Any]:
        uname = platform.uname()
        is_pi = "arm" in uname.machine.lower() or "aarch" in uname.machine.lower()
        
        cpu_temp = None
        # Try reading Pi thermal zone if running on Linux/Pi
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                cpu_temp = round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            pass

        return {
            "platform": uname.system,
            "machine": uname.machine,
            "node": uname.node,
            "host_mode": "Raspberry Pi 5 (Live Edge)" if is_pi else "Laptop (Development & Emulation)",
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "cpu_temp_c": cpu_temp
        }

class CoreEngine:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db = Database(config.system.db_path)
        
        # Inverter client: Cloud API or Local Solarman Modbus
        if getattr(config.sunsynk, "connection_type", "cloud") == "cloud":
            self.sunsynk = SunsynkCloudClient(
                username=config.sunsynk.username,
                password=config.sunsynk.password,
                inverter_sn=config.sunsynk.inverter_sn,
                base_url=config.sunsynk.base_url
            )
        else:
            self.sunsynk = SunSynkClient(
                host=config.sunsynk.host,
                serial_number=config.sunsynk.serial_number,
                port=config.sunsynk.port,
                slave_id=config.sunsynk.slave_id,
                timeout=config.sunsynk.timeout_sec
            )

        # Sonoff fleet
        self.sonoff = SonoffFleet(config)

        # RainPoint pool thermometer
        if getattr(config, "rainpoint", None) and config.rainpoint.enabled:
            self.rainpoint = RainPointClient(
                email=config.rainpoint.email,
                password=config.rainpoint.password,
                area_code=config.rainpoint.area_code,
                app_code=config.rainpoint.app_code,
                base_url=config.rainpoint.base_url
            )
        else:
            self.rainpoint = None

        # Live state cache
        self.latest_solar: Dict[str, Any] = {}
        self.latest_sonoff: Dict[str, Any] = {}
        self.latest_rainpoint: Dict[str, Any] = {}
        self._rainpoint_poll_counter = 0
        self.latest_system_mode: Dict[str, Any] = {}
        self.is_running = False
        self._poll_task: Optional[asyncio.Task] = None

    async def reload_config(self, new_config: AppConfig):
        """Hot-reload configuration and reconnect to hardware/cloud clients."""
        logger.info("Hot-reloading configuration in CoreEngine...")
        self.config = new_config
        if getattr(new_config.sunsynk, "connection_type", "cloud") == "cloud":
            self.sunsynk = SunsynkCloudClient(
                username=new_config.sunsynk.username,
                password=new_config.sunsynk.password,
                inverter_sn=new_config.sunsynk.inverter_sn,
                base_url=new_config.sunsynk.base_url
            )
        else:
            self.sunsynk = SunSynkClient(
                host=new_config.sunsynk.host,
                serial_number=new_config.sunsynk.serial_number,
                port=new_config.sunsynk.port,
                slave_id=new_config.sunsynk.slave_id,
                timeout=new_config.sunsynk.timeout_sec
            )
        self.sonoff = SonoffFleet(new_config)
        if getattr(new_config, "rainpoint", None) and new_config.rainpoint.enabled:
            self.rainpoint = RainPointClient(
                email=new_config.rainpoint.email,
                password=new_config.rainpoint.password,
                area_code=new_config.rainpoint.area_code,
                app_code=new_config.rainpoint.app_code,
                base_url=new_config.rainpoint.base_url
            )
        else:
            self.rainpoint = None

    async def start(self):
        """Start the background telemetry polling loop."""
        self.is_running = True
        logger.info(f"Starting Core Engine (poll interval: {self.config.system.poll_interval_sec}s)...")
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        """Stop background polling."""
        self.is_running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        allow_mock = (self.config.system.mode in ("auto", "mock"))
        
        while self.is_running:
            try:
                # 1. Poll SunSynk
                solar_data = await self.sunsynk.read_telemetry(allow_mock=allow_mock)
                self.latest_solar = solar_data

                # 2. Poll Sonoff / Tuya devices
                sonoff_data = await self.sonoff.poll_all(allow_mock=allow_mock)
                self.latest_sonoff = sonoff_data

                # 3. Poll RainPoint Pool Thermometer (every ~30s / 10 poll cycles)
                if self.rainpoint:
                    self._rainpoint_poll_counter += 1
                    if self._rainpoint_poll_counter >= 10 or not self.latest_rainpoint:
                        self._rainpoint_poll_counter = 0
                        try:
                            rp_data = await self.rainpoint.poll_pool_temperature(allow_mock=allow_mock)
                            self.latest_rainpoint = rp_data
                        except Exception as e:
                            logger.warning(f"Error polling RainPoint: {e}")

                # Attach pool water temperature to pool_pump telemetry if available
                if self.latest_rainpoint and "pool_pump" in self.latest_sonoff:
                    if self.latest_rainpoint.get("temp_c") is not None:
                        self.latest_sonoff["pool_pump"]["water_temp_c"] = self.latest_rainpoint.get("temp_c")
                        self.latest_sonoff["pool_pump"]["water_temp_f"] = self.latest_rainpoint.get("temp_f")

                # 4. Save telemetry snapshot to database
                self.db.record_telemetry(solar_data, sonoff_data)

            except Exception as e:
                logger.error(f"Error during polling loop: {e}", exc_info=True)

            await asyncio.sleep(self.config.system.poll_interval_sec)

    async def get_live_state(self) -> Dict[str, Any]:
        """Aggregate all live telemetry, system stats, and switch states."""
        return {
            "timestamp": time.time(),
            "solar": self.latest_solar,
            "sonoff": self.latest_sonoff,
            "rainpoint": self.latest_rainpoint,
            "system_harness": SystemHarness.get_system_stats()
        }

    async def get_system_mode(self) -> Dict[str, Any]:
        allow_mock = (self.config.system.mode in ("auto", "mock"))
        mode_data = await self.sunsynk.read_system_mode(allow_mock=allow_mock)
        self.latest_system_mode = mode_data
        return mode_data

    async def update_system_mode(self, settings: Dict[str, Any]) -> bool:
        allow_mock = (self.config.system.mode in ("auto", "mock"))
        old_mode = self.latest_system_mode
        success = await self.sunsynk.update_system_mode(settings, allow_mock=allow_mock)
        if success:
            for k, v in settings.items():
                self.db.record_audit(k, old_mode.get(k), v, applied_by="user_dashboard")
        return success

    async def set_switch(self, device_key: str, state: str) -> bool:
        return await self.sonoff.set_device_switch(device_key, state)

    def set_geyser_temp(self, temp_c: float):
        self.sonoff.set_geyser_target_temp(temp_c)
        self.config.sonoff_geyser.target_temp_c = temp_c

    async def get_geyser_auto_control(self) -> Dict[str, Any]:
        return await self.sonoff.get_geyser_auto_control()

    async def update_geyser_auto_control(self, rules: list, enabled: int = 1) -> bool:
        return await self.sonoff.update_geyser_auto_control(rules, enabled)

    async def get_energy_day(self, date_str: str) -> Dict[str, Any]:
        if hasattr(self.sunsynk, "get_energy_day"):
            return await self.sunsynk.get_energy_day(date_str)
        return {"date": date_str, "series": []}

    async def get_energy_month(self, month_str: str) -> Dict[str, Any]:
        if hasattr(self.sunsynk, "get_energy_month"):
            return await self.sunsynk.get_energy_month(month_str)
        return {"month": month_str, "series": []}

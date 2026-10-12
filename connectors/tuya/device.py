"""
Tuya / CBI Astute DIN-Rail Smart DB Switch Connector.
Supports:
1. Local LAN control and telemetry over port 6668 via TinyTuya (v3.4 / v3.5).
2. Energy metering (Watts, Current, Voltage, Daily kWh) on DPS 17, 18, 19, 20.
3. Switch toggle on DPS 1, with seamless Tuya OpenAPI Cloud fallback.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional

try:
    import tinytuya
    TINYTUYA_AVAILABLE = True
except ImportError:
    TINYTUYA_AVAILABLE = False

logger = logging.getLogger("TuyaDevice")

class GlobalTuyaCloud:
    _instance = None

    @classmethod
    def get_client(cls, api_key: str = "q8vkvxpt4dcwjxnxeh5s", api_secret: str = "b81ee31931de422382b2c1e9d6a3c881", region: str = "eu"):
        if cls._instance is None and TINYTUYA_AVAILABLE and api_key and api_secret:
            try:
                cls._instance = tinytuya.Cloud(apiRegion=region, apiKey=api_key, apiSecret=api_secret)
                logger.info("Initialized global Tuya Cloud client for remote fallback")
            except Exception as e:
                logger.warning(f"Could not initialize Tuya Cloud: {e}")
        return cls._instance

class TuyaDbSwitch:
    def __init__(self, name: str, device_id: str, host: str, local_key: str = "",
                 version: float = 3.4, rated_watts: float = 1100.0):
        self.name = name
        self.device_id = device_id
        self.host = host
        self.local_key = local_key
        self.version = float(version)
        self.rated_watts = rated_watts

        self.is_connected = False
        self.state = "off"
        self.power_watts = 0.0
        self.voltage = 230.0
        self.current = 0.0
        self.daily_kwh = 0.0
        self.last_update = 0.0

        self.cloud = GlobalTuyaCloud.get_client()

        self._device: Optional[Any] = None
        if TINYTUYA_AVAILABLE and self.device_id and self.host:
            self._init_client()

    def _init_client(self):
        try:
            self._device = tinytuya.OutletDevice(
                dev_id=self.device_id,
                address=self.host,
                local_key=self.local_key,
                version=self.version
            )
            self._device.set_version(self.version)
            self._device.set_socketPersistent(False)
            self._device.set_socketTimeout(2.0)
            logger.info(f"Initialized TinyTuya client for {self.name} ({self.host}, v{self.version})")
        except Exception as e:
            logger.warning(f"Could not initialize TinyTuya device {self.name}: {e}")

    def update_credentials(self, host: Optional[str] = None, local_key: Optional[str] = None):
        if host:
            self.host = host
        if local_key is not None:
            self.local_key = local_key
        self._init_client()

    async def poll(self, allow_mock: bool = True) -> Dict[str, Any]:
        """Poll switch state and energy metering DPS from device (LAN first, then Cloud)."""
        loop = asyncio.get_running_loop()

        # 1. Try Local LAN via TinyTuya
        if TINYTUYA_AVAILABLE and self._device and self.local_key:
            try:
                status = await loop.run_in_executor(None, self._device.status)
                if status and "dps" in status and status["dps"]:
                    dps = status["dps"]
                    # DPS 1: Switch state (bool)
                    if "1" in dps:
                        self.state = "on" if dps["1"] else "off"

                    # DPS 19: Power (Watts * 10 or Watts)
                    if "19" in dps:
                        p_val = float(dps["19"])
                        self.power_watts = round(p_val / 10.0, 1) if p_val > 5000 else round(p_val, 1)
                    elif self.state == "on":
                        self.power_watts = self.rated_watts
                    else:
                        self.power_watts = 0.0

                    # DPS 18: Current (mA)
                    if "18" in dps:
                        self.current = round(float(dps["18"]) / 1000.0, 2)

                    # DPS 20: Voltage (0.1V)
                    if "20" in dps:
                        self.voltage = round(float(dps["20"]) / 10.0, 1)

                    # DPS 17: Cumulative energy (0.01 kWh)
                    if "17" in dps:
                        self.daily_kwh = round(float(dps["17"]) / 100.0, 2)

                    self.is_connected = True
                    self.last_update = time.time()
                    return self.to_dict(is_mock=False)
            except Exception as e:
                logger.debug(f"Tuya LAN poll error for {self.name}: {e}")

        # 2. Fallback to Tuya OpenAPI Cloud
        if self.cloud and self.device_id:
            try:
                c_status = await loop.run_in_executor(None, lambda: self.cloud.getstatus(self.device_id))
                if c_status and c_status.get("success"):
                    for item in c_status.get("result", []):
                        code = item.get("code")
                        val = item.get("value")
                        if code == "switch":
                            self.state = "on" if val else "off"
                            if not self.power_watts:
                                self.power_watts = self.rated_watts if self.state == "on" else 0.0
                        elif code == "cur_power":
                            p = float(val)
                            self.power_watts = round(p / 10.0, 1) if p > 5000 else round(p, 1)
                        elif code == "cur_current":
                            self.current = round(float(val) / 1000.0, 2)
                        elif code == "cur_voltage":
                            self.voltage = round(float(val) / 10.0, 1)
                        elif code == "add_ele":
                            self.daily_kwh = round(float(val) / 100.0, 2)

                    self.is_connected = True
                    self.last_update = time.time()
                    return self.to_dict(is_mock=False)
            except Exception as e:
                logger.debug(f"Tuya Cloud poll error for {self.name}: {e}")

        self.is_connected = False
        if allow_mock:
            return self.to_dict(is_mock=True)
        return self.to_dict(is_mock=False)

    async def set_switch(self, new_state: str) -> bool:
        """Turn switch on or off with LAN and Cloud fallback."""
        is_on = (new_state.lower() == "on")
        success = False
        loop = asyncio.get_running_loop()

        # 1. Try local LAN
        if TINYTUYA_AVAILABLE and self._device and self.local_key:
            try:
                if is_on:
                    res = await loop.run_in_executor(None, self._device.turn_on)
                else:
                    res = await loop.run_in_executor(None, self._device.turn_off)
                if res and res.get("Error") is None:
                    success = True
            except Exception as e:
                logger.debug(f"Tuya LAN set_switch failed for {self.name}: {e}")

        # 2. Fallback to Tuya Cloud API
        if not success and self.cloud and self.device_id:
            try:
                res = await loop.run_in_executor(
                    None,
                    lambda: self.cloud.sendcommand(self.device_id, {'commands': [{'code': 'switch', 'value': is_on}]})
                )
                if res and res.get("result") is True:
                    success = True
            except Exception as e:
                logger.error(f"Tuya Cloud set_switch failed for {self.name}: {e}")

        if success or not self.device_id:
            self.state = "on" if is_on else "off"
            self.power_watts = self.rated_watts if is_on else 0.0
            self.last_update = time.time()
            return True

        return False

    def to_dict(self, is_mock: bool = False) -> Dict[str, Any]:
        return {
            "name": self.name,
            "device_id": self.device_id,
            "host": self.host,
            "connected": self.is_connected,
            "is_connected": self.is_connected,
            "is_mock": is_mock,
            "state": self.state,
            "has_temp_sensor": False,
            "temperature_c": None,
            "target_temp_c": None,
            "power_watts": self.power_watts if self.state == "on" else 0.0,
            "voltage": self.voltage,
            "current_amps": self.current,
            "daily_kwh": round(getattr(self, "daily_kwh", 0.0), 2),
            "rated_watts": self.rated_watts,
            "rssi": -50,
            "auto_control_enabled": False,
            "auto_control": []
        }

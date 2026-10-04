"""
Sonoff Local eWeLink LAN Protocol Client.
Communicates directly with Sonoff devices over the local Wi-Fi network (Port 8081).
Does NOT require cloud internet connection.
"""

import aiohttp
import asyncio
import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("SonoffLAN")

class SonoffDevice:
    """Client for a single Sonoff device over local Wi-Fi LAN."""

    def __init__(self, name: str, host: str, port: int = 8081, device_id: str = "", api_key: str = "",
                 has_temp_sensor: bool = False, rated_watts: float = 0.0):
        self.name = name
        self.host = host
        self.port = port
        self.device_id = device_id
        self.api_key = api_key
        self.has_temp_sensor = has_temp_sensor
        self.rated_watts = rated_watts
        
        # Internal state
        self.is_connected = False
        self.state = "off"
        self.temperature_c = 48.0 if has_temp_sensor else None
        self.target_temp_c = 55.0
        self.voltage = 230.0
        self.current = 0.0
        self.power_watts = 0.0
        self.last_update = 0.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/zeroconf"

    async def get_device_info(self) -> Optional[Dict[str, Any]]:
        """Fetch device status from Sonoff local REST API."""
        url = f"{self.base_url}/info"
        payload = {"deviceid": self.device_id, "data": {}}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=2.5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", {})
        except Exception as e:
            logger.debug(f"Device {self.name} ({self.host}) LAN info request failed: {e}")
        return None

    async def set_switch(self, state: str) -> bool:
        """Turn switch 'on' or 'off'."""
        state = state.lower()
        if state not in ("on", "off"):
            raise ValueError("State must be 'on' or 'off'")

        url = f"{self.base_url}/switch"
        payload = {"deviceid": self.device_id, "data": {"switch": state}}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=2.5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("error") == 0:
                            self.state = state
                            self.power_watts = self.rated_watts if state == "on" else 0.0
                            return True
        except Exception as e:
            logger.debug(f"Failed to set switch for {self.name} on {self.host}: {e}")
        
        # If offline/mock allowed, update local state
        self.state = state
        self.power_watts = self.rated_watts if state == "on" else 0.0
        return False

    async def poll(self, allow_mock: bool = True) -> Dict[str, Any]:
        """Poll the device for state, temperature, and power telemetry."""
        info = await self.get_device_info()
        
        if info:
            self.is_connected = True
            self.state = info.get("switch", self.state)
            
            # Parse temperature if available (e.g. from TH Elite / TH Origin)
            if self.has_temp_sensor and "temperature" in info:
                try:
                    self.temperature_c = float(info["temperature"])
                except (ValueError, TypeError):
                    pass
            
            # Parse power / voltage / current (e.g. from POW Elite)
            if "power" in info:
                try:
                    self.power_watts = float(info["power"])
                    self.voltage = float(info.get("voltage", 230.0))
                    self.current = float(info.get("current", self.power_watts / max(1.0, self.voltage)))
                except (ValueError, TypeError):
                    pass
            elif self.state == "on" and self.rated_watts > 0:
                self.power_watts = self.rated_watts

            self.last_update = time.time()
            return self.to_dict(is_mock=False)

        self.is_connected = False
        if allow_mock:
            self._update_mock_telemetry()
            return self.to_dict(is_mock=True)

        return self.to_dict(is_mock=False)

    def _update_mock_telemetry(self):
        """Simulate realistic behavior when device is offline."""
        if self.state == "on":
            self.power_watts = self.rated_watts * 0.98
            self.current = round(self.power_watts / 230.0, 2)
            # If geyser is on, water heats up gradually
            if self.has_temp_sensor and self.temperature_c is not None:
                self.temperature_c = min(68.0, round(self.temperature_c + 0.15, 2))
        else:
            self.power_watts = 0.0
            self.current = 0.0
            # Geyser slowly cools down
            if self.has_temp_sensor and self.temperature_c is not None:
                self.temperature_c = max(38.0, round(self.temperature_c - 0.03, 2))
        self.last_update = time.time()

    def to_dict(self, is_mock: bool = False) -> Dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "connected": self.is_connected or is_mock,
            "is_mock": is_mock,
            "state": self.state,
            "has_temp_sensor": self.has_temp_sensor,
            "temperature_c": self.temperature_c,
            "target_temp_c": self.target_temp_c,
            "power_watts": round(self.power_watts, 1),
            "voltage": round(self.voltage, 1),
            "current_amps": round(self.current, 2),
            "rated_watts": self.rated_watts
        }

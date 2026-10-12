"""
RainPoint / HomGar Cloud Connector.
Connects to RainPoint Smart+ / HomGar cloud to fetch live pool thermometer telemetry
(e.g., RainPoint HCS0528ARF / HCS0565ARF floating pool thermometer via HWG023WBRF Wi-Fi hub).
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Dict, Any, Optional
import aiohttp

logger = logging.getLogger("RainPointClient")

# Known structural field tags from RainPoint payload protocol
STA_TEM_FIELD = 9       # Temperature in F*10 (signed 16-bit little-endian)
STA_WKSTATE_FIELD = 30  # Work state
STA_BAT_FIELD = 31      # Battery flag (1 = healthy, 2 = low)
STA_RSSI_FIELD = 32     # Radio signal strength
STA_REPTIME_FIELD = 54  # Report timestamp

class RainPointClient:
    def __init__(
        self,
        email: str,
        password: str,
        area_code: str = "27",
        app_code: str = "2",
        base_url: str = "https://region3.homgarus.com",
        cache_file: Optional[str] = "data/rainpoint_cache.json"
    ):
        self.email = email
        self.password = password
        self.area_code = str(area_code)
        self.app_code = str(app_code)
        self.base_url = base_url.rstrip("/")
        self.cache_file = cache_file

        self.token: Optional[str] = None
        self.token_expires: float = 0
        self.mid: Optional[int] = None
        self.hid: Optional[int] = None
        self.subdevice_name: str = "Pool Thermometer"
        self.hub_name: str = "RainPoint Hub"
        self.last_reading: Dict[str, Any] = {}

        self._load_cache()

    def _load_cache(self):
        if self.cache_file and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.token = data.get("token")
                    self.token_expires = data.get("token_expires", 0)
                    self.mid = data.get("mid")
                    self.hid = data.get("hid")
                    self.subdevice_name = data.get("subdevice_name", self.subdevice_name)
                    self.hub_name = data.get("hub_name", self.hub_name)
                    self.last_reading = data.get("last_reading", {})
            except Exception as e:
                logger.debug(f"Could not load RainPoint cache: {e}")

    def _save_cache(self):
        if self.cache_file:
            try:
                os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "token": self.token,
                        "token_expires": self.token_expires,
                        "mid": self.mid,
                        "hid": self.hid,
                        "subdevice_name": self.subdevice_name,
                        "hub_name": self.hub_name,
                        "last_reading": self.last_reading
                    }, f, indent=2)
            except Exception as e:
                logger.debug(f"Could not save RainPoint cache: {e}")

    def _get_headers(self, with_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "lang": "en",
            "appCode": self.app_code,
            "User-Agent": "okhttp/4.9.3"
        }
        if with_auth and self.token:
            headers["auth"] = self.token
        return headers

    async def login(self) -> bool:
        if not self.email or not self.password:
            logger.warning("RainPoint credentials not configured")
            return False

        dev_id = hashlib.md5((self.email + self.area_code).encode("utf-8")).hexdigest()
        md5_password = hashlib.md5(self.password.encode("utf-8")).hexdigest()

        payload = {
            "areaCode": self.area_code,
            "phoneOrEmail": self.email,
            "password": md5_password,
            "deviceId": dev_id
        }

        url = f"{self.base_url}/auth/basic/app/login"
        timeout = aiohttp.ClientTimeout(total=12)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload, headers=self._get_headers(with_auth=False)) as resp:
                    if resp.status != 200:
                        logger.error(f"RainPoint login HTTP error {resp.status}")
                        return False
                    data = await resp.json()
                    if data.get("code") == 0 and data.get("data"):
                        res_data = data["data"]
                        self.token = res_data.get("token")
                        expires_in = res_data.get("tokenExpired", 86400 * 30)
                        self.token_expires = time.time() + expires_in
                        logger.info("Successfully authenticated with RainPoint Cloud API")
                        self._save_cache()
                        return True
                    else:
                        logger.error(f"RainPoint login failed: {data.get('msg')} (code {data.get('code')})")
                        return False
        except Exception as e:
            logger.error(f"RainPoint login connection error: {e}")
            return False

    async def ensure_authenticated(self) -> bool:
        # Check if current token is present and not expiring within 2 hours
        if self.token and (self.token_expires - time.time()) > 7200:
            return True
        return await self.login()

    async def discover_devices(self) -> bool:
        """Find the hub (mid) and pool thermometer (subdevice) under the user's home."""
        if not await self.ensure_authenticated():
            return False

        timeout = aiohttp.ClientTimeout(total=12)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 1. Get Homes
                url_homes = f"{self.base_url}/app/member/appHome/list"
                async with session.get(url_homes, headers=self._get_headers()) as resp:
                    if resp.status != 200:
                        return False
                    res = await resp.json()
                    if res.get("code") != 0 or not res.get("data"):
                        return False
                    homes = res["data"]
                    self.hid = homes[0].get("hid")

                # 2. Get Devices for Home
                url_devs = f"{self.base_url}/app/device/getDeviceByHid?hid={self.hid}"
                async with session.get(url_devs, headers=self._get_headers()) as resp:
                    if resp.status != 200:
                        return False
                    res = await resp.json()
                    if res.get("code") != 0 or not res.get("data"):
                        return False

                    hubs = res["data"]
                    for hub in hubs:
                        self.mid = hub.get("mid")
                        self.hub_name = hub.get("name", self.hub_name)
                        for sub in hub.get("subDevices", []):
                            model = sub.get("model", "")
                            # Pool sensors typically HCS0528ARF or HCS0565ARF or have Pool in name
                            if "pool" in sub.get("name", "").lower() or "528" in model or "565" in model or "015" in model:
                                self.subdevice_name = sub.get("name", "Pool Thermometer")
                                break
                    self._save_cache()
                    return True
        except Exception as e:
            logger.error(f"RainPoint device discovery error: {e}")
            return False

    @staticmethod
    def decode_sensor_payload(raw: str) -> Dict[str, Any]:
        """
        Decode RainPoint hex payload string (e.g., 10#E707033203DC01B805853203FF0F8CD0961A).
        Returns dict with water_temp_c, water_temp_f, battery_ok.
        """
        result = {
            "temp_c": None,
            "temp_f": None,
            "battery_ok": True,
            "battery_flag": 1
        }
        if not raw or "#" not in raw:
            return result

        try:
            hex_data = raw.split("#")[1]
            data = list(bytes.fromhex(hex_data))
            entries = []
            i = 0
            n = len(data)
            while i < n:
                header = data[i]
                if not (header & 0x80):
                    # Compact form
                    entries.append({"field": (header >> 4) & 7, "val": [header]})
                    i += 1
                else:
                    extra_len = header & 3
                    span = extra_len + 2
                    index5 = (header >> 2) & 31
                    if index5 <= 30:
                        field = index5 + 8
                    else:
                        i += 1
                        if i >= len(data):
                            break
                        field = (data[i] & 0xFF) + 39
                    chunk = data[i:i + span]
                    entries.append({"field": field, "val": chunk[1:]})
                    i += span

            for e in entries:
                f_id = e["field"]
                val_bytes = bytes(e["val"])
                if f_id == STA_TEM_FIELD and len(val_bytes) >= 2:
                    raw_temp = int.from_bytes(val_bytes[:2], "little", signed=True)
                    f_val = raw_temp / 10.0
                    c_val = (f_val - 32.0) * 5.0 / 9.0
                    result["temp_f"] = round(f_val, 1)
                    result["temp_c"] = round(c_val, 1)
                elif f_id == STA_BAT_FIELD and len(val_bytes) >= 1:
                    flag = val_bytes[0]
                    result["battery_flag"] = flag
                    result["battery_ok"] = (flag == 1)

        except Exception as e:
            logger.debug(f"Failed decoding sensor payload '{raw}': {e}")

        return result

    async def poll_pool_temperature(self, allow_mock: bool = False) -> Dict[str, Any]:
        """Poll RainPoint Cloud for current pool temperature telemetry."""
        # Ensure we have hub ID
        if not self.mid:
            await self.discover_devices()

        if not self.mid:
            if self.last_reading:
                return self.last_reading
            if allow_mock:
                return self._mock_reading()
            return {"online": False, "temp_c": None, "error": "No RainPoint Hub found"}

        if not await self.ensure_authenticated():
            if self.last_reading:
                return self.last_reading
            if allow_mock:
                return self._mock_reading()
            return {"online": False, "temp_c": None, "error": "Authentication failed"}

        url = f"{self.base_url}/app/device/getDeviceStatus?mid={self.mid}"
        timeout = aiohttp.ClientTimeout(total=10)

        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=self._get_headers()) as resp:
                        if resp.status == 200:
                            res = await resp.json()
                            code = res.get("code")
                            if code == 1001:  # NOT_TOKEN (token expired/invalidated)
                                logger.info("RainPoint token invalidated, re-logging in...")
                                await self.login()
                                continue  # retry next attempt

                            if code == 0 and res.get("data"):
                                statuses = res["data"].get("subDeviceStatus", [])
                                hub_connected = False
                                hub_rssi = None
                                d01_payload = None
                                d01_time = None

                                for s in statuses:
                                    s_id = s.get("id")
                                    s_val = s.get("value")
                                    if s_id == "connected":
                                        hub_connected = (str(s_val) == "1")
                                    elif s_id == "state" and s_val:
                                        parts = str(s_val).split(",")
                                        if len(parts) >= 2:
                                            try:
                                                hub_rssi = int(parts[1])
                                            except ValueError:
                                                pass
                                    elif s_id == "D01" and s_val:
                                        d01_payload = str(s_val)
                                        d01_time = s.get("time")

                                decoded = self.decode_sensor_payload(d01_payload)
                                temp_c = decoded.get("temp_c")
                                temp_f = decoded.get("temp_f")

                                reading = {
                                    "online": True,
                                    "device_name": self.subdevice_name,
                                    "hub_name": self.hub_name,
                                    "hub_connected": hub_connected,
                                    "hub_rssi_dbm": hub_rssi,
                                    "temp_c": temp_c,
                                    "temp_f": temp_f,
                                    "battery_ok": decoded.get("battery_ok", True),
                                    "battery_flag": decoded.get("battery_flag", 1),
                                    "raw_payload": d01_payload,
                                    "timestamp_ms": d01_time or int(time.time() * 1000),
                                    "updated_at": time.time()
                                }
                                self.last_reading = reading
                                self._save_cache()
                                return reading
            except Exception as e:
                logger.warning(f"Error querying RainPoint status: {e}")

        if self.last_reading:
            res = dict(self.last_reading)
            res["stale"] = True
            return res

        if allow_mock:
            return self._mock_reading()

        return {"online": False, "temp_c": None, "error": "Failed polling RainPoint"}

    def _mock_reading(self) -> Dict[str, Any]:
        return {
            "online": True,
            "device_name": "15C Pool (Simulated)",
            "hub_name": "RainPoint Hub",
            "hub_connected": True,
            "hub_rssi_dbm": -50,
            "temp_c": 26.5,
            "temp_f": 79.7,
            "battery_ok": True,
            "battery_flag": 1,
            "updated_at": time.time()
        }

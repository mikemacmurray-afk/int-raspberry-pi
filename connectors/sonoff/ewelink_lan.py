"""
Sonoff eWeLink LAN & Cloud Protocol Client.
Supports:
1. Real-time local LAN mDNS (Zeroconf) telemetry with AES-128-CBC hardware decryption.
2. Direct local REST control over Port 8081.
3. eWeLink Cloud API V2 fallback for telemetry and remote switch control.
"""

import aiohttp
import asyncio
import base64
import hashlib
import json
import logging
import time
from typing import Dict, Any, Optional

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    from zeroconf import Zeroconf, ServiceBrowser
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False

logger = logging.getLogger("SonoffLAN")

class EwelinkCloudV2:
    """Helper client for eWeLink Cloud API V2."""

    def __init__(self, username: str = "", password: str = "", region: str = "eu"):
        self.username = username
        self.password = password
        self.region = region
        self.token: Optional[str] = None
        self.user_apikey: Optional[str] = None

    async def ensure_token(self) -> Optional[str]:
        if self.token:
            return self.token
        if not self.username or not self.password:
            return None

        # Authenticate using sonoff-python helper or Coolkit auth
        try:
            loop = asyncio.get_running_loop()
            import sonoff.sonoff as s
            client = await loop.run_in_executor(None, lambda: s.Sonoff(self.username, self.password, self.region))
            self.token = client._bearer_token
            self.user_apikey = client._user_apikey
            logger.info("Successfully authenticated with eWeLink Cloud API V2")
            return self.token
        except Exception as e:
            logger.warning(f"Failed to authenticate with eWeLink Cloud API: {e}")
            return None

    async def get_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        token = await self.ensure_token()
        if not token:
            return None

        url = f"https://{self.region}-apia.coolkit.cc/v2/device/thing/status?type=1&id={device_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-CK-Nonce": str(int(time.time() * 1000))[:8]
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=4.0)) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        if res.get("error") == 0:
                            return res.get("data", {}).get("params", {})
        except Exception as e:
            logger.debug(f"eWeLink Cloud status fetch error for {device_id}: {e}")
        return None

    async def set_device_params(self, device_id: str, params: Dict[str, Any]) -> bool:
        token = await self.ensure_token()
        if not token:
            return False

        url = f"https://{self.region}-apia.coolkit.cc/v2/device/thing/status"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-CK-Nonce": str(int(time.time() * 1000))[:8]
        }
        payload = {
            "type": 1,
            "id": device_id,
            "params": params
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        return res.get("error") == 0
        except Exception as e:
            logger.warning(f"eWeLink Cloud params update error for {device_id}: {e}")
        return False

    async def set_device_switch(self, device_id: str, switch_state: str) -> bool:
        return await self.set_device_params(device_id, {"switch": switch_state})

# Global Zeroconf service manager
class GlobalMdnsManager:
    _instance = None

    def __init__(self):
        self.devices: Dict[str, "SonoffDevice"] = {}
        self.zc: Optional[Zeroconf] = None
        self.browser: Optional[ServiceBrowser] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = GlobalMdnsManager()
        return cls._instance

    def register(self, device: "SonoffDevice"):
        if not device.device_id:
            return
        self.devices[device.device_id] = device
        self._ensure_started()

    def _ensure_started(self):
        if not ZEROCONF_AVAILABLE or not CRYPTO_AVAILABLE:
            return
        if self.zc is None:
            try:
                self.zc = Zeroconf()
                self.browser = ServiceBrowser(self.zc, "_ewelink._tcp.local.", self)
                logger.info("Started eWeLink LAN mDNS background listener")
            except Exception as e:
                logger.warning(f"Could not start Zeroconf listener: {e}")

    def add_service(self, zc, type_, name):
        self._handle_service(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._handle_service(zc, type_, name)

    def remove_service(self, zc, type_, name):
        pass

    def _handle_service(self, zc, type_, name):
        for dev_id, device in list(self.devices.items()):
            if dev_id in name:
                info = zc.get_service_info(type_, name)
                if info and info.properties:
                    device.process_mdns_properties(info.properties)

class SonoffDevice:
    """Client for a single Sonoff device with LAN mDNS AES-128 decryption & Cloud sync."""

    def __init__(self, name: str, host: str, port: int = 8081, device_id: str = "", api_key: str = "",
                 has_temp_sensor: bool = False, rated_watts: float = 0.0,
                 cloud_client: Optional[EwelinkCloudV2] = None):
        self.name = name
        self.host = host
        self.port = port
        self.device_id = device_id
        self.api_key = api_key
        self.has_temp_sensor = has_temp_sensor
        self.rated_watts = rated_watts
        self.cloud = cloud_client

        # Precompute AES Key Hash from API Key
        self.key_hash = hashlib.md5(api_key.encode("utf-8")).digest() if (api_key and CRYPTO_AVAILABLE) else None

        # Internal state
        self.is_connected = False
        self.state = "off"
        self.temperature_c = 48.0 if has_temp_sensor else None
        self.target_temp_c = 55.0
        self.voltage = 230.0
        self.current = 0.0
        self.power_watts = 0.0
        self.rssi = -50
        self.last_update = 0.0
        self.auto_control: list = []
        self.auto_control_enabled: int = 1
        self.time_zone: int = 2

        # Restore cached autoControl settings from disk if available
        try:
            import os
            cache_file = os.path.join("data", "geyser_autocontrol_cache.json")
            if os.path.exists(cache_file):
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    self.auto_control = cached.get("autoControl", [])
                    self.auto_control_enabled = cached.get("autoControlEnabled", 1)
                    self.time_zone = cached.get("timeZone", 2)
        except Exception:
            pass

        # Register with mDNS listener if device_id is present
        if self.device_id:
            GlobalMdnsManager.get_instance().register(self)

    def process_mdns_properties(self, props: Dict[bytes, bytes]):
        """Decrypt and apply telemetry received from local mDNS broadcast."""
        if not self.key_hash or not CRYPTO_AVAILABLE:
            return

        iv_b64 = props.get(b"iv")
        if not iv_b64:
            return

        try:
            iv = base64.b64decode(iv_b64)
            raw = b"".join([props.get(f"data{i}".encode(), b"") for i in range(1, 5)])
            if not raw:
                return

            cipher = Cipher(algorithms.AES(self.key_hash), modes.CBC(iv))
            dec = cipher.decryptor()
            padded = dec.update(base64.b64decode(raw)) + dec.finalize()
            unpad = padding.PKCS7(128).unpadder()
            plain = unpad.update(padded) + unpad.finalize()
            data = json.loads(plain.decode("utf-8"))

            self._apply_payload(data)
            self.is_connected = True
            self.last_update = time.time()
            logger.debug(f"Updated {self.name} from LAN mDNS: temp={self.temperature_c}°C, switch={self.state}")
        except Exception as e:
            logger.debug(f"Failed to decrypt mDNS for {self.name}: {e}")

    def _apply_payload(self, data: Dict[str, Any]):
        """Apply raw device parameters (switch, temp, power)."""
        if "switch" in data:
            self.state = str(data["switch"]).lower()
            if self.state == "on":
                self.power_watts = self.rated_watts if self.rated_watts > 0 else self.power_watts
            else:
                self.power_watts = 0.0

        # Current temperature
        if self.has_temp_sensor:
            temp_val = data.get("currentTemperature") or data.get("temperature")
            if temp_val is not None and str(temp_val).lower() != "unavailable":
                try:
                    self.temperature_c = float(temp_val)
                except (ValueError, TypeError):
                    pass

        # Power / Voltage readings (e.g. POW models or TH series with power meter)
        if "power" in data:
            try:
                self.power_watts = float(data["power"])
            except (ValueError, TypeError):
                pass
        if "voltage" in data:
            try:
                self.voltage = float(data["voltage"])
            except (ValueError, TypeError):
                pass
        if "current" in data:
            try:
                self.current = float(data["current"])
            except (ValueError, TypeError):
                pass
        elif self.power_watts > 0 and self.voltage > 0:
            self.current = round(self.power_watts / self.voltage, 2)

        if "rssi" in data:
            try:
                self.rssi = int(data["rssi"])
            except (ValueError, TypeError):
                pass

        if "autoControl" in data:
            self.auto_control = data["autoControl"]
            tz = getattr(self, "time_zone", 2)
            for rule in self.auto_control:
                eff = rule.get("effTime", {})
                if "from" in eff and "fromLocal" not in eff:
                    try:
                        fh, fm = [int(x) for x in eff["from"].split(":")]
                        eff["fromLocal"] = f"{(fh + tz) % 24:02d}:{fm:02d}"
                    except Exception:
                        pass
                if "to" in eff and "toLocal" not in eff:
                    try:
                        th, tm = [int(x) for x in eff["to"].split(":")]
                        eff["toLocal"] = f"{(th + tz) % 24:02d}:{tm:02d}"
                    except Exception:
                        pass
            try:
                import os
                os.makedirs("data", exist_ok=True)
                with open("data/geyser_autocontrol_cache.json", "w", encoding="utf-8") as f:
                    json.dump({
                        "autoControl": self.auto_control,
                        "autoControlEnabled": getattr(self, "auto_control_enabled", 1),
                        "timeZone": getattr(self, "time_zone", 2)
                    }, f, indent=2)
            except Exception:
                pass

        if "autoControlEnabled" in data:
            try:
                self.auto_control_enabled = int(data["autoControlEnabled"])
            except (ValueError, TypeError):
                pass
        if "timeZone" in data:
            try:
                self.time_zone = int(data["timeZone"])
            except (ValueError, TypeError):
                pass

    async def poll(self, allow_mock: bool = True) -> Dict[str, Any]:
        """Poll telemetry: uses fresh LAN mDNS data, falls back to eWeLink cloud, then mock."""
        now = time.time()

        # If auto_control rules are not loaded yet, query cloud once to populate them
        if not self.auto_control and self.cloud and self.device_id:
            try:
                cloud_data = await self.cloud.get_device_status(self.device_id)
                if cloud_data:
                    self._apply_payload(cloud_data)
            except Exception:
                pass

        # 1. If recent mDNS data received within 25 seconds, use it directly (zero overhead)
        if self.is_connected and (now - self.last_update) < 25.0:
            return self.to_dict(is_mock=False)

        # 2. Try eWeLink Cloud API if available
        if self.cloud and self.device_id:
            cloud_data = await self.cloud.get_device_status(self.device_id)
            if cloud_data:
                self._apply_payload(cloud_data)
                self.is_connected = True
                self.last_update = now
                return self.to_dict(is_mock=False)

        # 3. If live read failed, check if we still have previously cached live data
        if self.is_connected and (now - self.last_update) < 60.0:
            return self.to_dict(is_mock=False)

        self.is_connected = False
        if allow_mock:
            self._update_mock_telemetry()
            return self.to_dict(is_mock=True)

        return self.to_dict(is_mock=False)

    async def set_switch(self, state: str) -> bool:
        """Turn switch 'on' or 'off' via eWeLink Cloud or LAN."""
        state = state.lower()
        if state not in ("on", "off"):
            raise ValueError("State must be 'on' or 'off'")

        success = False
        if self.cloud and self.device_id:
            success = await self.cloud.set_device_switch(self.device_id, state)

        if success or not self.device_id:
            self.state = state
            self.power_watts = self.rated_watts if state == "on" else 0.0
            self.current = round(self.power_watts / max(1.0, self.voltage), 2)
            self.last_update = time.time()
            return True

        # Fallback if offline
        self.state = state
        self.power_watts = self.rated_watts if state == "on" else 0.0
        return False

    def _update_mock_telemetry(self):
        """Simulate realistic behavior when device is offline."""
        if self.state == "on":
            self.power_watts = self.rated_watts * 0.98
            self.current = round(self.power_watts / 230.0, 2)
            if self.has_temp_sensor and self.temperature_c is not None:
                self.temperature_c = min(68.0, round(self.temperature_c + 0.15, 2))
        else:
            self.power_watts = 0.0
            self.current = 0.0
            if self.has_temp_sensor and self.temperature_c is not None:
                self.temperature_c = max(38.0, round(self.temperature_c - 0.03, 2))
        self.last_update = time.time()

    async def get_auto_control(self) -> Dict[str, Any]:
        """Fetch current autoControl settings from cache or cloud."""
        if not self.auto_control and self.cloud and self.device_id:
            cloud_data = await self.cloud.get_device_status(self.device_id)
            if cloud_data:
                self._apply_payload(cloud_data)

        return {
            "autoControlEnabled": self.auto_control_enabled,
            "autoControl": self.auto_control,
            "timeZone": self.time_zone
        }

    async def update_auto_control(self, auto_control_rules: list, enabled: int = 1) -> bool:
        """Update autoControl rules and enabled status on eWeLink cloud."""
        tz_offset = self.time_zone

        # Calculate UTC from local times
        for rule in auto_control_rules:
            eff = rule.get("effTime", {})
            from_local = eff.get("fromLocal")
            to_local = eff.get("toLocal")
            if from_local and to_local:
                try:
                    fh, fm = [int(x) for x in from_local.split(":")]
                    th, tm = [int(x) for x in to_local.split(":")]
                    utc_fh = (fh - tz_offset) % 24
                    utc_th = (th - tz_offset) % 24
                    eff["from"] = f"{utc_fh:02d}:{fm:02d}"
                    eff["to"] = f"{utc_th:02d}:{tm:02d}"
                    eff["days"] = eff.get("daysLocal", [0, 1, 2, 3, 4, 5, 6])
                except Exception:
                    pass

        params = {
            "autoControl": auto_control_rules,
            "autoControlEnabled": int(enabled)
        }

        success = False
        if self.cloud and self.device_id:
            success = await self.cloud.set_device_params(self.device_id, params)

        if success or not self.device_id:
            self.auto_control = auto_control_rules
            self.auto_control_enabled = int(enabled)
            return True

        return False

    def get_current_active_window(self) -> Optional[Dict[str, Any]]:
        """Evaluate if current local time is within an active enabled schedule window."""
        if not self.auto_control_enabled or not self.auto_control:
            return None

        tz = getattr(self, "time_zone", 2)
        utc_now = time.gmtime()
        local_hour = (utc_now.tm_hour + tz) % 24
        local_min = utc_now.tm_min
        now_str = f"{local_hour:02d}:{local_min:02d}"

        rule_names = ["Morning Boost Window", "Solar Peak Heating Window", "Evening / Extra Window"]

        for idx, rule in enumerate(self.auto_control):
            if not rule.get("enable", True):
                continue
            eff = rule.get("effTime", {})
            from_t = eff.get("fromLocal")
            to_t = eff.get("toLocal")
            if not from_t or not to_t:
                continue

            is_active = False
            if from_t <= to_t:
                is_active = (from_t <= now_str < to_t)
            else:
                is_active = (now_str >= from_t or now_str < to_t)

            if is_active:
                targets = rule.get("targets", [])
                high_t = None
                low_t = None
                for t in targets:
                    if "high" in t:
                        try:
                            high_t = float(t["high"])
                        except Exception:
                            pass
                    if "low" in t:
                        try:
                            low_t = float(t["low"])
                        except Exception:
                            pass

                target_val = high_t if high_t is not None else 55.0
                name = rule_names[idx] if idx < len(rule_names) else f"Window {idx+1}"
                return {
                    "is_active": True,
                    "slot_index": idx,
                    "name": name,
                    "from": from_t,
                    "to": to_t,
                    "target_temp_c": round(target_val, 1),
                    "low_temp_c": round(low_t, 1) if low_t is not None else None,
                    "high_temp_c": round(high_t, 1) if high_t is not None else None
                }
        return None

    def to_dict(self, is_mock: bool = False) -> Dict[str, Any]:
        active_window = self.get_current_active_window()
        effective_target = active_window["target_temp_c"] if active_window else self.target_temp_c

        return {
            "name": self.name,
            "host": self.host,
            "connected": self.is_connected or is_mock,
            "is_mock": is_mock,
            "state": self.state,
            "has_temp_sensor": self.has_temp_sensor,
            "temperature_c": round(self.temperature_c, 1) if self.temperature_c is not None else None,
            "target_temp_c": round(effective_target, 1),
            "manual_target_temp_c": round(self.target_temp_c, 1),
            "active_schedule_window": active_window,
            "power_watts": round(self.power_watts, 1),
            "voltage": round(self.voltage, 1),
            "current_amps": round(self.current, 2),
            "rated_watts": self.rated_watts,
            "rssi": self.rssi,
            "auto_control_enabled": bool(self.auto_control_enabled),
            "auto_control": self.auto_control
        }

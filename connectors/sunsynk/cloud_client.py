"""
Sunsynk Connect Cloud API Client.
Interfaces with official Sunsynk Cloud API (api.sunsynk.net) for live telemetry,
energy flow, and Time-of-Use / System Mode settings management.
Falls back seamlessly to realistic simulation if credentials are not configured
or cloud server is unreachable.
"""

import time
import math
import logging
from typing import Dict, Any, Optional, List

try:
    from sunsynk.client import SunsynkClient as SCloudClient
    from sunsynk.exceptions import SunsynkAuthenticationError
except ImportError:
    SCloudClient = None
    SunsynkAuthenticationError = Exception

logger = logging.getLogger("SunsynkCloudClient")

WORK_MODE_MAP = {
    1: "Selling First",
    2: "Zero Export to Load",
    3: "Zero Export to CT"
}

PRIORITY_MAP = {
    0: "Battery First",
    1: "Load First"
}

class SunsynkCloudClient:
    def __init__(self, username: str = "", password: str = "", inverter_sn: str = "", base_url: Optional[str] = None):
        self.username = username
        self.password = password
        self.inverter_sn = inverter_sn
        self.base_url = base_url
        self._cloud_client: Optional[Any] = None
        self.plant_id: Optional[int] = None
        self.plant_name: str = ""
        self.is_connected = False
        self.last_read_time = 0.0

        # Fallback / mock settings cache
        self._mock_system_mode = {
            "priority": 1,
            "priority_str": "Load First",
            "work_mode": 3,
            "work_mode_str": "Zero Export to CT",
            "max_sell_power": 5000,
            "solar_export_enabled": False,
            "tou_enabled": True,
            "battery_low_soc": 20,
            "battery_restart_soc": 35,
            "battery_shutdown_soc": 15,
            "tou_slots": [
                {"slot": 1, "time": "01:00", "power": 3000, "soc": 80, "grid_charge": True},
                {"slot": 2, "time": "05:00", "power": 3000, "soc": 50, "grid_charge": False},
                {"slot": 3, "time": "09:00", "power": 5000, "soc": 100, "grid_charge": False},
                {"slot": 4, "time": "13:00", "power": 5000, "soc": 100, "grid_charge": False},
                {"slot": 5, "time": "17:00", "power": 4000, "soc": 70, "grid_charge": False},
                {"slot": 6, "time": "21:00", "power": 3000, "soc": 35, "grid_charge": False}
            ]
        }

    async def _ensure_authenticated(self) -> bool:
        """Authenticate with Sunsynk Connect API and discover inverter SN if needed."""
        if not self.username or not self.password:
            return False

        if SCloudClient is None:
            logger.warning("sunsynk-api-client package is not installed.")
            return False

        try:
            if self._cloud_client is None:
                self._cloud_client = SCloudClient(
                    username=self.username,
                    password=self.password,
                    base_url=self.base_url
                )
                await self._cloud_client.login()
                logger.info("Successfully authenticated with Sunsynk Connect Cloud API.")

            # Auto-discover plant ID if not set
            if not self.plant_id:
                try:
                    plants = await self._cloud_client.get_plants()
                    if plants:
                        self.plant_id = plants[0].id
                        self.plant_name = plants[0].name
                        logger.info(f"Discovered plant: {self.plant_name} (ID: {self.plant_id})")
                except Exception as e:
                    logger.warning(f"Failed to fetch plant list: {e}")

            # Auto-discover inverter serial number if not configured
            if not self.inverter_sn:
                inverters = await self._cloud_client.get_inverters()
                if inverters:
                    self.inverter_sn = inverters[0].sn
                    logger.info(f"Discovered inverter serial number: {self.inverter_sn}")
                else:
                    logger.warning("No inverters found under this Sunsynk account.")
                    return False

            return True
        except Exception as e:
            logger.error(f"Sunsynk Cloud API authentication error: {e}")
            self._cloud_client = None
            return False

    async def read_telemetry(self, allow_mock: bool = True) -> Dict[str, Any]:
        """Fetch live telemetry from Sunsynk Cloud API (or fallback to simulation)."""
        authed = await self._ensure_authenticated()

        if authed and self._cloud_client and self.inverter_sn:
            try:
                import asyncio
                flow_res, inp_res, bat_res = await asyncio.gather(
                    self._cloud_client.get_inverter_flow(self.inverter_sn),
                    self._cloud_client.get_inverter_realtime_input(self.inverter_sn),
                    self._cloud_client.get_inverter_realtime_battery(self.inverter_sn),
                    return_exceptions=True
                )

                if isinstance(flow_res, Exception) and isinstance(inp_res, Exception):
                    raise ConnectionError(f"Failed to fetch telemetry from Sunsynk Cloud: {flow_res}")

                flow = flow_res if not isinstance(flow_res, Exception) else None
                inp = inp_res if not isinstance(inp_res, Exception) else None
                bat = bat_res if not isinstance(bat_res, Exception) else None

                self.is_connected = True
                self.last_read_time = time.time()

                # 1. Solar Generation extraction
                pv_w = 0.0
                pv1_w, pv1_v, pv1_i = 0.0, 0.0, 0.0
                pv2_w, pv2_v, pv2_i = 0.0, 0.0, 0.0
                daily_pv = 0.0

                if inp:
                    pv_w = float(inp.pac or 0.0)
                    daily_pv = float(inp.generated_today or 0.0)
                    if inp.pv_iv and len(inp.pv_iv) > 0:
                        pv1_w = float(inp.pv_iv[0].ppv or 0.0)
                        pv1_v = float(inp.pv_iv[0].vpv or 0.0)
                        pv1_i = float(inp.pv_iv[0].ipv or 0.0)
                    if inp.pv_iv and len(inp.pv_iv) > 1:
                        pv2_w = float(inp.pv_iv[1].ppv or 0.0)
                        pv2_v = float(inp.pv_iv[1].vpv or 0.0)
                        pv2_i = float(inp.pv_iv[1].ipv or 0.0)

                # Fallback to flow.raw['pv'] list if inp didn't return solar power
                if pv_w <= 0.0 and flow:
                    pv_list = flow.raw.get("pv", [])
                    if isinstance(pv_list, list) and pv_list:
                        pv_w = sum(float(p.get("power", 0.0)) for p in pv_list)
                        if len(pv_list) > 0:
                            pv1_w = float(pv_list[0].get("power", 0.0))
                        if len(pv_list) > 1:
                            pv2_w = float(pv_list[1].get("power", 0.0))
                    if pv_w <= 0.0:
                        pv_w = max(0.0, float(flow.pv_power or 0.0))

                # 2. Battery telemetry extraction
                soc = float(flow.soc if flow and flow.soc is not None else (bat.soc if bat else 50.0))
                batt_w = 0.0
                batt_v = 51.2 + (soc / 100.0) * 2.8
                batt_current = 0.0
                batt_temp = 28.0
                daily_charge = 0.0
                daily_discharge = 0.0

                if bat:
                    batt_w = float(bat.power if bat.power is not None else 0.0)
                    batt_v = float(bat.voltage if bat.voltage is not None else batt_v)
                    batt_current = float(bat.current if bat.current is not None else 0.0)
                    batt_temp = float(bat.temp if bat.temp is not None else batt_temp)
                    daily_charge = float(bat.charge_today or 0.0)
                    daily_discharge = float(bat.discharge_today or 0.0)
                elif flow:
                    batt_w = float(flow.battery_power or 0.0)
                    batt_current = round(batt_w / max(1.0, batt_v), 2)

                # 3. Load & Grid extraction
                load_w = float(flow.load_or_eps_power or flow.home_load_power or 0.0) if flow else 0.0
                if load_w < 0:
                    load_w = max(0.0, float(flow.ups_load_power or 0.0)) if flow else 0.0
                grid_w = float(flow.grid_or_meter_power or 0.0) if flow else 0.0

                return {
                    "timestamp": time.time(),
                    "source": "sunsynk_cloud_api",
                    "inverter_sn": self.inverter_sn,
                    "solar": {
                        "total_watts": round(pv_w, 1),
                        "pv1_watts": round(pv1_w, 1),
                        "pv1_volts": round(pv1_v, 1),
                        "pv1_amps": round(pv1_i, 1),
                        "pv2_watts": round(pv2_w, 1),
                        "pv2_volts": round(pv2_v, 1),
                        "pv2_amps": round(pv2_i, 1),
                        "daily_kwh": round(daily_pv, 2)
                    },
                    "battery": {
                        "soc_percent": int(soc),
                        "voltage": round(batt_v, 2),
                        "current_amps": round(batt_current, 2),
                        "watts": round(batt_w, 1),
                        "temperature_c": round(batt_temp, 1),
                        "daily_charge_kwh": round(daily_charge, 2),
                        "daily_discharge_kwh": round(daily_discharge, 2)
                    },
                    "grid": {
                        "voltage": 230.0,
                        "frequency_hz": 50.0,
                        "watts": round(grid_w, 1),
                        "daily_import_kwh": 0.0
                    },
                    "load": {
                        "total_watts": round(load_w, 1),
                        "daily_kwh": 0.0
                    },
                    "inverter": {
                        "temperature_c": round(batt_temp + 5.0, 1),
                        "status": "Online (Cloud)"
                    }
                }
            except Exception as e:
                logger.warning(f"Error querying Sunsynk Cloud API: {e}")
                self.is_connected = False

        if allow_mock:
            return self._generate_mock_telemetry()

        raise ConnectionError("Unable to reach Sunsynk Cloud API and mock is disabled.")

    async def read_system_mode(self, allow_mock: bool = True) -> Dict[str, Any]:
        """Read 6-slot TOU settings and Work Mode from Sunsynk Cloud API."""
        authed = await self._ensure_authenticated()

        if authed and self._cloud_client and self.inverter_sn:
            try:
                settings = await self._cloud_client.get_inverter_settings(self.inverter_sn)
                if settings:
                    slots = []
                    for i in range(6):
                        t_str = settings.sell_times[i] if i < len(settings.sell_times) else f"{i*4:02d}:00"
                        p_val = settings.sell_time_power[i] if i < len(settings.sell_time_power) else 3000
                        c_val = settings.capacities[i] if i < len(settings.capacities) else 80
                        gc_val = bool(settings.grid_charge_on[i]) if i < len(settings.grid_charge_on) else False
                        slots.append({
                            "slot": i + 1,
                            "time": str(t_str or "00:00"),
                            "power": int(p_val or 0),
                            "soc": int(c_val or 100),
                            "grid_charge": gc_val
                        })

                    res = {
                        "source": "sunsynk_cloud_api",
                        "inverter_sn": self.inverter_sn,
                        "priority": settings.energy_mode or 1,
                        "priority_str": PRIORITY_MAP.get(settings.energy_mode or 1, "Load First"),
                        "work_mode": settings.sys_work_mode or 3,
                        "work_mode_str": WORK_MODE_MAP.get(settings.sys_work_mode or 3, "Zero Export to CT"),
                        "max_sell_power": settings.solar_max_sell_power or 5000,
                        "solar_export_enabled": bool(settings.solar_sell),
                        "tou_enabled": bool(settings.peak_and_valley),
                        "battery_low_soc": settings.battery_low_cap or 20,
                        "battery_restart_soc": settings.battery_restart_cap or 35,
                        "battery_shutdown_soc": settings.battery_shutdown_cap or 15,
                        "tou_slots": slots
                    }
                    self._mock_system_mode = res
                    return res
            except Exception as e:
                logger.warning(f"Failed to read settings from Sunsynk Cloud API: {e}")

        if allow_mock:
            return self._mock_system_mode

        raise ConnectionError("Unable to read Sunsynk Cloud settings.")

    async def update_system_mode(self, settings_update: Dict[str, Any], allow_mock: bool = True) -> bool:
        """Write modified Time-of-Use & operating settings back to Sunsynk Cloud."""
        authed = await self._ensure_authenticated()

        if authed and self._cloud_client and self.inverter_sn:
            try:
                current_settings = await self._cloud_client.get_inverter_settings(self.inverter_sn)
                payload = dict(current_settings.raw) if current_settings else {}

                if "work_mode" in settings_update:
                    payload["sysWorkMode"] = int(settings_update["work_mode"])
                if "priority" in settings_update:
                    payload["energyMode"] = int(settings_update["priority"])
                if "battery_low_soc" in settings_update:
                    payload["batteryLowCap"] = int(settings_update["battery_low_soc"])
                if "battery_restart_soc" in settings_update:
                    payload["batteryRestartCap"] = int(settings_update["battery_restart_soc"])
                if "battery_shutdown_soc" in settings_update:
                    payload["batteryShutdownCap"] = int(settings_update["battery_shutdown_soc"])
                if "tou_enabled" in settings_update:
                    payload["peakAndVallery"] = 1 if settings_update["tou_enabled"] else 0

                if "tou_slots" in settings_update:
                    for s in settings_update["tou_slots"]:
                        idx = s["slot"]
                        if 1 <= idx <= 6:
                            if "time" in s:
                                payload[f"sellTime{idx}"] = s["time"]
                            if "power" in s:
                                payload[f"sellTime{idx}Pac"] = int(s["power"])
                            if "soc" in s:
                                payload[f"cap{idx}"] = int(s["soc"])
                            if "grid_charge" in s:
                                payload[f"time{idx}on"] = 1 if s["grid_charge"] else 0

                await self._cloud_client.set_inverter_settings(self.inverter_sn, payload)
                logger.info(f"Successfully applied settings to Sunsynk Inverter {self.inverter_sn} via Cloud API.")

                # Update local cache
                for k, v in settings_update.items():
                    self._mock_system_mode[k] = v
                return True
            except Exception as e:
                logger.error(f"Failed to update settings via Sunsynk Cloud API: {e}")

        # Update local simulation cache if cloud is not active
        for k, v in settings_update.items():
            self._mock_system_mode[k] = v

        return True if allow_mock else False

    def _generate_mock_telemetry(self) -> Dict[str, Any]:
        """Realistic solar and battery simulation matching the live time of day."""
        now = time.localtime()
        hours = now.tm_hour + (now.tm_min / 60.0)

        if 6.0 <= hours <= 18.0:
            solar_factor = math.sin((hours - 6.0) / 12.0 * math.pi)
            total_pv = int(solar_factor * 6800 * (0.95 + 0.05 * math.sin(time.time() / 15.0)))
        else:
            total_pv = 0

        pv1_w = int(total_pv * 0.55)
        pv2_w = total_pv - pv1_w
        base_load = int(650 + 250 * math.sin(time.time() / 60.0))

        if hours >= 14.0 or hours < 6.0:
            batt_soc = max(35, int(98 - ((hours - 14.0) % 24) * 4.5))
        else:
            batt_soc = min(100, int(45 + (hours - 6.0) * 7.0))

        surplus = total_pv - base_load
        if surplus > 0:
            if batt_soc < 100:
                batt_w = min(surplus, 4000)
                grid_w = -(surplus - batt_w) if self._mock_system_mode.get("solar_export_enabled") else 0
            else:
                batt_w = 0
                grid_w = -surplus if self._mock_system_mode.get("solar_export_enabled") else 0
        else:
            batt_w = -min(abs(surplus), 3500)
            deficit_remaining = abs(surplus) - abs(batt_w)
            grid_w = deficit_remaining

        return {
            "timestamp": time.time(),
            "source": "simulation_emulator",
            "solar": {
                "total_watts": total_pv,
                "pv1_watts": pv1_w,
                "pv1_volts": 345.2 if pv1_w > 0 else 0.0,
                "pv1_amps": round(pv1_w / 345.2, 1) if pv1_w > 0 else 0.0,
                "pv2_watts": pv2_w,
                "pv2_volts": 340.8 if pv2_w > 0 else 0.0,
                "pv2_amps": round(pv2_w / 340.8, 1) if pv2_w > 0 else 0.0,
                "daily_kwh": round(24.5 * max(0.1, math.sin(min(1.0, (hours - 5.0) / 13.0) * (math.pi / 2))), 2)
            },
            "battery": {
                "soc_percent": batt_soc,
                "voltage": round(51.2 + (batt_soc / 100.0) * 2.8, 2),
                "current_amps": round(batt_w / 52.0, 1),
                "watts": batt_w,
                "temperature_c": 28.5,
                "daily_charge_kwh": 14.2,
                "daily_discharge_kwh": 8.7
            },
            "grid": {
                "voltage": 231.4,
                "frequency_hz": 50.02,
                "watts": grid_w,
                "daily_import_kwh": 3.4
            },
            "load": {
                "total_watts": base_load,
                "daily_kwh": 16.8
            },
            "inverter": {
                "temperature_c": 36.8 + (total_pv / 8000.0) * 12.0,
                "status": "Simulated Normal"
            }
        }

    async def get_energy_day(self, date_str: str) -> Dict[str, Any]:
        """Fetch 24h real-time telemetry curves (PV, Battery, SOC, Load, Grid)."""
        authed = await self._ensure_authenticated()
        if not authed or not self._cloud_client or not self.plant_id:
            return {"date": date_str, "series": [], "summary": {}}

        color_map = {
            "PV": "#f59e0b",
            "Battery": "#10b981",
            "SOC": "#38bdf8",
            "Load": "#ef4444",
            "Grid": "#8b5cf6"
        }

        try:
            p_day = await self._cloud_client.get_plant_energy_day(self.plant_id, date_str)
            series_list = []
            summary = {}
            for s in (p_day.series or []):
                pts = [[r.time, r.value] for r in (s.records or [])]
                series_list.append({
                    "name": s.label,
                    "label": s.label,
                    "unit": s.unit,
                    "color": color_map.get(s.label, "#38bdf8"),
                    "data": pts
                })
                # Integrate power (W) over 5-minute (1/12 hour) intervals to kWh
                if s.unit == "W" and pts:
                    kwh = round(sum(p[1] for p in pts if p[1] > 0) / 1000.0 / 12.0, 1)
                    if s.label == "PV":
                        summary["pv_daily_kwh"] = kwh
                    elif s.label == "Load":
                        summary["load_daily_kwh"] = kwh
                    elif s.label == "Grid":
                        summary["grid_buy_kwh"] = kwh
                    elif s.label == "Battery":
                        chg_kwh = round(sum(abs(p[1]) for p in pts if p[1] < 0) / 1000.0 / 12.0, 1)
                        dischg_kwh = round(sum(p[1] for p in pts if p[1] > 0) / 1000.0 / 12.0, 1)
                        summary["charge_daily_kwh"] = chg_kwh
                        summary["discharge_daily_kwh"] = dischg_kwh

            return {
                "date": date_str,
                "plant_id": self.plant_id,
                "plant_name": self.plant_name,
                "series": series_list,
                "summary": summary
            }
        except Exception as e:
            logger.error(f"Error fetching plant day energy curve: {e}")
            return {"date": date_str, "series": [], "summary": {}, "error": str(e)}

    async def get_energy_month(self, month_str: str) -> Dict[str, Any]:
        """Fetch monthly daily energy breakdown in kWh."""
        authed = await self._ensure_authenticated()
        if not authed or not self._cloud_client or not self.plant_id:
            return {"month": month_str, "series": [], "summary": {}}

        color_map = {
            "PV Generation": "#f59e0b",
            "Load Power Consumption": "#ef4444",
            "Discharge Energy": "#38bdf8",
            "Charge Energy": "#10b981",
            "Purchased electricity": "#8b5cf6",
            "Sold electricity": "#06b6d4"
        }

        try:
            p_month = await self._cloud_client.get_plant_energy_month(self.plant_id, month_str)
            series_list = []
            summary = {}
            for s in (p_month.series or []):
                pts = [[r.time, r.value] for r in (s.records or [])]
                total_kwh = round(sum(r.value for r in (s.records or [])), 1)
                series_list.append({
                    "name": s.label,
                    "label": s.label,
                    "unit": s.unit,
                    "color": color_map.get(s.label, "#38bdf8"),
                    "data": pts
                })
                if s.label == "PV Generation":
                    summary["pv_monthly_kwh"] = total_kwh
                elif s.label == "Load Power Consumption":
                    summary["load_monthly_kwh"] = total_kwh
                elif s.label == "Discharge Energy":
                    summary["discharge_monthly_kwh"] = total_kwh
                elif s.label == "Charge Energy":
                    summary["charge_monthly_kwh"] = total_kwh
                elif s.label == "Purchased electricity":
                    summary["grid_buy_monthly_kwh"] = total_kwh

            return {
                "month": month_str,
                "plant_id": self.plant_id,
                "plant_name": self.plant_name,
                "series": series_list,
                "summary": summary
            }
        except Exception as e:
            logger.error(f"Error fetching plant month energy breakdown: {e}")
            return {"month": month_str, "series": [], "summary": {}, "error": str(e)}

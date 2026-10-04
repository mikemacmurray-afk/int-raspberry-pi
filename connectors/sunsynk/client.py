"""
High-Level SunSynk 8kW Inverter Client.
Handles live telemetry polling and System Mode reading & parameter updates.
Includes built-in simulation/mock generation for testing without live hardware.
"""

import time
import math
import logging
from typing import Dict, Any, Optional, List
from .solarman_v5 import SolarmanV5
from .registers import (
    to_signed16, decode_time_reg, encode_time_str,
    REG_DAILY_PV_ENERGY, REG_DAILY_BATTERY_CHARGE, REG_DAILY_BATTERY_DISCHARGE,
    REG_DAILY_GRID_IMPORT, REG_DAILY_LOAD_ENERGY,
    REG_PV1_VOLTAGE, REG_PV1_CURRENT, REG_PV2_VOLTAGE, REG_PV2_CURRENT,
    REG_GRID_L1_VOLTAGE, REG_GRID_FREQUENCY, REG_GRID_POWER,
    REG_INVERTER_TEMP, REG_INVERTER_TOTAL_POWER,
    REG_BATTERY_TEMP, REG_BATTERY_VOLTAGE, REG_BATTERY_SOC,
    REG_PV1_POWER, REG_PV2_POWER, REG_BATTERY_POWER, REG_BATTERY_CURRENT,
    REG_BATTERY_LOW_SOC, REG_BATTERY_RESTART_SOC, REG_BATTERY_SHUTDOWN_SOC,
    REG_PRIORITY_LOAD_BATT, REG_WORK_MODE, REG_MAX_SELL_POWER, REG_SOLAR_EXPORT_ENABLE,
    REG_TOU_ENABLE, REG_TOU_TIME_BASE, REG_TOU_POWER_BASE, REG_TOU_SOC_BASE, REG_TOU_GRID_CHARGE_BASE,
    WORK_MODE_MAP, PRIORITY_MAP
)

logger = logging.getLogger("SunSynkClient")

class SunSynkClient:
    def __init__(self, host: str, serial_number: int, port: int = 8899, slave_id: int = 1, timeout: float = 4.0):
        self.host = host
        self.serial_number = serial_number
        self.solarman = SolarmanV5(host, serial_number, port, slave_id, timeout)
        self.is_connected = False
        self.last_read_time = 0.0

        # Cached System Mode settings (used also for mock simulation)
        self._mock_system_mode = {
            "priority": 1,                     # 1 = Load First
            "priority_str": "Load First",
            "work_mode": 2,                     # 2 = Zero Export to CT
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

    async def read_telemetry(self, allow_mock: bool = True) -> Dict[str, Any]:
        """
        Poll SunSynk registers over Wi-Fi.
        Falls back to realistic solar/battery simulation if inverter is unreachable and allow_mock is True.
        """
        # Block 1: Real-time AC and DC measurements (Reg 150 - 192)
        regs_block1 = await self.solarman.read_holding_registers(150, 43)
        # Block 2: PV string voltages and currents (Reg 109 - 113)
        regs_block2 = await self.solarman.read_holding_registers(109, 5) if regs_block1 else None
        # Block 3: Daily totals (Reg 60 - 78)
        regs_block3 = await self.solarman.read_holding_registers(60, 20) if regs_block1 else None

        if regs_block1:
            self.is_connected = True
            self.last_read_time = time.time()
            return self._decode_telemetry(regs_block1, regs_block2, regs_block3)
        
        self.is_connected = False
        if allow_mock:
            return self._generate_mock_telemetry()
        
        raise ConnectionError(f"Unable to reach SunSynk inverter at {self.host}:{self.solarman.port}")

    def _decode_telemetry(self, b1: List[int], b2: Optional[List[int]], b3: Optional[List[int]]) -> Dict[str, Any]:
        """Convert raw holding registers into friendly physics units."""
        # Offsets in b1 (starting from 150):
        grid_v = b1[REG_GRID_L1_VOLTAGE - 150] * 0.1
        grid_freq = b1[REG_GRID_FREQUENCY - 150] * 0.01
        grid_w = to_signed16(b1[REG_GRID_POWER - 150])
        inv_temp = b1[REG_INVERTER_TEMP - 150] * 0.1
        inv_w = b1[REG_INVERTER_TOTAL_POWER - 150]

        batt_temp = b1[REG_BATTERY_TEMP - 150] * 0.1
        batt_v = b1[REG_BATTERY_VOLTAGE - 150] * 0.01
        batt_soc = b1[REG_BATTERY_SOC - 150]
        pv1_w = b1[REG_PV1_POWER - 150]
        pv2_w = b1[REG_PV2_POWER - 150]
        batt_w = to_signed16(b1[REG_BATTERY_POWER - 150])
        batt_current = to_signed16(b1[REG_BATTERY_CURRENT - 150]) * 0.01

        # PV details
        pv1_v = (b2[0] * 0.1) if b2 else 0.0
        pv1_i = (b2[1] * 0.1) if b2 else 0.0
        pv2_v = (b2[2] * 0.1) if b2 else 0.0
        pv2_i = (b2[3] * 0.1) if b2 else 0.0

        # Totals
        daily_pv = (b3[0] * 0.1) if b3 else 0.0
        daily_batt_charge = (b3[10] * 0.1) if b3 and len(b3) > 10 else 0.0
        daily_batt_discharge = (b3[11] * 0.1) if b3 and len(b3) > 11 else 0.0
        daily_grid_import = (b3[12] * 0.1) if b3 and len(b3) > 12 else 0.0
        daily_load = (b3[17] * 0.1) if b3 and len(b3) > 17 else 0.0

        total_pv = pv1_w + pv2_w
        load_w = max(0, inv_w)

        return {
            "timestamp": time.time(),
            "source": "live_hardware",
            "solar": {
                "total_watts": total_pv,
                "pv1_watts": pv1_w,
                "pv1_volts": round(pv1_v, 1),
                "pv1_amps": round(pv1_i, 1),
                "pv2_watts": pv2_w,
                "pv2_volts": round(pv2_v, 1),
                "pv2_amps": round(pv2_i, 1),
                "daily_kwh": round(daily_pv, 2)
            },
            "battery": {
                "soc_percent": batt_soc,
                "voltage": round(batt_v, 2),
                "current_amps": round(batt_current, 2),
                "watts": batt_w,  # Positive = charging, negative = discharging
                "temperature_c": round(batt_temp, 1),
                "daily_charge_kwh": round(daily_batt_charge, 2),
                "daily_discharge_kwh": round(daily_batt_discharge, 2)
            },
            "grid": {
                "voltage": round(grid_v, 1),
                "frequency_hz": round(grid_freq, 2),
                "watts": grid_w,  # Positive = importing, negative = exporting
                "daily_import_kwh": round(daily_grid_import, 2)
            },
            "load": {
                "total_watts": load_w,
                "daily_kwh": round(daily_load, 2)
            },
            "inverter": {
                "temperature_c": round(inv_temp, 1),
                "status": "Normal"
            }
        }

    async def read_system_mode(self, allow_mock: bool = True) -> Dict[str, Any]:
        """
        Read the active SunSynk System Mode configuration:
        Work Mode, TOU Enable, 6 Time Slots (time, power, soc %, grid charge), Battery limits.
        """
        regs = await self.solarman.read_holding_registers(REG_BATTERY_LOW_SOC, 39)
        if regs:
            # 217: Low SOC, 218: Restart SOC, 219: Shutdown SOC
            batt_low = regs[0]
            batt_restart = regs[1]
            batt_shutdown = regs[2]

            # 220: Priority, 221: Work mode, 222: Max sell, 223: Export enable
            priority = regs[3]
            work_mode = regs[4]
            max_sell = regs[5]
            export_en = bool(regs[6])

            # 230: TOU Enable (offset 13)
            tou_en = bool(regs[13])

            # 6 TOU slots
            slots = []
            for i in range(6):
                t_val = regs[15 + i]       # 232..237
                p_val = regs[21 + i]       # 238..243
                soc_val = regs[27 + i]     # 244..249
                gc_val = bool(regs[33 + i]) # 250..255
                slots.append({
                    "slot": i + 1,
                    "time": decode_time_reg(t_val),
                    "power": p_val,
                    "soc": soc_val,
                    "grid_charge": gc_val
                })

            result = {
                "source": "live_hardware",
                "priority": priority,
                "priority_str": PRIORITY_MAP.get(priority, "Unknown"),
                "work_mode": work_mode,
                "work_mode_str": WORK_MODE_MAP.get(work_mode, "Unknown"),
                "max_sell_power": max_sell,
                "solar_export_enabled": export_en,
                "tou_enabled": tou_en,
                "battery_low_soc": batt_low,
                "battery_restart_soc": batt_restart,
                "battery_shutdown_soc": batt_shutdown,
                "tou_slots": slots
            }
            self._mock_system_mode = result
            return result

        if allow_mock:
            return self._mock_system_mode

        raise ConnectionError("Unable to read SunSynk System Mode settings from inverter")

    async def update_system_mode(self, settings: Dict[str, Any], allow_mock: bool = True) -> bool:
        """Write modified System Mode parameters to the inverter."""
        success = True

        # Update Work Mode if provided
        if "work_mode" in settings:
            wm = int(settings["work_mode"])
            ok = await self.solarman.write_single_register(REG_WORK_MODE, wm)
            success = success and ok

        if "priority" in settings:
            pri = int(settings["priority"])
            ok = await self.solarman.write_single_register(REG_PRIORITY_LOAD_BATT, pri)
            success = success and ok

        if "tou_enabled" in settings:
            en = 1 if settings["tou_enabled"] else 0
            ok = await self.solarman.write_single_register(REG_TOU_ENABLE, en)
            success = success and ok

        if "battery_low_soc" in settings:
            ok = await self.solarman.write_single_register(REG_BATTERY_LOW_SOC, int(settings["battery_low_soc"]))
            success = success and ok

        if "battery_restart_soc" in settings:
            ok = await self.solarman.write_single_register(REG_BATTERY_RESTART_SOC, int(settings["battery_restart_soc"]))
            success = success and ok

        if "battery_shutdown_soc" in settings:
            ok = await self.solarman.write_single_register(REG_BATTERY_SHUTDOWN_SOC, int(settings["battery_shutdown_soc"]))
            success = success and ok

        # Update TOU Slots if provided
        if "tou_slots" in settings:
            for s in settings["tou_slots"]:
                idx = s["slot"] - 1
                if 0 <= idx < 6:
                    if "time" in s:
                        await self.solarman.write_single_register(REG_TOU_TIME_BASE + idx, encode_time_str(s["time"]))
                    if "power" in s:
                        await self.solarman.write_single_register(REG_TOU_POWER_BASE + idx, int(s["power"]))
                    if "soc" in s:
                        await self.solarman.write_single_register(REG_TOU_SOC_BASE + idx, int(s["soc"]))
                    if "grid_charge" in s:
                        gc = 1 if s["grid_charge"] else 0
                        await self.solarman.write_single_register(REG_TOU_GRID_CHARGE_BASE + idx, gc)

        # Update cached settings
        for k, v in settings.items():
            self._mock_system_mode[k] = v

        if not success and allow_mock:
            logger.info("Live write failed; updated mock system mode state for simulation.")
            return True

        return success

    def _generate_mock_telemetry(self) -> Dict[str, Any]:
        """Generate high-fidelity solar simulation based on current time of day."""
        now = time.localtime()
        hours = now.tm_hour + (now.tm_min / 60.0)

        # Solar curve: 06:00 to 18:00 peaking at 12:30 (up to 6800 Watts for 8kW inverter)
        if 6.0 <= hours <= 18.0:
            solar_factor = math.sin((hours - 6.0) / 12.0 * math.pi)
            total_pv = int(solar_factor * 6800 * (0.95 + 0.05 * math.sin(time.time() / 15.0)))
        else:
            total_pv = 0

        pv1_w = int(total_pv * 0.55)
        pv2_w = total_pv - pv1_w

        # Simulated base house load (450W - 1200W fluctuating)
        base_load = int(650 + 250 * math.sin(time.time() / 60.0))

        # Battery SOC fluctuates based on solar surplus or deficit
        # High at midday, discharges in the evening
        if hours >= 14.0 or hours < 6.0:
            batt_soc = max(35, int(98 - ((hours - 14.0) % 24) * 4.5))
        else:
            batt_soc = min(100, int(45 + (hours - 6.0) * 7.0))

        # Power flow balance
        surplus = total_pv - base_load
        if surplus > 0:
            if batt_soc < 100:
                batt_w = min(surplus, 4000)  # Charging battery
                grid_w = -(surplus - batt_w) if self._mock_system_mode.get("solar_export_enabled") else 0
            else:
                batt_w = 0
                grid_w = -surplus if self._mock_system_mode.get("solar_export_enabled") else 0
        else:
            # Deficit: battery discharges to support load
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

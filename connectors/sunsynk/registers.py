"""
SunSynk 8kW Modbus Register Map Definitions & Decoding Helpers.
Supports both telemetry reading and System Mode reading & control.
"""

from typing import Dict, Any, List

def to_signed16(val: int) -> int:
    """Convert unsigned 16-bit int to signed 16-bit int (Two's Complement)."""
    return val - 0x10000 if val > 0x7FFF else val

def decode_time_reg(val: int) -> str:
    """Decode time register into HH:MM string."""
    # Format is either (hour * 100) + minute or high_byte:low_byte
    high = (val >> 8) & 0xFF
    low = val & 0xFF
    if high < 24 and low < 60:
        return f"{high:02d}:{low:02d}"
    hours = val // 100
    minutes = val % 100
    return f"{hours:02d}:{minutes:02d}"

def encode_time_str(time_str: str) -> int:
    """Encode HH:MM string into Sunsynk time register format."""
    try:
        parts = time_str.split(":")
        h = int(parts[0])
        m = int(parts[1])
        # Sunsynk standard register format: (hour * 100) + minute
        return (h * 100) + m
    except Exception:
        return 0

# Core Telemetry Register Addresses
REG_DAILY_PV_ENERGY = 60          # 0.1 kWh
REG_DAILY_BATTERY_CHARGE = 70     # 0.1 kWh
REG_DAILY_BATTERY_DISCHARGE = 71  # 0.1 kWh
REG_DAILY_GRID_IMPORT = 72        # 0.1 kWh
REG_DAILY_GRID_EXPORT = 74        # 0.1 kWh
REG_DAILY_LOAD_ENERGY = 77        # 0.1 kWh

REG_PV1_VOLTAGE = 109             # 0.1 V
REG_PV1_CURRENT = 110             # 0.1 A
REG_PV2_VOLTAGE = 111             # 0.1 V
REG_PV2_CURRENT = 112             # 0.1 A

REG_GRID_L1_VOLTAGE = 150         # 0.1 V
REG_GRID_FREQUENCY = 151          # 0.01 Hz
REG_INVERTER_L1_VOLTAGE = 154     # 0.1 V
REG_GRID_CURRENT = 160            # 0.01 A
REG_GRID_POWER = 169              # 1 W (Signed: positive = import, negative = export)

REG_INVERTER_TEMP = 175           # 0.1 C (offset -100C or direct depending on firmware)
REG_DCDC_TEMP = 176               # 0.1 C
REG_INVERTER_TOTAL_POWER = 178    # 1 W (essential + non-essential load)

REG_BATTERY_TEMP = 182            # 0.1 C (or direct C)
REG_BATTERY_VOLTAGE = 183         # 0.01 V
REG_BATTERY_SOC = 184             # 1 %
REG_PV1_POWER = 186               # 1 W
REG_PV2_POWER = 187               # 1 W
REG_BATTERY_POWER = 190           # 1 W (Signed: positive = charge, negative = discharge)
REG_BATTERY_CURRENT = 191         # 0.01 A (Signed)

# System Mode Registers (Reading & Control)
REG_BATTERY_LOW_SOC = 217         # 1 % (Low battery alarm / fallback)
REG_BATTERY_RESTART_SOC = 218     # 1 % (Restart after shutdown)
REG_BATTERY_SHUTDOWN_SOC = 219    # 1 % (Inverter cuts off to preserve battery)

REG_PRIORITY_LOAD_BATT = 220      # 0 = Battery First, 1 = Load First
REG_WORK_MODE = 221               # 0 = Selling First, 1 = Zero Export to Load, 2 = Zero Export to CT
REG_MAX_SELL_POWER = 222          # Watts
REG_SOLAR_EXPORT_ENABLE = 223     # 0 = Off, 1 = On

REG_TOU_ENABLE = 230              # Time Of Use Master Enable: 0 = Disabled, 1 = Enabled

# Time of Use 6 Slots:
# 232..237 : Slot 1..6 Time
# 238..243 : Slot 1..6 Max Power (Watts)
# 244..249 : Slot 1..6 Target SOC %
# 250..255 : Slot 1..6 Grid Charge Toggle (0 = Off, 1 = On)
REG_TOU_TIME_BASE = 232
REG_TOU_POWER_BASE = 238
REG_TOU_SOC_BASE = 244
REG_TOU_GRID_CHARGE_BASE = 250

WORK_MODE_MAP = {
    0: "Selling First",
    1: "Zero Export to Load",
    2: "Zero Export to CT"
}

PRIORITY_MAP = {
    0: "Battery First",
    1: "Load First"
}

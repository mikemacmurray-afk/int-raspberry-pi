# Project Handover: SunSynk 8kW & Sonoff Home Energy Conductor

**Repository**: [mikemacmurray-afk/int-raspberry-pi](https://github.com/mikemacmurray-afk/int-raspberry-pi)  
**Date**: October 4, 2026  
**Target Hardware**: Raspberry Pi 5 (Edge Gateway)  
**Development/Emulation Platform**: Windows Laptop / Localhost  

---

## 1. Executive Summary & Objective

The objective of this project is to build an automated **Home Energy Management & Load Orchestration System** running on a **Raspberry Pi 5**, with initial development, emulation, and live testing performed directly from a **Windows laptop**.

The system interfaces with three main hardware systems entirely over **local Wi-Fi (LAN)** without relying on external cloud connections:
1. **SunSynk 8kW Hybrid Solar Inverter**: Real-time telemetry monitoring (PV, Battery, Grid, Load) and bidirectional **System Mode parameter control** (Work Modes, Time-of-Use 6-slot matrix, Battery safety thresholds).
2. **Sonoff Smart Geyser Controller**: Real-time water temperature probe reading, power measurement (W/V/A), thermostat setpoints, and power switching.
3. **Two DB Smart Switches**: Dedicated relay control for the **Pool Pump** and **Geyser Backup / Secondary Isolation**.

---

## 2. Key Architecture & Design Decisions

### A. All-Wi-Fi Architecture (No Physical RS485/Serial Cables)
* **SunSynk 8kW Communication**: Uses the **Solarman V5 protocol** over local UDP/TCP port `8899` to communicate directly with the SunSynk Wi-Fi data logger. Modbus RTU frames are encapsulated in Solarman V5 packets, allowing full register reading and writing without cloud latency.
* **Sonoff Communication**: Uses the local **eWeLink LAN protocol** over HTTP port `8081` (`/zeroconf/info` and `/zeroconf/switch`). If home internet drops, local automation and geyser management continue uninterrupted.
* **Contactor Safety**: Heavy inductive loads (pool pump motor inrush) and high resistive continuous loads (3kW geyser element) should ideally be switched via industrial DIN rail contactors triggered by the smart switches to prevent relay contact welding.

### B. Dual-Mode "Pi Harness" (Laptop Emulator + Pi 5 Host)
Because communication uses standard TCP/IP Wi-Fi sockets, the Python codebase is platform-agnostic:
* Running on **Windows Laptop**: Acts as the development station and laptop emulator. If the physical devices are unreachable or offsite, the system automatically falls back to realistic simulation curves (solar generation curve, battery charge/discharge, geyser temperature rise).
* Running on **Raspberry Pi 5**: Runs the exact same codebase as a persistent 24/7 Linux system service.

---

## 3. Codebase File Structure

```
d:/Work/Agents/int-raspberry-pi/
├── .gitignore                      # Git ignore rules for Python, DB, and IDE files
├── README.md                       # High-level project documentation & quickstart
├── HANDOVER.md                     # This complete handover document
├── requirements.txt                # Python dependencies (FastAPI, uvicorn, pydantic, pyyaml, etc.)
├── main.py                         # Application entry point; boots engine & web dashboard
│
├── config/
│   ├── config.yaml                 # Device IPs, ports, logger serial number, and setpoints
│   └── settings.py                 # Pydantic configuration loader & schema models
│
├── connectors/
│   ├── sunsynk/
│   │   ├── registers.py            # SunSynk 8kW Modbus register map & Two's Complement decoders
│   │   ├── solarman_v5.py          # Solarman V5 frame encoder/decoder & TCP/UDP transport
│   │   └── client.py               # High-level client (telemetry polling, System Mode read/write, mock generator)
│   └── sonoff/
│       ├── ewelink_lan.py          # Local eWeLink LAN client (temperature, power, on/off control)
│       └── client.py               # Sonoff Fleet manager (Geyser, Pool Pump, Geyser Backup)
│
├── core/
│   ├── database.py                 # SQLite time-series logger (data/energy_history.db) & audit logs
│   └── engine.py                   # Central background polling loop & hardware platform diagnostics
│
├── web/
│   ├── server.py                   # FastAPI REST API & WebSocket endpoints
│   └── static/
│       └── index.html              # Glassmorphic dark-mode web dashboard with Chart.js
│
└── tools/
    ├── scan_network.py             # Wi-Fi subnet discovery tool for ports 8899 and 8081
    ├── probe_sunsynk.py            # Standalone CLI tool to probe SunSynk inverter registers
    └── probe_sonoff.py             # Standalone CLI tool to probe Sonoff switches & temp probe
```

---

## 4. How to Run and Test

### 1. Launch the Web Dashboard
```powershell
python main.py
```
Open your browser at: **`http://localhost:8000`**

### 2. Discover Device IPs on Home Wi-Fi
If device IPs are not yet known from the Wi-Fi router's DHCP table:
```powershell
python tools/scan_network.py
```
* Identifies SunSynk Logger at Port **8899**
* Identifies Sonoff LAN switches at Port **8081**

### 3. Test Connecting Directly to Devices
**Probe SunSynk Inverter:**
```powershell
python tools/probe_sunsynk.py --host <INVERTER_IP> --serial <LOGGER_SERIAL_NUMBER>
```
*Verifies Solar PV Watts, Battery %, Grid flow, and prints active 6-slot Time of Use table.*

**Probe Sonoff Geyser Controller:**
```powershell
python tools/probe_sonoff.py --host <SONOFF_IP>
```
*Verifies LAN communication, switch state, and water temperature.*

---

## 5. Next Steps & Roadmap for Successor

1. **Configure Real Device Credentials in [`config/config.yaml`](file:///d:/Work/Agents/int-raspberry-pi/config/config.yaml)**:
   * Input the SunSynk Wi-Fi Logger Serial Number (10- or 12-digit number on barcode).
   * Input the assigned local IP addresses for the SunSynk logger and Sonoff devices.
2. **Define Automation Logic (The Orchestrator)**:
   * **Solar Surplus Diversion**: When Solar generation exceeds load by > 2.5 kW and Battery SOC > 80%, auto-trigger Geyser and Pool Pump.
   * **Load Shedding / Battery Defense**: If grid drops and battery discharge exceeds 3 kW, immediately shed pool pump and geyser.
   * **Morning Comfort Guarantee**: If geyser water temperature < 50°C by 05:30, run heating cycle until 06:15.
3. **Deploy to Raspberry Pi 5**:
   * Flash Raspberry Pi OS (64-bit) onto Pi 5 NVMe / SSD.
   * Clone the repository, run `pip install -r requirements.txt`.
   * Configure `systemd` service to auto-start `main.py` on boot.

# SunSynk 8kW & Sonoff Home Energy Conductor

A lightweight, high-performance home energy management and automation system designed for **Raspberry Pi 5** and **Laptop Emulation / Development**.

Connects directly over **Wi-Fi** to:
1. **SunSynk 8kW Hybrid Inverter**: Real-time telemetry monitoring + **System Mode parameter control** (Work Mode, TOU 6-slot matrix, Battery Shutdown/Restart/Low cutoffs) via Solarman V5 Modbus TCP/UDP.
2. **Sonoff Geyser Controller**: Live water temperature monitoring (with probe), power monitoring, and thermostat target control.
3. **2x DB Smart Switches**: Pool Pump relay and secondary Geyser Backup / isolation switch.

---

## Architecture

```
                       ┌─────────────────────────────────┐
                       │  Home Wi-Fi Network (LAN)       │
                       └────────────────┬────────────────┘
                ┌───────────────────────┼───────────────────────┐
                │                       │                       │
                ▼                       ▼                       ▼
      ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
      │  Laptop / Pi 5   │    │  SunSynk 8kW     │    │  3x Sonoff Units │
      │  - FastAPI Web   │    │  Wi-Fi Stick     │    │  - Geyser & Temp │
      │  - DB History    │    │  (Port 8899)     │    │  - Pool Pump     │
      │  - Mode Controls │    │  Solarman V5     │    │  - Geyser Backup │
      └──────────────────┘    └──────────────────┘    └──────────────────┘
```

Because communication uses IP-based Wi-Fi networking, the **exact same code runs on your Windows Laptop or directly on the Raspberry Pi 5**.

---

## Quick Start on Your Laptop

### 1. Run the Dashboard
```bash
python main.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

> **Note on "Auto" Mode**: When the system starts, it attempts to communicate with the real hardware IPs configured in `config/config.yaml`. If devices are offline or not yet configured, it seamlessly falls back to realistic simulation so you can explore the dashboard, test SunSynk parameter modifications, and toggle switches immediately.

---

## Diagnostics & Tools

### 1. Discover Devices on your Home Wi-Fi
If you don't know the exact IP addresses assigned to your devices by your router:
```bash
python tools/scan_network.py
```
This scans your local subnet for open ports:
* **Port 8899**: SunSynk / Solarman Wi-Fi Data Logger
* **Port 8081**: Sonoff eWeLink LAN

### 2. Probe SunSynk Inverter
Test reading live Modbus registers directly from your inverter dongle:
```bash
python tools/probe_sunsynk.py --host 192.168.1.60 --serial 2300000000
```

### 3. Probe Sonoff Geyser / DB Switch
Test LAN control and read live water temperature:
```bash
python tools/probe_sonoff.py --host 192.168.1.70
```

---

## Configuration (`config/config.yaml`)

Edit `config/config.yaml` to set your actual device IPs:

```yaml
system:
  mode: "auto"              # "auto" (tries real, falls back to mock), "real", or "mock"
  poll_interval_sec: 3
  db_path: "data/energy_history.db"

sunsynk:
  enabled: true
  host: "192.168.1.60"       # IP of your SunSynk Wi-Fi stick
  port: 8899
  serial_number: 2300000000  # Barcode number on the Wi-Fi stick
  slave_id: 1

sonoff_geyser:
  enabled: true
  host: "192.168.1.70"
  has_temp_sensor: true
  target_temp_c: 55.0

sonoff_pool_pump:
  enabled: true
  host: "192.168.1.71"
  rated_watts: 1100

sonoff_geyser_backup:
  enabled: true
  host: "192.168.1.72"
  rated_watts: 3000
```

---

## Deploying to Raspberry Pi 5 Later

1. Clone this repository onto your Raspberry Pi 5:
   ```bash
   git clone https://github.com/mikemacmurray-afk/int-raspberry-pi.git
   cd int-raspberry-pi
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run or enable as a systemd service:
   ```bash
   python main.py
   ```

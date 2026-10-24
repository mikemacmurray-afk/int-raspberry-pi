import os
import yaml
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional

CONFIG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFIG_DIR.parent
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.yaml"

class SunsynkConfig(BaseModel):
    enabled: bool = True
    connection_type: str = "cloud"  # "cloud" (Sunsynk Connect API) or "solarman" (Port 8899)
    # Cloud API settings
    username: str = ""
    password: str = ""
    inverter_sn: str = ""
    base_url: Optional[str] = None
    # Solarman Wi-Fi settings (legacy / local port 8899)
    host: str = "192.168.3.4"
    port: int = 8899
    protocol: str = "tcp"
    serial_number: int = 2300000000
    slave_id: int = 1
    timeout_sec: float = 4.0

class EwelinkConfig(BaseModel):
    username: str = ""
    password: str = ""
    region: str = "eu"

class SonoffDeviceConfig(BaseModel):
    driver: str = "sonoff"  # "sonoff" or "tuya"
    enabled: bool = True
    name: str = "Sonoff Device"
    host: str = "127.0.0.1"
    port: int = 8081
    device_id: str = ""
    api_key: str = ""
    local_key: str = ""
    version: float = 3.4
    has_temp_sensor: bool = False
    target_temp_c: float = 55.0
    max_cutoff_temp_c: float = 65.0
    min_temp_c: float = 45.0
    rated_watts: float = 0.0
    ewelink_username: str = ""
    ewelink_password: str = ""
    ewelink_region: str = "eu"

class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000

class RainPointConfig(BaseModel):
    enabled: bool = True
    email: str = "mikem@investiture.co.za"
    password: str = "M4n4g3r$"
    area_code: str = "27"
    app_code: str = "2"
    base_url: str = "https://region3.homgarus.com"

class SystemConfig(BaseModel):
    mode: str = "auto"  # "auto", "real", "mock"
    poll_interval_sec: float = 3.0
    db_path: str = "data/energy_history.db"

class FamilyRelayConfig(BaseModel):
    enabled: bool = True
    url: str = "https://learnai.betterfreelife.com/family-relay"
    secret: str = "cranleigh_family_relay_2026"
    local_actor: str = "grandparents"
    sync_interval_sec: int = 15

class AppConfig(BaseModel):
    system: SystemConfig = Field(default_factory=SystemConfig)
    sunsynk: SunsynkConfig = Field(default_factory=SunsynkConfig)
    ewelink: EwelinkConfig = Field(default_factory=EwelinkConfig)
    sonoff_geyser: SonoffDeviceConfig = Field(default_factory=lambda: SonoffDeviceConfig(name="Main Geyser", has_temp_sensor=True, rated_watts=3000))
    sonoff_pool_pump: SonoffDeviceConfig = Field(default_factory=lambda: SonoffDeviceConfig(name="Pool Pump", rated_watts=1100))
    sonoff_geyser_backup: SonoffDeviceConfig = Field(default_factory=lambda: SonoffDeviceConfig(name="Geyser Backup DB Switch", rated_watts=3000))
    rainpoint: RainPointConfig = Field(default_factory=RainPointConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    family_relay: FamilyRelayConfig = Field(default_factory=FamilyRelayConfig)

def load_config(path: Optional[str] = None) -> AppConfig:
    config_file = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_file.exists():
        return AppConfig()
    
    with open(config_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return AppConfig(**data)

def save_config(config: AppConfig, path: Optional[str] = None):
    config_file = Path(path) if path else DEFAULT_CONFIG_PATH
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)

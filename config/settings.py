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
    host: str = "192.168.1.60"
    port: int = 8899
    protocol: str = "tcp"
    serial_number: int = 2300000000
    slave_id: int = 1
    timeout_sec: float = 4.0

class SonoffDeviceConfig(BaseModel):
    enabled: bool = True
    name: str = "Sonoff Device"
    host: str = "127.0.0.1"
    port: int = 8081
    device_id: str = ""
    api_key: str = ""
    has_temp_sensor: bool = False
    target_temp_c: float = 55.0
    max_cutoff_temp_c: float = 65.0
    min_temp_c: float = 45.0
    rated_watts: float = 0.0

class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000

class SystemConfig(BaseModel):
    mode: str = "auto"  # "auto", "real", "mock"
    poll_interval_sec: float = 3.0
    db_path: str = "data/energy_history.db"

class AppConfig(BaseModel):
    system: SystemConfig = Field(default_factory=SystemConfig)
    sunsynk: SunsynkConfig = Field(default_factory=SunsynkConfig)
    sonoff_geyser: SonoffDeviceConfig = Field(default_factory=lambda: SonoffDeviceConfig(name="Main Geyser", has_temp_sensor=True, rated_watts=3000))
    sonoff_pool_pump: SonoffDeviceConfig = Field(default_factory=lambda: SonoffDeviceConfig(name="Pool Pump", rated_watts=1100))
    sonoff_geyser_backup: SonoffDeviceConfig = Field(default_factory=lambda: SonoffDeviceConfig(name="Geyser Backup DB Switch", rated_watts=3000))
    web: WebConfig = Field(default_factory=WebConfig)

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

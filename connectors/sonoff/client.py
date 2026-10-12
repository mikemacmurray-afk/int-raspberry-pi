"""
High-Level Sonoff Fleet Manager.
Coordinates the Geyser Controller and the 2 DB Switches (Pool Pump & Geyser Backup).
"""

import asyncio
from typing import Dict, Any, Optional
from config.settings import AppConfig
from .ewelink_lan import SonoffDevice, EwelinkCloudV2

class SonoffFleet:
    def __init__(self, config: AppConfig):
        cfg = config

        # Setup Cloud Client if credentials present
        ewelink_user = cfg.ewelink.username or cfg.sonoff_geyser.ewelink_username
        ewelink_pw = cfg.ewelink.password or cfg.sonoff_geyser.ewelink_password
        ewelink_reg = cfg.ewelink.region or cfg.sonoff_geyser.ewelink_region or "eu"

        self.cloud_client: Optional[EwelinkCloudV2] = None
        if ewelink_user and ewelink_pw:
            self.cloud_client = EwelinkCloudV2(username=ewelink_user, password=ewelink_pw, region=ewelink_reg)

        self.geyser = SonoffDevice(
            name=cfg.sonoff_geyser.name,
            host=cfg.sonoff_geyser.host,
            port=cfg.sonoff_geyser.port,
            device_id=cfg.sonoff_geyser.device_id,
            api_key=cfg.sonoff_geyser.api_key,
            has_temp_sensor=cfg.sonoff_geyser.has_temp_sensor,
            rated_watts=cfg.sonoff_geyser.rated_watts,
            cloud_client=self.cloud_client
        )
        self.geyser.target_temp_c = cfg.sonoff_geyser.target_temp_c

        if getattr(cfg.sonoff_pool_pump, "driver", "sonoff") == "tuya":
            from connectors.tuya.device import TuyaDbSwitch
            self.pool_pump = TuyaDbSwitch(
                name=cfg.sonoff_pool_pump.name,
                device_id=cfg.sonoff_pool_pump.device_id,
                host=cfg.sonoff_pool_pump.host,
                local_key=getattr(cfg.sonoff_pool_pump, "local_key", ""),
                version=getattr(cfg.sonoff_pool_pump, "version", 3.4),
                rated_watts=cfg.sonoff_pool_pump.rated_watts
            )
        else:
            self.pool_pump = SonoffDevice(
                name=cfg.sonoff_pool_pump.name,
                host=cfg.sonoff_pool_pump.host,
                port=cfg.sonoff_pool_pump.port,
                device_id=cfg.sonoff_pool_pump.device_id,
                api_key=cfg.sonoff_pool_pump.api_key,
                has_temp_sensor=False,
                rated_watts=cfg.sonoff_pool_pump.rated_watts,
                cloud_client=self.cloud_client
            )

        if getattr(cfg.sonoff_geyser_backup, "driver", "sonoff") == "tuya":
            from connectors.tuya.device import TuyaDbSwitch
            self.geyser_backup = TuyaDbSwitch(
                name=cfg.sonoff_geyser_backup.name,
                device_id=cfg.sonoff_geyser_backup.device_id,
                host=cfg.sonoff_geyser_backup.host,
                local_key=getattr(cfg.sonoff_geyser_backup, "local_key", ""),
                version=getattr(cfg.sonoff_geyser_backup, "version", 3.4),
                rated_watts=cfg.sonoff_geyser_backup.rated_watts
            )
        else:
            self.geyser_backup = SonoffDevice(
                name=cfg.sonoff_geyser_backup.name,
                host=cfg.sonoff_geyser_backup.host,
                port=cfg.sonoff_geyser_backup.port,
                device_id=cfg.sonoff_geyser_backup.device_id,
                api_key=cfg.sonoff_geyser_backup.api_key,
                has_temp_sensor=False,
                rated_watts=cfg.sonoff_geyser_backup.rated_watts,
                cloud_client=self.cloud_client
            )

    async def poll_all(self, allow_mock: bool = True) -> Dict[str, Any]:
        """Poll all Sonoff devices concurrently."""
        g_data, p_data, b_data = await asyncio.gather(
            self.geyser.poll(allow_mock=allow_mock),
            self.pool_pump.poll(allow_mock=allow_mock),
            self.geyser_backup.poll(allow_mock=allow_mock),
            return_exceptions=True
        )

        return {
            "geyser": g_data if isinstance(g_data, dict) else self.geyser.to_dict(is_mock=True),
            "pool_pump": p_data if isinstance(p_data, dict) else self.pool_pump.to_dict(is_mock=True),
            "geyser_backup": b_data if isinstance(b_data, dict) else self.geyser_backup.to_dict(is_mock=True)
        }

    async def set_device_switch(self, device_key: str, state: str) -> bool:
        """Set switch state ('on' or 'off') for a given device key."""
        target = None
        if device_key == "geyser":
            target = self.geyser
        elif device_key == "pool_pump":
            target = self.pool_pump
        elif device_key == "geyser_backup":
            target = self.geyser_backup
        
        if not target:
            raise KeyError(f"Unknown device key: {device_key}")

        return await target.set_switch(state)

    def set_geyser_target_temp(self, temp_c: float):
        """Update the target temperature for the geyser."""
        self.geyser.target_temp_c = float(temp_c)

    async def get_geyser_auto_control(self) -> Dict[str, Any]:
        """Fetch geyser auto control rules and status."""
        return await self.geyser.get_auto_control()

    async def update_geyser_auto_control(self, rules: list, enabled: int = 1) -> bool:
        """Update geyser auto control rules and status on eWeLink."""
        return await self.geyser.update_auto_control(rules, enabled)

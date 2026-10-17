"""
Apps Manager for Raspberry Pi 5 Desktop.
Manages installed applications, GitHub repository cloning, static hosting,
and microservice processes.
"""

import os
import sys
import json
import asyncio
import logging
import shutil
import time
import socket
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("AppsManager")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
APPS_DIR = BASE_DIR / "apps"
APPS_CONFIG_PATH = DATA_DIR / "apps.json"

DEFAULT_APPS = [
    {
        "id": "energy",
        "name": "Home Energy & SunSynk",
        "icon": "⚡",
        "category": "Energy",
        "type": "internal",
        "url": "/energy",
        "description": "Live SunSynk 8kW inverter telemetry, battery SOC, grid routing, and TOU settings.",
        "default_maximized": True,
        "is_system": True,
        "width": 1100,
        "height": 650
    },
    {
        "id": "pool",
        "name": "Pool Automation",
        "icon": "🏊",
        "category": "Outdoor",
        "type": "internal",
        "url": "/energy#pool",
        "description": "RainPoint wireless pool thermometer and 1100W pump contactor control.",
        "default_maximized": False,
        "is_system": True,
        "width": 850,
        "height": 550
    },
    {
        "id": "geyser",
        "name": "Geyser Thermi",
        "icon": "♨️",
        "category": "Climate",
        "type": "internal",
        "url": "/energy#geyser",
        "description": "Sonoff TH Elite water temperature probe and automated heating windows.",
        "default_maximized": False,
        "is_system": True,
        "width": 850,
        "height": 550
    },
    {
        "id": "github_hub",
        "name": "GitHub App Hub",
        "icon": "🐙",
        "category": "System",
        "type": "internal",
        "url": "/apps/hub",
        "description": "Clone, install, and manage applications and microservices from GitHub.",
        "default_maximized": False,
        "is_system": True,
        "width": 960,
        "height": 620
    },
    {
        "id": "system_diag",
        "name": "CrPi5 Diagnostics",
        "icon": "🖥️",
        "category": "System",
        "type": "internal",
        "url": "/apps/system",
        "description": "Pi 5 quad-core metrics, thermal monitoring, touchscreen, and service logs.",
        "default_maximized": False,
        "is_system": True,
        "width": 880,
        "height": 580
    }
]

class AppsManager:
    def __init__(self):
        self.apps_file = APPS_CONFIG_PATH
        self.apps_dir = APPS_DIR
        self.apps: List[Dict[str, Any]] = []
        self.running_processes: Dict[str, asyncio.subprocess.Process] = {}
        self._ensure_dirs()
        self.load_apps()

    def _ensure_dirs(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.apps_dir.mkdir(parents=True, exist_ok=True)

    def load_apps(self):
        if self.apps_file.exists():
            try:
                with open(self.apps_file, "r", encoding="utf-8") as f:
                    self.apps = json.load(f)
            except Exception as e:
                logger.error(f"Error loading apps.json: {e}")
                self.apps = list(DEFAULT_APPS)
                self.save_apps()
        else:
            self.apps = list(DEFAULT_APPS)
            self.save_apps()

        # Ensure all default system apps exist
        existing_ids = {a["id"] for a in self.apps}
        modified = False
        for def_app in DEFAULT_APPS:
            if def_app["id"] not in existing_ids:
                self.apps.append(def_app)
        # Auto-discover any apps created or cloned into apps/
        if self.scan_local_apps():
            modified = True

        if modified:
            self.save_apps()

    def scan_local_apps(self) -> bool:
        """
        Scans the apps/ directory for any local application folders.
        If a folder has manifest.json or index.html, it auto-registers it.
        """
        modified = False
        existing_ids = {a["id"] for a in self.apps}
        if not self.apps_dir.exists():
            return False

        for item in self.apps_dir.iterdir():
            if not item.is_dir():
                continue
            folder_name = item.name
            manifest_file = item / "manifest.json"
            index_file = item / "index.html"

            if manifest_file.exists():
                try:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    app_id = meta.get("id") or folder_name.lower().replace("-", "_")
                    if app_id not in existing_ids:
                        meta.setdefault("id", app_id)
                        meta.setdefault("name", folder_name.replace("-", " ").replace("_", " ").title())
                        meta.setdefault("icon", "📦")
                        meta.setdefault("type", "static")
                        meta.setdefault("url", f"/apps/hosted/{folder_name}/index.html")
                        meta.setdefault("is_system", False)
                        self.apps.append(meta)
                        existing_ids.add(app_id)
                        modified = True
                except Exception as e:
                    logger.warning(f"Failed to read manifest in {item}: {e}")
            elif index_file.exists():
                app_id = folder_name.lower().replace("-", "_")
                if app_id not in existing_ids:
                    app_meta = {
                        "id": app_id,
                        "name": folder_name.replace("-", " ").replace("_", " ").title(),
                        "icon": "📦",
                        "category": "Local",
                        "type": "static",
                        "url": f"/apps/hosted/{folder_name}/index.html",
                        "description": f"Local application in apps/{folder_name}",
                        "default_maximized": False,
                        "is_system": False,
                        "width": 960,
                        "height": 600
                    }
                    self.apps.append(app_meta)
                    existing_ids.add(app_id)
                    modified = True

        return modified

    def save_apps(self):
        try:
            with open(self.apps_file, "w", encoding="utf-8") as f:
                json.dump(self.apps, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving apps.json: {e}")

    def get_apps(self) -> List[Dict[str, Any]]:
        # Decorate with process running state
        result = []
        for app in self.apps:
            app_copy = dict(app)
            app_id = app.get("id")
            proc = self.running_processes.get(app_id)
            app_copy["is_running"] = proc is not None and proc.returncode is None
            result.append(app_copy)
        return result

    def get_app(self, app_id: str) -> Optional[Dict[str, Any]]:
        for app in self.apps:
            if app.get("id") == app_id:
                return app
        return None

    def register_app(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        app_id = app_data.get("id")
        if not app_id:
            import re
            base = re.sub(r'[^a-zA-Z0-9_-]', '_', app_data.get("name", "app").lower())
            app_id = f"{base}_{int(time.time())}"
            app_data["id"] = app_id

        # Update if exists or append
        existing = False
        for i, app in enumerate(self.apps):
            if app.get("id") == app_id:
                self.apps[i] = app_data
                existing = True
                break
        if not existing:
            self.apps.append(app_data)

        self.save_apps()
        return app_data

    async def clone_github_repo(
        self,
        repo_url: str,
        name: Optional[str] = None,
        icon: Optional[str] = "📦",
        category: Optional[str] = "Custom",
        port: Optional[int] = None,
        start_cmd: Optional[str] = None,
        app_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Clones a GitHub repository into apps/<repo_slug>, inspects it,
        and registers it as a desktop application.
        """
        repo_url = repo_url.strip()
        slug = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        app_name = name.strip() if name and name.strip() else slug.replace("-", " ").title()
        app_id = slug.lower().replace("-", "_")

        target_dir = self.apps_dir / slug

        # Check if already cloned
        if target_dir.exists():
            # Update via git pull
            proc = await asyncio.create_subprocess_exec(
                "git", "pull",
                cwd=str(target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"Git pull warning: {stderr.decode()}")
        else:
            # Clone repo shallow
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", repo_url, str(target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"Git clone failed: {stderr.decode()}")

        # Auto-detect app type if not provided
        detected_type = app_type
        detected_url = ""

        index_file = target_dir / "index.html"
        pkg_file = target_dir / "package.json"
        req_file = target_dir / "requirements.txt"

        if port:
            detected_type = "port"
            detected_url = f"http://localhost:{port}"
        elif index_file.exists():
            detected_type = "static"
            detected_url = f"/apps/hosted/{slug}/index.html"
        elif pkg_file.exists() or req_file.exists():
            detected_type = "service"
            detected_url = f"/apps/hosted/{slug}"
        else:
            detected_type = "static"
            detected_url = f"/apps/hosted/{slug}/index.html"

        app_meta = {
            "id": app_id,
            "name": app_name,
            "icon": icon or "📦",
            "category": category or "Custom",
            "type": detected_type,
            "url": detected_url,
            "repo_url": repo_url,
            "slug": slug,
            "port": port,
            "start_cmd": start_cmd,
            "description": f"Installed from {repo_url}",
            "default_maximized": False,
            "is_system": False,
            "width": 960,
            "height": 600,
            "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        # If it has a start command and port, we can launch it
        if start_cmd and port:
            await self.start_app_process(app_id, start_cmd, target_dir)

        self.register_app(app_meta)
        return app_meta

    async def pull_repo(self, app_id: str) -> Dict[str, Any]:
        app = self.get_app(app_id)
        if not app:
            raise ValueError(f"App {app_id} not found")
        slug = app.get("slug") or app.get("id")
        target_dir = self.apps_dir / slug
        if not target_dir.exists():
            raise FileNotFoundError(f"Directory {target_dir} does not exist")

        proc = await asyncio.create_subprocess_exec(
            "git", "pull",
            cwd=str(target_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return {
            "success": proc.returncode == 0,
            "output": stdout.decode() if proc.returncode == 0 else stderr.decode()
        }

    async def start_app_process(self, app_id: str, cmd: Optional[str] = None, cwd: Optional[Path] = None) -> bool:
        app = self.get_app(app_id)
        if not app:
            return False

        command = cmd or app.get("start_cmd")
        if not command:
            return False

        work_dir = cwd or (self.apps_dir / (app.get("slug") or app_id))
        if not work_dir.exists():
            return False

        # Stop existing if running
        await self.stop_app_process(app_id)

        try:
            logger.info(f"Starting process for {app_id}: {command} in {work_dir}")
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(work_dir),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            self.running_processes[app_id] = proc
            return True
        except Exception as e:
            logger.error(f"Failed to start process for {app_id}: {e}")
            return False

    async def stop_app_process(self, app_id: str) -> bool:
        proc = self.running_processes.get(app_id)
        if proc:
            try:
                proc.terminate()
                await asyncio.sleep(0.5)
                if proc.returncode is None:
                    proc.kill()
            except Exception as e:
                logger.error(f"Error terminating process for {app_id}: {e}")
            finally:
                self.running_processes.pop(app_id, None)
            return True
        return False

    async def delete_app(self, app_id: str) -> bool:
        app = self.get_app(app_id)
        if not app:
            return False
        if app.get("is_system"):
            raise ValueError("System applications cannot be uninstalled")

        # Stop process if running
        await self.stop_app_process(app_id)

        # Remove folder if cloned
        slug = app.get("slug") or app_id
        target_dir = self.apps_dir / slug
        if target_dir.exists():
            try:
                shutil.rmtree(target_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Could not completely remove {target_dir}: {e}")

        # Remove from list
        self.apps = [a for a in self.apps if a.get("id") != app_id]
        self.save_apps()
        return True

    def get_system_metrics(self) -> Dict[str, Any]:
        """
        Gathers real-time Pi 5 hardware metrics: CPU %, Memory %, Temperature, Uptime, IP.
        """
        metrics = {
            "hostname": socket.gethostname(),
            "cpu_percent": 0.0,
            "ram_percent": 0.0,
            "ram_used_mb": 0,
            "ram_total_mb": 0,
            "temp_c": None,
            "disk_percent": 0.0,
            "ip_address": "127.0.0.1",
            "uptime_seconds": 0
        }

        # Try psutil
        try:
            import psutil
            metrics["cpu_percent"] = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            metrics["ram_percent"] = mem.percent
            metrics["ram_used_mb"] = round(mem.used / (1024 * 1024))
            metrics["ram_total_mb"] = round(mem.total / (1024 * 1024))
            disk = psutil.disk_usage('/')
            metrics["disk_percent"] = disk.percent
            metrics["uptime_seconds"] = round(time.time() - psutil.boot_time())
        except Exception:
            pass

        # Temperature (Raspberry Pi thermal zone)
        try:
            thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
            if thermal_path.exists():
                raw = thermal_path.read_text().strip()
                metrics["temp_c"] = round(float(raw) / 1000.0, 1)
        except Exception:
            pass

        # Fallback temperature simulation if running on laptop
        if metrics["temp_c"] is None:
            metrics["temp_c"] = 43.5  # Typical cool Pi 5 idle temp

        # Local IP address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            metrics["ip_address"] = s.getsockname()[0]
            s.close()
        except Exception:
            metrics["ip_address"] = "192.168.3.169"

        return metrics

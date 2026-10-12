"""
FastAPI Server for Home Energy Management.
Serves REST API, live telemetry, and web dashboard.
"""

from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

from config.settings import load_config
from core.engine import CoreEngine

config = load_config()
engine = CoreEngine(config)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start polling loop
    await engine.start()
    yield
    # Shutdown: Stop polling loop
    await engine.stop()

app = FastAPI(title="Pi 5 Home Energy Management", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/api/state")
async def get_state() -> Dict[str, Any]:
    return await engine.get_live_state()

@app.get("/api/history")
async def get_history(limit: int = 60):
    return {"history": engine.db.get_recent_history(limit=limit)}

@app.get("/api/system_mode")
async def get_system_mode():
    return await engine.get_system_mode()

@app.post("/api/system_mode")
async def set_system_mode(settings: Dict[str, Any] = Body(...)):
    ok = await engine.update_system_mode(settings)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to write parameters to SunSynk inverter")
    return {"success": True, "updated": settings}

@app.post("/api/switch/{device}")
async def set_switch(device: str, payload: Dict[str, Any] = Body(...)):
    state = payload.get("state")
    if not state or state not in ("on", "off"):
        raise HTTPException(status_code=400, detail="Invalid state. Expected 'on' or 'off'")
    ok = await engine.set_switch(device, state)
    return {"device": device, "state": state, "success": ok}

@app.post("/api/geyser/temp")
async def set_geyser_temp(payload: Dict[str, Any] = Body(...)):
    temp = payload.get("target_temp_c")
    if temp is None or not (30.0 <= float(temp) <= 75.0):
        raise HTTPException(status_code=400, detail="Temperature must be between 30°C and 75°C")
    engine.set_geyser_temp(float(temp))
    return {"success": True, "target_temp_c": float(temp)}

@app.get("/api/geyser/autocontrol")
async def get_geyser_autocontrol():
    return await engine.get_geyser_auto_control()

@app.post("/api/geyser/autocontrol")
async def update_geyser_autocontrol(payload: Dict[str, Any] = Body(...)):
    rules = payload.get("autoControl", [])
    enabled = payload.get("autoControlEnabled", 1)
    ok = await engine.update_geyser_auto_control(rules, enabled)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update Geyser autoControl on eWeLink")
    return {"success": True, "autoControlEnabled": enabled, "autoControl": rules}

@app.get("/api/sunsynk/energy/day")
async def get_sunsynk_energy_day(date: Optional[str] = None):
    import datetime
    d = date or datetime.date.today().strftime("%Y-%m-%d")
    return await engine.get_energy_day(d)

@app.get("/api/sunsynk/energy/month")
async def get_sunsynk_energy_month(month: Optional[str] = None):
    import datetime
    m = month or datetime.date.today().strftime("%Y-%m")
    return await engine.get_energy_month(m)

@app.get("/api/database/stats")
async def get_database_stats():
    return engine.db.get_database_stats()

@app.get("/api/database/history")
async def get_database_history(start: Optional[float] = None, end: Optional[float] = None, points: int = 150):
    import time
    now = time.time()
    s = start if start is not None else (now - 86400)
    e = end if end is not None else now
    return {"history": engine.db.get_history_range(s, e, points)}


@app.post("/api/reload")
async def reload_config_endpoint():
    import importlib
    import sys
    for mod in ["connectors.sunsynk.cloud_client", "connectors.sunsynk.client", "core.engine"]:
        if mod in sys.modules:
            try:
                importlib.reload(sys.modules[mod])
            except Exception:
                pass
    new_cfg = load_config()
    await engine.reload_config(new_cfg)
    return {"success": True, "message": "Configuration reloaded successfully"}

# Serve web dashboard
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

"""
FastAPI Server for Home Energy Management.
Serves REST API, live telemetry, and web dashboard.
"""

from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Dict, Any
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

# Serve web dashboard
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")

app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

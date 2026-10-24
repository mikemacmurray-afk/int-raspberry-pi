"""
FastAPI Server for Home Energy Management.
Serves REST API, live telemetry, and web dashboard.
"""

from fastapi import FastAPI, HTTPException, Body, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager

import asyncio
from config.settings import load_config
from core.engine import CoreEngine
from core.messages_manager import MessagesManager

config = load_config()
engine = CoreEngine(config)

# Family Messaging Manager & Cloud Relay Config
relay_cfg = getattr(config, "family_relay", None)
RELAY_ENABLED = relay_cfg.enabled if relay_cfg else True
RELAY_URL = relay_cfg.url if relay_cfg else "https://learnai.betterfreelife.com/family-relay"
RELAY_SECRET = relay_cfg.secret if relay_cfg else "cranleigh_family_relay_2026"
LOCAL_ACTOR = relay_cfg.local_actor if relay_cfg else "grandparents"
SYNC_INTERVAL = int(relay_cfg.sync_interval_sec) if relay_cfg else 15

messages_mgr = MessagesManager(local_actor=LOCAL_ACTOR)

async def _family_relay_sync_loop():
    """Background loop that synchronizes messages with the Hetzner cloud relay."""
    if not RELAY_ENABLED or not RELAY_URL:
        return
    # Initial pause to let server startup complete
    await asyncio.sleep(3)
    while True:
        try:
            await messages_mgr.sync_with_relay(RELAY_URL, RELAY_SECRET)
        except Exception:
            pass
        await asyncio.sleep(SYNC_INTERVAL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start polling loops
    await engine.start()
    sync_task = asyncio.create_task(_family_relay_sync_loop())
    yield
    # Shutdown: Stop polling loop
    sync_task.cancel()
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

# -------------------------------------------------------------
# Apps & GitHub Management APIs
# -------------------------------------------------------------
from core.apps_manager import AppsManager, APPS_DIR
apps_mgr = AppsManager()

# Ensure APPS_DIR exists and mount it for hosted static apps
APPS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/apps/hosted", StaticFiles(directory=APPS_DIR), name="hosted_apps")

@app.get("/api/apps")
async def list_apps():
    return {"apps": apps_mgr.get_apps()}

@app.post("/api/apps/register")
async def register_app_endpoint(payload: Dict[str, Any] = Body(...)):
    app_meta = apps_mgr.register_app(payload)
    return {"success": True, "app": app_meta}

@app.delete("/api/apps/{app_id}")
async def delete_app_endpoint(app_id: str):
    try:
        ok = await apps_mgr.delete_app(app_id)
        if not ok:
            raise HTTPException(status_code=404, detail="App not found")
        return {"success": True, "id": app_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/apps/clone")
async def clone_github_endpoint(payload: Dict[str, Any] = Body(...)):
    repo_url = payload.get("repo_url")
    if not repo_url:
        raise HTTPException(status_code=400, detail="Repository URL is required")
    name = payload.get("name")
    icon = payload.get("icon", "📦")
    category = payload.get("category", "Custom")
    port = payload.get("port")
    start_cmd = payload.get("start_cmd")
    app_type = payload.get("type")

    try:
        app_meta = await apps_mgr.clone_github_repo(
            repo_url=repo_url,
            name=name,
            icon=icon,
            category=category,
            port=port,
            start_cmd=start_cmd,
            app_type=app_type
        )
        return {"success": True, "app": app_meta}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clone GitHub repo: {str(e)}")

@app.post("/api/apps/{app_id}/pull")
async def pull_app_endpoint(app_id: str):
    try:
        res = await apps_mgr.pull_repo(app_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/apps/{app_id}/start")
async def start_app_endpoint(app_id: str):
    ok = await apps_mgr.start_app_process(app_id)
    return {"success": ok}

@app.post("/api/apps/{app_id}/stop")
async def stop_app_endpoint(app_id: str):
    ok = await apps_mgr.stop_app_process(app_id)
    return {"success": ok}

@app.get("/api/system/metrics")
async def system_metrics():
    return apps_mgr.get_system_metrics()

# Reverse proxy for microservices running on local ports (e.g. /proxy/3000/...)
@app.api_route("/proxy/{port}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def reverse_proxy(port: int, path: str, request: Request):
    import aiohttp
    url = f"http://127.0.0.1:{port}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
    params = dict(request.query_params)
    body = await request.body()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=request.method,
                url=url,
                headers=headers,
                params=params,
                data=body,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as upstream:
                content = await upstream.read()
                resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in ("transfer-encoding", "content-encoding")}
                return Response(content=content, status_code=upstream.status, headers=resp_headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxy error connecting to port {port}: {str(e)}")

# -------------------------------------------------------------
# Desktop & Application UI Routes
# -------------------------------------------------------------
@app.get("/")
async def desktop_root():
    return FileResponse(STATIC_DIR / "desktop.html")

@app.get("/desktop")
async def desktop_page():
    return FileResponse(STATIC_DIR / "desktop.html")

@app.get("/portal")
async def portal_page():
    return FileResponse(STATIC_DIR / "desktop.html")

@app.get("/portal-classic")
async def portal_classic():
    return FileResponse(STATIC_DIR / "portal.html")

@app.get("/energy")
async def energy_dashboard():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/dashboard")
async def dashboard_alias():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/apps/hub")
async def github_hub_page():
    return FileResponse(STATIC_DIR / "github_hub.html")

@app.get("/apps/system")
async def system_diag_page():
    return FileResponse(STATIC_DIR / "system_diag.html")

# -------------------------------------------------------------
# Family Messages APIs
# -------------------------------------------------------------
@app.get("/api/family/state")
async def get_family_state(peer: Optional[str] = None):
    return {
        "actor": messages_mgr.local_actor,
        "profiles": messages_mgr.get_profiles(),
        "messages": messages_mgr.get_messages(peer=peer),
        "unread": messages_mgr.get_unread_counts()
    }

@app.post("/api/family/messages")
async def send_family_message(payload: Dict[str, Any] = Body(...)):
    recipient = payload.get("recipient")
    body = payload.get("body")
    msg_id = payload.get("id")
    if not recipient or not body:
        raise HTTPException(status_code=400, detail="Missing recipient or body")
    try:
        msg = messages_mgr.send_message(recipient=recipient, body=body, msg_id=msg_id)
        # Immediately trigger background sync so the message hits the cloud relay right away
        if RELAY_ENABLED and RELAY_URL:
            asyncio.create_task(messages_mgr.sync_with_relay(RELAY_URL, RELAY_SECRET))
        return {"success": True, "message": msg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.patch("/api/family/messages/read")
async def mark_family_messages_read(payload: Dict[str, Any] = Body(...)):
    sender = payload.get("sender")
    if not sender:
        raise HTTPException(status_code=400, detail="Missing sender")
    count = messages_mgr.mark_read(sender)
    if RELAY_ENABLED and RELAY_URL:
        asyncio.create_task(messages_mgr.sync_with_relay(RELAY_URL, RELAY_SECRET))
    return {"success": True, "read_count": count}

@app.get("/api/family/unread")
async def get_family_unread():
    return {"unread": messages_mgr.get_unread_counts()}

@app.post("/api/family/sync")
async def trigger_family_sync():
    """Manually trigger immediate bidirectional sync with cloud relay."""
    if not RELAY_ENABLED or not RELAY_URL:
        return {"synced": False, "reason": "Relay disabled"}
    res = await messages_mgr.sync_with_relay(RELAY_URL, RELAY_SECRET)
    return res

app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")

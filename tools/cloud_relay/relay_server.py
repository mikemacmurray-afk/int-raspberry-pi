"""
Family Messages Cloud Relay Server.
Lightweight, standalone relay service designed to run on the Hetzner server
to bridge messages between Grandparents' Pi and Kids' Pi across different homes.
"""

import sqlite3
import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Header, Depends, Body
from fastapi.responses import JSONResponse
import uvicorn

logger = logging.getLogger("FamilyRelay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

RELAY_SECRET = os.environ.get("FAMILY_RELAY_SECRET", "cranleigh_family_relay_2026")
DB_PATH = Path(os.environ.get("RELAY_DB_PATH", "data/messages.db"))

app = FastAPI(title="Family Messages Cloud Relay", version="1.0.0")

def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

@app.on_event("startup")
def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT,
                relay_received_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relay_recipient ON messages(recipient, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relay_sender ON messages(sender, created_at)")
        conn.commit()
    logger.info("Family Messages Cloud Relay DB initialized.")

def verify_secret(x_relay_secret: Optional[str] = Header(None)):
    if not x_relay_secret or x_relay_secret != RELAY_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Relay-Secret")
    return True

@app.get("/health")
def health():
    return {"status": "ok", "service": "family-messages-relay", "time": datetime.now(timezone.utc).isoformat()}

@app.post("/api/relay/messages", dependencies=[Depends(verify_secret)])
def post_message(payload: Dict[str, Any] = Body(...)):
    msg_id = payload.get("id")
    sender = payload.get("sender")
    recipient = payload.get("recipient")
    body = payload.get("body")
    created_at = payload.get("created_at") or datetime.now(timezone.utc).isoformat()
    read_at = payload.get("read_at")
    now = datetime.now(timezone.utc).isoformat()

    if not msg_id or not sender or not recipient or not body:
        raise HTTPException(status_code=400, detail="Missing required message fields")

    with get_db() as conn:
        conn.execute("""
            INSERT INTO messages (id, sender, recipient, body, created_at, read_at, relay_received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET read_at = COALESCE(excluded.read_at, messages.read_at)
        """, (msg_id, sender, recipient, body, created_at, read_at, now))
        conn.commit()

    return {"success": True, "id": msg_id}

@app.post("/api/relay/messages/batch", dependencies=[Depends(verify_secret)])
def post_messages_batch(payload: Dict[str, Any] = Body(...)):
    messages = payload.get("messages", [])
    now = datetime.now(timezone.utc).isoformat()
    synced_ids = []

    with get_db() as conn:
        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id:
                continue
            conn.execute("""
                INSERT INTO messages (id, sender, recipient, body, created_at, read_at, relay_received_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET read_at = COALESCE(excluded.read_at, messages.read_at)
            """, (
                msg_id,
                msg.get("sender", "unknown"),
                msg.get("recipient", "unknown"),
                msg.get("body", ""),
                msg.get("created_at", now),
                msg.get("read_at"),
                now
            ))
            synced_ids.append(msg_id)
        conn.commit()

    return {"success": True, "synced_ids": synced_ids}

@app.get("/api/relay/messages", dependencies=[Depends(verify_secret)])
def get_messages(
    for_pod: Optional[str] = None,
    pod: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100
):
    with get_db() as conn:
        query = "SELECT * FROM messages WHERE 1=1"
        params = []

        target_pod = for_pod or pod
        if target_pod:
            # Return messages where the pod is recipient OR sender (to mirror conversation state)
            query += " AND (recipient = ? OR sender = ?)"
            params.extend([target_pod, target_pod])

        if since:
            query += " AND created_at > ?"
            params.append(since)

        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(min(limit, 500))

        rows = conn.execute(query, params).fetchall()
        return {"messages": [dict(r) for r in rows]}

@app.patch("/api/relay/messages/read", dependencies=[Depends(verify_secret)])
def mark_read(payload: Dict[str, Any] = Body(...)):
    sender = payload.get("sender")
    recipient = payload.get("recipient")
    read_at = payload.get("read_at") or datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        cur = conn.execute("""
            UPDATE messages 
            SET read_at = ? 
            WHERE sender = ? AND recipient = ? AND read_at IS NULL
        """, (read_at, sender, recipient))
        conn.commit()
        return {"success": True, "updated": cur.rowcount}

if __name__ == "__main__":
    port = int(os.environ.get("RELAY_PORT", 8090))
    uvicorn.run(app, host="0.0.0.0", port=port)

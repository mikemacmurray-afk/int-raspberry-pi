"""
Family Messages Manager & Relay Sync Engine.
Handles local message storage (SQLite) and background synchronization
with the Cloud Messaging Relay between Grandparents' Pi and Kids' Pi.
"""

import sqlite3
import time
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger("MessagesManager")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "family_messages.db"

DEFAULT_PROFILES = [
    {
        "id": "kids",
        "name": "Kids & Grandchildren",
        "avatar": "K",
        "color": "#ec4899",
        "subtitle": "Little hellos, big love"
    },
    {
        "id": "grandparents",
        "name": "Grandparents (15 Cranleigh)",
        "avatar": "G",
        "color": "#38bdf8",
        "subtitle": "Always a little closer"
    },
    {
        "id": "parents",
        "name": "Mom & Dad",
        "avatar": "M",
        "color": "#10b981",
        "subtitle": "Home & Family"
    }
]

class MessagesManager:
    def __init__(self, db_path: Path = DB_PATH, local_actor: str = "grandparents"):
        self.db_path = db_path
        self.local_actor = local_actor
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    avatar TEXT NOT NULL,
                    color TEXT NOT NULL,
                    subtitle TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_at TEXT,
                    synced INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender, recipient, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_unread ON messages(recipient, read_at)")

            # Seed default profiles if empty
            cur = conn.execute("SELECT COUNT(*) FROM profiles")
            if cur.fetchone()[0] == 0:
                for p in DEFAULT_PROFILES:
                    conn.execute(
                        "INSERT INTO profiles (id, name, avatar, color, subtitle) VALUES (?, ?, ?, ?, ?)",
                        (p["id"], p["name"], p["avatar"], p["color"], p["subtitle"])
                    )
            conn.commit()

    def get_profiles(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM profiles").fetchall()
            return [dict(r) for r in rows]

    def get_messages(self, peer: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if peer:
                rows = conn.execute("""
                    SELECT * FROM messages 
                    WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
                    ORDER BY created_at ASC
                    LIMIT ?
                """, (self.local_actor, peer, peer, self.local_actor, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM messages 
                    WHERE sender = ? OR recipient = ?
                    ORDER BY created_at ASC
                    LIMIT ?
                """, (self.local_actor, self.local_actor, limit)).fetchall()
            return [dict(r) for r in rows]

    def send_message(self, recipient: str, body: str, msg_id: Optional[str] = None) -> Dict[str, Any]:
        body = body.strip()
        if not body:
            raise ValueError("Message body cannot be empty")
        
        message_id = msg_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO messages (id, sender, recipient, body, created_at, read_at, synced)
                VALUES (?, ?, ?, ?, ?, NULL, 0)
                ON CONFLICT(id) DO NOTHING
            """, (message_id, self.local_actor, recipient, body, now))
            conn.commit()

        return {
            "id": message_id,
            "sender": self.local_actor,
            "recipient": recipient,
            "body": body,
            "created_at": now,
            "read_at": None,
            "synced": 0
        }

    def mark_read(self, sender: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cur = conn.execute("""
                UPDATE messages 
                SET read_at = ? 
                WHERE recipient = ? AND sender = ? AND read_at IS NULL
            """, (now, self.local_actor, sender))
            conn.commit()
            return cur.rowcount

    def get_unread_counts(self) -> Dict[str, int]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT sender, COUNT(*) as cnt 
                FROM messages 
                WHERE recipient = ? AND read_at IS NULL 
                GROUP BY sender
            """, (self.local_actor,)).fetchall()
            return {r["sender"]: r["cnt"] for r in rows}

    def get_unsynced_messages(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE synced = 0").fetchall()
            return [dict(r) for r in rows]

    def mark_as_synced(self, msg_ids: List[str]):
        if not msg_ids:
            return
        placeholders = ",".join("?" for _ in msg_ids)
        with self._get_connection() as conn:
            conn.execute(f"UPDATE messages SET synced = 1 WHERE id IN ({placeholders})", msg_ids)
            conn.commit()

    def upsert_remote_message(self, msg: Dict[str, Any]) -> bool:
        """Saves a message received from the Cloud Relay."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                INSERT INTO messages (id, sender, recipient, body, created_at, read_at, synced)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET 
                    read_at = COALESCE(excluded.read_at, messages.read_at),
                    synced = 1
            """, (
                msg["id"],
                msg["sender"],
                msg["recipient"],
                msg["body"],
                msg["created_at"],
                msg.get("read_at")
            ))
            conn.commit()
            return cur.rowcount > 0

    async def sync_with_relay(self, relay_url: str, secret: str = "cranleigh_family_relay_2026") -> Dict[str, Any]:
        """
        Bidirectional sync with the Cloud Messaging Relay:
        1. Pushes local outgoing messages (synced == 0) to relay.
        2. Pulls new incoming messages from relay for this pod.
        """
        import aiohttp
        if not relay_url:
            return {"synced": False, "reason": "No relay_url provided"}

        base_url = relay_url.rstrip("/")
        headers = {
            "Content-Type": "application/json",
            "X-Relay-Secret": secret
        }
        synced_count = 0
        pulled_count = 0

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                # 1. Push local unsynced messages
                unsynced = self.get_unsynced_messages()
                if unsynced:
                    async with session.post(
                        f"{base_url}/api/relay/messages/batch",
                        json={"messages": unsynced},
                        headers=headers
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            synced_ids = data.get("synced_ids", [])
                            self.mark_as_synced(synced_ids)
                            synced_count = len(synced_ids)

                # 2. Pull remote messages for this pod
                async with session.get(
                    f"{base_url}/api/relay/messages",
                    params={"for_pod": self.local_actor, "limit": 100},
                    headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        remote_msgs = data.get("messages", [])
                        for r_msg in remote_msgs:
                            if self.upsert_remote_message(r_msg):
                                pulled_count += 1

            return {"synced": True, "pushed": synced_count, "pulled": pulled_count}
        except Exception as e:
            logger.debug(f"Relay sync notice (offline or standby): {e}")
            return {"synced": False, "error": str(e)}


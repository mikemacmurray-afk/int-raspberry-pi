"""
Family Messages Sync Bridge for Son & Grandchildren's Pi (pidash).

Synchronizes messages between the local pidash SQLite database and the
Hetzner Cloud Relay (https://learnai.betterfreelife.com/family-relay).

Features:
- Auto-discovers pidash SQLite database in ~/family-pod/ or .wrangler/state/
- Pushes messages sent by 'kids' to the cloud relay.
- Pulls messages sent by 'grandparents' from the cloud relay into the local database.
- Propagates read receipts.
- Runs either as a continuous background daemon or one-shot cron job.
"""

import os
import sys
import time
import glob
import sqlite3
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone
import urllib.request
import urllib.error
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("KidPodSync")

DEFAULT_RELAY_URL = os.environ.get("FAMILY_RELAY_URL", "https://learnai.betterfreelife.com/family-relay")
DEFAULT_SECRET = os.environ.get("FAMILY_RELAY_SECRET", "cranleigh_family_relay_2026")
LOCAL_ACTOR = "kids"
REMOTE_PEER = "grandparents"

def find_sqlite_db(custom_path: str = None) -> Path:
    if custom_path and os.path.exists(custom_path):
        return Path(custom_path)

    search_patterns = [
        os.path.expanduser("~/family-pod/app/.wrangler/state/v3/d1/miniflare-D1DatabaseObject/*.sqlite"),
        os.path.expanduser("~/family-pod/data/*.sqlite"),
        os.path.expanduser("~/family-pod/*.sqlite"),
        "./.wrangler/state/v3/d1/miniflare-D1DatabaseObject/*.sqlite",
        "./*.sqlite",
    ]
    for pattern in search_patterns:
        matches = glob.glob(pattern)
        if matches:
            # Pick latest modified sqlite file
            latest = max(matches, key=os.path.getmtime)
            return Path(latest)

    return None

def get_db(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_sync_tracking(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _relay_sync_tracking (
            message_id TEXT PRIMARY KEY,
            synced_at TEXT NOT NULL
        )
    """)
    conn.commit()

def sync_once(db_path: Path, relay_url: str, secret: str) -> dict:
    base_url = relay_url.rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "X-Relay-Secret": secret,
        "User-Agent": "pidash-sync-agent/1.0"
    }

    with get_db(db_path) as conn:
        init_sync_tracking(conn)

        # 1. Gather unsynced messages sent by 'kids'
        unsynced_query = """
            SELECT m.id, m.sender, m.recipient, m.body, m.created_at, m.read_at
            FROM messages m
            LEFT JOIN _relay_sync_tracking t ON m.id = t.message_id
            WHERE t.message_id IS NULL AND m.sender = ?
            ORDER BY m.created_at ASC LIMIT 100
        """
        rows = conn.execute(unsynced_query, (LOCAL_ACTOR,)).fetchall()
        unsynced_msgs = [dict(r) for r in rows]

        pushed_count = 0
        if unsynced_msgs:
            payload = json.dumps({"messages": unsynced_msgs}).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}/api/relay/messages/batch",
                data=payload,
                headers=headers,
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        synced_ids = data.get("synced_ids", [])
                        now = datetime.now(timezone.utc).isoformat()
                        for sid in synced_ids:
                            conn.execute(
                                "INSERT OR REPLACE INTO _relay_sync_tracking (message_id, synced_at) VALUES (?, ?)",
                                (sid, now)
                            )
                        conn.commit()
                        pushed_count = len(synced_ids)
                        logger.info(f"Pushed {pushed_count} messages to Cloud Relay.")
            except Exception as e:
                logger.warning(f"Error pushing messages to Cloud Relay: {e}")

        # 2. Pull remote messages for 'kids'
        pulled_count = 0
        pull_url = f"{base_url}/api/relay/messages?for_pod={LOCAL_ACTOR}&limit=100"
        pull_req = urllib.request.Request(pull_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(pull_req, timeout=10) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    remote_msgs = data.get("messages", [])
                    now = datetime.now(timezone.utc).isoformat()
                    for r_msg in remote_msgs:
                        mid = r_msg["id"]
                        sender = r_msg["sender"]
                        recipient = r_msg["recipient"]
                        body = r_msg["body"]
                        created_at = r_msg["created_at"]
                        read_at = r_msg.get("read_at")

                        # Insert into local pidash messages table if not present
                        cur = conn.execute("""
                            INSERT INTO messages (id, sender, recipient, body, created_at, read_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                read_at = COALESCE(excluded.read_at, messages.read_at)
                        """, (mid, sender, recipient, body, created_at, read_at))

                        # Mark as tracked
                        conn.execute(
                            "INSERT OR IGNORE INTO _relay_sync_tracking (message_id, synced_at) VALUES (?, ?)",
                            (mid, now)
                        )
                        if cur.rowcount > 0:
                            pulled_count += 1

                    conn.commit()
                    if pulled_count > 0:
                        logger.info(f"Pulled {pulled_count} new messages from Grandparents into local pod.")
        except Exception as e:
            logger.warning(f"Error pulling messages from Cloud Relay: {e}")

        return {"pushed": pushed_count, "pulled": pulled_count}

def main():
    parser = argparse.ArgumentParser(description="Family Messages Relay Sync for Kids Pod")
    parser.add_argument("--db", help="Path to pidash SQLite database", default=None)
    parser.add_argument("--relay-url", help="Hetzner Relay URL", default=DEFAULT_RELAY_URL)
    parser.add_argument("--secret", help="Relay Secret", default=DEFAULT_SECRET)
    parser.add_argument("--interval", type=int, default=15, help="Poll interval in seconds (0 = run once)")
    args = parser.parse_args()

    db_path = find_sqlite_db(args.db)
    if not db_path:
        logger.error("Could not find pidash SQLite database. Please pass --db /path/to/database.sqlite")
        sys.exit(1)

    logger.info(f"Targeting pidash database: {db_path}")
    logger.info(f"Syncing with Cloud Relay: {args.relay_url}")

    if args.interval <= 0:
        res = sync_once(db_path, args.relay_url, args.secret)
        logger.info(f"Sync finished: {res}")
    else:
        logger.info(f"Starting continuous sync daemon (interval: {args.interval}s)...")
        while True:
            try:
                sync_once(db_path, args.relay_url, args.secret)
            except Exception as e:
                logger.error(f"Sync cycle error: {e}")
            time.sleep(args.interval)

if __name__ == "__main__":
    main()

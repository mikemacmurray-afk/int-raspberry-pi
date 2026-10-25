# Cross-Pod Family Messaging Sync Architecture & Integration Guide

This specification details the cloud relay architecture, interface endpoints, server deployments, and sync agent setup linking the **Grandparents' Pi 5 (15 Cranleigh)** and the **Son & Grandchildren's Pi (`pidash`)** via a standalone microservice on the production Hetzner server.

---

## 1. Architectural Overview

```
┌─────────────────────────────────┐                ┌─────────────────────────────────┐
│     Grandparents' Pi 5          │                │      Kids & Grandchildren's Pi   │
│        (15 Cranleigh)           │                │           (pidash pod)          │
│                                 │                │                                 │
│  Actor: "grandparents"          │                │  Actor: "kids"                  │
│  UI: apps/family_messages/      │                │  UI: components/pod/messages    │
│  DB: data/family_messages.db    │                │  DB: family-pod.sqlite (D1)     │
│  Sync: CoreEngine lifespan loop │                │  Sync: pidash_sync_agent.py     │
└────────────────┬────────────────┘                └────────────────┬────────────────┘
                 │                                                  │
                 │ HTTPS (TLS)                                      │ HTTPS (TLS)
                 │ Header: X-Relay-Secret                           │ Header: X-Relay-Secret
                 │                                                  │
                 ▼                                                  ▼
      ┌────────────────────────────────────────────────────────────────────────┐
      │               Production Hetzner Server (89.167.37.84)                 │
      │                     learnai.betterfreelife.com                         │
      │                                                                        │
      │   Nginx (Port 443 / SSL)                                               │
      │     └─► /family-relay/  ──── proxy_pass ────► http://127.0.0.1:8090/   │
      │                                                                        │
      │   Systemd Unit: family-relay.service                                   │
      │   Engine: FastAPI + Uvicorn                                            │
      │   DB: /home/deploy/family-relay/data/messages.db (SQLite WAL)          │
      └────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Hetzner Cloud Relay Server Deployment Specs

| Parameter | Value |
|---|---|
| **Server Host** | `89.167.37.84` (`MTTS-4gb-hel1-1`) |
| **Domain** | `learnai.betterfreelife.com` |
| **System User** | `deploy` |
| **Service Path** | `/home/deploy/family-relay/` |
| **Virtual Environment** | `/home/deploy/family-relay/.venv/` |
| **Internal Port** | `127.0.0.1:8090` |
| **Public HTTPS URL** | `https://learnai.betterfreelife.com/family-relay` |
| **Systemd Service** | `family-relay.service` |
| **Database** | SQLite WAL mode at `/home/deploy/family-relay/data/messages.db` |
| **Relay Auth Header** | `X-Relay-Secret: cranleigh_family_relay_2026` |

### 2.1 Systemd Service Unit (`/etc/systemd/system/family-relay.service`)

```ini
[Unit]
Description=Family Messages Cloud Relay Service
After=network.target

[Service]
Type=simple
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/family-relay
Environment=PYTHONUNBUFFERED=1
Environment=RELAY_PORT=8090
Environment=FAMILY_RELAY_SECRET=cranleigh_family_relay_2026
Environment=RELAY_DB_PATH=/home/deploy/family-relay/data/messages.db
ExecStart=/home/deploy/family-relay/.venv/bin/uvicorn relay_server:app --host 127.0.0.1 --port 8090
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2.2 Nginx Location Block (`/etc/nginx/sites-enabled/learnai.betterfreelife.com`)

```nginx
# Family Messages Cloud Relay
location /family-relay/ {
    proxy_pass http://127.0.0.1:8090/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

---

## 3. Database Schema

The database schema is identical across the Cloud Relay and both Raspberry Pis, ensuring zero impedance mismatch:

```sql
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,               -- UUIDv4 string
    sender TEXT NOT NULL,              -- e.g. "grandparents" or "kids"
    recipient TEXT NOT NULL,           -- e.g. "kids" or "grandparents"
    body TEXT NOT NULL,                -- Text or emoji message payload
    created_at TEXT NOT NULL,          -- ISO 8601 UTC timestamp
    read_at TEXT,                      -- Nullable ISO 8601 UTC timestamp
    relay_received_at TEXT NOT NULL    -- Cloud relay ingress timestamp (relay only)
);

CREATE INDEX IF NOT EXISTS idx_messages_recipient_created ON messages (recipient, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_sender_created ON messages (sender, created_at);
```

---

## 4. REST API Interface Specification

All endpoints under `/api/relay/` require the following header:
```http
X-Relay-Secret: cranleigh_family_relay_2026
```

### 4.1 Health Check
* **Method**: `GET`
* **Path**: `/family-relay/health`
* **Auth**: None (Public)
* **Response**:
```json
{
  "status": "ok",
  "service": "family-messages-relay",
  "time": "2026-10-25T05:30:00.000000+00:00"
}
```

### 4.2 Push Single Message
* **Method**: `POST`
* **Path**: `/family-relay/api/relay/messages`
* **Headers**: `X-Relay-Secret: cranleigh_family_relay_2026`, `Content-Type: application/json`
* **Request Body**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "sender": "kids",
  "recipient": "grandparents",
  "body": "Hello Grandpa and Grandma! ❤️",
  "created_at": "2026-10-25T05:30:00.000000+00:00",
  "read_at": null
}
```
* **Response (200 OK)**:
```json
{
  "success": true,
  "id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 4.3 Batch Push Messages
* **Method**: `POST`
* **Path**: `/family-relay/api/relay/messages/batch`
* **Headers**: `X-Relay-Secret: cranleigh_family_relay_2026`, `Content-Type: application/json`
* **Request Body**:
```json
{
  "messages": [
    {
      "id": "msg-uuid-1",
      "sender": "kids",
      "recipient": "grandparents",
      "body": "We made cookies! 🍪",
      "created_at": "2026-10-25T05:31:00.000000+00:00",
      "read_at": null
    }
  ]
}
```
* **Response (200 OK)**:
```json
{
  "success": true,
  "synced_ids": ["msg-uuid-1"]
}
```

### 4.4 Pull Messages for Pod
* **Method**: `GET`
* **Path**: `/family-relay/api/relay/messages?for_pod={actor}&since={timestamp}&limit={int}`
* **Query Parameters**:
  * `for_pod` (string, required): Returns messages where `recipient = actor` OR `sender = actor` so conversation history mirrors symmetrically.
  * `since` (string, optional): ISO timestamp filter (`created_at > since`).
  * `limit` (integer, default `100`, max `500`).
* **Headers**: `X-Relay-Secret: cranleigh_family_relay_2026`
* **Response (200 OK)**:
```json
{
  "messages": [
    {
      "id": "msg-uuid-1",
      "sender": "grandparents",
      "recipient": "kids",
      "body": "Good morning our darling angels! Sending big hugs!",
      "created_at": "2026-10-25T05:25:00.000000+00:00",
      "read_at": null,
      "relay_received_at": "2026-10-25T05:25:01.000000+00:00"
    }
  ]
}
```

### 4.5 Mark Messages as Read
* **Method**: `PATCH`
* **Path**: `/family-relay/api/relay/messages/read`
* **Headers**: `X-Relay-Secret: cranleigh_family_relay_2026`, `Content-Type: application/json`
* **Request Body**:
```json
{
  "sender": "grandparents",
  "recipient": "kids",
  "read_at": "2026-10-25T05:32:00.000000+00:00"
}
```
* **Response (200 OK)**:
```json
{
  "success": true,
  "updated": 1
}
```

---

## 5. Setup Guide for the Son & Grandchildren's Pi (`pidash`)

The Son and Grandchildren's Pi runs the original `pidash` application (Cloudflare Wrangler D1 SQLite / Next.js). **No UI code modifications are required.** The sync bridge runs alongside `pidash` and synchronizes messages silently in the background.

### 5.1 Files Included in `int-raspberry-pidash`
* **Sync Script**: `scripts/pi/pidash_sync_agent.py`
* **Systemd Unit**: `scripts/pi/family-sync.service`

### 5.2 Step-by-Step Installation on the Kids' Pi

1. **SSH into the Kids' Pi**:
   ```bash
   ssh al@maclighting.local
   # or ssh by IP:
   # ssh al@192.168.x.x
   ```

2. **Navigate to the App Directory & Pull Latest Changes**:
   ```bash
   cd ~/family-pod/app
   git pull origin dev-v1.0
   ```

3. **Verify SQLite Database Discovery (Dry Run)**:
   ```bash
   python3 scripts/pi/pidash_sync_agent.py --interval 0
   ```
   *Expected output:*
   ```
   [INFO] KidPodSync: Targeting pidash database: /home/al/family-pod/app/.wrangler/state/v3/d1/miniflare-D1DatabaseObject/xxxx.sqlite
   [INFO] KidPodSync: Syncing with Cloud Relay: https://learnai.betterfreelife.com/family-relay
   [INFO] KidPodSync: Pulled 3 new messages from Grandparents into local pod.
   [INFO] KidPodSync: Sync finished: {'pushed': 0, 'pulled': 3}
   ```

4. **Install and Enable Systemd Service for Auto-Start on Boot**:
   ```bash
   sudo cp scripts/pi/family-sync.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now family-sync.service
   ```

5. **Verify Service is Active**:
   ```bash
   systemctl status family-sync.service --no-pager
   ```

6. **Monitor Live Sync Logs**:
   ```bash
   journalctl -u family-sync.service -f
   ```

---

## 6. How Bidirectional Synchronization Operates

1. **Kid Sends a Message to Grandparents**:
   * The kid taps a quick reply or sends a message in `pidash`.
   * `pidash` inserts the record into its local `messages` table with `sender = 'kids'`.
   * Within seconds, `pidash_sync_agent.py` detects the new row (not yet in `_relay_sync_tracking`).
   * The agent posts it to `POST https://learnai.betterfreelife.com/family-relay/api/relay/messages/batch`.
   * The Hetzner relay stores the message.
   * On the Grandparents' Pi 5, the background loop pulls it down into `data/family_messages.db`.
   * A heart badge / unread counter lights up on the Cranleigh OS desktop and in the Family Messages app.

2. **Grandparent Sends a Message to Kids**:
   * Grandparents tap a message or send a heart on the Pi 5 touchscreen.
   * The Pi 5 conductor immediately triggers an async HTTPS push to the Hetzner relay.
   * On the Kids' Pi, `pidash_sync_agent.py` pulls the message on its next 15-second cycle.
   * It inserts the message directly into `family-pod.sqlite`.
   * `pidash` detects the new database record and displays it on the kids' screen automatically.

---

## 7. Operational & Diagnostic Commands

### Test Hetzner Cloud Relay from Terminal
```bash
curl -s https://learnai.betterfreelife.com/family-relay/health
```

### Inspect Messages on Cloud Relay for Grandparents
```bash
curl -s -H "X-Relay-Secret: cranleigh_family_relay_2026" \
  "https://learnai.betterfreelife.com/family-relay/api/relay/messages?for_pod=grandparents"
```

### Trigger Manual Sync on Grandparents' Pi 5
```bash
curl -X POST http://192.168.3.169:8050/api/family/sync
```

### Restart Hetzner Relay Service (if needed)
```bash
ssh deploy@89.167.37.84 "sudo systemctl restart family-relay.service"
```

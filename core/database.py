"""
SQLite Time-Series Database for Energy & Device Telemetry.
Stores historical readings and system mode configuration changes.
"""

import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

class Database:
    def __init__(self, db_path: str = "data/energy_history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    solar_watts REAL,
                    battery_soc INTEGER,
                    battery_watts REAL,
                    grid_watts REAL,
                    load_watts REAL,
                    geyser_temp REAL,
                    geyser_watts REAL,
                    geyser_state TEXT,
                    pool_pump_watts REAL,
                    pool_pump_state TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(timestamp)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_mode_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    parameter TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    applied_by TEXT DEFAULT 'user'
                )
            """)

    def record_telemetry(self, solar_data: Dict[str, Any], sonoff_data: Dict[str, Any]):
        """Insert a snapshot of system telemetry."""
        now = time.time()
        solar = solar_data.get("solar", {})
        battery = solar_data.get("battery", {})
        grid = solar_data.get("grid", {})
        load = solar_data.get("load", {})

        geyser = sonoff_data.get("geyser", {})
        pool = sonoff_data.get("pool_pump", {})

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO telemetry (
                    timestamp, solar_watts, battery_soc, battery_watts,
                    grid_watts, load_watts, geyser_temp, geyser_watts,
                    geyser_state, pool_pump_watts, pool_pump_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                solar.get("total_watts", 0),
                battery.get("soc_percent", 0),
                battery.get("watts", 0),
                grid.get("watts", 0),
                load.get("total_watts", 0),
                geyser.get("temperature_c"),
                geyser.get("power_watts", 0),
                geyser.get("state", "off"),
                pool.get("power_watts", 0),
                pool.get("state", "off")
            ))

    def get_recent_history(self, limit: int = 60) -> List[Dict[str, Any]]:
        """Fetch the most recent data points for dashboard graphs."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT timestamp, solar_watts, battery_soc, battery_watts,
                       grid_watts, load_watts, geyser_temp, geyser_watts
                FROM telemetry
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()
            # Return in chronological order
            return [dict(r) for r in reversed(rows)]

    def record_audit(self, param: str, old_val: Any, new_val: Any, applied_by: str = "user"):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO system_mode_audit (timestamp, parameter, old_value, new_value, applied_by)
                VALUES (?, ?, ?, ?, ?)
            """, (time.time(), param, str(old_val), str(new_val), applied_by))

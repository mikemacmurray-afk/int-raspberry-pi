"""
SQLite Time-Series Database for Energy & Device Telemetry.
Optimized for Raspberry Pi 5 / Edge SBC deployment with:
1. WAL (Write-Ahead Logging) mode & NORMAL synchronous PRAGMA for high write throughput & low SD wear.
2. High-resolution raw telemetry (3-second polling).
3. Automated hourly rollups and daily summaries for ultra-fast historical queries.
4. Intelligent retention management to prevent unbounded disk growth.
"""

import sqlite3
import time
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("Database")

class Database:
    def __init__(self, db_path: str = "data/energy_history.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # Raspberry Pi performance optimizations
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # 1. High-resolution telemetry (raw samples)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    solar_watts REAL,
                    solar_pv1_watts REAL DEFAULT 0,
                    solar_pv2_watts REAL DEFAULT 0,
                    solar_daily_kwh REAL DEFAULT 0,
                    battery_soc INTEGER,
                    battery_watts REAL,
                    battery_volts REAL DEFAULT 53.2,
                    battery_temp_c REAL DEFAULT 25.0,
                    battery_daily_charge_kwh REAL DEFAULT 0,
                    battery_daily_discharge_kwh REAL DEFAULT 0,
                    grid_watts REAL,
                    grid_volts REAL DEFAULT 230.0,
                    grid_daily_buy_kwh REAL DEFAULT 0,
                    grid_daily_sell_kwh REAL DEFAULT 0,
                    load_watts REAL,
                    load_daily_kwh REAL DEFAULT 0,
                    geyser_temp REAL,
                    geyser_target_temp_c REAL,
                    geyser_watts REAL,
                    geyser_state TEXT,
                    pool_pump_watts REAL,
                    pool_pump_state TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry(timestamp)")

            # Safe migrations for existing database columns
            new_columns = [
                ("solar_pv1_watts", "REAL DEFAULT 0"),
                ("solar_pv2_watts", "REAL DEFAULT 0"),
                ("solar_daily_kwh", "REAL DEFAULT 0"),
                ("battery_volts", "REAL DEFAULT 53.2"),
                ("battery_temp_c", "REAL DEFAULT 25.0"),
                ("battery_daily_charge_kwh", "REAL DEFAULT 0"),
                ("battery_daily_discharge_kwh", "REAL DEFAULT 0"),
                ("grid_volts", "REAL DEFAULT 230.0"),
                ("grid_daily_buy_kwh", "REAL DEFAULT 0"),
                ("grid_daily_sell_kwh", "REAL DEFAULT 0"),
                ("load_daily_kwh", "REAL DEFAULT 0"),
                ("geyser_target_temp_c", "REAL")
            ]
            for col_name, col_type in new_columns:
                try:
                    conn.execute(f"ALTER TABLE telemetry ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # 2. Hourly Energy Rollup (Aggregated on the hour)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hourly_telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date_hour TEXT UNIQUE NOT NULL,
                    timestamp REAL NOT NULL,
                    samples_count INTEGER DEFAULT 0,
                    pv_avg_w REAL DEFAULT 0,
                    pv_max_w REAL DEFAULT 0,
                    pv_kwh REAL DEFAULT 0,
                    load_avg_w REAL DEFAULT 0,
                    load_kwh REAL DEFAULT 0,
                    battery_soc_avg REAL DEFAULT 0,
                    battery_charge_kwh REAL DEFAULT 0,
                    battery_discharge_kwh REAL DEFAULT 0,
                    grid_buy_kwh REAL DEFAULT 0,
                    geyser_avg_temp REAL DEFAULT 0,
                    geyser_run_minutes REAL DEFAULT 0,
                    pool_run_minutes REAL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hourly_time ON hourly_telemetry(timestamp)")

            # 3. Daily Summary Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_energy_summary (
                    date TEXT PRIMARY KEY NOT NULL,
                    pv_generated_kwh REAL DEFAULT 0,
                    load_consumed_kwh REAL DEFAULT 0,
                    battery_charged_kwh REAL DEFAULT 0,
                    battery_discharged_kwh REAL DEFAULT 0,
                    grid_purchased_kwh REAL DEFAULT 0,
                    grid_sold_kwh REAL DEFAULT 0,
                    geyser_energy_kwh REAL DEFAULT 0,
                    pool_pump_energy_kwh REAL DEFAULT 0,
                    min_battery_soc INTEGER DEFAULT 100,
                    max_battery_soc INTEGER DEFAULT 0,
                    max_geyser_temp REAL DEFAULT 0
                )
            """)

            # 4. System Mode & Settings Audit Log
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON system_mode_audit(timestamp)")

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
                    timestamp, solar_watts, solar_pv1_watts, solar_pv2_watts, solar_daily_kwh,
                    battery_soc, battery_watts, battery_volts, battery_temp_c,
                    battery_daily_charge_kwh, battery_daily_discharge_kwh,
                    grid_watts, grid_volts, grid_daily_buy_kwh, grid_daily_sell_kwh,
                    load_watts, load_daily_kwh,
                    geyser_temp, geyser_target_temp_c, geyser_watts, geyser_state,
                    pool_pump_watts, pool_pump_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now,
                solar.get("total_watts", 0),
                solar.get("pv1_watts", 0),
                solar.get("pv2_watts", 0),
                solar.get("daily_kwh", 0),
                battery.get("soc_percent", 0),
                battery.get("watts", 0),
                battery.get("voltage", 53.2),
                battery.get("temperature", 25.0),
                battery.get("daily_charge_kwh", 0),
                battery.get("daily_discharge_kwh", 0),
                grid.get("watts", 0),
                grid.get("voltage", 230.0),
                grid.get("daily_buy_kwh", 0),
                grid.get("daily_sell_kwh", 0),
                load.get("total_watts", 0),
                load.get("daily_kwh", 0),
                geyser.get("temperature_c"),
                geyser.get("target_temp_c"),
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
            return [dict(r) for r in reversed(rows)]

    def get_history_range(self, start_ts: float, end_ts: float, max_points: int = 200) -> List[Dict[str, Any]]:
        """Fetch telemetry within a time window, downsampling if needed."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT count(*) as count FROM telemetry
                WHERE timestamp >= ? AND timestamp <= ?
            """, (start_ts, end_ts))
            row_count = cur.fetchone()["count"]

            if row_count <= max_points or row_count == 0:
                cur = conn.execute("""
                    SELECT timestamp, solar_watts, solar_pv1_watts, solar_pv2_watts,
                           battery_soc, battery_watts, grid_watts, load_watts,
                           geyser_temp, geyser_watts, geyser_state, pool_pump_watts, pool_pump_state
                    FROM telemetry
                    WHERE timestamp >= ? AND timestamp <= ?
                    ORDER BY timestamp ASC
                """, (start_ts, end_ts))
                return [dict(r) for r in cur.fetchall()]
            else:
                step = max(1, row_count // max_points)
                cur = conn.execute("""
                    SELECT timestamp, solar_watts, solar_pv1_watts, solar_pv2_watts,
                           battery_soc, battery_watts, grid_watts, load_watts,
                           geyser_temp, geyser_watts, geyser_state, pool_pump_watts, pool_pump_state
                    FROM (
                        SELECT *, ROW_NUMBER() OVER (ORDER BY timestamp ASC) as rn
                        FROM telemetry
                        WHERE timestamp >= ? AND timestamp <= ?
                    )
                    WHERE rn % ? = 0
                    ORDER BY timestamp ASC
                """, (start_ts, end_ts, step))
                return [dict(r) for r in cur.fetchall()]

    def record_audit(self, param: str, old_val: Any, new_val: Any, applied_by: str = "user"):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO system_mode_audit (timestamp, parameter, old_value, new_value, applied_by)
                VALUES (?, ?, ?, ?, ?)
            """, (time.time(), param, str(old_val), str(new_val), applied_by))

    def get_database_stats(self) -> Dict[str, Any]:
        """Return diagnostic metrics about the SQLite database on disk."""
        db_size_bytes = os.path.getsize(self.db_path) if self.db_path.exists() else 0
        wal_file = Path(f"{self.db_path}-wal")
        wal_size_bytes = os.path.getsize(wal_file) if wal_file.exists() else 0

        with self._get_connection() as conn:
            cur = conn.execute("SELECT count(*) as total, min(timestamp) as oldest, max(timestamp) as newest FROM telemetry")
            row = cur.fetchone()
            total_records = row["total"] or 0
            oldest_ts = row["oldest"]
            newest_ts = row["newest"]

            cur_hourly = conn.execute("SELECT count(*) as total FROM hourly_telemetry")
            hourly_count = cur_hourly.fetchone()["total"] or 0

            cur_daily = conn.execute("SELECT count(*) as total FROM daily_energy_summary")
            daily_count = cur_daily.fetchone()["total"] or 0

        return {
            "db_path": str(self.db_path),
            "size_mb": round((db_size_bytes + wal_size_bytes) / (1024 * 1024), 2),
            "total_telemetry_rows": total_records,
            "oldest_timestamp": oldest_ts,
            "newest_timestamp": newest_ts,
            "hourly_rows": hourly_count,
            "daily_rows": daily_count,
            "wal_enabled": True
        }

    def purge_old_telemetry(self, days_to_keep: int = 14) -> int:
        """Purge high-resolution 3s telemetry older than N days to prevent SD card saturation."""
        cutoff_ts = time.time() - (days_to_keep * 86400)
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM telemetry WHERE timestamp < ?", (cutoff_ts,))
            deleted = cur.rowcount
            logger.info(f"Purged {deleted} old telemetry rows older than {days_to_keep} days.")
            return deleted

"""
SQLite database management for Doorstep Resolve orders, inventory, and resolutions.
"""

import sqlite3
import json
from datetime import datetime, time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from .models import Order, Policy, InventoryItem, ShippingEstimate

DEFAULT_DB_PATH = Path(__file__).parent.parent / "doorstep_resolve.db"


class Database:
    """Manages SQLite persistence for orders, inventory, resolutions, and audit history."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path) if db_path else str(DEFAULT_DB_PATH)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    price REAL NOT NULL,
                    delivered_at TEXT NOT NULL,
                    return_window_days INTEGER DEFAULT 30,
                    replacement_allowed INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    warehouse_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS shipping_estimates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    warehouse_id TEXT NOT NULL,
                    carrier TEXT NOT NULL,
                    method_name TEXT NOT NULL,
                    cutoff_time TEXT NOT NULL,
                    transit_hours INTEGER NOT NULL,
                    shipping_cost REAL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS resolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    action_type TEXT NOT NULL,
                    option_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    estimated_arrival TEXT,
                    evidence_json TEXT NOT NULL,
                    customer_notes TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(order_id)
                );

                CREATE TABLE IF NOT EXISTS case_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )
            # Seed initial sample data if orders table is empty
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM orders")
            if cur.fetchone()[0] == 0:
                self._seed_default_data(conn)
            else:
                # Safe migration for existing databases: remove duplicate WH-EAST-1 16:00 route without touching history/resolutions
                cur.execute(
                    """
                    DELETE FROM shipping_estimates
                    WHERE warehouse_id = 'WH-EAST-1'
                      AND carrier = 'FastTrack Logistics'
                      AND method_name = 'Standard Ground'
                      AND cutoff_time = '16:00'
                    """
                )

    def _seed_default_data(self, conn: sqlite3.Connection) -> None:
        orders = [
            ("ORD-1001", "SKU-HEADPHONES-PRO", "Noise Cancelling Wireless Headphones", 199.99, "2026-10-15T14:00:00", 30, 1),
            ("ORD-1002", "SKU-CHARGER-100W", "100W USB-C GaN Charger", 49.99, "2026-10-16T12:00:00", 30, 1),
            ("ORD-1003", "SKU-JACKET-LTD", "Limited Edition Winter Jacket", 249.00, "2026-10-18T10:00:00", 30, 1),
            ("ORD-1004", "SKU-ESPRESSO-DELUXE", "Deluxe Compact Espresso Machine", 320.00, "2026-09-10T14:00:00", 30, 1),
            ("ORD-1005", "SKU-MONITOR-PULSE", "Continuous Health Pulse Monitor", 145.00, "2026-10-17T09:00:00", 30, 1),
        ]
        conn.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", orders
        )

        inventory = [
            ("SKU-HEADPHONES-PRO", "SKU-HP-BLK", "WH-EAST-1", 12),
            ("SKU-CHARGER-100W", "SKU-CHG-100W", "WH-WEST-1", 8),
            ("SKU-JACKET-LTD", "SKU-JKT-M-BLUE", "WH-CENTRAL-1", 0),
            ("SKU-JACKET-LTD", "SKU-JKT-M-BLUE", "WH-EAST-1", 0),
            ("SKU-ESPRESSO-DELUXE", "SKU-ESP-SS", "WH-EAST-1", 5),
            ("SKU-MONITOR-PULSE", "SKU-MON-WHT", "WH-NORTH-1", 10),
        ]
        conn.executemany(
            "INSERT INTO inventory (item_id, sku, warehouse_id, quantity) VALUES (?, ?, ?, ?)",
            inventory,
        )

        shipping = [
            ("WH-WEST-1", "Apex Freight", "Standard Ground", "16:00", 48, 0.0),
            ("WH-CENTRAL-1", "Apex Freight", "Standard Ground", "17:00", 24, 0.0),
            ("WH-EAST-1", "FastTrack Logistics", "Standard Ground", "17:00", 24, 0.0),
            ("WH-NORTH-1", "GroundLogistics", "Standard Ground", "15:00", 48, 0.0),
            ("WH-NORTH-1", "SwiftExpress", "Expedited Air", "15:00", 12, 14.99),
        ]
        conn.executemany(
            "INSERT INTO shipping_estimates (warehouse_id, carrier, method_name, cutoff_time, transit_hours, shipping_cost) VALUES (?, ?, ?, ?, ?, ?)",
            shipping,
        )

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            window_days = int(res.get("return_window_days", 30))
            replacement_allowed = bool(res.get("replacement_allowed", 1))
            window_expiry = None
            if res.get("delivered_at"):
                try:
                    delivered_dt = datetime.fromisoformat(res["delivered_at"])
                    window_expiry = (delivered_dt + timedelta(days=window_days)).isoformat()
                except Exception:
                    pass

            res["policy"] = {
                "return_window_days": window_days,
                "replacement_allowed": replacement_allowed,
                "allows_replacement": replacement_allowed,
                "window_expiry": window_expiry,
            }
            return res

    def get_inventory_for_item(self, item_id: str) -> List[InventoryItem]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM inventory WHERE item_id = ?", (item_id,))
            rows = cur.fetchall()
            return [
                InventoryItem(
                    item_id=r["item_id"],
                    sku=r["sku"],
                    warehouse_id=r["warehouse_id"],
                    quantity=r["quantity"],
                )
                for r in rows
            ]

    def get_shipping_estimates(self, warehouse_ids: Optional[List[str]] = None) -> List[ShippingEstimate]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            if warehouse_ids:
                placeholders = ",".join("?" for _ in warehouse_ids)
                cur.execute(
                    f"SELECT * FROM shipping_estimates WHERE warehouse_id IN ({placeholders})",
                    warehouse_ids,
                )
            else:
                cur.execute("SELECT * FROM shipping_estimates")
            rows = cur.fetchall()
            estimates = []
            for r in rows:
                h, m = map(int, r["cutoff_time"].split(":"))
                estimates.append(
                    ShippingEstimate(
                        warehouse_id=r["warehouse_id"],
                        carrier=r["carrier"],
                        method_name=r["method_name"],
                        cutoff_time=time(h, m),
                        transit_hours=r["transit_hours"],
                        shipping_cost=r["shipping_cost"],
                    )
                )
            return estimates

    def get_resolution_by_idempotency_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM resolutions WHERE idempotency_key = ?", (idempotency_key,))
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["evidence"] = json.loads(res["evidence_json"])
            return res

    def record_resolution(
        self,
        case_id: str,
        order_id: str,
        idempotency_key: str,
        action_type: str,
        option_id: str,
        status: str,
        confirmed_at: str,
        estimated_arrival: Optional[str],
        evidence: List[str],
        customer_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            evidence_json = json.dumps(evidence)
            cur.execute(
                """
                INSERT INTO resolutions (
                    case_id, order_id, idempotency_key, action_type, option_id,
                    status, confirmed_at, estimated_arrival, evidence_json, customer_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id, order_id, idempotency_key, action_type, option_id,
                    status, confirmed_at, estimated_arrival, evidence_json, customer_notes
                ),
            )
            # Log audit event
            self.add_case_history_event(
                case_id=case_id,
                order_id=order_id,
                event_type="RESOLUTION_CONFIRMED",
                details={
                    "idempotency_key": idempotency_key,
                    "action_type": action_type,
                    "option_id": option_id,
                    "status": status,
                    "estimated_arrival": estimated_arrival,
                },
                conn=conn,
            )
            conn.commit()

            return {
                "case_id": case_id,
                "order_id": order_id,
                "idempotency_key": idempotency_key,
                "action_type": action_type,
                "option_id": option_id,
                "status": status,
                "confirmed_at": confirmed_at,
                "estimated_arrival": estimated_arrival,
                "evidence": evidence,
                "customer_notes": customer_notes,
                "idempotent_replay": False,
            }

    def add_case_history_event(
        self,
        case_id: str,
        order_id: str,
        event_type: str,
        details: Dict[str, Any],
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        close_conn = False
        if conn is None:
            conn = self._get_connection()
            close_conn = True

        try:
            timestamp = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO case_history (case_id, order_id, timestamp, event_type, details_json) VALUES (?, ?, ?, ?, ?)",
                (case_id, order_id, timestamp, event_type, json.dumps(details)),
            )
            if close_conn:
                conn.commit()
        finally:
            if close_conn:
                conn.close()

    def get_case_history(
        self, order_id: Optional[str] = None, case_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            if order_id and case_id:
                cur.execute(
                    "SELECT * FROM case_history WHERE order_id = ? OR case_id = ? ORDER BY id ASC",
                    (order_id, case_id),
                )
            elif order_id:
                cur.execute("SELECT * FROM case_history WHERE order_id = ? ORDER BY id ASC", (order_id,))
            elif case_id:
                cur.execute("SELECT * FROM case_history WHERE case_id = ? ORDER BY id ASC", (case_id,))
            else:
                cur.execute("SELECT * FROM case_history ORDER BY id ASC")

            rows = cur.fetchall()
            events = []
            for r in rows:
                ev = dict(r)
                ev["details"] = json.loads(ev["details_json"])
                del ev["details_json"]
                # Provide created_at and event_name aliases for robust UI presentation
                ev["created_at"] = ev.get("timestamp")
                ev["event_name"] = ev.get("event_type")
                events.append(ev)
            return events

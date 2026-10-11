"""Storage layer for LifeVault.

Provides an abstract Storage interface and a concrete SQLite implementation.
Designed to be backed by SQLite locally and swapped for DynamoDB in the cloud.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

VALID_TYPES = {"warranty", "subscription", "insurance", "bill", "document"}


class Storage(ABC):
    """Abstract base class for LifeVault records storage."""

    @abstractmethod
    def add_record(self, record_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new life-admin record and return the created record."""
        pass

    @abstractmethod
    def get_record(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a record by primary ID."""
        pass

    @abstractmethod
    def search_records(self, query: str) -> List[Dict[str, Any]]:
        """Case-insensitive partial match across name, vendor, and notes.

        Returns all matching records.
        """
        pass

    @abstractmethod
    def update_record(self, record_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update fields of an existing record."""
        pass

    @abstractmethod
    def delete_record(self, record_id: int) -> bool:
        """Delete a record by ID. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    def list_records(self, type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all records, optionally filtered by record type."""
        pass

    @abstractmethod
    def list_upcoming(self, days: int) -> List[Dict[str, Any]]:
        """List upcoming deadlines within the next `days` days."""
        pass

    @abstractmethod
    def list_expired(self, days: int) -> List[Dict[str, Any]]:
        """List records that expired in the last `days` days."""
        pass

    @abstractmethod
    def list_bills(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List bill records, optionally filtered by name or vendor."""
        pass

    @abstractmethod
    def spending_by_period(self, start: str, end: str) -> Dict[str, Any]:
        """Calculate spending total and category breakdown between start and end dates (inclusive)."""
        pass


class SqliteStorage(Storage):
    """SQLite implementation of the Storage interface using built-in sqlite3."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            self.db_path = str(Path(__file__).resolve().parent / "lifevault.db")
        else:
            self.db_path = db_path
        self.init_db()

    @contextmanager
    def _get_connection(self):
        """Yield a SQLite connection with dictionary-like row access, ensuring closure."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self, drop_existing: bool = False) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if drop_existing:
                cursor.execute("DROP TABLE IF EXISTS records")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    vendor TEXT,
                    amount REAL,
                    currency TEXT DEFAULT 'USD',
                    purchase_date TEXT,
                    expiry_date TEXT,
                    renewal_cycle TEXT,
                    reminder_date TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_record(self, record_data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a record into the database."""
        created_at = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO records (
                    type, name, vendor, amount, currency,
                    purchase_date, expiry_date, renewal_cycle,
                    reminder_date, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_data.get("type", "").strip().lower(),
                    record_data.get("name", "").strip(),
                    record_data.get("vendor"),
                    record_data.get("amount"),
                    record_data.get("currency", "USD"),
                    record_data.get("purchase_date"),
                    record_data.get("expiry_date"),
                    record_data.get("renewal_cycle"),
                    record_data.get("reminder_date"),
                    record_data.get("notes"),
                    created_at,
                ),
            )
            conn.commit()
            record_id = cursor.lastrowid

        return self.get_record(record_id)  # type: ignore

    def get_record(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single record by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM records WHERE id = ?", (record_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def search_records(self, query: str) -> List[Dict[str, Any]]:
        """Case-insensitive partial matching across name, vendor, and notes."""
        clean_query = f"%{query.strip().lower()}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM records
                WHERE LOWER(name) LIKE ?
                   OR LOWER(vendor) LIKE ?
                   OR LOWER(notes) LIKE ?
                ORDER BY expiry_date ASC, name ASC
                """,
                (clean_query, clean_query, clean_query),
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_record(self, record_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update specified fields of a record."""
        valid_fields = {
            "type", "name", "vendor", "amount", "currency",
            "purchase_date", "expiry_date", "renewal_cycle",
            "reminder_date", "notes"
        }
        filtered = {k: v for k, v in updates.items() if k in valid_fields}
        if not filtered:
            return self.get_record(record_id)

        set_clause = ", ".join(f"{k} = ?" for k in filtered.keys())
        params = list(filtered.values()) + [record_id]

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE records SET {set_clause} WHERE id = ?", params)
            conn.commit()

        return self.get_record(record_id)

    def delete_record(self, record_id: int) -> bool:
        """Delete a record by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM records WHERE id = ?", (record_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_records(self, type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List records, optionally filtering by type."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if type:
                cursor.execute(
                    "SELECT * FROM records WHERE LOWER(type) = ? ORDER BY expiry_date ASC, name ASC",
                    (type.strip().lower(),),
                )
            else:
                cursor.execute("SELECT * FROM records ORDER BY expiry_date ASC, name ASC")
            return [dict(row) for row in cursor.fetchall()]

    def list_upcoming(self, days: int) -> List[Dict[str, Any]]:
        """Return records expiring or renewing between today and today + days."""
        today_str = date.today().isoformat()
        future_str = (date.today() + timedelta(days=days)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM records
                WHERE expiry_date IS NOT NULL
                  AND expiry_date >= ?
                  AND expiry_date <= ?
                ORDER BY expiry_date ASC
                """,
                (today_str, future_str),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_expired(self, days: int) -> List[Dict[str, Any]]:
        """Return records that expired between today - days and today."""
        today_str = date.today().isoformat()
        past_str = (date.today() - timedelta(days=days)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM records
                WHERE expiry_date IS NOT NULL
                  AND expiry_date >= ?
                  AND expiry_date < ?
                ORDER BY expiry_date DESC
                """,
                (past_str, today_str),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_bills(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return bill records, ordered by purchase date ascending."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if name:
                clean = f"%{name.strip().lower()}%"
                cursor.execute(
                    """
                    SELECT * FROM records
                    WHERE LOWER(type) = 'bill'
                      AND (LOWER(name) LIKE ? OR LOWER(vendor) LIKE ?)
                    ORDER BY purchase_date ASC, id ASC
                    """,
                    (clean, clean),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM records
                    WHERE LOWER(type) = 'bill'
                    ORDER BY purchase_date ASC, id ASC
                    """
                )
            return [dict(row) for row in cursor.fetchall()]

    def spending_by_period(self, start: str, end: str) -> Dict[str, Any]:
        """Aggregate total spending and category breakdown for a date range."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT type, SUM(amount) as cat_total, COUNT(*) as count
                FROM records
                WHERE amount IS NOT NULL
                  AND purchase_date IS NOT NULL
                  AND purchase_date >= ?
                  AND purchase_date <= ?
                GROUP BY type
                ORDER BY cat_total DESC
                """,
                (start, end),
            )
            rows = cursor.fetchall()

            categories: Dict[str, float] = {}
            total = 0.0
            top_category = None
            top_amount = 0.0

            for row in rows:
                c_type = row["type"]
                c_total = round(float(row["cat_total"] or 0.0), 2)
                categories[c_type] = c_total
                total += c_total
                if top_category is None:
                    top_category = c_type
                    top_amount = c_total

            return {
                "start": start,
                "end": end,
                "total": round(total, 2),
                "categories": categories,
                "top_category": top_category,
                "top_amount": top_amount,
            }

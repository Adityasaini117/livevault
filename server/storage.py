"""Storage layer for StockPilot AI.

Provides an abstract Storage interface and a concrete SQLite implementation.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


class Storage(ABC):
    """Abstract base class for StockPilot inventory and job storage."""

    @abstractmethod
    def get_part(self, name_or_sku: str) -> Optional[Dict[str, Any]]:
        """Fetch a part by exact name or SKU (case-insensitive)."""
        pass

    @abstractmethod
    def search_parts(self, query: str) -> List[Dict[str, Any]]:
        """Partial case-insensitive search across part names and SKUs."""
        pass

    @abstractmethod
    def get_stock(self, part_id: int) -> Optional[int]:
        """Return the current stock quantity for a part ID."""
        pass

    @abstractmethod
    def adjust_stock(self, part_id: int, delta: int) -> Optional[int]:
        """Adjust stock level by delta (+/-) and return the new quantity."""
        pass

    @abstractmethod
    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Fetch job details by job ID."""
        pass

    @abstractmethod
    def attach_part_to_job(self, job_id: int, part_id: int, qty: int) -> Dict[str, Any]:
        """Record a part attached to a job in the usage log."""
        pass

    @abstractmethod
    def log_usage(
        self,
        part_id: int,
        job_id: Optional[int],
        qty: int,
        used_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record part usage event."""
        pass

    @abstractmethod
    def get_usage_history(self, part_id: int, days: int = 90) -> List[Dict[str, Any]]:
        """Return usage history for a part over the last N days."""
        pass

    @abstractmethod
    def list_parts(self) -> List[Dict[str, Any]]:
        """List all parts in inventory."""
        pass


class SqliteStorage(Storage):
    """SQLite implementation of the Storage interface using built-in sqlite3."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            self.db_path = str(Path(__file__).resolve().parent / "stockpilot.db")
        else:
            self.db_path = db_path
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a sqlite connection with dictionary row access."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self, drop_existing: bool = False) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if drop_existing:
                cursor.execute("DROP TABLE IF EXISTS usage_log")
                cursor.execute("DROP TABLE IF EXISTS jobs")
                cursor.execute("DROP TABLE IF EXISTS parts")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS parts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    reorder_level INTEGER NOT NULL,
                    unit_cost REAL NOT NULL,
                    supplier TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY,
                    vehicle TEXT NOT NULL,
                    customer TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    part_id INTEGER NOT NULL,
                    job_id INTEGER,
                    qty INTEGER NOT NULL,
                    used_at TEXT NOT NULL,
                    FOREIGN KEY(part_id) REFERENCES parts(id),
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                )
                """
            )
            conn.commit()

    def get_part(self, name_or_sku: str) -> Optional[Dict[str, Any]]:
        """Fetch a part by exact name or SKU (case-insensitive)."""
        term = name_or_sku.strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Match exact SKU first
            cursor.execute(
                "SELECT * FROM parts WHERE LOWER(sku) = LOWER(?)",
                (term,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Match exact name
            cursor.execute(
                "SELECT * FROM parts WHERE LOWER(name) = LOWER(?)",
                (term,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)

            return None

    def search_parts(self, query: str) -> List[Dict[str, Any]]:
        """Partial case-insensitive search returning all matching parts."""
        clean = query.strip().lower()
        if not clean:
            return []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Direct substring match on whole query or singularized form
            candidates = [clean]
            if clean.endswith("s") and len(clean) > 2:
                candidates.append(clean[:-1])

            matched_ids = set()
            results = []

            for cand in candidates:
                pattern = f"%{cand}%"
                cursor.execute(
                    """
                    SELECT * FROM parts
                    WHERE LOWER(name) LIKE ? OR LOWER(sku) LIKE ?
                    ORDER BY name ASC
                    """,
                    (pattern, pattern),
                )
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    if row_dict["id"] not in matched_ids:
                        matched_ids.add(row_dict["id"])
                        results.append(row_dict)

            if results:
                return results

            # 2. Token-based matching: each word must match name or sku
            tokens = [t.rstrip("s") for t in clean.split() if len(t.rstrip("s")) > 0]
            if not tokens:
                tokens = clean.split()

            where_clauses = []
            params = []
            for t in tokens:
                where_clauses.append("(LOWER(name) LIKE ? OR LOWER(sku) LIKE ?)")
                params.extend([f"%{t}%", f"%{t}%"])

            sql = f"""
                SELECT * FROM parts
                WHERE {' AND '.join(where_clauses)}
                ORDER BY name ASC
            """
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_stock(self, part_id: int) -> Optional[int]:
        """Return the current stock quantity for a part ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT qty FROM parts WHERE id = ?", (part_id,))
            row = cursor.fetchone()
            return row["qty"] if row else None

    def adjust_stock(self, part_id: int, delta: int) -> Optional[int]:
        """Adjust stock level by delta and return the updated quantity."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE parts SET qty = qty + ? WHERE id = ?",
                (delta, part_id),
            )
            conn.commit()
            return self.get_stock(part_id)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Fetch job details by job ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def attach_part_to_job(self, job_id: int, part_id: int, qty: int) -> Dict[str, Any]:
        """Record a part attached to a job in the usage log."""
        return self.log_usage(part_id=part_id, job_id=job_id, qty=qty)

    def log_usage(
        self,
        part_id: int,
        job_id: Optional[int],
        qty: int,
        used_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a part usage event."""
        if used_at is None:
            used_at = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO usage_log (part_id, job_id, qty, used_at)
                VALUES (?, ?, ?, ?)
                """,
                (part_id, job_id, qty, used_at),
            )
            conn.commit()
            log_id = cursor.lastrowid
            return {
                "id": log_id,
                "part_id": part_id,
                "job_id": job_id,
                "qty": qty,
                "used_at": used_at,
            }

    def get_usage_history(self, part_id: int, days: int = 90) -> List[Dict[str, Any]]:
        """Return usage history for a part over the last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM usage_log
                WHERE part_id = ? AND used_at >= ?
                ORDER BY used_at DESC
                """,
                (part_id, cutoff),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_parts(self) -> List[Dict[str, Any]]:
        """List all parts in inventory."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM parts ORDER BY name ASC")
            return [dict(row) for row in cursor.fetchall()]

"""SQLite-backed Data Processor with rts/wts bookkeeping per data item."""

from __future__ import annotations

import sqlite3
import threading

from src.common.messages import OpResult, Timestamp


class DataProcessor:
    """Applies R/W ops to local SQLite and maintains rts(x), wts(x) per item.

    Two tables:
        Assembly_Line_Steps (step_id PK, machine_id, status)
        step_meta           (step_id PK, rts_counter, rts_site, wts_counter, wts_site)

    Reference: Ozsu & Valduriez 2020, Section 5.2.2, p. 198 — rts(x), wts(x)
    are the latest read/write timestamps seen for item x.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def init_schema(self) -> None:
        """Create tables if not exist; called on site startup."""
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS Assembly_Line_Steps (
                step_id   INTEGER PRIMARY KEY,
                machine_id TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'PENDING'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS step_meta (
                step_id     INTEGER PRIMARY KEY,
                rts_counter INTEGER NOT NULL DEFAULT 0,
                rts_site    INTEGER NOT NULL DEFAULT 0,
                wts_counter INTEGER NOT NULL DEFAULT 0,
                wts_site    INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

    def apply_read(self, step_id: int, ts: Timestamp) -> OpResult:
        """Return current status; set rts(step_id) = max(rts, ts)."""
        with self._write_lock:
            conn = self._conn()
            row = conn.execute(
                "SELECT status FROM Assembly_Line_Steps WHERE step_id = ?", (step_id,)
            ).fetchone()
            if row is None:
                return OpResult(ok=False, error="NOT_FOUND")
            status = row[0]

            meta = conn.execute(
                "SELECT rts_counter, rts_site FROM step_meta WHERE step_id = ?",
                (step_id,),
            ).fetchone()
            if meta is None:
                conn.execute(
                    "INSERT OR IGNORE INTO step_meta"
                    " (step_id, rts_counter, rts_site, wts_counter, wts_site)"
                    " VALUES (?, ?, ?, 0, 0)",
                    (step_id, ts.counter, ts.site_id),
                )
            elif (ts.counter, ts.site_id) > (meta[0], meta[1]):
                conn.execute(
                    "UPDATE step_meta SET rts_counter=?, rts_site=? WHERE step_id=?",
                    (ts.counter, ts.site_id, step_id),
                )
            conn.commit()
            return OpResult(ok=True, value=status)

    def apply_write(self, step_id: int, status: str, ts: Timestamp) -> OpResult:
        """Persist status; set wts(step_id) = ts."""
        with self._write_lock:
            conn = self._conn()
            exists = conn.execute(
                "SELECT 1 FROM Assembly_Line_Steps WHERE step_id = ?", (step_id,)
            ).fetchone()
            if exists is None:
                return OpResult(ok=False, error="NOT_FOUND")
            conn.execute(
                "UPDATE Assembly_Line_Steps SET status=? WHERE step_id=?",
                (status, step_id),
            )
            conn.execute(
                """
                INSERT INTO step_meta (step_id, rts_counter, rts_site, wts_counter, wts_site)
                VALUES (?, 0, 0, ?, ?)
                ON CONFLICT(step_id) DO UPDATE
                  SET wts_counter = excluded.wts_counter,
                      wts_site    = excluded.wts_site
                """,
                (step_id, ts.counter, ts.site_id),
            )
            conn.commit()
            return OpResult(ok=True)

    def get_rts(self, step_id: int) -> Timestamp | None:
        """Return latest read timestamp for step_id, or None if never read."""
        conn = self._conn()
        row = conn.execute(
            "SELECT rts_counter, rts_site FROM step_meta WHERE step_id=?", (step_id,)
        ).fetchone()
        if row is None:
            return None
        return Timestamp(counter=row[0], site_id=row[1])

    def get_wts(self, step_id: int) -> Timestamp | None:
        """Return latest write timestamp for step_id, or None if never written."""
        conn = self._conn()
        row = conn.execute(
            "SELECT wts_counter, wts_site FROM step_meta WHERE step_id=?", (step_id,)
        ).fetchone()
        if row is None:
            return None
        return Timestamp(counter=row[0], site_id=row[1])

    def close(self) -> None:
        if hasattr(self._local, "conn"):
            self._local.conn.close()
            del self._local.conn

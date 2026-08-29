"""Data-access layer for the webhook service.

Two implementations of BookingRepository:
- RealPostgresRepository — production, wraps a psycopg 3 connection.
- FakeRepository (in tests) — mirrors the same interface in memory.

The endpoint only ever talks through this interface, so /vapi/end-of-call can
be exercised end-to-end in CI without a live database.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    import psycopg
except ImportError:  # pragma: no cover — real DB not needed for the tests.
    psycopg = None


class DbError(RuntimeError):
    """Raised when the underlying database is unreachable or misconfigured."""


class BookingRepository:
    """Interface. Concrete implementations override each method."""

    def get_booking(self, booking_ref: str) -> Optional[dict]:
        raise NotImplementedError

    def find_call_by_vapi_id(self, vapi_call_id: str) -> Optional[int]:
        raise NotImplementedError

    def insert_call_log(self, data: dict) -> int:
        raise NotImplementedError

    def insert_support_request(self, data: dict) -> int:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError


class RealPostgresRepository(BookingRepository):
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    @classmethod
    def connect(cls, dsn: str) -> "RealPostgresRepository":
        if psycopg is None:
            raise DbError("psycopg is not installed")
        try:
            conn = psycopg.connect(dsn)
        except Exception as error:  # pragma: no cover — DB unreachable path.
            raise DbError(str(error)) from error
        return cls(conn)

    def get_booking(self, booking_ref: str) -> Optional[dict]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT customer_name, email, passport_status "
                "FROM bookings WHERE booking_ref = %s",
                (booking_ref,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "customer_name": row[0],
            "email": row[1],
            "passport_status": row[2],
        }

    def find_call_by_vapi_id(self, vapi_call_id: str) -> Optional[int]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM call_logs WHERE vapi_call_id = %s",
                (vapi_call_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def insert_call_log(self, data: dict) -> int:
        return self._insert_returning_id("call_logs", data)

    def insert_support_request(self, data: dict) -> int:
        return self._insert_returning_id("support_requests", data)

    def _insert_returning_id(self, table: str, data: dict) -> int:
        columns = list(data.keys())
        placeholders = ", ".join(["%s"] * len(columns))
        column_list = ", ".join(columns)
        sql = (
            f"INSERT INTO {table} ({column_list}) "
            f"VALUES ({placeholders}) RETURNING id"
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, [data[column] for column in columns])
            row = cur.fetchone()
        return row[0]

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

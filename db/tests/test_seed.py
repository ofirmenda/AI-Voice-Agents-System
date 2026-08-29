"""Tests for db/init.sql shape and db/load_bookings.py.

Cannot spin up a real Postgres inside pytest, so we test the pieces the loader
composes: parse_bookings against the CSV, insert_bookings against a fake
cursor, and structural assertions on init.sql (correct tables, seed names, and
ALTER statements are present).
"""

from __future__ import annotations

from pathlib import Path

from load_bookings import BOOKING_COLUMNS, insert_bookings, parse_bookings


REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "voice-agent" / "data" / "check-in-calls.csv"
INIT_SQL = REPO_ROOT / "db" / "init.sql"


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []
        self.rowcount = 1

    def execute(self, sql: str, values) -> None:
        self.calls.append((sql, list(values)))

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        return None


class FakeConn:
    def __init__(self) -> None:
        self._cursor = FakeCursor()
        self.committed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True


# --- CSV parsing ----------------------------------------------------------


def test_parse_bookings_returns_four_rows():
    rows = parse_bookings(CSV_PATH)
    assert len(rows) == 4


def test_parsed_rows_carry_only_booking_columns():
    rows = parse_bookings(CSV_PATH)
    for row in rows:
        assert set(row.keys()) == set(BOOKING_COLUMNS)


def test_michal_row_has_missing_passport_status():
    rows = parse_bookings(CSV_PATH)
    michal = next(r for r in rows if r["booking_ref"] == "ELAL-7734")
    assert michal["passport_status"] == "missing"
    assert "מיכל" in michal["customer_name"]
    assert michal["seat"] is None  # blank in sheet → NULL in DB


def test_all_four_booking_refs_present():
    rows = parse_bookings(CSV_PATH)
    refs = {row["booking_ref"] for row in rows}
    assert refs == {"ELAL-7734", "ELAL-2101", "ELAL-5580", "ELAL-3948"}


# --- insert logic ---------------------------------------------------------


def test_insert_bookings_runs_one_statement_per_row_and_commits():
    rows = parse_bookings(CSV_PATH)
    conn = FakeConn()

    inserted = insert_bookings(conn, rows)

    assert len(conn._cursor.calls) == 4
    assert inserted == 4
    assert conn.committed

    # Every statement uses the parameterised INSERT — no string interpolation
    # of untrusted values.
    for sql, values in conn._cursor.calls:
        assert sql.startswith("INSERT INTO bookings (")
        assert "ON CONFLICT (booking_ref) DO NOTHING" in sql
        assert len(values) == len(BOOKING_COLUMNS)


# --- init.sql structural checks ------------------------------------------


def test_init_sql_defines_all_three_tables():
    sql = INIT_SQL.read_text(encoding="utf-8")
    assert "CREATE TABLE support_requests" in sql
    assert "CREATE TABLE bookings" in sql
    assert "CREATE TABLE call_logs" in sql


def test_init_sql_keeps_original_support_request_seed_names():
    sql = INIT_SQL.read_text(encoding="utf-8")
    for name in ("John Smith", "Sarah Cohen", "David Levi", "Emma Johnson", "Michael Brown"):
        assert name in sql, f"missing original seed row: {name}"


def test_init_sql_marks_vapi_call_id_unique_on_call_logs():
    sql = INIT_SQL.read_text(encoding="utf-8")
    # Idempotency guard used by /vapi/end-of-call in the webhook service.
    assert "vapi_call_id" in sql
    assert "UNIQUE" in sql


def test_init_sql_adds_call_id_and_booking_ref_to_support_requests():
    sql = INIT_SQL.read_text(encoding="utf-8")
    assert "ALTER TABLE support_requests ADD COLUMN call_id" in sql
    assert "ALTER TABLE support_requests ADD COLUMN booking_ref" in sql


def test_init_sql_uses_transaction_block():
    sql = INIT_SQL.read_text(encoding="utf-8")
    # BEGIN/COMMIT wrap the DDL; leading -- comments are fine.
    assert "\nBEGIN;" in sql or sql.lstrip().startswith("BEGIN;")
    assert sql.rstrip().endswith("COMMIT;")

"""Seed the bookings table from the Google Sheet CSV export.

`voice-agent/data/check-in-calls.csv` is the source of truth (the Sheet's raw
export, 29 columns). Only the input columns — those known before the call — go
into the `bookings` table. Run this once after `db/init.sql` has created the
schema:

    DATABASE_URL=postgres://user:pw@host/db python db/load_bookings.py

The loader is idempotent (ON CONFLICT DO NOTHING) so re-running is safe. In
docker-compose (Phase 5) this runs as a one-shot service after the postgres
health check passes.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

try:
    import psycopg  # psycopg 3, installed via db/requirements.txt
except ImportError:  # pragma: no cover — tests exercise parse/insert directly.
    psycopg = None


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = REPO_ROOT / "voice-agent" / "data" / "check-in-calls.csv"

BOOKING_COLUMNS = [
    "booking_ref",
    "phone_number",
    "id_last4",
    "customer_name",
    "destination",
    "flight_date",
    "flight_number",
    "departure_time",
    "ticket_type",
    "baggage_allowance",
    "outbound_baggage_price",
    "return_baggage_price",
    "seat",
    "available_seats",
    "passport_status",
    "check_in_status",
    "priority_boarding_price",
    "meal_options",
    "lounge_access",
    "available_upgrades",
]

# Cells the Sheet may leave blank rather than "" — normalize to NULL so
# Postgres uses the column defaults where relevant.
NULLABLE_ON_BLANK = {"seat", "email"}


def parse_bookings(csv_path: Path) -> list[dict]:
    """Return one dict per booking, keyed by the target column names."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict] = []
        for raw in reader:
            row: dict[str, str | None] = {}
            for column in BOOKING_COLUMNS:
                value = (raw.get(column) or "").strip()
                if not value and column in NULLABLE_ON_BLANK:
                    row[column] = None
                else:
                    row[column] = value
            rows.append(row)
    return rows


def insert_bookings(conn, rows: list[dict]) -> int:
    """Insert rows; skip conflicts on booking_ref. Returns rows inserted."""
    columns_sql = ", ".join(BOOKING_COLUMNS)
    placeholders = ", ".join(["%s"] * len(BOOKING_COLUMNS))
    statement = (
        f"INSERT INTO bookings ({columns_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT (booking_ref) DO NOTHING"
    )
    inserted = 0
    with conn.cursor() as cursor:
        for row in rows:
            cursor.execute(statement, [row[column] for column in BOOKING_COLUMNS])
            if getattr(cursor, "rowcount", 0) and cursor.rowcount > 0:
                inserted += cursor.rowcount
    conn.commit()
    return inserted


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    csv_path = Path(argv[0]) if argv else DEFAULT_CSV
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL environment variable is required.", file=sys.stderr)
        return 2
    if psycopg is None:
        print("psycopg is not installed. `pip install 'psycopg[binary]'`", file=sys.stderr)
        return 1
    rows = parse_bookings(csv_path)
    with psycopg.connect(dsn) as conn:
        inserted = insert_bookings(conn, rows)
    print(f"inserted {inserted} bookings from {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

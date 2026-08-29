-- EL AL voice-ops: initial schema and seed data.
-- Mounted into /docker-entrypoint-initdb.d/ so Postgres runs it on first start.
-- The support_requests table keeps its original columns and seed rows from the
-- Langflow assignment untouched; new columns are added only via ALTER TABLE.

BEGIN;

CREATE TABLE support_requests (
  id SERIAL PRIMARY KEY,
  customer_name VARCHAR(100),
  email VARCHAR(255),
  category VARCHAR(100),
  priority VARCHAR(50),
  status VARCHAR(50),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Original 5 seed rows from the Langflow assignment. Do not modify.
INSERT INTO support_requests (customer_name, email, category, priority, status) VALUES
  ('John Smith',    'john.smith@example.com',    'Billing',         'High',   'Open'),
  ('Sarah Cohen',   'sarah.cohen@example.com',   'Baggage',         'Medium', 'Open'),
  ('David Levi',    'david.levi@example.com',    'Flight Change',   'Low',    'Resolved'),
  ('Emma Johnson',  'emma.johnson@example.com',  'Refund',          'High',   'Open'),
  ('Michael Brown', 'michael.brown@example.com', 'Loyalty Program', 'Medium', 'Open');

CREATE TABLE bookings (
  booking_ref             VARCHAR(20) PRIMARY KEY,
  phone_number            VARCHAR(30),
  id_last4                CHAR(4),
  customer_name           VARCHAR(100),
  email                   VARCHAR(255),
  destination             VARCHAR(100),
  flight_date             DATE,
  flight_number           VARCHAR(10),
  departure_time          TIME,
  ticket_type             VARCHAR(20),
  baggage_allowance       TEXT,
  outbound_baggage_price  VARCHAR(20),
  return_baggage_price    VARCHAR(20),
  seat                    VARCHAR(10),
  available_seats         TEXT,
  passport_status         VARCHAR(20),
  check_in_status         VARCHAR(20),
  priority_boarding_price VARCHAR(20),
  meal_options            TEXT,
  lounge_access           VARCHAR(10),
  available_upgrades      TEXT
);

CREATE TABLE call_logs (
  id                      SERIAL PRIMARY KEY,
  booking_ref             VARCHAR(20) REFERENCES bookings(booking_ref),
  vapi_call_id            VARCHAR(80) UNIQUE, -- idempotency guard for /vapi/end-of-call
  call_status             VARCHAR(40),
  checkin_completed       BOOLEAN,
  baggage_changed         TEXT,
  final_seat              VARCHAR(10),
  ancillary_selected      TEXT,
  unresolved_request      TEXT,
  human_followup_required BOOLEAN,
  call_summary            TEXT,
  recording_url           TEXT,
  call_timestamp          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE support_requests ADD COLUMN call_id     INT REFERENCES call_logs(id);
ALTER TABLE support_requests ADD COLUMN booking_ref VARCHAR(20);

COMMIT;

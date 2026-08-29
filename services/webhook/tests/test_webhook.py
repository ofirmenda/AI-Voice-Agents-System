"""End-to-end tests for /vapi/end-of-call.

Uses an in-memory FakeRepository that implements the BookingRepository
interface, so the endpoint runs its full flow without a live Postgres.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import create_app, derive_category, derive_priority
from repository import BookingRepository


FIXTURE = Path(__file__).parent / "fixtures" / "vapi_end_of_call.json"
SECRET = "test-secret-42"


class FakeRepository(BookingRepository):
    def __init__(self) -> None:
        self.bookings: dict[str, dict] = {
            "ELAL-7734": {
                "customer_name": "מיכל אברהם",
                "email": None,
                "passport_status": "missing",
            },
            "ELAL-3948": {
                "customer_name": "אבי לוי",
                "email": "avi.levi@example.com",
                "passport_status": "valid",
            },
        }
        self.call_logs: dict[int, dict] = {}
        self.support_requests: list[dict] = []
        self.commits = 0
        self.rollbacks = 0
        self._next_call_id = 100
        self._next_support_id = 200

    def get_booking(self, booking_ref):
        row = self.bookings.get(booking_ref)
        return dict(row) if row else None

    def find_call_by_vapi_id(self, vapi_call_id):
        for cid, log in self.call_logs.items():
            if log["vapi_call_id"] == vapi_call_id:
                return cid
        return None

    def insert_call_log(self, data):
        cid = self._next_call_id
        self._next_call_id += 1
        self.call_logs[cid] = dict(data)
        return cid

    def insert_support_request(self, data):
        sid = self._next_support_id
        self._next_support_id += 1
        row = dict(data)
        row["id"] = sid
        self.support_requests.append(row)
        return sid

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def client(repo: FakeRepository) -> TestClient:
    app = create_app(repo_factory=lambda: repo, webhook_secret=SECRET)
    return TestClient(app)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- auth ----------------------------------------------------------------


def test_missing_secret_returns_401(client):
    response = client.post("/vapi/end-of-call", json=_payload())
    assert response.status_code == 401


def test_wrong_secret_returns_401(client):
    response = client.post(
        "/vapi/end-of-call",
        json=_payload(),
        headers={"X-Webhook-Secret": "not-the-secret"},
    )
    assert response.status_code == 401


# --- happy path & ticket rules ------------------------------------------


def test_happy_path_writes_call_log_and_high_priority_documents_ticket(client, repo):
    response = client.post(
        "/vapi/end-of-call",
        json=_payload(),
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["idempotent"] is False
    assert body["call_id"] is not None
    assert body["support_request_id"] is not None

    # call_logs — one row, all the pieces of the payload wired through.
    assert len(repo.call_logs) == 1
    log = next(iter(repo.call_logs.values()))
    assert log["booking_ref"] == "ELAL-7734"
    assert log["vapi_call_id"] == "vapi-call-2b5d1f9e-7734"
    assert log["human_followup_required"] is True
    assert log["checkin_completed"] is False
    assert "דרכון" in log["unresolved_request"]
    assert log["recording_url"].endswith(".wav")

    # support_requests — one ticket, priority=High because passport is missing,
    # category=documents from the Hebrew keyword classifier.
    assert len(repo.support_requests) == 1
    ticket = repo.support_requests[0]
    assert ticket["customer_name"] == "מיכל אברהם"
    assert ticket["priority"] == "High"
    assert ticket["category"] == "documents"
    assert ticket["status"] == "Open"
    assert ticket["booking_ref"] == "ELAL-7734"
    assert ticket["call_id"] == body["call_id"]

    assert repo.commits == 1
    assert repo.rollbacks == 0


def test_no_ticket_when_human_followup_not_required(client, repo):
    payload = _payload()
    payload["message"]["call"]["id"] = "vapi-call-happy-3948"
    payload["message"]["call"]["metadata"]["booking_ref"] = "ELAL-3948"
    structured = payload["message"]["analysis"]["structuredData"]
    structured["human_followup_required"] = False
    structured["checkin_completed"] = True
    structured["unresolved_request"] = ""

    response = client.post(
        "/vapi/end-of-call",
        json=payload,
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 200
    assert response.json()["support_request_id"] is None
    assert len(repo.support_requests) == 0
    assert len(repo.call_logs) == 1


# --- errors --------------------------------------------------------------


def test_unknown_booking_returns_404_and_writes_nothing(client, repo):
    payload = _payload()
    payload["message"]["call"]["metadata"]["booking_ref"] = "ELAL-9999"

    response = client.post(
        "/vapi/end-of-call",
        json=payload,
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 404
    assert len(repo.call_logs) == 0
    assert len(repo.support_requests) == 0
    assert repo.commits == 0
    assert repo.rollbacks == 1


def test_malformed_payload_is_422(client):
    response = client.post(
        "/vapi/end-of-call",
        json={"nonsense": True},
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 422


def test_missing_booking_ref_is_422(client, repo):
    payload = _payload()
    payload["message"]["call"]["metadata"] = {}

    response = client.post(
        "/vapi/end-of-call",
        json=payload,
        headers={"X-Webhook-Secret": SECRET},
    )
    assert response.status_code == 422
    assert len(repo.call_logs) == 0


# --- idempotency --------------------------------------------------------


def test_replay_of_same_vapi_call_id_is_idempotent(client, repo):
    payload = _payload()

    first = client.post(
        "/vapi/end-of-call",
        json=payload,
        headers={"X-Webhook-Secret": SECRET},
    )
    second = client.post(
        "/vapi/end-of-call",
        json=copy.deepcopy(payload),
        headers={"X-Webhook-Secret": SECRET},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    assert second.json()["call_id"] == first.json()["call_id"]

    # No duplicate rows in either table.
    assert len(repo.call_logs) == 1
    assert len(repo.support_requests) == 1


# --- pure derivations ---------------------------------------------------


def test_derive_category_prefers_documents_over_baggage():
    assert derive_category("הדרכון חסר, גם המזוודה") == "documents"


def test_derive_category_baggage_hebrew():
    assert derive_category("הנוסע ביקש מזוודה נוספת") == "baggage"


def test_derive_category_seat_english():
    assert derive_category("preferred seat unavailable") == "seat"


def test_derive_category_other_default():
    assert derive_category(None) == "other"
    assert derive_category("") == "other"


def test_derive_priority_high_on_missing_passport():
    assert derive_priority("missing", True) == "High"


def test_derive_priority_high_on_incomplete_checkin():
    assert derive_priority("valid", False) == "High"


def test_derive_priority_medium_when_all_ok():
    assert derive_priority("valid", True) == "Medium"

"""Vapi post-call webhook.

Consumes the end-of-call-report Vapi sends when a check-in call finishes,
writes a `call_logs` row, and — if the AI decided human follow-up is needed —
opens a `support_requests` ticket for the async Langflow triage pipeline.
Idempotent on the Vapi call id.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from repository import BookingRepository, DbError, RealPostgresRepository

logger = logging.getLogger("webhook")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


# --- payload models -------------------------------------------------------


class Call(BaseModel):
    id: str = Field(..., min_length=1)
    metadata: dict = Field(default_factory=dict)
    recordingUrl: Optional[str] = None
    endedReason: Optional[str] = None


class StructuredData(BaseModel):
    call_status: str = ""
    checkin_completed: bool = False
    baggage_changed: Optional[str] = None
    final_seat: Optional[str] = None
    ancillary_selected: Optional[str] = None
    unresolved_request: Optional[str] = None
    human_followup_required: bool = False


class Analysis(BaseModel):
    structuredData: StructuredData = Field(default_factory=StructuredData)


class Message(BaseModel):
    type: str
    call: Call
    summary: Optional[str] = None
    transcript: Optional[str] = None
    analysis: Analysis = Field(default_factory=Analysis)


class Payload(BaseModel):
    message: Message


# --- derivations ---------------------------------------------------------


CATEGORY_KEYWORDS = {
    "documents": ["דרכון", "תעודת זהות", "ויזה", "passport", "visa"],
    "baggage": ["מזוודה", "כבודה", "משקל", "baggage", "luggage"],
    "seat": ["מושב", "שורה", "מקום", "seat", "row"],
}


def derive_category(unresolved_request: Optional[str]) -> str:
    """Rough keyword classifier for ticket categorisation.

    Order matters: documents beats baggage beats seat. A request that touches
    multiple topics is filed under the most action-blocking one.
    """
    text = (unresolved_request or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in keywords):
            return category
    return "other"


def derive_priority(passport_status: Optional[str], checkin_completed: bool) -> str:
    if passport_status == "missing" or not checkin_completed:
        return "High"
    return "Medium"


# --- app factory ---------------------------------------------------------


def create_app(
    *,
    repo_factory: Optional[Callable[[], BookingRepository]] = None,
    webhook_secret: Optional[str] = None,
) -> FastAPI:
    """Factory so tests can inject a fake repository and a known secret."""
    resolved_secret = (
        webhook_secret if webhook_secret is not None else os.environ.get("WEBHOOK_SECRET", "")
    )

    app = FastAPI(title="EL AL post-call webhook")
    app.state.repo_factory = repo_factory
    app.state.webhook_secret = resolved_secret

    def _get_repo(request: Request) -> BookingRepository:
        factory = request.app.state.repo_factory
        if factory is not None:
            return factory()
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            raise HTTPException(status_code=503, detail="database not configured")
        try:
            return RealPostgresRepository.connect(dsn)
        except DbError as error:
            logger.exception("database unreachable")
            raise HTTPException(status_code=503, detail="database unavailable") from error

    @app.post("/vapi/end-of-call")
    def end_of_call(
        payload: Payload,
        request: Request,
        x_webhook_secret: Optional[str] = Header(default=None),
    ) -> dict:
        expected = request.app.state.webhook_secret
        if not expected or x_webhook_secret != expected:
            raise HTTPException(status_code=401, detail="invalid webhook secret")

        message = payload.message
        if message.type != "end-of-call-report":
            raise HTTPException(
                status_code=422,
                detail=f"unsupported message type: {message.type}",
            )
        booking_ref = message.call.metadata.get("booking_ref")
        if not booking_ref:
            raise HTTPException(
                status_code=422,
                detail="call.metadata.booking_ref missing",
            )

        repo = _get_repo(request)
        try:
            booking = repo.get_booking(booking_ref)
            if booking is None:
                raise HTTPException(status_code=404, detail=f"unknown booking_ref: {booking_ref}")

            existing = repo.find_call_by_vapi_id(message.call.id)
            if existing is not None:
                logger.info("replay of vapi call %s — no-op", message.call.id)
                return {
                    "call_id": existing,
                    "support_request_id": None,
                    "idempotent": True,
                }

            structured = message.analysis.structuredData
            call_id = repo.insert_call_log({
                "booking_ref": booking_ref,
                "vapi_call_id": message.call.id,
                "call_status": structured.call_status or "",
                "checkin_completed": structured.checkin_completed,
                "baggage_changed": structured.baggage_changed,
                "final_seat": structured.final_seat,
                "ancillary_selected": structured.ancillary_selected,
                "unresolved_request": structured.unresolved_request,
                "human_followup_required": structured.human_followup_required,
                "call_summary": message.summary or "",
                "recording_url": message.call.recordingUrl,
            })

            support_request_id: Optional[int] = None
            if structured.human_followup_required:
                support_request_id = repo.insert_support_request({
                    "customer_name": booking["customer_name"],
                    "email": booking["email"],
                    "category": derive_category(structured.unresolved_request),
                    "priority": derive_priority(
                        booking["passport_status"], structured.checkin_completed
                    ),
                    "status": "Open",
                    "call_id": call_id,
                    "booking_ref": booking_ref,
                })

            repo.commit()
            logger.info(
                "call_logs id=%s support_request_id=%s booking_ref=%s",
                call_id, support_request_id, booking_ref,
            )
            return {
                "call_id": call_id,
                "support_request_id": support_request_id,
                "idempotent": False,
            }

        except HTTPException:
            repo.rollback()
            raise
        except DbError as error:
            repo.rollback()
            logger.exception("database error while handling end-of-call")
            raise HTTPException(status_code=500, detail="database error") from error
        except Exception:
            repo.rollback()
            raise

    return app


app = create_app()

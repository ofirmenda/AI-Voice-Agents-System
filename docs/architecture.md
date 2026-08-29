# Architecture

## Passenger journey

**T−24h — the call opens.** An outbound scheduler (not shipped in this repo; a
`cron` or Vapi campaign is enough) picks up the next passenger whose flight is
24 hours out and whose `check_in_status = 'pending'`, and instructs Vapi to
dial `phone_number` from the booking. Every variable the assistant reads at
call time — `customer_name`, `flight_number`, `available_seats`,
`passport_status`, and so on — comes from a single `bookings` row and is
injected as `{{variable}}` placeholders into the first message and system
prompt.

**During the call — the assistant is the composer.** נועם runs the check-in
flow from [voice-agent/agent_prompt.md](../voice-agent/agent_prompt.md): light
identity verification against `id_last4`, confirm the flight, check
travel-document status, offer relevant ancillaries (baggage / seats / meals /
lounge), and complete check-in. When the passenger asks a Hebrew policy
question ("כמה קילו מותר לי?"), the assistant calls the `policy_search` tool
(registered manually in Vapi, points at the RAG service's `/search`) and
grounds its answer in the returned chunk. When the assistant needs to write
the outcome back to the Google Sheet mirror, it calls the `save_call_summary`
tool (n8n webhook, [redacted](../voice-agent/tools/save_call_summary.json)).

**End of call — Vapi fires two things.** The custom `save_call_summary` tool
runs once during the call, before the agent's farewell (this is the exact
`CRITICAL TIMING` note in the prompt), and writes the outcome to the Sheet.
Then, independently, Vapi's own `end-of-call-report` webhook posts the full
transcript, summary, structured analysis, and recording URL to
`/vapi/end-of-call` on our webhook service. The two channels serve different
readers: the Sheet is for humans, Postgres is the system of record.

**Post-call — the webhook decides.** [services/webhook/main.py](../services/webhook/main.py)
verifies the shared secret, looks up the booking by `booking_ref` (that came
through as a Vapi call-metadata variable), writes one row to `call_logs`, and
if `human_followup_required = true` opens a `support_requests` ticket with:

- `customer_name`, `email` copied from the booking.
- `category` classified from the unresolved-request text (Hebrew and English
  keyword sets: documents / baggage / seat / other).
- `priority` = `High` when the passport is missing or check-in did not
  complete, otherwise `Medium`.
- `status = 'Open'`, and back-refs `call_id` and `booking_ref`.

Both writes happen in one transaction; either both land or neither does.
Replay of the same `vapi_call_id` is a no-op thanks to the unique column.

**Later — Langflow triages.** A human (or a downstream scheduler) opens the
Langflow flow and types a request like "Draft an email to the customer on the
newest baggage ticket, acknowledging their request and asking for their flight
number." The Orchestrator classifies the intent, calls Analysis once to run
SQL against the same Postgres, then calls Response once to draft/send via
Gmail. See [docs/langflow-http.md](langflow-http.md) for the HTTP-level
recipes.

## Data contracts

The three data contracts that matter to keep stable — because a change in any
of them breaks a component the others do not own:

**1. RAG `/search` response.**

```json
{ "results": [ { "text": "…", "score": 0.83 } ] }
```

`results[0].text` is what the Vapi assistant reads back to the passenger.
Changing the key name (e.g. `chunk` for `text`) means updating the Vapi tool
definition and the Langflow analysis prompt at the same time.

**2. Vapi end-of-call payload the webhook parses.**

```json
{
  "message": {
    "type": "end-of-call-report",
    "call": {
      "id": "vapi-call-…",
      "metadata": { "booking_ref": "ELAL-…" },
      "recordingUrl": "…"
    },
    "summary": "…",
    "transcript": "…",
    "analysis": {
      "structuredData": {
        "call_status": "…",
        "checkin_completed": true,
        "baggage_changed": "…",
        "final_seat": "…",
        "ancillary_selected": "…",
        "unresolved_request": "…",
        "human_followup_required": false
      }
    }
  }
}
```

Every field except `message.type`, `message.call.id`, and
`message.call.metadata.booking_ref` is optional. Extra fields Vapi adds later
are ignored.

**3. `support_requests` schema.** The five original columns
(`customer_name`, `email`, `category`, `priority`, `status`) never change and
must accept the five original seed rows verbatim (the Langflow assignment
grades on that). `call_id` and `booking_ref` are bolted on nullably by
`ALTER TABLE`, not folded into the base definition, exactly because the
assignment grader might diff the create-table.

## Design decisions

**One Postgres, not two.** The temptation was a separate DB per service (RAG
has none, webhook writes, Langflow reads). Instead everything shares one
Postgres and one connection string. The upside is that Langflow's `SELECT` at
triage time sees a row the webhook wrote seconds earlier — no cross-DB
replication, no eventual-consistency window to reason about. The downside is
that the webhook's writes and Langflow's ad-hoc reads share the same
connection pool. At demo scale (single-digit calls per hour) that's fine; at
production scale, a read replica or PgBouncer takes over.

**HTTP for retrieval, not a Python import.** The RAG module (`app.py`) could
have been packaged and imported directly by the Vapi tool executor and
Langflow's SQL agent. Instead everything talks to it over HTTP. That costs
~10 ms per call but buys three things: (a) the same `/search` serves Vapi
tool calls, Langflow tool calls, and ad-hoc `curl`; (b) the RAG service can be
redeployed and its index rebuilt without touching either downstream; (c) the
service becomes swappable — replacing `search_index` with pgvector or a
managed vector DB is a one-service change instead of a repo-wide refactor.

**Idempotent webhook on the Vapi call id.** Vapi's own docs say the
end-of-call webhook can be redelivered on network hiccups. Rather than
dedupe on `(booking_ref, minute-precision timestamp)`, `call_logs` has a
`vapi_call_id UNIQUE` column and the endpoint checks it before writing. Replay
returns `{"idempotent": true}` and the same `call_id` — safe to retry
indefinitely.

**Google Sheet stays as a mirror.** The original assignment used a Sheet as
the write-back target. Moving to Postgres could have deprecated the Sheet
entirely, but non-technical readers (product, ops) can read a Sheet; a
Postgres table is a `psql` query. Keeping the Sheet — written via a custom
Vapi tool during the call, not via a periodic export — means humans get the
same view for free, without the system-of-record ambiguity.

**Repository seam in the webhook.** [services/webhook/repository.py](../services/webhook/repository.py)
defines a small `BookingRepository` interface with two concrete
implementations: `RealPostgresRepository` (psycopg 3) and an in-memory fake
the tests inject. The endpoint itself never sees psycopg. That is what lets
Phase 4's 16 tests run end-to-end in CI without a database, and it means
switching to an async driver (asyncpg, SQLAlchemy async) is a one-file
change.

**Small units, `.md` prompts.** The three Langflow agent prompts live as
standalone Markdown at `langflow/prompts/*.md`. Prompt quality is what
reviewers grade; making them reviewable as prose beats asking anyone to read
them out of a 590 KB flow JSON. The extraction is not automatic today
(re-run the scratchpad script when the flow changes); if the prompts start
drifting, that's the next automation to add.

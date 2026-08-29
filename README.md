# AI-Voice-Agents-System

![tests](https://github.com/ofirmenda/AI-Voice-Agents-System/actions/workflows/tests.yml/badge.svg)

A system of cooperating AI agents that share responsibility for a customer service journey. A **real-time Hebrew voice agent** (נועם) dials the customer over the phone and runs the conversation live. An **asynchronous multi-agent Langflow pipeline** — orchestrator → analysis → response — picks up whatever the voice call couldn't close and drafts a reply by email. The demo applies the system to airline check-in: the voice agent dials passengers 24 h before departure, completes check-in, answers policy questions from a retrieval service, offers relevant ancillary services, and turns unresolved requests into support tickets. Langflow then reads those tickets, runs SQL against the shared Postgres, and sends replies through Gmail. Everything runs behind one HTTP RAG service and one Postgres so the pieces stay swappable.

> **Disclaimer.** This is a portfolio demonstration built around EL AL Israel Airlines as the application domain. Policy documents, pricing, and passenger data are illustrative and not authorised by EL AL. The architecture is domain-neutral and reuses cleanly for hotel check-in, appointment reminders, insurance intake, and any other proactive service journey.

## Architecture

```
Scheduler (T-24h)  ──▶  Vapi voice agent (Hebrew)  ◀──▶  RAG service /search
                                  │                            ▲
                                  ▼                            │
                        Post-call webhook                      │
                                  │                            │
                                  ▼                            │
                    Postgres: bookings, call_logs,             │
                              support_requests                 │
                                  │                            │
                                  ▼                            │
                    Langflow: orchestrator ▶ analysis ▶ response
                              (SQL tool)      (Gmail tool)
```

One Postgres is the system of record. The Google Sheet stays as a human-readable mirror (via a legacy n8n tool call on the Vapi assistant), not the source of truth. Full journey and data contracts are in [docs/architecture.md](docs/architecture.md).

## Quickstart

```bash
cp .env.example .env
# edit .env — set OPENAI_API_KEY and WEBHOOK_SECRET at minimum
docker compose up --build
```

That brings up:

| Service   | URL                      | What                                       |
|-----------|--------------------------|--------------------------------------------|
| postgres  | `localhost:5432`         | schema + 5 support_requests seeds          |
| db-seed   | –                        | one-shot, loads 4 bookings from the Sheet CSV |
| rag       | `http://localhost:8001`  | `/health`, `/search`, `/ingest`            |
| webhook   | `http://localhost:8002`  | `/vapi/end-of-call`                        |
| langflow  | `http://localhost:7860`  | Playground UI (import `langflow/flow.json`) |

After `docker compose up`, ingest the Hebrew policy corpus so `/search` works:

```bash
for p in baggage hand-luggage check-in-windows meals-and-kosher seats-and-boarding; do
  curl -sS -X POST http://localhost:8001/ingest \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"/app/docs/policies/${p}.md\"}"
done
```

Confirm retrieval:

```bash
curl -sS http://localhost:8001/health
curl -sS -X POST http://localhost:8001/search \
  -H "Content-Type: application/json" \
  -d '{"question": "כמה קילו מזוודה מותרות לי בכרטיס Lite?"}'
```

## One measured number

Of the four example calls seeded from the Google Sheet, **1/4 = 25% closed without human touch** (`ELAL-3948`, אבי לוי). Three needed follow-up: a missing passport (`ELAL-7734`), a seat swap that could not be confirmed on the call (`ELAL-2101`), and a Premium upgrade price bargaining request (`ELAL-5580`). Two of those three were still successful check-ins — the follow-up is only for the ancillary. The number to watch as the system runs is not "share of calls where a human helped" but "share of *check-ins* that completed autonomously," which on the same four rows is **3/4 = 75%**. `/search` p50 latency is logged per request in the RAG container as `latency_ms` and should be extracted for the next revision of this number.

## Components

### Voice agent — `voice-agent/`

Runs on Vapi. Hebrew system prompt for נועם is in [voice-agent/agent_prompt.md](voice-agent/agent_prompt.md) (a copy is also inlined in [vapi-assistant.json](voice-agent/vapi-assistant.json)); if you edit one, edit the other. The prompt covers the Hebrew-only rule, masculine self-reference, spoken-number rules, pronunciation overrides for EL AL / check-in / lounge, a `## Current Booking Data` block of `{{variable}}` placeholders bound to the Sheet columns, and the core principle that add-on failures never block check-in — only missing documents or an unconfirmed safety question do. Two custom tools are exported at [voice-agent/tools/](voice-agent/tools/): `end_outbound_call` (Vapi endCall) and `save_call_summary` (apiRequest to n8n → Google Sheet, URL redacted before commit).

The 4-row Sheet export the Vapi assistant reads at call time and writes back to lives at [voice-agent/data/check-in-calls.csv](voice-agent/data/check-in-calls.csv). This is also the source the [db/load_bookings.py](db/load_bookings.py) loader uses to seed Postgres.

### RAG service — `services/rag/`

FastAPI wrapper around the existing embeddings CLI. Stable response contract for tool callers: `results[0].text`. Three endpoints:

- `GET /health` → `{status, chunks, source}`
- `POST /search` → `{results: [{text, score}]}`; 422 on empty question, 503 with no index
- `POST /ingest` → `{chunks}`; accepts `.txt`, `.md`, `.pdf`

Index is loaded once at startup and kept in memory; every query is logged with a `latency_ms` field so the README number is directly derivable from container logs.

### Post-call webhook — `services/webhook/`

FastAPI single-endpoint receiver for Vapi's automatic `end-of-call-report`. Verifies `X-Webhook-Secret`, looks up the booking, writes one row to `call_logs`, and — only when `human_followup_required` is true — opens a `support_requests` ticket for Langflow. Idempotent on `vapi_call_id`. Category is derived from the unresolved-request text (documents / baggage / seat / other, Hebrew and English keyword sets); priority is High when the passport is missing or check-in did not complete, otherwise Medium.

### Database — `db/`

Single Postgres. [db/init.sql](db/init.sql) creates `support_requests` (original assignment columns + `call_id`, `booking_ref` bolted on nullably), `bookings`, and `call_logs` (with `vapi_call_id UNIQUE` for webhook idempotency), and seeds the original 5 support_requests rows verbatim. [db/load_bookings.py](db/load_bookings.py) runs after Postgres is healthy and inserts the 4 booking rows from the CSV using `ON CONFLICT (booking_ref) DO NOTHING`.

### Multi-agent triage — `langflow/`

Three Agents wired agent-as-tool: **Orchestrator** (memory tool + Analysis as a tool) → **Analysis** (SQL tool against the shared Postgres) → **Response** (Gmail via Composio). Prompts extracted to reviewable Markdown at [langflow/prompts/](langflow/prompts/). Running the flow over HTTP is documented in [docs/langflow-http.md](docs/langflow-http.md). Model comparison and rationale in [docs/model-comparison.md](docs/model-comparison.md).

## Demo assets

- Deck (7 slides, PDF): [docs/presentation.pdf](docs/presentation.pdf)
- Hebrew check-in call recording: [docs/demo/voice recording.wav](docs/demo/voice%20recording.wav)
- Langflow walkthrough (screen recording): [docs/demo/flow_presentation.mp4](docs/demo/flow_presentation.mp4)

## Tests

```bash
pytest -v
```

The suite covers RAG (unit + API), database (schema and CSV loader), webhook (happy path, ticket creation, no-ticket, unknown booking, replay-idempotency, category/priority derivation), and compose plumbing. Live embeddings tests skip cleanly when `OPENAI_API_KEY` is unset, which is how CI runs.

## What I would do next

- **Real telephony.** Vapi handles PSTN today via Twilio behind the scenes — swap the Twilio number to a purchased Israeli DID and add the outbound queue (scheduler at T-24h) that Vapi doesn't provide out of the box.
- **pgvector.** The RAG index is a JSON blob loaded into process memory. Move embeddings into a `chunks` table with a `vector(1536)` column and an IVF-Flat index; `/search` becomes a `SELECT ... ORDER BY embedding <=> $1 LIMIT k` and the whole service becomes horizontally scalable.
- **Latency budget.** A voice conversation has a hard budget of ~1500 ms round-trip before it feels awkward. Right now that budget is split across Deepgram (STT), the LLM, `/search`, and Vapi's default TTS. Instrument each hop, publish a p50/p95 dashboard, and cache the top-k policy chunks for the ~20 most common Hebrew baggage/seat/meal questions so `/search` on those never hits OpenAI.

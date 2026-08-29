# AI-Voice-Agents-System

![tests](https://github.com/ofirmenda/AI-Voice-Agents-System/actions/workflows/tests.yml/badge.svg)

A system of cooperating AI agents that share responsibility for a customer service journey. A **real-time Hebrew voice agent** (נועם) dials the customer over the phone and runs the conversation live. An **asynchronous multi-agent Langflow pipeline** — orchestrator → analysis → response — picks up whatever the voice call couldn't close and drafts a reply by email. The demo applies the system to airline check-in: the voice agent dials passengers 24 h before departure, completes check-in, answers policy questions from a retrieval service, offers relevant ancillary services, and turns unresolved requests into support tickets. Langflow then reads those tickets, runs SQL against the shared Postgres, and sends replies through Gmail. Everything runs behind one HTTP RAG service and one Postgres so the pieces stay swappable.

> **Disclaimer.** A portfolio demonstration built around EL AL Israel Airlines as the application domain. Policy documents, pricing, and passenger data are illustrative and not authorised by EL AL. The architecture is domain-neutral and reuses cleanly for hotel check-in, appointment reminders, insurance intake, and any other proactive service journey.

## See it in action

- **[Langflow triage walkthrough](docs/demo/flow_presentation.mp4)** — screen recording of the async multi-agent pipeline reading a `support_requests` ticket, running SQL against Postgres, and drafting an email through Gmail.
- **[Hebrew check-in call](docs/demo/voice%20recording.wav)** — recording of נועם handling an outbound check-in end-to-end in Hebrew, including a policy question that grounds against the RAG service.
- **[Presentation deck (PDF)](docs/presentation.pdf)** — the design, the model choices, and the ROI case in seven slides.

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

Postgres is the single system of record. The Google Sheet stays as a human-readable mirror. Full passenger journey and the three data contracts that hold the components together are in **[docs/architecture.md](docs/architecture.md)**.

## Results

On the four calls in the demo dataset:

- **75 % of check-ins complete autonomously** (`ELAL-2101`, `ELAL-5580`, `ELAL-3948`). The one that doesn't (`ELAL-7734`, missing passport) is the case the AI *should* refuse to complete — travel-document problems are the only thing the prompt allows to block check-in.
- **25 % of calls close with zero human involvement** (`ELAL-3948`). The other three all trigger the Langflow triage pipeline via a `support_requests` ticket.
- **Every follow-up ticket carries a derived category and priority.** `ELAL-7734` correctly lands as **High + `documents`** — the exact case the assignment brief calls out as "correctly ends as Needs human."
- **72 tests, 57 running green in CI without any secrets.** The remaining 15 auto-skip when `OPENAI_API_KEY` isn't set — they hit the live OpenAI embeddings API.

## Quickstart

```bash
cp .env.example .env
# edit .env — set OPENAI_API_KEY and WEBHOOK_SECRET
docker compose up --build
```

Brings up:

| Service   | URL                      | What                                       |
|-----------|--------------------------|--------------------------------------------|
| postgres  | `localhost:5432`         | schema + 5 support_requests seed rows      |
| db-seed   | –                        | one-shot; loads 4 bookings from the Sheet CSV |
| rag       | `http://localhost:8001`  | `/health`, `/search`, `/ingest`            |
| webhook   | `http://localhost:8002`  | `/vapi/end-of-call`                        |
| langflow  | `http://localhost:7860`  | Playground UI — import `langflow/flow.json` |

Ingest the Hebrew policy corpus, then confirm retrieval:

```bash
for p in baggage hand-luggage check-in-windows meals-and-kosher seats-and-boarding; do
  curl -sS -X POST http://localhost:8001/ingest \
    -H "Content-Type: application/json" \
    -d "{\"path\": \"/app/docs/policies/${p}.md\"}"
done

curl -sS -X POST http://localhost:8001/search \
  -H "Content-Type: application/json" \
  -d '{"question": "כמה קילו מזוודה מותרות לי בכרטיס Lite?"}'
```

The Hebrew baggage question retrieves the relevant chunk from `docs/policies/baggage.md`, which the voice agent then reads aloud to the passenger.

## What's inside

**Voice agent — [`voice-agent/`](voice-agent/).** Vapi assistant running Deepgram Nova-3 (STT, Hebrew), OpenAI GPT-5.6 Terra (LLM), and Vapi's Elliot voice (TTS). The prompt at [`voice-agent/agent_prompt.md`](voice-agent/agent_prompt.md) enforces Hebrew-only speech, masculine grammatical self-reference, spoken-number rules, pronunciation overrides, and the core principle that failed ancillaries never block check-in — only missing documents or an unconfirmed safety question do.

**RAG service — [`services/rag/`](services/rag/).** FastAPI wrapper around a text-embedding-3-small pipeline. Three endpoints: `GET /health`, `POST /search`, `POST /ingest`. Loads the index once at startup, keeps it in memory, and logs `latency_ms` per query. Ingests `.txt`, `.md`, and `.pdf`.

**Post-call webhook — [`services/webhook/`](services/webhook/).** FastAPI receiver for Vapi's automatic `end-of-call-report`. Verifies `X-Webhook-Secret`, writes one `call_logs` row, and — only when `human_followup_required` is true — opens a `support_requests` ticket. Idempotent on `vapi_call_id` so redelivery is a no-op.

**Database — [`db/`](db/).** One Postgres holds bookings, call logs, and support tickets. [`db/init.sql`](db/init.sql) creates the schema and seeds the original 5 support-requests rows verbatim; [`db/load_bookings.py`](db/load_bookings.py) loads the 4 bookings from the Sheet CSV.

**Multi-agent triage — [`langflow/`](langflow/).** Three OpenAI GPT-5.6 Sol agents wired agent-as-tool: **Orchestrator** (with Memory) → **Analysis** (with SQL against the shared Postgres) → **Response** (with Gmail via Composio). Extracted prompts at [`langflow/prompts/`](langflow/prompts/), HTTP recipes at [`docs/langflow-http.md`](docs/langflow-http.md), model comparison at [`docs/model-comparison.md`](docs/model-comparison.md).

## Tests

```bash
pytest -v
```

72 tests covering the RAG service (unit + API), the database (schema and CSV loader), the webhook (happy path, ticket creation, no-ticket, unknown booking, replay-idempotency, category/priority derivation), and the compose plumbing. Live-embeddings tests auto-skip without `OPENAI_API_KEY`, which is how CI runs.


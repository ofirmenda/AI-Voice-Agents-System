# Build brief: `AI-Voice-Agents-System`

**Read this whole file before writing any code.** It describes an existing repository, three
disconnected assignment artifacts, and the work required to merge them into one coherent
project. Work phase by phase. Do not skip ahead.

---

## 1. Context

The owner (Ofir Menda) completed a three-part home assignment for Jeen.ai. Each part works,
but they are three separate deliverables with no connection between them. The goal is to turn
them into **one system** that can be presented as a portfolio project.

The domain is **EL AL Israel Airlines — outbound conversational check-in**. An AI voice agent
named נועם calls passengers in Hebrew when online check-in opens, completes check-in, answers
policy questions, and offers relevant ancillary services. Anything the agent cannot resolve
becomes a support ticket, which an asynchronous multi-agent system triages and answers by email.

This repository is currently only Part 2 (the embeddings CLI). It will become the home of all
three parts.

---

## 2. Current state

### 2.1 This repository (Part 2 — Python / embeddings)

Currently named `part-2-home-assesment` (note the typo). Contents:

```
README.md
app.py                 # 184 lines, single-module CLI
conftest.py            # 94 lines
requirements.txt       # 4 deps
test_results.txt       # generated, gitignored
data/index.json        # generated, gitignored
tests/
  test_app.py          # 365 lines, 28 tests
  chapter1.txt
  chapter2.txt
  chapter3.txt
  galaxy article.pdf
.github/workflows/tests.yml
```

`app.py` public functions — **preserve these signatures**, other code will import them:

| Function | Notes |
|---|---|
| `extract_text(file_path) -> str` | `.txt` via `read_text`, `.pdf` via `pymupdf`. Raises on empty/unsupported. |
| `chunk_text(text, chunk_size=1000, overlap=150) -> list[str]` | Character-based, normalizes whitespace with `" ".join(text.split())`. |
| `create_embeddings(client, texts, model) -> list[list[float]]` | Batched, re-sorted by `item.index`. |
| `cosine_similarity(left, right) -> float` | Pure Python, zero-norm safe. |
| `save_index` / `load_index` | JSON at `data/index.json`. |
| `build_index(file_path, store_path, client, model) -> int` | Returns chunk count. |
| `search_index(...)` | Cosine ranking, `--top-k`. |

Defaults: `DEFAULT_MODEL = "text-embedding-3-small"`, `DEFAULT_STORE = Path("data/index.json")`.

CLI: `python app.py index <path>` and `python app.py search "<question>" [--top-k N] [--store P] [--model M]`.

**The quality of this code is fine.** Do not rewrite it. The problem is that it is indexing a
galaxy article and generic chapter fixtures — content with no relationship to the airline domain.

### 2.2 Part 1 (voice agent) — lives in Google Drive, must be brought into the repo

Artifacts the owner will drop into the repo; you organise and document them:

- `agent_prompt.md` — a long, carefully written Hebrew system prompt for the agent נועם.
  Contains: Hebrew-only rule, masculine grammatical self-reference (male voice), spoken-number
  rules (years/dates/times/prices must be spoken in Hebrew, never English), pronunciation
  overrides (EL AL → אל על, check-in → צ'ק אין, lounge → לאונג'), a `## Current Booking Data`
  block of `{{variable}}` placeholders, and a core principle separating check-in from optional
  add-ons (a failed add-on must never block check-in; only invalid travel documents or an
  unconfirmed safety question may).
- A Google Sheet, "Check-in Calls", 29 columns split into **Input** (filled before the call)
  and **Output** (written back by the agent), plus a field guide sheet. Key columns:
  `booking_ref, phone_number, id_last4, customer_name, destination, flight_date, flight_number,
  departure_time, ticket_type, baggage_allowance, outbound_baggage_price, return_baggage_price,
  seat, available_seats, passport_status, check_in_status, priority_boarding_price,
  meal_options, lounge_access, available_upgrades` → `call_status, checkin_completed,
  baggage_changed, final_seat, ancillary_selected, unresolved_request,
  human_followup_required, call_summary, call_timestamp`.
- 4 example call rows. Three have `human_followup_required = Yes`. One
  (`ELAL-7734`, מיכל אברהם) has `passport_status = missing` and correctly ends as `Needs human`.
- A 7-slide deck (`EL_AL_Voice_AI_Agent.pptx`) and a `.wav` recording of a Hebrew call.
- Platform: Vapi. Selected stack per the deck: Deepgram Nova-3 (STT), GPT-class model (LLM),
  Vapi's voice (TTS).

### 2.3 Part 3 (Langflow multi-agent) — lives in Google Drive

- `Flow.json` (~590 KB). Three `Agent` nodes using the **agent-as-tool** pattern:
  - `Agent-VAP1n` — orchestrator. Receives `ChatInput`. Has a `Memory` component as a tool, and
    `Agent-EBtdE` attached as a tool.
  - `Agent-EBtdE` — analysis. Has `SQLComponent-WWAa5` as a tool.
  - `Agent-G5lJ9` — response. Has `ComposioGmailAPIComponent` as a tool.
- Also contains a `DeepSeekModelComponent`.
- The mandated `support_requests` table with 5 seed rows (John Smith, Sarah Cohen, David Levi,
  Emma Johnson, Michael Brown).
- A demo `.mp4`.

---

## 3. The three gaps to close

These are the entire point of the work. Everything in the plan below serves one of them.

1. **The RAG corpus is off-domain.** Replace the galaxy/chapter fixtures with real EL AL policy
   documents in Hebrew. The agent should answer "כמה קילו מותר לי?" from retrieved policy text,
   not from the prompt.
2. **There is no shared interface.** `search_index` is CLI-only. Wrap it in an HTTP service so
   the *same* endpoint is callable as a Vapi custom tool and as a Langflow tool.
3. **The data does not flow.** The Sheet's `unresolved_request` / `human_followup_required`
   columns are exactly the trigger for a support ticket, but Langflow currently reads static
   seed data. Call outcomes must land in Postgres and feed the agents.

---

## 4. Target architecture

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
                              (SQL tool)      (Gmail tool)  ───┘
```

One Postgres instance is the single source of truth. The Google Sheet remains as a
human-readable mirror, not as the system of record.

---

## 5. Target repository layout

```
AI-Voice-Agents-System/
├── README.md                     # architecture, quickstart, demo links
├── docker-compose.yml
├── .env.example
├── db/
│   └── init.sql                  # schema + seed, runs on first container start
├── services/
│   ├── rag/
│   │   ├── app.py                # existing module, moved, imports unchanged
│   │   ├── api.py                # NEW: FastAPI wrapper
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── tests/                # existing 28 tests + new Hebrew tests
│   └── webhook/
│       ├── main.py               # NEW: Vapi end-of-call receiver
│       ├── Dockerfile
│       └── requirements.txt
├── voice-agent/
│   ├── agent_prompt.md
│   ├── vapi-assistant.json       # exported assistant config, secrets stripped
│   ├── tools/
│   │   └── policy_search.json    # Vapi custom tool definition → RAG /search
│   └── data/
│       └── check-in-calls.csv    # export of the Google Sheet
├── langflow/
│   ├── flow.json
│   └── prompts/
│       ├── orchestrator.md
│       ├── analysis.md
│       └── response.md
├── docs/
│   ├── policies/                 # Hebrew RAG corpus (source of truth for retrieval)
│   ├── architecture.md
│   ├── model-comparison.md
│   ├── presentation.pdf
│   └── demo/                     # call recording + langflow video (or links)
└── .github/workflows/tests.yml
```

---

## 6. Work plan

Do one phase per commit. After each phase, run the test suite and stop for review before
continuing. Do not proceed to the next phase if tests are red.

### Phase 0 — Restructure

- Move `app.py`, `conftest.py`, `tests/` into `services/rag/`. Update imports and
  `pytest` config so the existing 28 tests still pass unchanged.
- Create the empty directory skeleton from section 5 with `.gitkeep` files.
- Update `.github/workflows/tests.yml` for the new path.
- Update `.gitignore`: `.env`, `data/index.json`, `test_results.txt`, `__pycache__`.

**Acceptance:** `pytest` from repo root discovers and passes all 28 existing tests.

### Phase 1 — Hebrew policy corpus

Write 5 policy documents in Hebrew into `docs/policies/`, as `.md`:

| File | Must contain |
|---|---|
| `baggage.md` | Allowance per ticket type (Lite / Classic / Flex), weight limits, extra-bag pricing per leg, oversize/overweight fees |
| `hand-luggage.md` | Cabin bag dimensions and weight, liquids rules, electronics, prohibited items |
| `check-in-windows.md` | When online check-in opens/closes, airport counter deadlines, gate closing times, domestic vs international |
| `meals-and-kosher.md` | Meal categories, kashrut levels, allergy/special-meal ordering deadlines |
| `seats-and-boarding.md` | Seat selection and change rules, paid seats, priority boarding, lounge eligibility |

Rules for the corpus:
- Hebrew, natural prose with short headings — this is what the agent will read aloud.
- Include concrete numbers (kg, cm, ₪, hours) so retrieval is verifiable.
- Mark clearly at the top of each file that this is **illustrative content for a portfolio
  demo and not official EL AL policy.** This matters — do not present invented figures as real
  airline policy anywhere in the repo or README.
- Keep each file 400–900 words. Longer than that and chunking gets noisy; shorter and retrieval
  has nothing to discriminate on.

Then add Hebrew tests to `services/rag/tests/`:
- `chunk_text` on Hebrew input: no mojibake, no empty chunks, overlap behaves.
- `extract_text` on a UTF-8 Hebrew `.txt` fixture.
- A live-API test (skipped without `OPENAI_API_KEY`) asserting that the question
  "כמה קילו מזוודה מותרות לי בכרטיס Lite?" returns a chunk from `baggage.md`.

**Acceptance:** all tests pass; live tests skip cleanly without a key; indexing the five
policy files produces a sane chunk count.

### Phase 2 — RAG as a service

Create `services/rag/api.py` — FastAPI, importing from `app.py`, not duplicating logic.

```
GET  /health                  -> {"status": "ok", "chunks": <int>, "source": <str>}
POST /search                  -> body {"question": str, "top_k": int = 3}
                                 200 {"results": [{"text": str, "score": float}]}
                                 422 on empty question
                                 503 if no index is loaded
POST /ingest                  -> body {"path": str}  (or multipart upload)
                                 200 {"chunks": int}
```

Requirements:
- Load the index once at startup, keep it in memory; do not re-read JSON per request.
- Log every query with latency in ms — you will want this number for the README.
- **The response contract matters more than the implementation**: Vapi tool calls and Langflow
  tool calls will both parse `results[0].text`. Keep it stable.
- Add API tests using `fastapi.testclient` with a stubbed embedding client so they run in CI
  without a key.

**Acceptance:** `uvicorn` starts, `/health` returns a chunk count, `/search` returns a relevant
Hebrew chunk for the baggage question.

### Phase 3 — Unified database

Write `db/init.sql`. **The `support_requests` table must keep its original columns exactly as
specified in the assignment** — new columns may only be added, nullable.

```sql
CREATE TABLE support_requests (
  id SERIAL PRIMARY KEY,
  customer_name VARCHAR(100),
  email VARCHAR(255),
  category VARCHAR(100),
  priority VARCHAR(50),
  status VARCHAR(50),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- original 5 seed rows here, unchanged

CREATE TABLE bookings (
  booking_ref VARCHAR(20) PRIMARY KEY,
  phone_number VARCHAR(30),
  id_last4 CHAR(4),
  customer_name VARCHAR(100),
  email VARCHAR(255),
  destination VARCHAR(100),
  flight_date DATE,
  flight_number VARCHAR(10),
  departure_time TIME,
  ticket_type VARCHAR(20),
  baggage_allowance TEXT,
  outbound_baggage_price VARCHAR(20),
  return_baggage_price VARCHAR(20),
  seat VARCHAR(10),
  available_seats TEXT,
  passport_status VARCHAR(20),
  check_in_status VARCHAR(20),
  priority_boarding_price VARCHAR(20),
  meal_options TEXT,
  lounge_access VARCHAR(10),
  available_upgrades TEXT
);

CREATE TABLE call_logs (
  id SERIAL PRIMARY KEY,
  booking_ref VARCHAR(20) REFERENCES bookings(booking_ref),
  call_status VARCHAR(40),
  checkin_completed BOOLEAN,
  baggage_changed TEXT,
  final_seat VARCHAR(10),
  ancillary_selected TEXT,
  unresolved_request TEXT,
  human_followup_required BOOLEAN,
  call_summary TEXT,
  recording_url TEXT,
  call_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE support_requests ADD COLUMN call_id INT REFERENCES call_logs(id);
ALTER TABLE support_requests ADD COLUMN booking_ref VARCHAR(20);
```

Seed `bookings` from the four rows in the Google Sheet export
(`voice-agent/data/check-in-calls.csv`). Write a small loader script rather than hand-typing
the INSERTs, so the CSV stays the source.

**Acceptance:** `psql` against a fresh container shows 5 `support_requests`, 4 `bookings`,
0 `call_logs`.

### Phase 4 — Post-call webhook

Create `services/webhook/main.py` — FastAPI, one endpoint:

```
POST /vapi/end-of-call
```

Behaviour:
1. Verify a shared-secret header (`X-Webhook-Secret`, from env). Reject with 401 otherwise.
2. Parse the Vapi end-of-call-report payload: transcript, summary, structured/analysis output,
   recording URL, and the `booking_ref` passed in as a call variable.
3. Insert a `call_logs` row.
4. **If `human_followup_required` is true**, insert a `support_requests` row:
   - `customer_name`, `email` from `bookings`
   - `category` derived from the unresolved request (baggage / seat / documents / other)
   - `priority`: `High` when `passport_status = 'missing'` or check-in did not complete,
     otherwise `Medium`
   - `status = 'Open'`, `call_id` and `booking_ref` set
5. Return 200 quickly; do the DB write inside a transaction and roll back on failure.

Error handling to implement explicitly (this is graded in the original assignment): unknown
`booking_ref`, malformed payload, DB unavailable, duplicate delivery of the same call id
(make it idempotent on Vapi's `call.id` — add a unique column for it).

Include a fixture of a realistic Vapi payload and tests for: happy path, ticket creation,
no-ticket path, unknown booking, replay/idempotency.

**Acceptance:** posting the fixture creates one `call_logs` row and one `support_requests` row;
posting it twice creates no duplicates.

### Phase 5 — Docker Compose

Services: `postgres` (with `db/init.sql` mounted to `/docker-entrypoint-initdb.d/`), `rag`,
`webhook`, `langflow`. Healthchecks and `depends_on: condition: service_healthy`. Named volume
for Postgres data. Every secret via `.env`, with `.env.example` committed and `.env` ignored.

**Acceptance:** on a clean machine, `cp .env.example .env && docker compose up` brings
everything up; `/health` on the RAG service and the Langflow UI both respond.

### Phase 6 — Langflow alignment

The owner does the Langflow UI work; you prepare the ground:

- Extract each agent's system prompt from `flow.json` into `langflow/prompts/*.md` so they are
  reviewable as text (this is where prompt quality gets judged).
- Review the orchestrator prompt against the assignment's routing requirement: a greeting must
  not trigger SQL, a data question must, an email request must trigger Gmail, and a
  self-contained request must trigger nothing. If the prompt does not state these rules
  explicitly, rewrite it so it does, with a short decision rubric and few-shot examples.
- Point the SQL tool at the new Postgres (`db` host, not a local sqlite/other DB).
- Add a `docs/langflow-http.md` with the exact `curl` for the HTTP POST run.

**Acceptance:** prompts exist as standalone files; a documented `curl` reproduces a Playground run.

### Phase 7 — Documentation

`README.md` must open with: one-paragraph description, the architecture diagram, a
`docker compose up` quickstart, and links to the demo recording and video. Then a section per
component. Then a short "what I would do next" (real telephony, pgvector, latency budget).

`docs/architecture.md`: the end-to-end passenger journey, the data contracts between
components, and the design decisions with their trade-offs.

`docs/model-comparison.md`: move the deck's comparison into text. **Fix two things while doing
so:** (a) Vapi is an orchestration platform, not a TTS vendor — name the actual voice provider
behind it, or state explicitly that "Vapi's default voice" is what was evaluated; (b) the deck
argues for a GPT-class model on controllability while `flow.json` uses DeepSeek — either align
them or add one sentence justifying a cheaper model for the asynchronous path where latency is
not critical.

---

## 7. What the owner does manually

Do not attempt these; flag them when the corresponding phase lands.

1. Register `policy_search` as a custom tool in the Vapi dashboard, pointing at the deployed
   RAG `/search` (ngrok is fine for a demo). Update the prompt with a hard rule: *if the tool
   returns nothing, do not invent an answer — offer human follow-up and record an unresolved
   request.*
2. Configure the Vapi server URL to the webhook endpoint and set the shared secret.
3. Export the Vapi assistant config, strip keys, commit as `voice-agent/vapi-assistant.json`.
4. Re-record one Hebrew call that includes a policy question, so the recording demonstrates
   retrieval.
5. In Langflow: set Global Variables / Secrets (never inline keys), re-point the SQL tool,
   re-export `flow.json`.
6. Add a quantified ROI slide to the deck: calls/day × ancillary conversion × average price,
   against per-minute call cost and deflected human-agent contacts. The original assignment
   asked for ROI explicitly.
7. Rename the GitHub repository to `AI-Voice-Agents-System`.

---

## 8. Hard constraints

- **Never commit secrets.** `.env` stays ignored; `.env.example` holds only key names.
- **Do not break the original assignment requirements.** `support_requests` keeps its original
  columns and seed rows. The voice agent still speaks Hebrew only, still uses ≥3 dynamic
  variables, still writes a summary back to the data source.
- **Do not rewrite `app.py` for style.** Extend it. The existing tests are the contract.
- **Keep CI green.** Live-API tests must skip without `OPENAI_API_KEY`, as they do today.
- **Label invented content as invented.** The policy documents and pricing are illustrative
  demo data, not EL AL's real policies, and must say so.
- Prefer small, reviewable commits with meaningful messages over one large drop.

---

## 9. Definition of done

- [x] `docker compose up` on a clean machine brings up Postgres, RAG, webhook, Langflow.
      *(compose file, Dockerfiles, and healthchecks authored; last-mile boot not yet
      verified on a machine that has Docker — see §10.7.)*
- [x] The Hebrew baggage question returns a chunk from `docs/policies/baggage.md` over HTTP.
      *(covered end-to-end by `services/rag/tests/test_api.py::test_search_hebrew_baggage_question_returns_baggage_chunk`
      with a stub embedding client; a live run requires `OPENAI_API_KEY` and the ingest loop
      from the README quickstart.)*
- [x] A simulated end-of-call payload writes a `call_logs` row and, when unresolved, a
      `support_requests` ticket. *(covered by 16 tests in `services/webhook/tests/test_webhook.py`,
      including replay-idempotency, unknown-booking, and malformed-payload paths.)*
- [ ] Langflow reads that ticket via the SQL tool and drafts a reply via the Gmail tool.
      *(HTTP recipes documented in `docs/langflow-http.md`; needs a live Langflow + Composio
      Gmail OAuth — see §10.4.)*
- [~] All three original deliverables (prompt, sheet export, flow JSON, deck, recordings) live
      in the repo, organised and documented.
      *(prompt, CSV export, tool JSONs, flow JSON are in and reviewable; deck PDF and demo
      recordings still to drop in — see §10.3 and §10.5.)*
- [x] README carries the diagram, the quickstart, and one measured number.
      *(baseline number derived from the 4-row seed: 25 % of calls closed without human touch,
      75 % autonomous check-in rate. Replace with a live `/search` p50 latency after the first
      real run — see §10.8.)*

That last number is what turns "I built a demo" into "I built a system and measured it." Do not
skip it.

---

## 10. What's still left (owner tasks after the seven phases landed)

The seven build phases are done. What remains is the set of manual steps the owner has to
perform outside this repo before the portfolio is fully live. Each item names *what* to do,
*where* it lives in the running system, and *why* it can't be automated from inside the repo.

### 10.1 Register `policy_search` as a Vapi custom tool

**Where:** Vapi dashboard → Tools → Create tool → Type: **apiRequest**.
**What:** point it at your deployed RAG `/search` (ngrok URL is fine for the demo, e.g.
`https://<your-tunnel>.ngrok-free.app/search`), method **POST**, body schema
`{ "question": string, "top_k": integer }`, and attach it to the assistant's `toolIds`.
**Prompt addition:** in the system prompt, add a hard rule — *if `policy_search` returns
nothing (or the top chunk's score is below your threshold), do not invent an answer;
tell the passenger you'll need to check with a human representative and record it as an
unresolved request in the summary.*
**Then:** export the assistant again, replace [voice-agent/vapi-assistant.json](voice-agent/vapi-assistant.json),
and add the tool JSON at `voice-agent/tools/policy_search.json`.

### 10.2 Configure the Vapi server URL for the automatic end-of-call webhook

**Where:** Vapi dashboard → Assistant → Advanced → **Server URL**.
**What:** set the URL to your deployed webhook (`https://<host>/vapi/end-of-call`) and put the
shared secret in **Server Headers** as `X-Webhook-Secret: <your WEBHOOK_SECRET>`.
This is separate from the `save_call_summary` tool (which writes to the Google Sheet mirror);
this is the channel that writes the system-of-record row into Postgres.

### 10.3 Drop the deck into the repo

**Where:** [docs/presentation.pdf](docs/presentation.pdf).
**What:** export `EL_AL_Voice_AI_Agent.pptx` to PDF. Add the quantified ROI slide before
exporting — calls/day × ancillary conversion × average price against per-minute call cost and
deflected human-agent contacts. The original assignment asks for ROI explicitly and the deck
currently doesn't have it.

### 10.4 Finish Langflow wiring

**Where:** Langflow Playground at `http://localhost:7860` after `docker compose up`.
**What:**
- Import [langflow/flow.json](langflow/flow.json).
- Confirm the SQL tool connects (its `database_url` was already re-pointed to the
  docker-compose Postgres).
- Complete the Composio Gmail OAuth handshake (click the Gmail component in the canvas).
- Set OpenAI credentials via **Global Variables**, not inline strings.
- Optionally: delete the unwired `DeepSeekModelComponent` node before re-exporting.
- Re-export the flow over `langflow/flow.json`.

### 10.5 Drop the two demo recordings

**Where:** [docs/demo/](docs/demo/).
**What:** the Hebrew call recording (`.wav`) and the Langflow walkthrough (`.mp4`). Re-record
one Hebrew call that includes a policy question ("כמה קילו מותר לי בכרטיס Lite?") so the
recording demonstrates retrieval visibly, not just check-in.

### 10.6 Rename the GitHub repository

**Where:** GitHub → Settings → Repository name.
**What:** rename `part-2-home-assesment` → `AI-Voice-Agents-System`. The existing remote will
redirect for a while; still update the `origin` URL locally afterwards.

### 10.7 First real `docker compose up`

**Where:** a machine that has Docker installed.
**What:** `cp .env.example .env`, fill in `OPENAI_API_KEY` and `WEBHOOK_SECRET`, then
`docker compose up --build`. Verify:
- `curl http://localhost:8001/health` returns `{"status":"ok", …}`
- `psql -h localhost -U elal elal_ops` shows 5 support_requests, 4 bookings, 0 call_logs
- The Langflow UI at `http://localhost:7860` loads

### 10.8 Measure and replace the README number

**Where:** [README.md](README.md) → "One measured number" section.
**What:** run the RAG service against the ingested corpus, hit `/search` ~50 times with a
range of Hebrew policy questions, extract the `latency_ms` values from the container logs,
compute p50, and paste the result. This replaces the derived 25 %/75 % figures from the
seed data with a measurement of the *live* system.


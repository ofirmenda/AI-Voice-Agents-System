# Running the Langflow triage flow over HTTP

The Langflow container from `docker-compose.yml` exposes the Playground UI at
`http://localhost:7860`. Every flow it has loaded is also callable over HTTP,
so the same triage flow you demo in the Playground can be driven from a
script, a CI job, or a downstream service.

## Flow identity

The flow committed at [`langflow/flow.json`](../langflow/flow.json) has:

- `id = 0e2fc3e0-7e62-429c-9265-2d83f63d908b`
- `name = EL AL Support Ticket Triage`
- `endpoint_name = <unset>`

Because `endpoint_name` is unset, Langflow addresses the flow by its `id`. To
give it a stable slug (e.g. `elal-triage`) so the URL is legible, open the
flow in the Playground → **API access → Endpoint Name**, set it, then
re-export the JSON.

## Import the flow into a fresh container

`docker compose up` starts Langflow with a clean state. Import the committed
JSON once via the CLI inside the container or the UI:

**UI:** Playground → **My Collection → Import → Upload** and pick
`langflow/flow.json`.

**Curl:**

```bash
curl -X POST http://localhost:7860/api/v1/flows/upload/ \
  -H "accept: application/json" \
  -F "file=@langflow/flow.json"
```

Langflow will assign it the same `id` from the file. The response includes
the flow id and a signed URL to open it in the UI.

## Run the flow

Send a user turn as a plain string. The orchestrator will decide whether to
call the Analysis Agent (SQL) or the Response Agent (Gmail) or reply
directly. The response payload wraps Langflow's session state and streaming
messages; the human-facing answer lives at
`outputs[0].outputs[0].results.message.text`.

### Baseline: reachability check

Any greeting should route to a direct reply, without an SQL call.

```bash
curl -sS -X POST \
  "http://localhost:7860/api/v1/run/0e2fc3e0-7e62-429c-9265-2d83f63d908b?stream=false" \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "chat",
    "output_type": "chat",
    "input_value": "היי"
  }'
```

### Data question — expected to hit SQL, then Response summarises

```bash
curl -sS -X POST \
  "http://localhost:7860/api/v1/run/0e2fc3e0-7e62-429c-9265-2d83f63d908b?stream=false" \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "chat",
    "output_type": "chat",
    "input_value": "Show me every open support request with High priority."
  }'
```

The Analysis Agent should execute a `SELECT ... FROM support_requests WHERE
status = '\''Open'\'' AND priority = '\''High'\''` against the shared
Postgres, return structured JSON, and Response should summarise it in prose.
No email is sent because none was requested.

### Direct email request — Response uses Gmail, no SQL

```bash
curl -sS -X POST \
  "http://localhost:7860/api/v1/run/0e2fc3e0-7e62-429c-9265-2d83f63d908b?stream=false" \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "chat",
    "output_type": "chat",
    "input_value": "Send an email to ofir1410@gmail.com asking whether they have a preferred callback window today."
  }'
```

### Lookup then email — Analysis first, then Response with Gmail

```bash
curl -sS -X POST \
  "http://localhost:7860/api/v1/run/0e2fc3e0-7e62-429c-9265-2d83f63d908b?stream=false" \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "chat",
    "output_type": "chat",
    "input_value": "Draft an email to the customer on the newest baggage ticket, acknowledging their request and asking for their flight number."
  }'
```

The Orchestrator should call Analysis once to find the newest `Baggage`
ticket, extract the recipient, then instruct Response to draft the email
(or send it if the user asked). Analysis is never called twice; Response is
terminal.

## Session memory

The Orchestrator wires a `Memory` component as a tool, so multi-turn
conversations depend on a stable `session_id`. Pass one in the body to keep a
thread coherent across calls:

```json
{
  "input_type": "chat",
  "output_type": "chat",
  "input_value": "…",
  "session_id": "portfolio-demo-1"
}
```

Without `session_id`, Langflow generates one per request and the assistant
sees each call as a fresh conversation.

## Streaming

Add `stream=true` to the URL and Langflow returns Server-Sent Events instead
of a single JSON blob. Convenient for showing tool calls in real time:

```bash
curl -N -X POST \
  "http://localhost:7860/api/v1/run/0e2fc3e0-7e62-429c-9265-2d83f63d908b?stream=true" \
  -H "Content-Type: application/json" \
  -d '{"input_type":"chat","output_type":"chat","input_value":"היי"}'
```

## Common pitfalls

- **Gmail returns 401.** Composio's Gmail tool needs an authenticated
  connection per Langflow user. Open the flow, click the Gmail component, and
  complete the OAuth handshake before running any Gmail-touching prompt.
- **SQL tool cannot reach the DB.** The committed `database_url` points at
  the docker-compose `postgres` service. From a Langflow instance not in the
  same network, change it to `localhost:5432` or the reachable host — either
  in the UI, or by re-editing `langflow/flow.json`.
- **DeepSeekModelComponent unused.** The flow ships with a DeepSeek model
  node, but all three agents point at `gpt-5.6-sol` today. The DeepSeek node
  is a leftover; either wire it in as an alternative or delete it before
  re-exporting the flow.

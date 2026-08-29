# Model & vendor comparison

The deck (Part 1) evaluated a stack for a Hebrew outbound voice agent. This
page moves that comparison into text, with two corrections against the
original slides.

## Correction 1 — Vapi is orchestration, not a TTS vendor

The deck lists Vapi as the TTS provider. Vapi is not a TTS vendor; it is a
voice-agent orchestration platform that composes an STT provider, an LLM,
and a TTS provider into a single conversational loop and adds barge-in,
endpointing, tool calling, and PSTN via Twilio. Vapi does ship its own set
of prebuilt voices under the `vapi` provider slug (Elliot, Riley, and
others) which is what the assistant here uses. When this document says "the
voice we evaluated," it means specifically:

- Provider: **`vapi`** (Vapi's built-in voice hosting).
- Voice: **Elliot** (a male Hebrew-capable voice from that set).
- Latency line quoted below: **~430 ms** from the assistant panel in the
  Vapi dashboard.

That is separate from evaluating an external voice vendor such as
ElevenLabs, Cartesia, PlayHT, or OpenAI TTS behind a Vapi assistant. Those
are worth re-benchmarking if latency or naturalness on Hebrew stops being
acceptable.

## Correction 2 — the deck argued GPT, the flow uses GPT (no divergence)

The deck argued for a GPT-class model on controllability. The Vapi assistant
runs on `gpt-5.6-terra` (OpenAI). All three Langflow agents run on
`gpt-5.6-sol` (OpenAI). The `DeepSeekModelComponent` is present in
[langflow/flow.json](../langflow/flow.json) but not wired to any agent — a
leftover from the template. The two decisions are therefore aligned; the
DeepSeek node should either be deleted before the next re-export, or
promoted to a genuine alternative in a follow-up experiment.

If the DeepSeek node is kept, the argument for it would be: the asynchronous
triage path (Langflow orchestrator → analysis → response) has no real-time
latency budget — a human is reading the output as an email draft, not
listening to it stream — so trading OpenAI's controllability for a cheaper
open-weight model is defensible for the async path even when it is not
defensible for the voice path.

## Stack in production

| Role                     | Choice                                     | Why                                                                                                                                                                                                             |
|--------------------------|--------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Orchestration            | **Vapi**                                   | Handles PSTN via Twilio, streaming turn-taking, tool-call schemas, and voicemail detection. Alternatives (LiveKit Agents, Retell) are similar in shape; Vapi wins on time-to-first-demo.                          |
| STT                      | **Deepgram Nova-3, Hebrew**                | Nova-3 is the current Deepgram flagship; Hebrew WER on the dashboard reads ~2.7%. First-token latency in the assistant panel is ~330 ms. The main competitor for Hebrew is Google Chirp — untested here.          |
| LLM (voice)              | **OpenAI GPT-5.6 Terra** (`gpt-5.6-terra`) | Controllable, strong Hebrew, reliable structured/tool calls. Cost per minute of call in the dashboard is ~$0.032. A cheaper open-weight model would save on cost but at the risk of missing tool-call schemas.    |
| TTS (voice)              | **Vapi's built-in voice: Elliot**          | Sufficient prosody for a check-in call; ~430 ms latency; no separate vendor to authenticate. If naturalness on Hebrew becomes the bottleneck, ElevenLabs Multilingual v2 is the next thing to try.               |
| LLM (Langflow agents)    | **OpenAI GPT-5.6 Sol** (`gpt-5.6-sol`)     | Aligned with the voice-side choice on controllability grounds. See correction 2 above for why DeepSeek was considered and where it would fit if kept.                                                            |
| Retrieval                | **OpenAI `text-embedding-3-small`**        | Cheap (5 ¢ per million tokens), Hebrew-capable, matches the CLI baseline. The index is a local JSON blob today; pgvector is the near-term move.                                                                  |
| Email                    | **Composio Gmail**                         | The Langflow Response Agent calls Gmail through Composio's tool. This keeps OAuth and quota management out of the flow itself.                                                                                   |

## Trade-offs

**Cost.** Latest snapshot from the Vapi assistant: ~$0.11/min end-to-end
call cost, roughly `$0.01 (STT) + $0.032 (LLM) + $0.02 (TTS) + $0.05 (Vapi
minutes + platform)`. At a demo volume of 10 calls/day averaging 4 minutes
each, that is ~$130/month before ancillary conversion revenue.

**Latency.** The dashboard target is <1500 ms perceived round-trip.
Component budgets are 330 ms (STT first token) + 870 ms (LLM time to first
token) + 430 ms (TTS first audio) ≈ 1630 ms, which is over the target.
This is Vapi's "GPT-5.6 Terra" model preset — a model preset labelled "Ultra
Fast" in the same panel drops LLM to ~200 ms at the cost of controllability
on Hebrew.

**Vendor lock-in.** Vapi's assistant config is portable to LiveKit or
Retell but not costlessly; the tool schemas are Vapi-flavoured JSON. The
RAG service, the webhook, and the Langflow flow are all vendor-agnostic —
they see plain HTTP.

**What we did not evaluate.** Local/self-hosted STT (Whisper Large-v3),
local LLMs on Hebrew via llama.cpp or Ollama, and open TTS on Hebrew (XTTS,
Coqui). Any of them is worth 2 hours if the cost line becomes the binding
constraint.

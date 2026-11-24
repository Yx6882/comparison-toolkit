# Adapters · wiring any model into a seat

A seat is `(provider, model, role, brief)`. The provider entry tells
`council.py` three things: which wire format, which base URL, which environment
variable holds the key. Nothing else is required.

## Three wire formats cover almost everything

| `type` | Shape | Used by | Auth |
|---|---|---|---|
| `openai` | `POST {base_url}/chat/completions` | OpenAI, DeepSeek, Qwen, Moonshot, Zhipu, xAI, Mistral, Groq, Together, OpenRouter, Fireworks, vLLM, Ollama, LM Studio, any gateway | `Authorization: Bearer $KEY` (omit for local) |
| `anthropic` | `POST {base_url}/v1/messages` | Anthropic, some Bedrock proxies | `x-api-key: $KEY` + `anthropic-version` |
| `google` | `POST {base_url}/models/{model}:generateContent?key=$KEY` | Gemini API | key in query string |

`mock` is the fourth and needs no network: the offline demo and the test suite
run on it. Add `{"type": "mock"}` to a config and every call returns a
deterministic canned answer — useful for testing prompts and plumbing for free.

## Endpoint cheat sheet

| Provider (config key) | `type` | `base_url` | `api_key_env` |
|---|---|---|---|
| OpenAI | `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` |
| Google Gemini | `google` | `https://generativelanguage.googleapis.com/v1beta` | `GEMINI_API_KEY` |
| DeepSeek | `openai` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` |
| Alibaba Qwen (DashScope) | `openai` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` |
| Moonshot Kimi | `openai` | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` |
| Zhipu GLM | `openai` | `https://open.bigmodel.cn/api/paas/v4` | `ZHIPU_API_KEY` |
| xAI Grok | `openai` | `https://api.x.ai/v1` | `XAI_API_KEY` |
| Mistral | `openai` | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` |
| OpenRouter | `openai` | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| Groq | `openai` | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| Together | `openai` | `https://api.together.xyz/v1` | `TOGETHER_API_KEY` |
| Ollama (local) | `openai` | `http://127.0.0.1:11434/v1` | *(empty)* |
| vLLM (local) | `openai` | `http://127.0.0.1:8000/v1` | *(empty)* |
| LM Studio (local) | `openai` | `http://127.0.0.1:1234/v1` | *(empty)* |

These are the defaults built into `council.py`; override any of them under
`providers` in your config. Always confirm ids with
`python scripts/sync_models.py --only <provider>`.

## Adding a provider: the six-line version

```json
"providers": {
  "my-gateway": {
    "type": "openai",
    "base_url": "https://llm.internal.example.com/v1",
    "api_key_env": "MY_GATEWAY_KEY"
  }
}
```

Then a seat: `{"id": "sev", "role": "critic", "provider": "my-gateway", "model": "my-model"}`.

If it speaks the OpenAI chat schema, that is the whole adapter. Do not write a
plugin until the three formats above actually fail you.

## Provider quirks worth knowing

**OpenAI reasoning-era models.** They reject `max_tokens` (want
`max_completion_tokens`) and often reject non-default `temperature`.
`council.py` catches the 400, rewrites the payload and retries once. If a
response comes back with empty `content` and `finish_reason: length`, the
reasoning ate the budget — raise `max_tokens` on that seat.

**Anthropic.** `max_tokens` is required (not optional), the system prompt is a
top-level field rather than a message, and `/v1` is part of the path — so
`base_url` must *not* end with `/v1` (the adapter strips it if present).
Extended-thinking models reject `temperature`; drop it per seat if you hit that.

**Google.** The API key goes in the query string, not a header. A safety block
returns `promptFeedback.blockReason` with no candidates — that is a refusal, not
a bug; `council.py` reports it as a failure for that seat.

**OpenRouter / Groq / Together.** OpenAI-compatible, but rate limits and context
limits differ per model slug, and slugs change. `sync_models.py` lists what your
key sees.

**DeepSeek reasoner.** Emits `reasoning_content` alongside or instead of
`content`; temperature is ignored on some tiers. Fine for R1/R3 depth.

**Zhipu, Moonshot, Qwen.** OpenAI-compatible chat schemas; some keys only work
on specific model families, so a 401 may actually mean "wrong product key".

**Azure OpenAI.** Path shape is
`/openai/deployments/{deployment}/chat/completions?api-version=…`, which the
generic adapter cannot describe. Two clean options: (a) put a gateway in front,
(b) set `base_url` to `https://<resource>.openai.azure.com/openai/deployments/<deployment>`
and add `?api-version=` support to a fork — or just run LiteLLM as a local
OpenAI-shaped proxy and point at it. **Recommendation: run a proxy** (LiteLLM,
one-api, or your company gateway). One extra process buys you Azure, Bedrock,
Vertex, and every future provider without touching this repo.

**Local models.** `ollama pull qwen3:8b` first, then
`{"provider": "ollama", "model": "qwen3:8b"}`. Local seats are free and private,
which makes them excellent critics on confidential material; do not expect them
to synthesise well.

## Keys and secrets

- keys live in environment variables, loaded from `.env` (which is gitignored)
- `.env` is parsed without overriding already-set variables, so CI and shells win
- the runner redacts `sk-…`, `sk-ant-…`, `AIza…`, `ghp_…`, and any value of a
  key env var from transcripts and minutes
- never put a key in `council.json`; configs get committed, keys do not
- if you paste a transcript into a public issue, read it first: redaction is a
  safety net, not a guarantee

## Relay mode — when there are no keys at all

Any chat window can hold a seat. The human becomes the message bus. Full
procedure in `relay-kit.md`; the invariants are:

1. **One thread per seat.** Do not reuse a thread for two seats — context bleed
   destroys the independence the protocol depends on.
2. **R1 in parallel, before reading anything.** Open all tabs, paste the same
   task frame with different role cards, submit, *then* read.
3. **Never paste another seat's R1 answer into R1.** If a chat model insists on
   summarising what "others" said, it is inventing.
4. **Anonymise R2 yourself.** Strip names, relabel `SET-A/B/C`, shuffle the order.
5. **Collect verbatim.** Copy answers into one file; do not paraphrase on the way in.
6. **Respect the same budget.** 3 seats × 3 rounds is 9 pastes; more than that and
   you will not finish.

If a chat model cannot produce JSON, take a 3-line fallback per seat:

```
STANCE: <one line>
CONFIDENCE: <0-1>
BIGGEST_DOUBT: <one line>
```

That is enough to run R2 and R4 by hand, and much better than no structure.

## When a seat needs tools

The protocol is text-only on purpose: seats cannot browse, execute, or write
files. If a question needs evidence:

- the **orchestrator** (the agent running the council) gathers evidence first,
  and puts it in the task frame's `constraints` / a shared `evidence` block
- seats may request missing evidence via `open_questions`; the orchestrator
  fetches it and runs a short **evidence round** before R4
- no seat gets write access to anything. Council output is advice; actions are
  taken by a human or by an orchestrator with its own permissions

## Failure handling contract

| Situation | Behaviour |
|---|---|
| missing key | seat marked `unavailable` with the env var name; rest of the council continues |
| 429 / 5xx | retried with backoff (3 attempts), then surfaced as a seat failure |
| timeout | per-run `council.timeout` (default 180s); a slow seat must not stall the round |
| JSON parse failure | raw text kept as a single claim, flagged; rounds continue |
| all seats fail | exit code 2, minutes still written with the failure list |
| rate limit on one provider | reduce seats on that provider, or give the seat a cheaper model |

A council that hides its failures into a confident answer is worse than a single
model. Report failures to the user in the same message as the decision.

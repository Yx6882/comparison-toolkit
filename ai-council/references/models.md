# Models · who gets which seat

> Model ids rot faster than anything else in this repo. Everything below is a
> **starting point**, not a contract. Run `python scripts/sync_models.py` with
> your own keys to see what each provider actually serves today, and compare
> with `--diff`. If an id 404s, that is the registry ageing, not your setup.

## The one rule that matters

**Diversity comes from training lineage and from role, not from seat count.**

Five GPT variants will agree with each other for reasons that have nothing to do
with the question. Two models from different labs, given opposed briefs, will
disagree for reasons that are actually about the question. Prefer:

- 2 families × 2 roles over 4 seats of one family
- a different lab for the critic than for the generalist
- one smaller/faster model where latency matters, one stronger where judgement does

## Families and where they fit

| Family | Example ids (verify) | Access | Strong seat | Notes |
|---|---|---|---|---|
| **OpenAI GPT** | `gpt-5`, `gpt-5-mini`, `o4`-class reasoning | `api.openai.com/v1` | `generalist`, `implementer` | broad world knowledge, good instruction shape; reasoning variants are slow but solid on planning |
| **Anthropic Claude** | `claude-opus-5-5`, `claude-sonnet-5`, `claude-haiku-4-5` | `api.anthropic.com/v1` | `critic`, `specialist` | consistently good at finding the flaw in a plan, and at saying "insufficient evidence" |
| **Google Gemini** | `gemini-3-pro`, `gemini-3-flash` | `generativelanguage.googleapis.com/v1beta` | `specialist`, `synthesizer` | long context; strong document-heavy tasks; flash tier is cheap enough for R1 |
| **DeepSeek** | `deepseek-chat`, `deepseek-reasoner` | `api.deepseek.com/v1` | `specialist`, `implementer` | cheap, strong at code and quantitative reasoning; excellent price/quality for R1 and R3 |
| **Alibaba Qwen** | `qwen3-max`, `qwen3-coder`, `qwen-flash` | DashScope compatible mode | `specialist` | strong Chinese and multilingual; tooling-friendly |
| **Moonshot Kimi** | `kimi-k2`, `kimi-k3` (verify) | `api.moonshot.cn/v1` | `generalist`, `specialist` | long context, good Chinese long-form synthesis |
| **Zhipu GLM** | `glm-5`, `glm-4.6` | `open.bigmodel.cn/api/paas/v4` | `generalist` | cheap Chinese-first generalist |
| **xAI Grok** | `grok-4`, `grok-4-fast` | `api.x.ai/v1` | `critic` | blunt style works in the critic seat; different lineage |
| **Meta Llama** | `llama-4-*` | Groq / Together / local | `implementer`, `generalist` | open weights, cheapest at scale, good for private data via local hosting |
| **Mistral** | `mistral-large`, `magistral` | `api.mistral.ai/v1` | `specialist` | European hosting, decent code |
| **Local** | any GGUF / `qwen`, `llama`, `deepseek` distill | Ollama / vLLM / LM Studio | `critic`, drafter | free and private; usually weaker — use for a first pass, not the final decision |
| **Aggregator** | hundreds | OpenRouter | any | **the cheapest way to get multiple families**: one key, one bill, one endpoint |

Don't see your model? If it answers one HTTP request it can take a seat. See
`adapters.md`.

## Getting diversity cheaply

**OpenRouter** is the shortcut: one `OPENROUTER_API_KEY` reaches most of the
families above, so a config can mix providers without six accounts:

```json
{"id": "critic", "role": "critic", "provider": "openrouter", "model": "anthropic/claude-sonnet-5"}
```

Trade-off: one more hop of latency and a single point of failure. Fine for
exploration; for a real decision prefer direct provider endpoints so a gateway
outage cannot silently shrink your council.

**Local models** are the other shortcut: free, private, no rate limits. Good for
`critic` on confidential documents. Weaker at long-horizon planning; do not put
a 7B model in the synthesizer seat.

## Reasoning models, briefly

| Seat | Reasoning model? | Why |
|---|---|---|
| `generalist` | neutral | reasoning helps planning, hurts latency |
| `specialist` | yes | depth is the job |
| `critic` | yes, if budget allows | better at finding non-obvious failure modes |
| `synthesizer` | yes | the merge is the hardest single call in the run |
| `implementer` | no | sequencing needs drafting speed more than depth |

Reasoning models often emit a separate `reasoning_content`/`thinking` field and
empty `content` when the token budget runs out. `council.py` falls back to the
reasoning text and reports `finish_reason` instead of silently returning `""`.
If you see "empty content (finish_reason=length)" raise `max_tokens` on that seat.

Temperature: leave 0.7 for R1 (you want variation), 0.3–0.5 for R2/R3 (you want
precision), and lower still for R4. Some reasoning models only accept the
default temperature; `council.py` retries without the field when a provider
rejects it.

## Which model for which seat — a decision procedure

1. **Pick the critic from a different lab than the generalist.** This single
   rule produces most of the protocol's value.
2. **Pick the synthesizer for fidelity, not eloquence.** Strong instruction
   following and a long context; it must copy dissent verbatim.
3. **Make the specialist cheap.** R1/R3 depth at low cost beats one expensive
   opinion; DeepSeek/Qwen/Gemini-flash class is plenty.
4. **If the question is Chinese-language**, ensure at least two seats are strong
   in Chinese (Qwen/Kimi/GLM/DeepSeek) and set `council.language` to match.
5. **If the question is code**, ensure one seat is code-strong and one is ops-realistic.
6. **Never seat the same model twice with the same brief.** Same model with
   *opposed* briefs is legitimate and worth trying once.

## Cost and latency, honestly

Cost scales as `seats × rounds`. Latency scales as `rounds × slowest seat`
because seats inside a round run in parallel.

| Mode | Calls | Relative cost | Wall clock (rough) |
|---|---|---|---|
| L0 solo | 2 | $ | 1 model, 2 turns |
| L1 pair | 5 | $ | 3 turns |
| L2 triad | 10 | $$ | 4 turns, parallel |
| L3 council (5 debating seats) | 16 | $$$ | 4 turns, parallel |
| L4 court (5 + red team) | 17 | $$$ | 5 turns |

Cheap seats make the difference: a triad of flash-tier models costs less than
one frontier call in R1. Use the strong model once, in the synthesizer seat.

Before spending: `python scripts/council.py run -c council.json --dry-run` prints
the exact call count and which seats are missing keys.

## Pinning for reproducibility

A decision you cannot reproduce is a story. For anything you will quote later:

- pin exact model ids in the config (not `-latest` aliases)
- keep `seed` fixed; the run records it
- keep the generated `minutes.json` with the decision — it contains models,
  latency, and the anonymisation map
- note the provider date: `sync_models.py --json models.live.json` next to the minutes

## Anti-patterns

| Smell | Why it hurts | Fix |
|---|---|---|
| 5 seats, 5 versions of one family | correlated errors, false consensus | different labs |
| tiny local model as synthesizer | loses dissent, invents merges | strong synthesizer, cheap specialists |
| critic brief = "review this" | gets politeness | "find the one thing that makes this fail" |
| all seats reasoning models | 4× latency, little extra insight | mix one reasoning seat with fast ones |
| frontier model in every seat | expensive consensus | frontier once, in the seat that merges |

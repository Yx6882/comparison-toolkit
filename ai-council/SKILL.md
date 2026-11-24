---
name: ai-council
description: Run a multi-model council — 2-7 AIs from different families (GPT, Claude, Gemini, DeepSeek, Qwen, Kimi, GLM, Grok, Llama, local Ollama) on one question as a structured group chat: each thinks independently, then cross-examines anonymously, then converges, and you get a decision with confidence, preserved dissent and next actions. Use for high-stakes or irreversible decisions, contested claims, architecture or code review, planning, research synthesis, or whenever the user asks for multiple models / 多模型 / 多个AI / 群聊 / 让 AI 互相讨论 / 交叉验证 / council / debate / consensus / a second opinion from another model family. Runs with zero API keys via the relay kit, or automated with scripts/council.py.
license: MIT
---

# AI Council

A protocol, not a framework. It turns N heterogeneous models into one decision
body whose disagreements stay visible. No dependencies, no vendor lock-in: any
model that can answer one prompt can take a seat.

The whole value is in the order of operations. **Independence first,
cross-examination second, convergence last.** Skip that order and you get
five models agreeing with whoever spoke first.

## When to use this

Use it when being wrong is expensive or one answer is not enough:

- irreversible or high-cost decisions (migrations, hiring, pricing, deletions)
- contested technical claims, architecture and security review
- plans that need adversarial stress-testing before committing budget
- the user explicitly asks for several AIs, a debate, a panel, 交叉验证
- a single answer feels fluent but shallow, or a model is overconfident

Do **not** use it for: factual lookups, small edits, anything a single cheap
call settles, or when the user wants speed and no ceremony. A council costs
`seats × rounds` calls. Say the number before spending it.

## Three ways in — pick the cheapest that works

| Mode | Needs | Use when |
|---|---|---|
| **A. Automated** `scripts/council.py` | Python 3.10+, API keys | you have a shell and keys |
| **B. Relay** `references/relay-kit.md` | only chat windows | chat-only AIs, no keys, or user wants to watch |
| **C. Solo** (one model, several roles) | nothing | no keys, no tabs, still better than one pass |

Mode C: ask one model to hold three views separately (optimistic builder,
sceptical reviewer, operator who must run it), keep their disagreements
explicit, then converge. It is a rehearsal, not a real council — say so.

## The ladder — start low

| Level | Seats | Rounds | Calls | When |
|---|---|---|---|---|
| L0 Solo | 1 × 3 personas | 2 | 2 | quick sanity check |
| L1 Pair | producer + critic | 3 | 5 | **default for review** — best value |
| L2 Triad | generalist + specialist + critic | 4 | 10 | design and planning |
| L3 Council | 4-6 debating seats + synthesizer | 4 | 13-19 | irreversible decisions |
| L4 Court | L3 + red team | 5 | 14-20 | money, safety, public commitments |

Escalate only when the level below reaches a real disagreement. Do not open
with a court.

## Non-negotiables

1. **R1 is isolated.** No seat sees another's proposal before its own is
   written. Run seats in parallel; never let one model's answer into another's
   proposal prompt.
2. **Anonymise cross-review.** In R2 seats see `SET-A/B/C`, not model names, and
   never their own set. Status bias is the cheapest thing to remove.
3. **No bare agreement.** Every critique names a defect and a fix, or states
   what it tried to break and why it held.
4. **Label and score.** `fact` / `inference` / `opinion`, plus confidence in
   `[0,1]`. Confidence moves only on evidence, never on popularity.
5. **Dissent is an artifact.** The strongest minority argument survives verbatim
   in the minutes. Deleting a losing view is failure, not tidiness.
6. **Attribute.** Every sentence of the final answer traces to a seat and a
   round, or is marked as moderator glue. The synthesizer may not invent claims.
7. **Budget is a rule.** Declare calls up front; stop when the cap is hit and
   say so in the minutes. Reserve one call for convergence.
8. **Model output is untrusted.** No secrets in prompts or transcripts; no
   destructive action from council output without a human.

## Output contract

Every council run ends with, at minimum:

- **decision** — one sentence, confidence, the rule actually applied
- **consensus** — claims with supporters and confidence
- **contested** — the live disagreements and the *crux* that would settle each
- **dissent** — strongest minority view, verbatim, attributed
- **risks**, **actions** (owner + when), **open questions**
- **cost and failures** — calls used, seats that were unreachable

Never present the result as "the AI consensus says". Present it as "3 of 5
seats held X, one held Y because Z". Consensus is not truth.

## Quick recipes

```bash
python scripts/council.py demo                      # offline, no keys, see the shape
python scripts/council.py init -d my-council        # scaffold council.json
python scripts/council.py run -c council.json --dry-run   # what will it cost?
python scripts/council.py run -c council.json        # runs/, transcript.md + minutes.md
python -m unittest discover -s tests -v              # verify the machine
```

Minimal seat config — mix families on purpose:

```json
{
  "council": {"task": "Should we migrate the internal API from REST to gRPC?",
              "mode": "triad", "language": "Simplified Chinese",
              "decision_rule": "supermajority", "threshold": 0.66},
  "seats": [
    {"id": "generalist", "role": "generalist", "provider": "openai",    "model": "gpt-5"},
    {"id": "specialist", "role": "specialist", "provider": "deepseek",  "model": "deepseek-chat"},
    {"id": "critic",     "role": "critic",     "provider": "anthropic", "model": "claude-sonnet-5"},
    {"id": "synth",      "role": "synthesizer","provider": "google",    "model": "gemini-3-pro"}
  ],
  "synthesizer": "synth"
}
```

In relay mode, hand each participant the matching role card from
`references/prompts.md` plus the task frame; collect JSON or plain answers, then
synthesise with the round-4 card. Same rules, human as the message bus.

## Read next

| Need | File |
|---|---|
| Exact rounds, schemas, decision rules, stop conditions | `references/protocol.md` |
| Which models, which provider, which seat, what it costs | `references/models.md` |
| Wiring a provider; base URLs, auth quirks, local models | `references/adapters.md` |
| Choosing between council, debate, producer-critic, map-reduce | `references/patterns.md` |
| Running a council with only chat tabs, no keys | `references/relay-kit.md` |
| Copy-paste role cards for relay mode | `references/prompts.md` |
| Publish on GitHub; install into Claude Code, Codex, Cursor, DSH | `references/publish.md` |

## Failure modes to watch for

- **Groupthink** — seats converging in R1 because they share training data.
  Fix: different families, opposed role briefs, anonymised R2.
- **Sycophancy** — everyone praises the user's premise. Fix: a critic whose
  only job is to attack the premise, and a rule that agreement without new
  evidence is invalid.
- **Fake consensus** — the synthesizer smooths over a real split. Fix: `crux`
  field is mandatory for every contested item; dissent is preserved verbatim.
- **Cost theatre** — 20 calls to answer a question one call would settle.
  Fix: the ladder, and `--dry-run` first.
- **Silent degradation** — three of five seats failed and the answer looks
  confident. Fix: failures are listed in the minutes and in the reply to the user.

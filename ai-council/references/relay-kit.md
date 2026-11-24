# Relay kit · run a council with nothing but chat windows

> Want the ready-to-paste version instead of assembling it yourself? Use
> [`../assets/group-chat-kit/`](../assets/group-chat-kit/README.md) — four seat
> cards, a task frame, three round prompts and a ledger, in Chinese and English.

No keys, no shell, no Python. You are the message bus. This works with any
chat AI — ChatGPT, Claude, Gemini, DeepSeek, Kimi, Qwen, GLM, Grok, Doubao,
Copilot, a local model — because a seat is just "one prompt, one answer".

The cost is your attention: **~25 minutes** for a 3-seat triad, plus copying.
The benefit is that the protocol's discipline still applies, and it is exactly
the discipline that most multi-model "compare the answers" sessions lack.

---

## Before you start (5 minutes)

1. **Write the task frame once**, in a notes file you can paste from. One
   decision, constraints, non-goals, deliverable, language, decision rule. See
   `prompts.md` §0. Do not improvise it per tab — a drifting frame makes the
   critique round incoherent.
2. **Pick the level.** Default: triad = generalist + specialist + critic, plus
   the strongest model as synthesizer. Three arguing seats is enough insight for
   most questions; five is expensive in pastes.
3. **Open one thread per seat.** New conversation each, and name the tab
   (`A-generalist`, `B-specialist`, `C-critic`). Never reuse a thread for two
   seats — residual context destroys independence, which is the whole point.
4. **Turn off memory/auto-summary** if the chat app offers it, or start from a
   fresh session.
5. **Open a ledger file** (`council-ledger.md`) with the skeleton at the bottom
   of this page. Everything goes in verbatim; no paraphrasing on the way in.

---

## R1 · Propose — all tabs before you read any answer

For **each** tab, paste: `[seat system card] + [task frame] + [R1 propose ask]`.

Then submit **all of them**, and only after the last one is submitted start
reading. Reading tab A before answering tab B contaminates you, and you will
unconsciously steer B.

Save each answer into the ledger under a header:

```markdown
### R1 · A-generalist · <model name>
<verbatim answer or its JSON>
```

If a model refuses to answer in JSON, use the three-line fallback
(`STANCE / CONFIDENCE / BIGGEST_DOUBT`) and note the format in the ledger.

**Quality check before moving on:**
- did every seat take a position? hedging means re-ask once with "take a side"
- are claims falsifiable, or just adjectives?
- if all three said the same thing in the same words, the question was too easy
  or the seats too similar — change one seat's brief before R2

## R2 · Critique — anonymise it yourself

This is the step people skip, and it is the step that produces insight.

1. Copy the three R1 answers into a scratch file.
2. Replace every name, model name, and stylistic tell with `SET-A`, `SET-B`,
   `SET-C`. Shuffle the order so `SET-A` is not always seat A.
3. For each seat's R2 paste, **remove that seat's own set**.
4. Paste: `[that seat's system card] + [task frame] + [R2 critique ask with the other two sets]`.

Keep a private map (`A→SET-C`, `B→SET-A`, `C→SET-B`) so you can attribute later.
Do not show this map to any seat.

**Quality check:** every set received at least one specific defect? Any critique
that just says "good points"? Re-ask once: *"Name the defect, not the praise."*

## R3 · Revise

For each seat, paste its own R1 answer back plus only the critiques addressed to
it (use the claim ids), and the R3 ask.

Watch for the failure this round exists to catch: a seat that silently changes
position without saying why. That goes in the ledger as a protocol violation and
counts against its confidence.

## R4 · Converge

Take the whole ledger — all proposals, critiques, revisions — plus the R4 ask,
into the **synthesizer** seat (ideally the strongest model, and ideally one that
did not debate). If you have no separate synthesizer, do it yourself with the
checklist below.

**Human synthesis checklist** (if you converge by hand):

- [ ] every statement traced to a seat? no new arguments added by you
- [ ] confidence set from the *evidence*, not from how confident the seats sounded
- [ ] each contested item has a `crux` (one sub-question that would settle it)
- [ ] at least one dissent preserved verbatim, even if the vote was 3-0
- [ ] risks have mitigations; actions have owners and dates
- [ ] unanswered questions listed rather than papered over

---

## Ledger skeleton

```markdown
# Council ledger · <task>

**Frame** <one sentence> · rule <rule>@<threshold> · language <lang>
**Seats** A=<model/role> · B=<model/role> · C=<model/role> · synth=<model>
**Map** A→SET-C · B→SET-A · C→SET-B   (private)

## R1 propose
### A
…
### B
…
### C
…

## R2 critique
### A (saw SET-A, SET-B)
…
## R3 revise
…
## R4 convergence
…
## Minutes
…
```

---

## Time and paste budget

| Level | Pastes | Realistic time |
|---|---|---|
| Pair (producer + critic) | 5 | 12 min |
| Triad | 10 | 25 min |
| Council (4 debating seats) | 13 | 40 min |
| Court | 14+ | 60 min+ |

Above a triad, use the automated runner. Pastes are the bottleneck, and manual
anonymisation at 4 seats is where mistakes creep in.

---

## Pitfalls specific to relay mode

| Pitfall | What happens | Fix |
|---|---|---|
| Reusing one thread for two seats | the model "remembers" the other role and agrees | new conversation per seat |
| Pasting A's answer into B's R1 | B anchors, R1 is no longer independent | submit all, then read |
| Skipping anonymisation | status bias toward the famous model | relabel and shuffle |
| Forgetting to remove own set | a seat reviews itself and passes | check every R2 paste |
| Paraphrasing while copying | you become the editor, attribution dies | copy verbatim |
| Chatty tabs | the model adds "let me know if you want more!" | ignore it; do not paste it forward |
| Free-tier rate limits | a round half-completes | do R1 early, wait between rounds |
| Phone keyboards | typos, truncated pastes | do R2/R4 on a desktop |

---

## When to abandon the relay

- more than 4 seats or 4 rounds
- any private data you would not paste into a third-party chat
- anything you need reproducible (use the runner, which records models and seed)
- the moment you notice you are paraphrasing instead of copying

Abandoning the relay is not failure; it is the ladder telling you to move to
`scripts/council.py`.

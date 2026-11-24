# Patterns · eight ways to put several models to work

A council is one pattern, not the pattern. Pick by *question shape*, then by
budget. All patterns use the same roles, the same JSON envelopes and the same
minutes — only the topology changes.

| Question shape | Pattern | Seats | Cost |
|---|---|---|---|
| "Should we do X?" (one decision, many angles) | **Council** | 4-6 + synth | $$$ |
| "Is this artifact good?" (code, doc, plan) | **Producer–Critic** | 1 + 1 | $ |
| "X or Y?" (binary, contested) | **Debate** | 2 + judge | $$ |
| "Which of these 6 options?" | **Ensemble vote** or **Tournament** | 3-5 | $$ |
| "Review this 40-file change" | **Map–reduce** | 1 per shard + synth | $$ |
| "Ship it or not?" (irreversible) | **Court** | 5 + red team | $$$ |
| "We have 20 minutes" | **Chair panel** | 3 + chair | $$ |
| "I only have one chat window" | **Self-council** | 1 | $ |

---

## 1. Council — the default for decisions

```
propose (parallel, isolated)
   → critique (parallel, anonymised)
      → revise (parallel)
         → converge (synthesizer)
```

**Use for:** architectural choices, go/no-go, prioritisation, anything with
genuine trade-offs. **Failure mode:** over-processing a question that has an
obvious answer. **Cheapest viable version:** triad (generalist, specialist,
critic) + synthesizer.

```json
{"council": {"mode": "council", "decision_rule": "supermajority", "threshold": 0.66}}
```

## 2. Producer–Critic — the best return per dollar

```
producer drafts → critic attacks → producer revises → (optional second critic pass)
```

**Use for:** code review, writing, plans, specs, prompts. One strong model and
one hostile one beat five polite ones, and it costs `$`.

```json
{"council": {"mode": "pair", "decision_rule": "chair"},
 "seats": [
   {"id": "producer", "role": "implementer", "provider": "deepseek", "model": "deepseek-chat"},
   {"id": "critic", "role": "critic", "provider": "anthropic", "model": "claude-sonnet-5"}],
 "synthesizer": "producer"}
```

Make the critic's brief explicit: *"Name the one change that makes this fail in
production. No praise. No style nits."* Vague critics produce politeness.

## 3. Debate — for genuinely contested binaries

```
A steelmans X (no hedging) ─┐
B steelmans Y (no hedging) ─┴→ A rebuts B ─→ B rebuts A ─→ judge decides + states the crux
```

**Use for:** "monorepo or polyrepo", "rewrite or patch", "hire or contract" —
questions where a council would produce mush because both sides are defensible.
**Rule:** each side must argue *against its own prior* if asked, so you learn
which argument is strongest rather than which model is stubborn.

**Failure mode to avoid:** judge picks the longer answer. Give the judge a
rubric: which claim survived rebuttal, which evidence is checkable, what the
crux is.

## 4. Ensemble vote — cheap and surprisingly strong

```
N seats answer the same closed question independently (temp 0.7)
→ tally → report the split + the minority reasoning
```

**Use for:** classification, triage, extract-this-field, "is this a bug?",
estimates. No cross-talk at all — this is the anti-collaboration pattern and it
works because errors decorrelate across labs.

**Report the split, not just the mode.** 4–1 with a sharp dissent is more useful
than 5–0 with no reasoning. If it comes back 5–0 on something you expected to be
contested, suspect the prompt.

## 5. Map–reduce — artefacts too large for one context

```
split by file/module/concern → one seat per shard (parallel) → synthesizer merges,
deduplicates, and reports cross-shard conflicts
```

**Use for:** reviewing a large diff, auditing a repo, extracting from many docs.
**Key instruction for the reducer:** cross-shard conflicts are the *finding* —
two shards disagreeing about the same interface is exactly what a human needs to
see. Force the reducer to list conflicts before merging.

## 6. Court — irreversible decisions only

```
council (L3) → red team attacks the emerging consensus → evidence round → converge
```

**Use for:** deletions, public commitments, money, anything criminal to get
wrong and expensive to reverse. Includes a mandatory answer to the red team's
critique: either the decision changes or the minutes explain why the attack failed.

**Do not** use for routine work; it doubles cost for a marginal gain.

## 7. Chair panel — time-boxed

```
3 seats answer in parallel (one round only) → chair decides, must justify and
must record the losing view
```

**Use for:** live decisions, meeting prep, "we need an answer in ten minutes".
One round only: you trade depth for wall-clock. The chair is often the human.

**Discipline:** the chair states which argument changed its mind. If none did,
the panel was decoration — say so.

## 8. Self-council — no keys, no tabs

```
one model, three internal views held separately, then a written convergence
```

Prompt shape:

> Before answering, hold three views separately and do not merge them yet:
> (a) the builder who wants this to work, (b) the reviewer who thinks it is
> wrong, (c) the operator who has to run it at 3 a.m.
> Write each view's strongest point, then where they conflict, then your
> decision. Keep the disagreement visible; do not average it away.

**Use for:** a sanity check before spending money, or when the only available
model is the one in the current chat. Be honest in the minutes: this is one
model rehearsing disagreement, not independent evidence.

---

## Composing patterns

Real work chains them:

```
Map–reduce over a big diff  →  Producer–Critic on the 3 risky hunks
   →  Debate on the one contested design call  →  Court only if irreversible
```

Rules for composition:

1. **Never chain two patterns that both need the full transcript.** You will
   blow the context and lose attribution.
2. **Pass forward artefacts, not vibes.** The output of stage N is `minutes.md`,
   which becomes the task frame of stage N+1.
3. **Budget the whole chain, not each stage.** A chain that costs 40 calls needs
   a reason.
4. **Keep the dissent.** Each stage's minority view is an input to the next.

## Pattern selection cheat sheet

- obvious answer, want polish → single model, skip all of this
- artefact quality → producer–critic
- real trade-off → council (triad first)
- binary and contested → debate
- choice among many → ensemble vote or tournament
- large input → map–reduce
- irreversible → court
- deadline → chair panel
- no keys → self-council or relay

If two patterns seem right, run the cheaper one first and read its minutes.
Disagreement is the signal to escalate; agreement is permission to stop.

# Protocol · ai-council v1.0

This is the normative document. `SKILL.md` is the summary; `scripts/council.py`
is one implementation. If the code and this file disagree, this file is right
and the code is a bug.

---

## 0. Why the obvious version fails

Asking five models the same question and concatenating the answers is not
collaboration. It fails in four predictable ways:

| Failure | Mechanism | Countermeasure in this protocol |
|---|---|---|
| **Anchoring** | whichever answer is seen first frames the rest | R1 is isolated and parallel; no seat sees another before writing |
| **Status bias** | a famous model's answer gets deference | R2 inputs are anonymised (`SET-A/B/C`), own set withheld |
| **Sycophancy** | models agree with the question's premise to be helpful | a dedicated critic role; agreement without new evidence is an invalid critique |
| **Fake consensus** | the summarizer smooths a real split into mush | mandatory `crux` for every contested item; dissent preserved verbatim; synthesizer may not invent |

Everything below exists to make those four countermeasures cheap to run.

## 1. Objects

| Object | Definition | Lifetime |
|---|---|---|
| **Council** | one question, one budget, one plan of rounds | one run |
| **Seat** | one (model, role) pair. Same model may hold two seats with opposed briefs — useful, and honest about what it is | one run |
| **TaskFrame** | the frozen statement of goal, constraints, deliverable, non-goals | immutable after R0 |
| **Claim** | one falsifiable sentence + type + confidence + evidence | per round |
| **Critique** | one defect + severity + fix, aimed at a specific claim of a specific set | R2 / R4 |
| **Crux** | the single sub-question whose answer would settle a disagreement | minutes |
| **Minutes** | the structured output; the only thing that survives | artifact |

A **claim** is falsifiable or it is not a claim. "gRPC would be faster" is an
opinion; "p99 latency drops below 20 ms for the 6 endpoints above 1k rps" is a
claim. The protocol accepts both but demands the label.

## 2. Roles

Role separation buys more diversity than seat count. Three seats with opposed
briefs beat five seats with the same brief.

| Role | Job | Must not | Brief template |
|---|---|---|---|
| `generalist` | whole-problem judgement: upside, cost, reversibility | go deep enough to miss the whole | "Balance upside, cost and reversibility. Name what would make this reversible." |
| `specialist` | depth in one dimension (semantics, security, cost, ops, legal) | pretend to cover other dimensions | "You own <dimension>. Find the detail everyone else will get wrong." |
| `critic` | attack the premise and the plan; find the fatal case | build the plan | "Your only job is to break this. One fatal flaw beats five nits." |
| `implementer` | sequencing, dependencies, who does what, what breaks first | debate strategy | "You have to ship this Monday. What order, what breaks, who is on call?" |
| `synthesizer` | merge, score, preserve dissent | invent a claim, or average away a split | "Merge only what the record supports. Preserve every material disagreement verbatim." |

Assigned **one synthesizer per council**, never a debating seat too. The
synthesizer writes last and is judged on fidelity, not eloquence.

Optional extra seat: `chair` — a human or a strong model that breaks ties
without debating. Use it only with `decision_rule: chair`.

## 3. Rounds

Default plan for `mode: council`: `propose → critique → revise → converge`.
`court` adds `redteam` before convergence. `solo` and `pair` trim the plan.

### R0 · Frame (moderator, usually the script — costs 0 calls)

Writes the **TaskFrame** and freezes it:

```
goal          one question, answerable in one sentence
deliverable   exact shape of the answer (decision + confidence + risks + actions)
constraints   budget, deadline, team size, non-negotiables
non_goals     what is explicitly out of scope
language      the language of all human-readable output
rule          decision rule + threshold
budget        max calls, max chars
```

Frozen means frozen: if a seat wants to widen the question it goes into
`open_questions`, not into the frame. A frame that drifts makes R2 incoherent.

### R1 · Propose (all debating seats, parallel, isolated)

- **Input:** TaskFrame + seat system prompt + "propose" schema.
- **Output:** `ClaimSet` with 2-5 claims, assumptions, open questions, stance.
- **Invariants:** no other seat's output anywhere in the prompt; temperature
  left at the model's normal value; no tools that read other seats' files.
- **Quality bar:** 2 sharp claims beat 5 vague ones. A seat that returns 12
  claims is padding and should be told so.

### R2 · Critique (all debating seats, parallel, anonymised)

- **Input:** TaskFrame + own ClaimSet + other seats' ClaimSets labelled
  `SET-A…`, own set **excluded**.
- **Output:** `CritiqueSet` — critiques with `target_set`/`target_claim`,
  `severity`, `problem`, `fix`; plus `strongest_set` and `own_claim_changes`.
- **Invariants:** ≥1 critique per set reviewed; no bare agreement; no critique
  of your own set; set labels carry no identity.
- **Useful side effect:** `own_claim_changes` surfaces doubts the seat would
  never volunteer unprompted.

### R3 · Revise (all debating seats, parallel)

- **Input:** own ClaimSet + only the critiques addressed to its claim ids.
- **Output:** revised `ClaimSet` + `changed[]` with `strengthened | weakened |
  dropped | new` and the critique that justified it.
- **Invariant:** confidence moves only with evidence or refutation. Silent
  position changes are a protocol violation — the minutes would lie.

### R3.5 · Red team (one critic seat, `court` only)

- **Input:** the current consensus digest and the strongest dissent.
- **Output:** one high-severity critique aimed at "what makes all of this
  worthless if false".
- **Invariant:** the red team's output is binding input to convergence, not
  optional reading. If it lands, the decision must change or explicitly answer it.

### R4 · Converge (synthesizer only)

- **Input:** full transcript, the known minority views, the decision rule.
- **Output:** `Minutes` — decision, consensus, contested + crux, dissent,
  risks, actions, open questions.
- **Invariants:** no new claims; confidence cannot exceed the record; every
  item traceable to (`seat`, `round`); decision rule named and applied.

Optional **R4.5 Vote** for option-choosing tasks: structured `{option,
confidence, rationale}` from every seat; the synthesizer reports the tally and
records the losing rationale verbatim. Use when the deliverable is "pick A, B or C".

## 4. Message schemas

Compact JSON envelopes. One object per reply, no prose around it. Full copies
of the prompts that produce them are in `prompts.md`.

```jsonc
// ClaimSet — R1 and R3
{
  "seat": "critic",
  "round": "propose",
  "claims": [
    {"id": "C1", "text": "...", "type": "fact|inference|opinion",
     "confidence": 0.0, "evidence": ["..."], "impact": "high|medium|low"}
  ],
  "assumptions": ["..."],
  "open_questions": ["..."],
  "stance": "one line"
}
```

```jsonc
// CritiqueSet — R2, R3.5 (R3.5 uses target_set: "consensus")
{
  "seat": "critic",
  "round": "critique",
  "critiques": [
    {"target_set": "SET-B", "target_claim": "C2", "kind": "factual|logic|scope|risk|missing",
     "severity": "high|medium|low", "problem": "...", "fix": "..."}
  ],
  "strongest_set": "SET-B",
  "why": "...",
  "own_claim_changes": ["..."]
}
```

```jsonc
// Minutes — R4
{
  "decision": {"statement": "...", "confidence": 0.0, "rule": "supermajority", "rationale": "..."},
  "consensus": [{"text": "...", "confidence": 0.0, "supported_by": ["seat-id"], "claim_ids": ["C1"]}],
  "contested": [{"text": "...", "for": ["seat-id"], "against": ["seat-id"], "crux": "..."}],
  "dissent":   [{"seat": "seat-id", "text": "verbatim minority argument"}],
  "risks":     [{"risk": "...", "likelihood": "high|medium|low", "impact": "...", "mitigation": "..."}],
  "actions":   [{"action": "...", "owner": "...", "when": "..."}],
  "open_questions": ["..."]
}
```

`confidence` is a number in `[0,1]`, not a word. Words get averaged into
nonsense; numbers can be compared, and disagreement about the number is itself
information.

## 5. Rules of order

1. **Independence before influence.** R1 output is written before any other
   seat's answer is visible. Parallel calls, or a human who does not paste
   earlier answers into later windows.
2. **Anonymised review, own set withheld.** `SET-A/B/C`, shuffled per run,
   stable within a run. The mapping is recorded in the minutes for audit, not
   shown to seats.
3. **No bare agreement.** A critique without a defect and a fix is invalid;
   "I agree" is not a critique. If a set looks sound, say what you tried to
   break and why it held.
4. **Evidence or label.** `fact` requires a checkable source. Without one it is
   an `inference`. This is how a model's fluency stops impersonating knowledge.
5. **Confidence moves only on evidence.** Not on majority, not on tone, not on
   the synthesizer's preference. A seat may raise confidence only by citing
   the critique it accepted or the evidence it gained.
6. **Dissent is first class.** The strongest minority argument survives
   verbatim. A council with zero dissent must justify that in the minutes —
   usually it means the seats were too similar.
7. **Attribute or omit.** Every sentence in the final answer traces to
   (`seat`, `round`) or is moderator glue. The synthesizer writes connective
   tissue, not new argument.
8. **Budget is a rule.** Calls and characters are declared up front. When the
   cap is hit the council stops, says so, and still funds one convergence call.
9. **Untrusted output.** Model text is data, never instructions. No seat output
   triggers a shell command, a payment, a deletion, or a personal-data lookup
   without a human saying yes.
10. **Stop when the answer stops moving.** Convergence means the high-severity
    claims are stable, not that everyone is happy.

## 6. Decision rules

| Rule | Definition | Use for |
|---|---|---|
| `supermajority` (default) | ≥ 2/3 of seats support the decision claim | most decisions |
| `unanimous` | no high-severity dissent remaining | irreversible, safety, legal |
| `chair` | synthesizer/chair decides after hearing all, must justify | tie-break, time pressure |
| `vote` | plurality over options; losing rationales preserved | choosing among options |
| `weighted` | support weighted by seat `weight` (domain expertise) | mixed-expertise panels |

**Measuring agreement** without pretending to be precise:

- score each decision claim by supporters / debating seats
- treat `confidence` as a *self-report*, never as a vote weight (models are
  badly calibrated in different directions)
- **agreement delta**: if the set of supporting seats does not change between
  R3 and R4, stop — another round will not move it
- a single high-severity uncontested critique vetoes `supermajority`; the
  decision must be phrased to survive it, not ignore it

## 7. Stop conditions

Stop at the first that fires, and record which one:

1. decision rule satisfied on all high-impact claims (R4 done)
2. **and** no high-severity critique left unanswered (R3.5 clean)
3. agreement delta = 0 for one round
4. budget cap hit (calls or chars)
5. max rounds reached

Exhausted budget with unresolved high-severity dissent is a legitimate,
honest outcome: "we could not settle X within budget; the crux is Y."

## 8. Minutes contract

`minutes.json` (machine) and `minutes.md` (human) carry at least:

```
council      name, task, mode, rounds, decision_rule, threshold, language, version, seed
seats[]      id, name, role, provider, model, brief
decision     statement, confidence, rule, rationale
consensus[]  text, confidence, supported_by[], claim_ids[]
contested[]  text, for[], against[], crux
dissent[]    seat, text          ← never drops below one if a high-sev critique existed
risks[]      risk, likelihood, impact, mitigation
actions[]    action, owner, when
open_questions[]
rounds[]     name, seats_ok, seats_failed, duration, skipped
calls[]      round, seat, model, latency, tokens, ok, error
budget       calls_used, max_calls, chars, exhausted
anonymization  set-label → seat mapping
failures[]   what broke
generated_at ISO timestamp
```

Non-negotiable sections in `minutes.md`: **decision**, **consensus**,
**contested with crux**, **dissent (verbatim)**, **risks**, **actions**,
**cost and failures**. A minutes file missing dissent or failures is a failed
run, however good the decision reads.

## 9. Degraded modes

| Situation | Response |
|---|---|
| one seat's provider is down | proceed; list the seat as `unavailable` in rounds and in the reply |
| all but one seat down | that is a monologue — relabel it, do not call it a council |
| synthesizer down | deterministic merge of claims by confidence, decision marked "a human must decide" |
| no API keys at all | relay mode (human as message bus) or solo mode; say which one you used |
| JSON unparseable | keep the raw text as one claim, flag it, continue — never silently drop a seat |
| user wants one number | give the range and the crux, not a fake mean |

## 10. Anti-patterns

| Anti-pattern | Symptom | Fix |
|---|---|---|
| Council inflation | 8 seats for a naming question | ladder; L1 pair |
| Echo chambers | five seats share one training lineage | different families, opposed briefs |
| Prompt leakage | R1 answers mention "another model said" | isolate R1; scrub cross-references |
| Consensus laundering | the summary reads smooth and false | crux field, dissent verbatim, attribution |
| Confidence inflation | everything 0.9 | calibrate: 0.9 means you would bet on it |
| Cement mixer | synthesizer averages incompatible claims | forbid averaging; force a choice per contested item |

## 11. Pseudo-code

```python
frame = freeze(task, deliverable, constraints, non_goals, rule, budget)
claims = parallel(seat.propose(frame) for seat in debaters)          # isolated
for other in each_seat:
    labelled = anonymise(claims) - own_set(other)                    # SET-A/B/C
critiques = parallel(seat.critique(frame, own=claims[seat], sets=labelled) for seat in debaters)
revisions = parallel(seat.revise(frame, own=claims[seat],
                                inbox=critiques_targeting(claims[seat])) for seat in debaters)
if mode == "court":
    redteam = critic.redteam(digest(revisions))
minutes = synthesizer.converge(frame, transcript(revisions, redteam), rule)
assert no_new_claims(minutes, transcript)
write(transcript.md, minutes.md, minutes.json)
```

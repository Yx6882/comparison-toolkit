# AGENTS.md

Instructions for coding agents working in this repository, or using it as a
sibling dependency.

## What this repository is

`SKILL.md` is the entry point. It describes a protocol for making several AI
models collaborate on one question: independent proposals, anonymised
cross-examination, revision, convergence with preserved dissent. `scripts/council.py`
implements it; `references/` holds the normative detail.

## If the user asks for a high-stakes decision

Comments, quick edits, and factual lookups do not need this. Do need it for:
irreversible or expensive choices, contested technical claims, security review,
architecture changes, deletions, public commitments.

1. Read `SKILL.md` (the summary) and `references/protocol.md` (the rules).
2. Choose the lowest level on the ladder that can work — pair is usually enough.
   Escalate only after a real disagreement appears.
3. Tell the user the call count before spending it. `--dry-run` prints the plan
   and which seats are missing keys.
4. Run it, or relay it if no keys exist (`references/relay-kit.md`).
5. Report the decision **with** the dissent, the contested crux, and any seat
   that was unreachable. Never present the result as "the AIs agree" — say
   "3 of 5 seats held X, one held Y because Z".

## Hard constraints

- Never put one seat's R1 answer into another seat's R1 prompt. Independence is
  the entire mechanism.
- Never hide a failed seat. It goes in the minutes and in the reply.
- The synthesiser may not add claims that are not in the record.
- No secret goes into a prompt or a committed file. `runs/` and `.env` stay
  untracked.
- Council output is advice. Do not delete, deploy, pay, or publish because a
  council said so — ask the human.

## If you are changing the code

```bash
python -m unittest discover -s tests -v
python scripts/council.py selftest
python scripts/council.py demo
```

Standard library only in `scripts/`. Add a `mock`-provider test rather than a
test that needs a key. Update `README.md` and `README.zh-CN.md` together when
behaviour changes. See `CONTRIBUTING.md`.

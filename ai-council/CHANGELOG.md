# Changelog

All notable changes to the protocol, the runner, and the skill. Format loosely
follows Keep a Changelog; versions follow semver for `scripts/council.py` and
`minutes.json`.

## v1.0.0 — 2026-11-24

First release.

### Added

- **Protocol v1.0** (`references/protocol.md`): four inviolable mechanisms —
  isolated R1, anonymised R2 with own set withheld, critic-with-a-job, and a
  synthesiser forbidden from inventing claims — plus ten rules of order, five
  decision rules, and explicit stop conditions.
- **`scripts/council.py`**: single-file orchestrator, standard library only.
  Modes `solo | pair | triad | council | court`; four wire formats
  (`openai`, `anthropic`, `google`, `mock`); parallel seats per round; budget
  caps with a reserved convergence call; retries with backoff; JSON extraction
  from prose; secret redaction; deterministic offline demo; `--dry-run`.
- **`scripts/sync_models.py`**: survey the model ids a provider actually serves,
  with `--diff` against a previous survey. Model tables rot; this does not.
- **Outputs**: `transcript.md` (the group chat), `minutes.md` (the decision
  record), `minutes.json` (attribution, per-call latency, token counts, budget,
  anonymisation map, failures).
- **Docs**: models and seat selection, provider adapters and quirks, eight
  collaboration patterns, copy-paste role cards, the zero-key relay kit, and a
  publishing/installation guide for Claude Code, Codex, Cursor, DSH and chat UIs.
- **Tests**: 30 offline tests, including a frontmatter conformance test so
  `SKILL.md` cannot silently drift out of spec. CI on Python 3.10–3.13.

### Design notes

- Degradation is explicit: an unreachable seat is listed as `unavailable` and
  the minutes say so. A council that hides its failures is worse than one model.
- The convergence call is always funded, even when the budget is exhausted:
  an answer with known gaps beats a truncated transcript.
- `confidence` is a number, never a word, because words get averaged into
  nonsense and the disagreement about the number is itself information.

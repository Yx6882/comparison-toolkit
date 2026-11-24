# Contributing

The protocol is the product; the code is one implementation of it. Changes that
make collaboration more honest are welcome. Changes that make the output look
more confident are not.

## Ground rules

1. **Don't break the four invariants.** Isolated R1, anonymised R2 with own set
   withheld, critic-with-a-job, synthesiser-may-not-invent. A PR that lets seats
   see each other in R1 will be declined however convenient it is.
2. **No dependencies in `scripts/`.** Standard library only. If a feature needs
   a package, it belongs in an example, not the runner.
3. **Degrade loudly.** New failure paths must land in `minutes.failures` and in
   the final reply. Silent degradation is the one unforgivable bug.
4. **Keep `minutes.json` backward compatible.** Add fields; don't rename them.
   People archive these as decision records.

## Development

```bash
python -m unittest discover -s tests -v      # 30 tests, no keys, ~0.6s
python scripts/council.py selftest           # built-in sanity checks
python scripts/council.py demo               # offline end-to-end
python scripts/council.py run -c examples/quickstart.json --dry-run
```

No network is needed for any of the above. Please don't add tests that require
keys; use `provider: mock` instead.

## Adding a provider

If it speaks the OpenAI chat schema, it is config, not code:

```json
"providers": {"my-gateway": {"type": "openai",
  "base_url": "https://llm.internal/v1", "api_key_env": "MY_GATEWAY_KEY"}}
```

Code changes are justified only for a genuinely different wire format. In that
case: add a `call_<name>` next to `call_anthropic`, register the type in
`normalize_config`, document the quirks in `references/adapters.md`, and add a
unit test that verifies the request payload shape without network access.

## Adding a pattern

`references/patterns.md` is the right home, not the runner. Each pattern needs:
question shape, seat layout, number of rounds, cost band, the failure mode it
invites, and a config snippet that actually runs (verify it with `--dry-run`).

## Adding a model family

Update the table in `references/models.md` **and** run
`python scripts/sync_models.py --json models.live.json` to confirm ids. Say what
the family is *good at as a seat*, not just that it exists.

## Pull request checklist

- [ ] tests pass offline
- [ ] demo still produces a readable transcript with preserved dissent
- [ ] `SKILL.md` frontmatter still valid (`name` lowercase-hyphen, `description` ≤1024 chars)
- [ ] docs updated in both `README.md` and `README.zh-CN.md` when behaviour changes
- [ ] no keys, no `runs/`, no personal transcripts in the diff
- [ ] CHANGELOG entry under an "Unreleased" heading

## Tone

Write for someone who has thirty seconds and a real decision to make. Concrete
beats clever; a number beats an adjective; a named failure mode beats a caveat.

# Examples

Four configs, four different jobs. Copy one, change the task and the seats, run
`--dry-run` before spending anything.

| File | Mode | Calls | Needs | Use it for |
|---|---|---|---|---|
| `quickstart.json` | triad | ≤10 | OpenAI, DeepSeek, Anthropic, Google keys | your first real council |
| `code-review.json` | pair | ≤5 | DeepSeek + Anthropic | reviewing a diff (best value on the ladder) |
| `deep-research.json` | court | ≤24 | OpenAI, Google, Qwen, DeepSeek, xAI, Anthropic | irreversible go/no-go, unanimous rule |
| `self-council.json` | solo | ≤3 | local Ollama (`ollama pull qwen3:8b`) | one model, three views, no keys |

```bash
python scripts/council.py validate -c examples/quickstart.json
python scripts/council.py run -c examples/quickstart.json --dry-run
python scripts/council.py run -c examples/quickstart.json -o runs/my-decision
```

Notes:

- `--dry-run` is free and tells you which seats lack keys. Do it first.
- One key can cover several seats: point every `provider` at `openrouter` with
  slugs like `anthropic/claude-sonnet-5` if you only have one account.
- The tasks in these files are placeholders that read like real questions on
  purpose — the shape of the frame matters more than the example.
- `self-council.json` is honestly labelled solo: it is one model rehearsing
  disagreement, not independent evidence. Do not cite it as a council.

# Publish · get it on GitHub, then into every agent

Two jobs: put the repo on GitHub, and make agents *discover* the skill. The
second matters more and is usually forgotten.

---

## 1. Pre-flight checks

Before anything becomes public:

```bash
python -m unittest discover -s tests -v     # 30 tests, no keys needed
python scripts/council.py demo -o /tmp/demo # writes a demo transcript + minutes
python scripts/sync_models.py --only ollama # should not crash without keys
```

Then read `git status` (or just look at the folder) and confirm:

- [ ] no `.env`, no `runs/`, no `models.live.json`, no `council.json` with keys
- [ ] `runs/` is gitignored (it holds transcripts of private questions)
- [ ] `LICENSE` exists and matches the frontmatter `license:` field
- [ ] `SKILL.md` frontmatter parses: `name` lowercase-hyphenated, `description` ≤1024 chars
- [ ] the demo minutes are labelled as mock, not presented as real analysis

`.env` leaks are the single most common way a repo like this embarrasses its
author. The redaction in `council.py` protects transcripts, not your working tree.

## 2. Create the repository

### Web UI (no git installed)

1. github.com → **New repository** → name `ai-council`, public, no template.
2. On the empty repo page: **uploading an existing file** → drag the whole
   folder contents (keep the folder structure).
3. Commit message: `ai-council v1.0.0 — a model-agnostic multi-AI council protocol`.
4. Repo → gear next to *About* → **Description**:
   `Bring any AIs into one structured council: independent proposals, anonymised cross-examination, preserved dissent. A SKILL.md + a zero-dependency runner.`
5. **Topics** (this is how people find it):
   `ai-agents`, `multi-agent`, `llm`, `agent-skills`, `orchestration`,
   `prompt-engineering`, `claude-code`, `codex`, `model-agnostic`,
   `multi-model`, `consensus`, `ai-council`.

### CLI

```bash
git init
git add .
git commit -m "ai-council v1.0.0 — a model-agnostic multi-AI council protocol"
git branch -M main
git remote add origin https://github.com/<you>/ai-council.git
git push -u origin main
git tag -a v1.0.0 -m "v1.0.0"
git push --tags
```

Then create a **Release** from the tag; paste the top section of `CHANGELOG.md`.

## 3. Making it installable

The repo *is* the skill: `SKILL.md` at the root with valid frontmatter is the
whole contract. Installation is a copy.

### Claude Code / Claude Agent Skills

```bash
mkdir -p ~/.claude/skills
cp -r ai-council ~/.claude/skills/ai-council
```

Project-scoped instead: `.claude/skills/ai-council/`. The `skills/` loader reads
the frontmatter and loads the body when the description matches a request. Keep
`references/` alongside — the body points at those files, and loading them only
when needed is the point of the progressive-disclosure layout.

### OpenAI Codex / any AGENTS.md-driven agent

Append to `AGENTS.md` (project root) or keep the repo as a sibling and reference it:

```markdown
## Multi-model decisions
Read `ai-council/SKILL.md` before any high-stakes or irreversible decision.
It defines a council protocol (independent proposals → anonymised critique →
revision → convergence) and a runner at `ai-council/scripts/council.py`.
```

`AGENTS.md` is read by Codex, Aider, Jules, and a growing list of tools. This
repo ships one that points back at the skill.

### Cursor

`.cursor/rules/ai-council.mdc`:

```markdown
---
description: Multi-model council for high-stakes decisions
globs: ["**/*"]
alwaysApply: false
---
When a request involves an irreversible decision or contested technical claim,
follow the protocol in ai-council/SKILL.md (independence → anonymised critique
→ revision → convergence), and keep dissent in the output.
```

### DSH / other Agent-Skills hosts

Copy the folder into the profile's skills directory. The frontmatter is
deliberately plain (`name`, `description`, `license`) so it needs no host-specific
fields.

### Chat-only products (ChatGPT, Gemini, Kimi, Doubao, Copilot)

Two options:

- **Project / GPT / Gem knowledge:** upload `SKILL.md` + `references/relay-kit.md`
  + `references/prompts.md`, then say "use the ai-council protocol".
- **Custom instructions / system prompt:** paste the *Non-negotiables* section of
  `SKILL.md` plus the role cards you need. Short and stable beats the whole repo.

### Self-hosted chat UIs (Open WebUI, LibreChat, Chatbox, Cherry Studio)

Paste `SKILL.md` as the system prompt, or add it as a knowledge file. The relay
kit is the operating manual for the user.

## 4. Discoverability

- README first screen answers: what is this, why does it work, how do I run it
  in 30 seconds. Both English and Chinese (`README.md`, `README.zh-CN.md`).
- Include the **offline demo** output in the README — a screenshot of the
  transcript is more persuasive than any claim about collaboration.
- `llms.txt` at the root: a short index for crawlers and agents.
- Add the repo to relevant awesome-lists (`awesome-ai-agents`,
  `awesome-agent-skills`, multi-agent tooling lists) via PR — slow but durable.
- Post the *insight*, not the code: "why asking five models the same question
  fails, and the four mechanisms that fix it" is the shareable artifact.

## 5. Versioning

- `SKILL.md` content and protocol are versioned together; bump `VERSION` in
  `council.py` and add a `CHANGELOG.md` entry.
- Keep `minutes.json` backward compatible: add fields, do not rename them. People
  will archive these as decision records.
- Tag releases; a skill that silently changes behaviour breaks trust faster than
  a library does.

## 6. What to say when someone asks "why not LangGraph / AutoGen / CrewAI?"

Because those are **frameworks** — you write code that runs agents. This is a
**protocol plus a 400-line script**: it works with any model, in any host, with
or without code, and its output is a decision record rather than a running
system. They compose: a LangGraph node can call `council.py` as a tool, and a
CrewAI crew can adopt the round structure. Use the framework when you need
durable orchestration; use this when you need several models to disagree
usefully once.

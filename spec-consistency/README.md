# spec-consistency

**Your spec sheet says 512 Wh. Your deck says 500 Wh. Your quote copied the deck.**

Every document in a product pack can be individually correct while the set is
wrong. This skill audits the set: it extracts `parameter: value unit` pairs from
Word, PowerPoint, Excel and Markdown, lines them up, and reports every
contradiction with the source sentence attached.

`MIT` · `Python 3.10+` · `35 offline tests` · `no API calls`

## 30-second demo

```bash
python scripts/spec_audit.py demo
```

It builds a three-document pack with three planted contradictions and audits it:

```
documents: 3 · parameters: 6 · comparable: 4
findings: 3 high / 3 medium / 2 low
  [high] 电池容量: 512Wh vs 500Wh vs 512Wh
  [high] 满载续航: 50分钟 vs 45分钟
  [high] 整机重量: 6kg vs 6.2kg vs 6.2kg
```

## Use it

```bash
python scripts/spec_audit.py scan ./product-material -o reports
python scripts/spec_audit.py scan ./product-material -o reports --fail-on high   # CI gate
```

Output: `reports/spec-consistency.md` (human) and `.json` (machine). Every
finding carries the document, location and original sentence, so a reader can
judge it instead of trusting it.

## What it checks

| Check | Example | Severity |
|---|---|---|
| Cross-document value mismatch | 6.2 kg in the spec, 6.0 kg in the deck | high |
| One document contradicting itself | two capacities in one quote (usually two SKUs) | medium |
| Different dimensions under one name | Wh vs % | medium |
| Unit-style drift only | 45 分钟 vs 45 min | low |
| Parameter present in one file only | charging time only in the spec | low |

Values are converted to a shared base unit before comparing (`6.2 kg` equals
`6200 g`; tolerance 0.5%).

## What it cannot do

- read numbers inside charts, images or PDFs — export first
- judge whether a value is *true*, only whether the documents agree
- separate `续航 45 分钟（满载）` from `续航 50 分钟（最长）` — put the condition in
  the parameter name
- know your synonyms — register them in `SYNONYMS`

So it produces a **judgement queue**, not a verdict. Deciding which value wins is
still your job; the spec sheet is usually the truth source, but "three documents
say 500" does not make 500 correct.

## Layout

```
SKILL.md                     # entry point for agents
references/consistency-rules.md  # eight parameter classes and their failure modes
references/workflow.md           # audit → fix → CI gate
scripts/spec_audit.py            # extractor + comparator + report
tests/test_spec_audit.py         # 35 offline tests
```

Chinese overview: [`README.zh-CN.md`](README.zh-CN.md).

## License

MIT.

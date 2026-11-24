# Workflow · from audit to fixed, and staying fixed

## When an audit is worth running

| Moment | Why |
|---|---|
| before a customer-facing pack goes out | the customer finds contradictions for free |
| after any spec change | every copy is now a suspect |
| before a bid submission | a wrong number can disqualify the whole bid |
| at release, and every release after | the pack rots exactly like code |
| monthly, as a CI gate | cheap, and it catches copy-paste from an old deck |

Do not run it on a draft — you will drown in findings that resolve themselves.
Run it on the version that is about to leave the building.

## The four steps

### 1. Assemble one folder

```
product-material/
├── 01-规格书.docx
├── 02-宣传页.pptx
├── 03-报价单.xlsx
├── 04-说明书.docx
└── 05-官网文案.md
```

One folder, no nesting needed. The scanner recurses, skips `.git`,
`node_modules` and `reports`. Name files with a consistent prefix so the report
reads in the order a reader would.

**Do not** include the internal engineering spreadsheet with unannounced
changes, or the report will flag planned changes as contradictions. If you must,
put it in a separate folder and audit it separately.

### 2. Run the audit

```bash
python scripts/spec_audit.py scan ./product-material -o reports
```

Read the headline first: documents, parameters, conflicts. Then the `high`
section only. Medium and low are for the cleanup pass, not for the launch
decision.

### 3. Judge each finding

For every `high`:

1. read the context column — is it the same parameter or a different one that
   shares a name?
2. decide the truth source (normally the spec sheet)
3. write the edit: file → old string → new string

A finding is only closed by one of:

- **fixed** — the wrong document changed
- **scoped** — the parameter name was made specific (`PX-200 电池容量`)
- **accepted** — a deliberate difference, recorded in the report footer with a
  reason and a date

"Looks fine" is not a closure. That is how the same conflict returns next quarter.

### 4. Apply the fix, then re-run

Apply edits in one reviewable pass, then run the audit again with
`--fail-on high`. Zero high findings is the gate.

## Example: the PX-200 pack

`python scripts/spec_audit.py demo` builds a three-document pack with three real
contradictions and audits it:

```
documents: 3 · parameters: 6 · comparable: 4
findings: 3 high / 3 medium / 2 low
  [high] 电池容量: 512Wh vs 500Wh vs 512Wh
  [high] 满载续航: 50分钟 vs 45分钟
  [high] 整机重量: 6kg vs 6.2kg vs 6.2kg
```

The three `medium` findings are the interesting ones: the quote holds two SKUs,
so `电池容量` and `单价` each have two values *inside one file*. That is not a
typo — it is the report telling you the parameter name needs the model in it.
Fixing the naming (`PX-200 电池容量` / `PX-200 Pro 电池容量`) removes the noise
and makes the next audit readable.

## Turning it into a gate

```yaml
# .github/workflows/spec.yml
- name: spec consistency
  run: |
    pip install python-docx python-pptx openpyxl
    python scripts/spec_audit.py scan ./product-material -o reports --fail-on high
- uses: actions/upload-artifact@v4
  with: { name: spec-report, path: reports/ }
```

The audit runs on every push that touches the pack. A `high` finding fails the
build, which is the only way anybody reads it.

## Reducing noise over time

The script improves with three small, local edits — all in `spec_audit.py`:

1. **`SYNONYMS`** — when two teams name the same thing differently, add the
   mapping. This is the highest-leverage edit.
2. **`KEY_HEADERS` / `VALUE_HEADERS`** — when your tables use different column
   labels (`指标 | 内容`), add them.
3. **`UNIT_TABLE`** — a unit your industry uses that is missing (`Mbps`, `Wh/kg`).

Keep those edits in the repo next to the documents they audit, not in a fork.

## What the report is good for beyond the fix

- a **glossary**: the parameter table at the end is the beginning of a data
  dictionary
- a **review checklist**: paste the `high` section into the launch checklist
- an **onboarding artefact**: a new hire reads one report and learns what the
  product's numbers actually are
- a **change log**: keep the reports, and you can see when a number moved and by
  how much

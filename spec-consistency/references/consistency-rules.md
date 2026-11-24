# Consistency rules, dimension by dimension

A product pack repeats about eight kinds of facts. Each has its own failure
mode. Use this list when deciding what to cross-check, and when writing the
"truth source" judgement.

## 1. Performance numbers

`电池容量 512 Wh`, `输出功率 600 W`, `续航 45 分钟`, `充电时长 3 小时`.

- **Typical conflict:** the marketing number is rounded or optimistic (500 Wh,
  50 min), the engineering number is exact.
- **Trap:** "up to" numbers. `续航最长 50 分钟` is not a conflict with
  `满载续航 45 分钟` — different conditions. Insist that the *condition* is part
  of the parameter name, or the audit will keep re-raising it.
- **Truth source:** the spec sheet, unless the deck states a test condition that
  the spec sheet omits (then the spec sheet is incomplete, which is its own
  finding).

## 2. Physical attributes

`整机重量 6.2 kg`, `外形尺寸 300×200×180 mm`, `颜色`, `材质`.

- **Typical conflict:** packaging weight vs product weight; mm vs cm drift.
- **Trap:** 尺寸 is often written as `300 × 200 × 180 mm` — the script reads the
  first number only. For any parameter containing `×`, check the full string by
  hand.
- **Truth source:** spec sheet; the quote usually copies it and is the most
  likely to be stale.

## 3. Electrical and interface

`输入 100-240 V`, `接口 USB-C ×2`, `额定电流 5 A`.

- **Typical conflict:** ranges collapse to a single number (`220 V`), or the
  region variant is quoted without saying which region.
- **Trap:** ranges are not scalars. `100-240 V` will not parse as one value;
  treat it as manual-review and note it in the report's "unverifiable" section.

## 4. Certifications and compliance

`认证 CE / FCC / RoHS`, `防护等级 IP54`, `执行标准 GB/T xxxx`.

- **Typical conflict:** a certification is claimed in the deck before it is
  granted. This is a legal exposure, not a typo — rank it high by hand even if
  the script cannot see it.
- **Check:** the certification body's exact wording, the certificate number, and
  the model names it covers.

## 5. Commercial terms

`单价 1299 元`, `起订量 100 台`, `交期 30 天`, `质保 2 年`.

- **Typical conflict:** the quote was built on an older spec, so the price
  silently reflects a different BOM.
- **Trap:** multi-SKU tables always hold several values per column. That is not
  an internal conflict; it is a model-name problem. Fix by adding the SKU to the
  parameter name.
- **Truth source:** the signed quote for price, the spec sheet for what the price
  buys. When they disagree, the finding is "the quote is priced against a
  different configuration", which is a business problem worth escalating.

## 6. Model naming

`PX-200`, `PX-200 Pro`, `PX200`, `PX-200（增强版）`.

- **Typical conflict:** four spellings, one product; search-and-replace misses two.
- **Rule:** one canonical form, used everywhere, including filenames and slide
  titles. Hyphenation and spacing are part of the name.
- The script does not audit naming directly; do it by reading the report's
  parameter list and the file names.

## 7. Terminology

`续航` / `使用时间` / `工作时间`; `整机重量` / `净重` / `质量`.

- **Typical conflict:** the same metric under three names, so nothing is ever
  compared.
- **Rule:** one term per concept, defined once in a glossary, used everywhere.
  The script's `SYNONYMS` map is where you encode this.
- If two documents use different terms for the same number, that is a `low`
  finding — but it is the *cause* of the next real conflict, so fix it.

## 8. Dates, versions, and identifiers

`版本 V2.3`, `更新日期 2026-03-01`, `型号编号 PX200-A1`.

- **Typical conflict:** the deck says V2.3, the file on disk is V2.1, the footer
  says 2025.
- **Check:** document footer, filename, cover page, and the version in the
  header all match, and the date is not in the future.

## Severity rules

| Severity | When | Example |
|---|---|---|
| **high** | the same parameter, same dimension, different value beyond tolerance | 512 Wh vs 500 Wh |
| **medium** | same name, different dimensions; one file contradicts itself | 容量 in Wh vs 容量 in % |
| **low** | unit-style drift only; a parameter exists in one file | 45 分钟 vs 45 min; 充电时长 only in the spec |

Tolerance defaults to 0.5% relative. Values that differ only by rounding
(`512` vs `512.0`) are not findings. Values that differ by a transcription error
(`618` vs `681`) are high — and worth a second look at the *other* documents,
because the typo usually travelled.

## What this audit deliberately does not do

- read charts, images, or PDFs — export to docx/xlsx first, or note the gap
- judge whether a number is *true* — only whether the documents agree
- fix the documents — it produces an edit list; applying it is a separate,
  reviewable step

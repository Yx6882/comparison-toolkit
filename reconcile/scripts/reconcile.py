#!/usr/bin/env python3
"""reconcile — compare any two files by extracting records, aligning keys, diffing attributes.

    python scripts/reconcile.py run 今日股价.csv 昨日股价.csv
    python scripts/reconcile.py run 合同A.docx 合同B.docx
    python scripts/reconcile.py run 物料A.xlsx 物料B.xlsx --key 物料号 --fields 单价,数量
    python scripts/reconcile.py demo

The engine is deliberately format-agnostic. Each loader turns a file into a list of
Entity(key, attrs). Then one matcher aligns left keys to right keys (exact, then
fuzzy), and one comparator diffs each pair of attributes (number+unit first, text
similarity second). Reports are the same regardless of input format.

What "any two files" honestly means:
  files with structure  -> good results (tables, docs, key-value parameters)
  free prose            -> works, but every sentence becomes a "difference"
  images / PDF / binary -> not supported; convert first
  semantic equivalence  -> only with a synonym table ("营收" vs "营业收入")
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import difflib
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Units — a small shared table so 6.2kg and 6200g compare equal
# ---------------------------------------------------------------------------

UNITS: dict[str, dict[str, float]] = {
    "mass": {"g": 1, "kg": 1000, "t": 1_000_000, "克": 1, "千克": 1000, "公斤": 1000, "斤": 500},
    "length": {"mm": 1, "cm": 10, "m": 1000, "km": 1_000_000, "in": 25.4, "英寸": 25.4, "毫米": 1, "厘米": 10, "米": 1000},
    "time": {"s": 1, "min": 60, "h": 3600, "秒": 1, "分钟": 60, "分": 60, "小时": 3600, "天": 86400},
    "power": {"w": 1, "kw": 1000, "瓦": 1, "千瓦": 1000},
    "energy": {"wh": 1, "kwh": 1000, "mwh": 1_000_000},
    "current": {"a": 1, "ma": 0.001, "安": 1},
    "voltage": {"v": 1, "kv": 1000, "伏": 1},
    "percent": {"%": 1, "％": 1},
    "money": {"元": 1, "千元": 1000, "万元": 10000, "美元": 7.0, "usd": 7.0, "rmb": 1, "cny": 1, "¥": 1, "￥": 1},
}
UNIT_TO_DIM: dict[str, str] = {}
for _dim, _table in UNITS.items():
    for _unit in _table:
        UNIT_TO_DIM.setdefault(_unit, _dim)
UNIT_RE = "|".join(sorted((re.escape(u) for u in UNIT_TO_DIM), key=len, reverse=True))
NUMBER_RE = re.compile(rf"(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_RE})?", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

SPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[，。；：、,.;:!?！？\"'“”‘’（）()\[\]【】《》<>]")
NOISE_WORDS = {"合计", "小计", "总计", "备注", "说明", "序号"}

FULLWIDTH = {chr(0xFF01 + i): chr(0x21 + i) for i in range(94)}


def normalize(text: Any) -> str:
    if text is None:
        return ""
    value = str(text).strip()
    value = "".join(FULLWIDTH.get(ch, ch) for ch in value)
    value = PUNCT_RE.sub("", value)
    value = SPACE_RE.sub("", value)
    return value.lower()


VERSION_LIKE_RE = re.compile(r"^[\s\^~>=<]*v?\d+(?:\.\d+){2,}(?:[-+][\w.]+)?\s*$")


def looks_like_version(text: Any) -> bool:
    """6.11.0 and 6.13.0 are different releases, not a 0.3% numeric drift."""
    return bool(VERSION_LIKE_RE.match(str(text or "")))


def parse_number(text: Any) -> tuple[float, str] | None:
    """Return (value in base unit, dimension) when the cell is numeric."""
    if text is None:
        return None
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return float(text), "none"
    raw = str(text).strip()
    if not raw:
        return None
    if looks_like_version(raw):
        return None  # versions compare as text, exactly
    raw = raw.replace(",", "").replace("，", "")
    match = NUMBER_RE.search(raw)
    if not match:
        return None
    # a cell with lots of prose around the number is not a numeric attribute
    if len(NUMBER_RE.sub("", raw).strip(PUNCT_RE.pattern)) > 6:
        return None
    value = float(match.group("value"))
    unit = (match.group("unit") or "").strip().lower() or (match.group("unit") or "")
    if not unit:
        return value, "none"
    dim = UNIT_TO_DIM.get(unit.lower())
    if dim is None:
        return value, "none"
    return value * UNITS[dim][unit.lower()], dim


# ---------------------------------------------------------------------------
# Entities and loaders
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Entity:
    key: str
    attrs: dict[str, str]
    ref: str
    raw: str = ""
    kind: str = "row"

    @property
    def display(self) -> str:
        return self.raw or self.key or (self.ref if self.ref else "")


@dataclasses.dataclass
class Table:
    source: str
    header: list[str]
    rows: list[list[str]]
    entities: list[Entity] = dataclasses.field(default_factory=list)
    key_column: str = ""
    notes: list[str] = dataclasses.field(default_factory=list)


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def load_xlsx(path: Path, sheet: str | None = None) -> Table:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
    rows = [[cell_text(c) for c in row] for row in ws.iter_rows(values_only=True)]
    wb.close()
    return table_from_rows(path.name, rows, extra=[f"sheet={ws.title}"])


def load_csv(path: Path) -> Table:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [list(row) for row in csv.reader(raw.splitlines(), dialect)]
    return table_from_rows(path.name, rows)


def table_from_rows(source: str, rows: list[list[str]], extra: list[str] | None = None) -> Table:
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return Table(source=source, header=[], rows=[], notes=["空表"])
    header = [cell or f"列{i + 1}" for i, cell in enumerate(rows[0])]
    body = [row for row in rows[1:] if any(cell for cell in row)]
    return Table(source=source, header=header, rows=body, notes=extra or [])


def load_table(path: Path, sheet: str | None = None) -> Table:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return load_xlsx(path, sheet)
    if suffix in {".csv", ".tsv", ".txt"}:
        return load_csv(path)
    raise SystemExit(f"不是表格文件：{path}")


TEXT_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv", ".docx", ".pptx", ".md", ".txt"}
DOC_SUFFIXES = TEXT_SUFFIXES | {
    ".json", ".xml", ".html", ".htm", ".log", ".yaml", ".yml", ".ini", ".toml",
    ".py", ".js", ".ts", ".css", ".sql", ".sh", ".ps1",
}


def load_document(path: Path) -> list[Entity]:
    suffix = path.suffix.lower()
    if suffix not in DOC_SUFFIXES:
        print(
            f"error: 不支持把 {suffix or '无扩展名'} 当文本对照：{path.name}。"
            "图片/音频走媒体对照，PDF 请先转成 docx/txt。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        blocks: list[tuple[str, str]] = []
        for index, para in enumerate(doc.paragraphs, start=1):
            text = para.text.strip()
            if text:
                blocks.append((f"段落{index}", text))
        for t_index, table in enumerate(doc.tables, start=1):
            for r_index, row in enumerate(table.rows, start=1):
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    blocks.append((f"表{t_index}行{r_index}", " | ".join(c for c in cells if c)))
    elif suffix == ".pptx":
        from pptx import Presentation

        prs = Presentation(str(path))
        blocks = []
        for s_index, slide in enumerate(prs.slides, start=1):
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = "".join(run.text for run in para.runs).strip()
                        if text:
                            blocks.append((f"第{s_index}页", text))
    else:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        blocks = [(f"第{i}行", line.strip()) for i, line in enumerate(text.splitlines(), start=1) if line.strip()]

    entities: list[Entity] = []
    for ref, text in blocks:
        key = normalize(text)[:60]
        entities.append(Entity(key=key or ref, attrs={"内容": text}, ref=ref, raw=text, kind="block"))
    return entities


# ---------------------------------------------------------------------------
# Key selection
# ---------------------------------------------------------------------------


STRONG_KEY_HINTS = ("代码", "编号", "单号", "物料号", "工号", "id", "code", "key", "sku")
MEDIUM_KEY_HINTS = ("名称", "项目", "参数", "科目", "型号", "姓名", "日期", "title", "name")


def pick_key_column(table: Table) -> tuple[str, float]:
    """Choose the column that behaves most like a primary key.

    A code column is a better key than a name column even when both are unique:
    names get reworded between versions, codes do not.
    """
    if not table.header or not table.rows:
        return "", 0.0
    best, best_score = table.header[0], -1.0
    for index, name in enumerate(table.header):
        values = [row[index] for row in table.rows if index < len(row) and row[index]]
        if not values:
            continue
        unique_ratio = len(set(values)) / len(values)
        numeric_ratio = sum(1 for v in values if parse_number(v)) / len(values)
        lowered = name.lower()
        if any(hint in lowered for hint in STRONG_KEY_HINTS):
            hint = 0.5
        elif any(hint in lowered for hint in MEDIUM_KEY_HINTS):
            hint = 0.22
        else:
            hint = 0.0
        score = unique_ratio * 0.55 + (1 - numeric_ratio) * 0.1 + hint
        if score > best_score:
            best, best_score = name, score
    return best, max(best_score, 0.0)


def build_entities(table: Table, key_column: str | None, fields: Sequence[str] | None) -> Table:
    key_col = key_column or pick_key_column(table)[0]
    if key_col not in table.header:
        # fall back to first column
        key_col = table.header[0] if table.header else ""
    key_index = table.header.index(key_col) if key_col in table.header else 0
    chosen_fields = [f for f in (fields or []) if f in table.header] or [
        name for name in table.header if name != key_col
    ]
    entities: list[Entity] = []
    for row_number, row in enumerate(table.rows, start=2):
        if key_index >= len(row):
            continue
        key = normalize(row[key_index])
        if not key or key in NOISE_WORDS:
            continue
        attrs = {
            name: (row[table.header.index(name)] if table.header.index(name) < len(row) else "")
            for name in chosen_fields
        }
        entities.append(
            Entity(key=key, attrs=attrs, ref=f"行{row_number}", raw=row[key_index], kind="row")
        )
    table.entities = entities
    table.key_column = key_col
    return table


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left, right).ratio()


CODE_RE = re.compile(r"^[a-z]{0,5}[-_ ]?\d{2,}[a-z0-9\-_.]*$")


def looks_like_code(key: str) -> bool:
    """M-1004 and M-1005 are different parts, not a typo of each other."""
    return bool(CODE_RE.match(key or ""))


def align_entities(
    left: list[Entity], right: list[Entity], *, fuzzy: bool = True, threshold: float = 0.82
) -> tuple[list[tuple[Entity, Entity]], list[Entity], list[Entity], list[tuple[Entity, Entity, float]]]:
    """Exact key match first, then fuzzy for the leftovers (docs rewrite sentences)."""
    right_by_key: dict[str, Entity] = {}
    for entity in right:
        right_by_key.setdefault(entity.key, entity)

    matched: list[tuple[Entity, Entity]] = []
    only_left: list[Entity] = []
    used_right: set[str] = set()
    for entity in left:
        candidate = right_by_key.get(entity.key)
        if candidate is not None and entity.key not in used_right:
            matched.append((entity, candidate))
            used_right.add(entity.key)
        else:
            only_left.append(entity)

    only_right = [entity for entity in right if entity.key not in used_right]
    fuzzy_pairs: list[tuple[Entity, Entity, float]] = []
    if fuzzy and only_left and only_right:
        for entity in list(only_left):
            if looks_like_code(entity.key):
                continue  # codes must match exactly
            best, best_score = None, 0.0
            for candidate in only_right:
                if looks_like_code(candidate.key):
                    continue
                score = similarity(entity.key, candidate.key)
                if score > best_score:
                    best, best_score = candidate, score
            if best is not None and best_score >= threshold:
                fuzzy_pairs.append((entity, best, best_score))
                only_left.remove(entity)
                only_right.remove(best)
        matched.extend((a, b) for a, b, _ in fuzzy_pairs)
    return matched, only_left, only_right, fuzzy_pairs


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


MONEY_FIELDS = ("金额", "单价", "总价", "价格", "费用", "成本", "报价", "amount", "price", "cost", "total")
QTY_FIELDS = ("数量", "件数", "台数", "套数", "个数", "qty", "quantity", "count")


def looks_money(field: str) -> bool:
    lowered = field.lower()
    return any(token in lowered for token in MONEY_FIELDS)


def looks_quantity(field: str) -> bool:
    lowered = field.lower()
    return any(token in lowered for token in QTY_FIELDS)


def pick_quantity(attrs: dict[str, str]) -> float | None:
    for name, value in attrs.items():
        if looks_quantity(name):
            parsed = parse_number(value)
            if parsed:
                return parsed[0]
    return None


@dataclasses.dataclass
class Diff:
    kind: str  # only_left | only_right | value | text
    key: str
    label: str
    field: str = ""
    left: str = ""
    right: str = ""
    delta: float | None = None
    delta_unit: str = "ratio"  # ratio | pp
    score: float | None = None
    severity: str = "medium"
    ref: str = ""
    note: str = ""
    impact: float | None = None  # 金额化影响：|差值| × 数量


def compare_values(field: str, left_raw: str, right_raw: str, *, tolerance: float) -> Diff | None:
    left_value = parse_number(left_raw)
    right_value = parse_number(right_raw)
    if left_value and right_value:
        (lv, ldim), (rv, rdim) = left_value, right_value
        if ldim == rdim and (ldim != "none" or True):
            if ldim != "none" and abs(lv - rv) <= 1e-9:
                return None
            if ldim == "none" and abs(lv - rv) <= 1e-9:
                return None
            base = abs(lv) or 1.0
            delta = (rv - lv) / base
            if abs(rv - lv) <= tolerance * max(1.0, abs(lv)):
                return None
            if ldim == "percent":
                # 1.2% vs 0.9% is a 0.3 percentage-point move, not -25%
                return Diff(
                    kind="value", key="", label=field, field=field, left=left_raw, right=right_raw,
                    delta=rv - lv, delta_unit="pp",
                    severity="high" if abs(rv - lv) >= 0.1 else "low",
                )
            return Diff(
                kind="value",
                key="",
                label=field,
                field=field,
                left=left_raw,
                right=right_raw,
                delta=delta,
                severity="high" if abs(delta) > 0.001 else "low",
            )
        if ldim != rdim:
            return Diff(
                kind="value", key="", label=field, field=field, left=left_raw, right=right_raw,
                severity="medium", note=f"单位维度不同：{ldim} vs {rdim}",
            )
    if normalize(left_raw) == normalize(right_raw):
        return None
    score = similarity(normalize(left_raw), normalize(right_raw))
    if score >= 0.999:
        return None
    return Diff(
        kind="text",
        key="",
        label=field,
        field=field,
        left=left_raw,
        right=right_raw,
        score=score,
        severity="high" if score < 0.6 else "medium",
    )


DATE_TOKEN_RE = re.compile(r"\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?")
SIMPLE_NUM_RE = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*(?:%|％)?")


def extract_numeric_tokens(text: str) -> list[str]:
    """Every number and date in a sentence — the part a human is really looking at."""
    cleaned = (text or "").replace(",", "").replace("，", "")
    dates = {d.replace(" ", "") for d in DATE_TOKEN_RE.findall(cleaned)}
    numbers = {n.replace(" ", "") for n in SIMPLE_NUM_RE.findall(DATE_TOKEN_RE.sub(" ", cleaned))}
    return sorted(dates | numbers)


def compare_entities(
    matched: list[tuple[Entity, Entity]],
    only_left: list[Entity],
    only_right: list[Entity],
    *,
    tolerance: float = 0.01,
    text_threshold: float = 0.995,
) -> list[Diff]:
    diffs: list[Diff] = []
    for left, right in matched:
        if left.kind == "block":
            # documents: compare the numbers/dates first, then the wording
            left_text = left.attrs.get("内容", left.raw)
            right_text = right.attrs.get("内容", right.raw)
            left_tokens = extract_numeric_tokens(left_text)
            right_tokens = extract_numeric_tokens(right_text)
            if left_tokens != right_tokens:
                diffs.append(
                    Diff(
                        kind="value",
                        key=left.display[:40],
                        label="数字 / 日期",
                        left=", ".join(left_tokens) or "—",
                        right=", ".join(right_tokens) or "—",
                        severity="high",
                        ref=f"{left.ref} → {right.ref}",
                        note="金额 / 日期 / 数量发生变化",
                    )
                )
            score = similarity(normalize(left_text), normalize(right_text))
            if score < text_threshold:
                diffs.append(
                    Diff(
                        kind="text",
                        key=left.display[:40],
                        label="文字表述",
                        left=left_text,
                        right=right_text,
                        score=score,
                        severity="medium" if score >= 0.75 else "high",
                        ref=f"{left.ref} → {right.ref}",
                        note="措辞不同",
                    )
                )
            continue
        fields = [name for name in left.attrs if name in right.attrs] or list(left.attrs)
        for field in fields:
            diff = compare_values(field, left.attrs.get(field, ""), right.attrs.get(field, ""), tolerance=tolerance)
            if diff is None:
                continue
            if diff.kind == "text" and diff.score is not None and diff.score >= text_threshold:
                continue
            diff.key = left.display
            diff.ref = f"{left.ref} → {right.ref}"
            if diff.kind == "value" and looks_money(field):
                left_num = parse_number(left.attrs.get(field, ""))
                right_num = parse_number(right.attrs.get(field, ""))
                if left_num and right_num:
                    quantity = pick_quantity(left.attrs) or 1.0
                    diff.impact = abs(right_num[0] - left_num[0]) * quantity
            diffs.append(diff)
    for entity in only_left:
        diffs.append(
            Diff(
                kind="only_left", key=entity.display, label="仅左侧存在", ref=entity.ref,
                left=entity.raw or entity.key, severity="medium",
                note="; ".join(f"{k}={v}" for k, v in entity.attrs.items() if v)[:120],
            )
        )
    for entity in only_right:
        diffs.append(
            Diff(
                kind="only_right", key=entity.display, label="仅右侧存在", ref=entity.ref,
                right=entity.raw or entity.key, severity="medium",
                note="; ".join(f"{k}={v}" for k, v in entity.attrs.items() if v)[:120],
            )
        )
    return diffs


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_report(
    left_path: Path,
    right_path: Path,
    mode: str,
    left_meta: dict[str, Any],
    right_meta: dict[str, Any],
    diffs: list[Diff],
    *,
    matched_count: int,
    fuzzy_pairs: list[tuple[Entity, Entity, float]],
) -> str:
    counts = {kind: sum(1 for d in diffs if d.kind == kind) for kind in ("value", "text", "only_left", "only_right")}
    lines = [
        "# 对照报告",
        "",
        f"- 左：`{left_path}` · 右：`{right_path}`",
        f"- 模式：{mode} · 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M}",
        f"- 对齐成功 {matched_count} 对（其中模糊匹配 {len(fuzzy_pairs)} 对）",
        f"- 差异：数值 {counts['value']} · 文本 {counts['text']} · 仅左 {counts['only_left']} · 仅右 {counts['only_right']}",
        "",
    ]
    if left_meta.get("key"):
        lines.append(f"- 左表主键列：`{left_meta['key']}`" + (f" · 右表主键列：`{right_meta['key']}`" if right_meta.get("key") else ""))
    for note in left_meta.get("notes", []) + right_meta.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")

    if fuzzy_pairs:
        lines.extend(["## 模糊匹配（名称不完全相同，按相似度对齐）", "", "| 左 | 右 | 相似度 |", "|---|---|---|"])
        for left, right, score in fuzzy_pairs[:15]:
            lines.append(f"| {left.raw or left.key} | {right.raw or right.key} | {score:.0%} |")
        lines.append("")

    ranked = sorted((diff for diff in diffs if diff.impact), key=lambda diff: -(diff.impact or 0))[:5]
    if ranked:
        lines.extend(
            [
                "## 优先看这些（按金额影响排序）",
                "",
                "| 键 | 字段 | 左 | 右 | 影响金额 |",
                "|---|---|---|---|---|",
            ]
        )
        for diff in ranked:
            lines.append(
                f"| {diff.key} | {diff.label} | {diff.left} | {diff.right} | {diff.impact:,.2f} |"
            )
        lines.extend(
            [
                "",
                "按「差值 × 数量」估算，**只用于排序，不代表实际损失**；数量缺失时按 1 计。",
                "",
            ]
        )

    def section(title: str, kinds: Sequence[str]) -> None:
        items = [d for d in diffs if d.kind in kinds]
        if not items:
            return
        lines.extend([f"## {title}（{len(items)}）", "", "| 键 | 字段 | 左 | 右 | 差异 |", "|---|---|---|---|---|"])
        for diff in items:
            if diff.kind == "value":
                if diff.delta_unit == "pp" and diff.delta is not None:
                    delta = f"{diff.delta:+.2f}pp"
                elif diff.delta is not None:
                    delta = f"{diff.delta * 100:+.1f}%"
                else:
                    delta = diff.note or "单位不同"
                left, right = diff.left, diff.right
            elif diff.kind == "text":
                delta = f"相似度 {diff.score:.0%}" if diff.score is not None else ""
                left, right = diff.left[:60], diff.right[:60]
            elif diff.kind == "only_left":
                delta, left, right = "左侧独有", (diff.left or "")[:60], "—"
            else:
                delta, left, right = "右侧独有", "—", (diff.right or "")[:60]
            lines.append(f"| {diff.key} | {diff.label} | {left} | {right} | {delta} |")
        lines.append("")

    section("数值/金额不一致", ["value"])
    section("文本不一致", ["text"])
    section("仅左侧存在", ["only_left"])
    section("仅右侧存在", ["only_right"])

    if not diffs:
        lines.extend(["## 结论", "", "两边对齐后没有发现差异。", ""])

    lines.extend(
        [
            "---",
            "",
            "> 对齐规则：先按键精确匹配，剩下的按名称相似度兜底（阈值可调）。",
            "> 数值会比较单位（6.2kg = 6200g）；文本按相似度判定，不改写原文。",
            "",
        ]
    )
    return "\n".join(lines)


def write_excel(out_dir: Path, diffs: list[Diff], matched_count: int) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "差异清单"
    ws.append(["#", "类型", "键", "字段", "左", "右", "差异", "影响金额", "严重度", "位置", "备注"])
    for index, diff in enumerate(diffs, start=1):
        if diff.delta is not None:
            delta_text = f"{diff.delta:+.2f}pp" if diff.delta_unit == "pp" else f"{diff.delta * 100:+.1f}%"
        elif diff.score is not None:
            delta_text = f"{diff.score:.0%}"
        else:
            delta_text = ""
        ws.append(
            [
                index,
                {"value": "数值", "text": "文本", "only_left": "仅左", "only_right": "仅右"}.get(diff.kind, diff.kind),
                diff.key,
                diff.label,
                diff.left,
                diff.right,
                delta_text,
                diff.impact,
                diff.severity,
                diff.ref,
                diff.note,
            ]
        )
    header_fill = PatternFill("solid", fgColor="E8EEF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True)
    widths = [5, 8, 28, 14, 32, 32, 12, 14, 8, 18, 40]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + index)].width = width
    ws.freeze_panes = "A2"

    summary = wb.create_sheet("汇总")
    summary["A1"] = "对照汇总"
    summary["A1"].font = Font(bold=True, size=14)
    summary["A3"] = "对齐成功"
    summary["B3"] = matched_count
    summary["A4"] = "差异总数"
    summary["B4"] = len(diffs)
    for row, label in ((5, "数值不一致"), (6, "文本不一致"), (7, "仅左侧"), (8, "仅右侧")):
        kinds = {5: "value", 6: "text", 7: "only_left", 8: "only_right"}[row]
        summary.cell(row=row, column=1, value=label)
        summary.cell(row=row, column=2, value=sum(1 for d in diffs if d.kind == kinds))
    summary.column_dimensions["A"].width = 16
    summary.column_dimensions["B"].width = 10

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "reconcile-diff.xlsx"
    wb.save(str(target))
    return target


# ---------------------------------------------------------------------------
# Fix suggestions — never touch the original file
# ---------------------------------------------------------------------------

FIX_RISK = {
    "value": "low",      # 可在表格里精确定位并替换
    "text": "medium",    # 文本替换可能多处误命中
    "only_left": "high",  # 删不删要业务判断
    "only_right": "high",  # 补不补要业务判断
}

FIX_ADVICE = {
    "low": "可自动生成修正副本；apply 会校验原值，不匹配则跳过",
    "medium": "只建议人工替换；自动替换可能改到别处",
    "high": "不自动改；需要人判断是补、删还是接受差异",
}


@dataclasses.dataclass
class Patch:
    file: str
    key: str
    field: str
    old: str
    new: str
    basis: str
    risk: str
    kind: str
    note: str = ""


def load_diff_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"差异报告不存在：{path}（先跑 reconcile.py run 生成 JSON）")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: 不是合法 JSON（{exc}）")


def build_patches(report_path: Path, *, target: str = "") -> list[Patch]:
    report = load_diff_json(report_path)
    basis = str(report.get("left") or "")
    target_name = target or str(report.get("right") or "")
    patches: list[Patch] = []
    for diff in report.get("diffs") or []:
        kind = str(diff.get("kind") or "")
        patches.append(
            Patch(
                file=target_name,
                key=str(diff.get("key") or ""),
                field=str(diff.get("field") or diff.get("label") or ""),
                old=str(diff.get("right") or ""),
                new=str(diff.get("left") or ""),
                basis=basis,
                risk=FIX_RISK.get(kind, "high"),
                kind=kind,
                note=str(diff.get("note") or ""),
            )
        )
    return patches


def render_patches(patches: list[Patch], report_path: Path) -> str:
    counts = {risk: sum(1 for p in patches if p.risk == risk) for risk in ("low", "medium", "high")}
    lines = [
        "# 修复建议",
        "",
        f"- 来源差异：`{report_path}`",
        f"- 依据（哪个是基准）：`{patches[0].basis if patches else ''}`",
        f"- 目标：`{patches[0].file if patches else ''}`",
        f"- 条目：低风险 {counts['low']} · 中风险 {counts['medium']} · 高风险 {counts['high']}",
        "",
        "> **只生成建议，不修改原文件。** 低风险项可用 `apply` 生成副本（会校验原值）；"
        "中高风险项请人工处理。",
        "",
    ]

    def section(title: str, risk: str) -> None:
        items = [p for p in patches if p.risk == risk]
        if not items:
            return
        lines.extend([f"## {title}（{len(items)}）", "", FIX_ADVICE[risk], ""])
        lines.append("| 键 | 字段 | 原值（目标） | 建议改成 |")
        lines.append("|---|---|---|---|")
        for patch in items:
            lines.append(f"| {patch.key} | {patch.field} | {patch.old or '—'} | {patch.new or '—'} |")
        lines.append("")

    section("低风险：可直接改", "low")
    section("中风险：建议人工替换", "medium")
    section("高风险：需要业务判断", "high")

    lines.extend(
        [
            "---",
            "",
            "> 建议的方向是「把目标文件对齐到基准文件」。如果基准才是错的，这份清单每一条都反了——"
            "先确认基准，再 apply。",
            "",
        ]
    )
    return "\n".join(lines)


def write_patches(out_dir: Path, patches: list[Patch]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / "fix-suggestions.md"
    md.write_text(render_patches(patches, out_dir / "(见上)"), encoding="utf-8")
    csv_path = out_dir / "fix-patch.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["文件", "键", "字段", "原值", "建议值", "依据", "风险", "类型", "备注"])
        for patch in patches:
            writer.writerow([patch.file, patch.key, patch.field, patch.old, patch.new, patch.basis, patch.risk, patch.kind, patch.note])
    return md, csv_path


def load_patch_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"补丁清单不存在：{path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def apply_csv_patches(target: Path, rows: list[dict[str, str]], *, key_column: str, out: Path) -> dict[str, Any]:
    source = list(csv.reader(target.open(encoding="utf-8-sig", newline="")))
    if not source:
        raise SystemExit(f"{target}: 空文件")
    header = source[0]
    if key_column not in header:
        raise SystemExit(f"{target}: 找不到主键列「{key_column}」，可用列：{header}")
    key_index = header.index(key_column)
    field_index = {name: index for index, name in enumerate(header)}

    applied, skipped, failed = 0, 0, 0
    details: list[str] = []
    for row in source[1:]:
        for patch in rows:
            if patch["风险"] != "low" or not row:
                continue
            if normalize(row[key_index] if key_index < len(row) else "") != normalize(patch["键"]):
                continue
            field = patch["字段"]
            if field not in field_index or field_index[field] >= len(row):
                failed += 1
                details.append(f"跳过 {patch['键']}/{field}：目标文件没有这一列")
                break
            index = field_index[field]
            if normalize(row[index]) != normalize(patch["原值"]):
                skipped += 1
                details.append(f"跳过 {patch['键']}/{field}：当前值 {row[index]!r} ≠ 补丁原值 {patch['原值']!r}")
                break
            row[index] = patch["建议值"]
            applied += 1
            details.append(f"已改 {patch['键']}/{field}：{patch['原值']} → {patch['建议值']}")
            break

    out.mkdir(parents=True, exist_ok=True)
    fixed = out / f"{target.stem}.fixed{target.suffix}"
    with fixed.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(source)
    return {"applied": applied, "skipped": skipped, "failed": failed, "output": fixed, "details": details}


def cmd_patch(args: argparse.Namespace) -> int:
    patches = build_patches(Path(args.diff), target=args.target)
    if not patches:
        print("没有可生成的修复建议（差异为空）")
        return 0
    out = Path(args.out or "fix-out")
    out.mkdir(parents=True, exist_ok=True)
    md, csv_path = write_patches(out, patches)
    # 用真实路径重写 md 头
    md.write_text(render_patches(patches, Path(args.diff)), encoding="utf-8")
    low = sum(1 for p in patches if p.risk == "low")
    print(f"修复建议 {len(patches)} 条（可自动改 {low} 条）")
    print(f"report: {md}\npatch : {csv_path}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    rows = load_patch_csv(Path(args.patch))
    target = Path(args.target)
    if not target.exists():
        print(f"error: 目标文件不存在：{target}", file=sys.stderr)
        return 2
    if target.suffix.lower() not in {".csv", ".tsv"}:
        print(
            "error: 目前只对 CSV 生成修正副本。xlsx/docx/pptx 请按 fix-suggestions.md 人工处理——"
            "自动改格式文件容易破坏合并单元格和样式。",
            file=sys.stderr,
        )
        return 2
    result = apply_csv_patches(target, rows, key_column=args.key, out=Path(args.out or "fix-out"))
    print(f"已改 {result['applied']} 条 · 跳过 {result['skipped']} 条（值不匹配）· 失败 {result['failed']} 条")
    for line in result["details"][:20]:
        print(f"  {line}")
    print(f"副本：{result['output']}（原文件未改动）")
    return 0




MULTI_DISCLAIMER = (
    "**多数不等于正确。** 两个来源一致可能一起错；三个来源里两个一致也只是「更可能」。"
    "表决只告诉你「谁不一样」，不告诉你「谁对」。"
)


@dataclasses.dataclass
class Vote:
    key: str
    field: str
    values: dict[str, str]          # 文件名 -> 原始值
    normalized: dict[str, str]      # 文件名 -> 归一化值（不对外展示）
    consensus: str                  # unanimous | majority | split | missing
    majority_value: str
    outliers: list[str] = dataclasses.field(default_factory=list)
    missing: list[str] = dataclasses.field(default_factory=list)


def normalize_value(value: str) -> str:
    """Numbers compare by unit+value; everything else by normalised text."""
    parsed = parse_number(value)
    if parsed:
        number, dim = parsed
        return f"{dim}:{number:.6f}"
    return normalize(value)


def vote_field(key: str, field: str, values: dict[str, str]) -> Vote:
    present = {name: value for name, value in values.items() if str(value).strip()}
    missing = [name for name in values if name not in present]
    if len(present) < 2:
        return Vote(
            key=key, field=field, values=values, normalized={},
            consensus="missing", majority_value=next(iter(present.values()), ""),
            missing=missing,
        )
    normalized = {name: normalize_value(value) for name, value in present.items()}
    counts: dict[str, int] = {}
    for value in normalized.values():
        counts[value] = counts.get(value, 0) + 1
    top_value, top_count = max(counts.items(), key=lambda item: item[1])
    display = next(value for name, value in present.items() if normalized[name] == top_value)
    if top_count == len(present):
        consensus, outliers = "unanimous", []
    elif top_count >= 2:
        consensus = "majority"
        outliers = [name for name, norm in normalized.items() if norm != top_value]
    else:
        consensus, outliers = "split", list(present)
    return Vote(
        key=key, field=field, values=values, normalized=normalized,
        consensus=consensus, majority_value=display, outliers=outliers, missing=missing,
    )


def multi_compare(paths: list[Path], *, key: str | None = None, fields: Sequence[str] | None = None) -> tuple[list[Vote], dict[str, Any]]:
    if len(paths) < 3:
        raise SystemExit("多方对照至少需要 3 个文件（两个文件请用 run）")
    sources: dict[str, dict[str, dict[str, str]]] = {}
    key_columns: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            print(f"error: 文件不存在：{path}", file=sys.stderr)
            raise SystemExit(2)
        table = build_entities(load_table(path), key, fields)
        key_columns[path.stem] = table.key_column
        sources[path.stem] = {entity.display: entity.attrs for entity in table.entities}
    if any(not entities for entities in sources.values()):
        empty = [name for name, entities in sources.items() if not entities]
        print(f"error: 这些文件没有可对照的记录：{empty}", file=sys.stderr)
        raise SystemExit(2)

    common_keys = set.intersection(*(set(entities) for entities in sources.values()))
    field_sets = [set().union(*(set(attrs) for attrs in entities.values())) for entities in sources.values()]
    common_fields = list(set.intersection(*field_sets)) if field_sets else []
    if not common_keys:
        print("error: 这些文件没有共同的键（检查 --key 或主键列名）", file=sys.stderr)
        raise SystemExit(2)

    votes: list[Vote] = []
    unit_field = next(
        (
            name
            for name in common_fields
            if any(token in name.lower() for token in ("单位", "币种", "unit", "currency"))
        ),
        None,
    )
    for key_value in sorted(common_keys):
        for field in common_fields:
            if field == unit_field:
                continue  # 单位列决定口径，不参与表决本身
            values = {}
            for name, entities in sources.items():
                attrs = entities.get(key_value, {})
                raw = str(attrs.get(field, ""))
                # 报价单常用「数值 + 单位列」：12000/元 与 12/千元 是同一个价。
                # 只对金额类字段拼接——数量列的单位不是「元」。
                if unit_field and raw.strip() and looks_money(field):
                    unit = str(attrs.get(unit_field, "")).strip()
                    if unit:
                        raw = f"{raw} {unit}"
                values[name] = raw
            votes.append(vote_field(key_value, field, values))

    stats = {
        "files": [path.name for path in paths],
        "key_columns": key_columns,
        "keys": len(common_keys),
        "fields": common_fields,
        "unanimous": sum(1 for v in votes if v.consensus == "unanimous"),
        "majority": sum(1 for v in votes if v.consensus == "majority"),
        "split": sum(1 for v in votes if v.consensus == "split"),
        "missing": sum(1 for v in votes if v.consensus == "missing"),
    }
    return votes, stats


def render_multi(paths: list[Path], votes: list[Vote], stats: dict[str, Any]) -> str:
    lines = [
        "# 多方对照（共识表决）",
        "",
        f"- 来源：{'、'.join(f'`{path.name}`' for path in paths)}",
        f"- 主键列：" + "、".join(f"{name}={column}" for name, column in stats["key_columns"].items()),
        f"- 共同键 {stats['keys']} 个 · 比较字段 {len(stats['fields'])} 个 · 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"**完全一致 {stats['unanimous']} · 多数一致 {stats['majority']} · 无共识 {stats['split']} · 缺失 {stats['missing']}**",
        "",
    ]

    def section(title: str, status: str, note: str = "") -> None:
        items = [v for v in votes if v.consensus == status]
        if not items:
            return
        lines.extend([f"## {title}（{len(items)}）", ""])
        if note:
            lines.extend([note, ""])
        if status == "unanimous":
            lines.extend(f"- `{v.key}` · {v.field} = {v.majority_value}" for v in items[:15])
            if len(items) > 15:
                lines.append(f"- … 另外 {len(items) - 15} 项")
        elif status in {"majority", "split"}:
            sources = list(stats["key_columns"])
            header = "| 键 | 字段 | " + " | ".join(sources) + " | 判定 |"
            lines.append(header)
            lines.append("|" + "---|" * (len(sources) + 3))
            for vote in items:
                cells = " | ".join(vote.values.get(name, "") or "—" for name in sources)
                verdict = f"多数={vote.majority_value}" if status == "majority" else "各不相同"
                lines.append(f"| {vote.key} | {vote.field} | {cells} | {verdict} |")
        else:
            lines.append("| 键 | 字段 | 缺失来源 |")
            lines.append("|---|---|---|")
            for vote in items:
                lines.append(f"| {vote.key} | {vote.field} | {', '.join(vote.missing)} |")
        lines.append("")

    section("完全一致", "unanimous")
    section(
        "多数一致（有离群）", "majority",
        "两个来源一致、一个不同。**先看离群的那个是不是有理由**——它可能是唯一对的。",
    )
    section(
        "无共识（各说各话）", "split",
        "没有多数。这种字段最危险：它说明**这个参数的口径本身没统一**，不是谁抄错了。",
    )
    section("数据缺失", "missing")

    if stats["majority"] == 0 and stats["split"] == 0 and stats["missing"] == 0:
        lines.extend(["## 结论", "", "所有共同字段在各方之间完全一致。", ""])

    lines.extend(["---", "", f"> {MULTI_DISCLAIMER}", ""])
    return "\n".join(lines)


def write_multi_excel(out_dir: Path, votes: list[Vote], stats: dict[str, Any]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "表决结果"
    sources = list(stats["key_columns"])
    ws.append(["键", "字段", *sources, "判定", "多数值", "离群来源", "缺失来源"])
    fills = {
        "majority": PatternFill("solid", fgColor="FFF2CC"),
        "split": PatternFill("solid", fgColor="FFC7CE"),
        "missing": PatternFill("solid", fgColor="E7E6E6"),
    }
    for vote in votes:
        ws.append([
            vote.key,
            vote.field,
            *[vote.values.get(name, "") for name in sources],
            {"unanimous": "一致", "majority": "多数", "split": "无共识", "missing": "缺失"}.get(vote.consensus, vote.consensus),
            vote.majority_value,
            ", ".join(vote.outliers),
            ", ".join(vote.missing),
        ])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF7")
        cell.alignment = Alignment(wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        verdict = str(row[2 + len(sources)].value)
        fill = fills.get({"一致": "unanimous", "多数": "majority", "无共识": "split", "缺失": "missing"}.get(verdict, ""))
        if fill:
            for cell in row:
                cell.fill = fill
    for index in range(1, len(sources) + 6):
        ws.column_dimensions[chr(64 + index)].width = 22 if index > 2 else 16
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "reconcile-multi.xlsx"
    wb.save(str(target))
    return target


def run_multi(paths: list[Path], *, out: Path, key: str | None = None, fields: Sequence[str] | None = None) -> dict[str, Any]:
    votes, stats = multi_compare(paths, key=key, fields=fields)
    report = render_multi(paths, votes, stats)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "reconcile-multi.md"
    target.write_text(report, encoding="utf-8")
    (out / "reconcile-multi.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "stats": stats,
                "votes": [
                    {
                        "key": vote.key,
                        "field": vote.field,
                        "consensus": vote.consensus,
                        "majority_value": vote.majority_value,
                        "outliers": vote.outliers,
                        "missing": vote.missing,
                    }
                    for vote in votes
                ],
                "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    xlsx = write_multi_excel(out, votes, stats)
    print(f"一致 {stats['unanimous']} · 多数 {stats['majority']} · 无共识 {stats['split']} · 缺失 {stats['missing']}")
    print(f"report: {target}\nxlsx  : {xlsx}")
    return {"votes": votes, "stats": stats, "report": report}


# ---------------------------------------------------------------------------
# Media mode — images and audio, as files. Never as identity.
# ---------------------------------------------------------------------------

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_SUFFIXES = {".wav"}

MEDIA_DISCLAIMER = (
    "**这不是身份识别。** 图像只比像素与感知哈希，音频只比波形特征；"
    "两者都不能判断「是不是同一个人」，也不构成活体检测或门禁依据。"
)


def dhash(image: "Any") -> str:
    from PIL import Image

    gray = image.convert("L").resize((9, 8), Image.LANCZOS)
    pixels = list(gray.getdata())
    bits = []
    for row in range(8):
        for col in range(8):
            bits.append("1" if pixels[row * 9 + col] > pixels[row * 9 + col + 1] else "0")
    return "".join(bits)


def hamming(left: str, right: str) -> int:
    return sum(1 for a, b in zip(left, right) if a != b)


def compare_images(left: Path, right: Path) -> dict[str, Any]:
    from PIL import Image, ImageChops

    with Image.open(left) as img_a, Image.open(right) as img_b:
        result: dict[str, Any] = {
            "kind": "image",
            "format_a": img_a.format or left.suffix.upper().lstrip("."),
            "format_b": img_b.format or right.suffix.upper().lstrip("."),
            "size_a": img_a.size,
            "size_b": img_b.size,
            "mode_a": img_a.mode,
            "mode_b": img_b.mode,
        }
        distance = hamming(dhash(img_a), dhash(img_b))
        result["hash_distance"] = distance
        if img_a.size != img_b.size:
            result["same_size"] = False
            return result
        result["same_size"] = True
        rgb_a, rgb_b = img_a.convert("RGB"), img_b.convert("RGB")
        diff = ImageChops.difference(rgb_a, rgb_b)
        result["bbox"] = diff.getbbox()
        gray = diff.convert("L")
        hist = gray.histogram()
        total = rgb_a.size[0] * rgb_a.size[1]
        changed = sum(hist[1:])
        result["changed_ratio"] = changed / total if total else 0.0
        result["max_channel_delta"] = int(gray.getextrema()[1])
        return result


def wav_stats(path: Path) -> dict[str, Any]:
    import array
    import math
    import wave

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.getnframes()
        raw = handle.readframes(frames)
    duration = frames / rate if rate else 0.0
    stats: dict[str, Any] = {
        "channels": channels,
        "sample_width": width,
        "rate": rate,
        "frames": frames,
        "duration": duration,
        "rms_db": None,
        "peak": None,
        "silence_ratio": None,
    }
    if width != 2:  # 只分析 16-bit PCM，其他只报头部
        return stats
    samples = array.array("h")
    usable = len(raw) - (len(raw) % 2)
    samples.frombytes(raw[:usable])
    if not samples:
        return stats
    peak = max(abs(value) for value in samples) / 32768
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768
    stats["peak"] = peak
    stats["rms_db"] = 20 * math.log10(rms) if rms > 0 else None
    stats["silence_ratio"] = sum(1 for value in samples if abs(value) < 500) / len(samples)
    return stats


def compare_audio(left: Path, right: Path) -> dict[str, Any]:
    a, b = wav_stats(left), wav_stats(right)
    result: dict[str, Any] = {"kind": "audio", "a": a, "b": b}
    result["duration_delta"] = abs(a["duration"] - b["duration"])
    result["duration_delta_ratio"] = (
        result["duration_delta"] / a["duration"] if a["duration"] else 0.0
    )
    if a["rms_db"] is not None and b["rms_db"] is not None:
        result["rms_delta_db"] = abs(a["rms_db"] - b["rms_db"])
    if a["silence_ratio"] is not None and b["silence_ratio"] is not None:
        result["silence_delta"] = abs(a["silence_ratio"] - b["silence_ratio"])
    return result


def render_media(left: Path, right: Path, data: dict[str, Any]) -> str:
    lines = [f"# 媒体对照 · {data['kind']}", "", f"- 左：`{left}`", f"- 右：`{right}`", ""]

    if data["kind"] == "image":
        lines.extend(
            [
                "| 项目 | 左 | 右 |",
                "|---|---|---|",
                f"| 格式 | {data['format_a']} | {data['format_b']} |",
                f"| 尺寸 | {data['size_a'][0]}×{data['size_a'][1]} | {data['size_b'][0]}×{data['size_b'][1]} |",
                f"| 色彩模式 | {data['mode_a']} | {data['mode_b']} |",
                "",
            ]
        )
        if not data.get("same_size"):
            lines.extend(["## 结论", "", "尺寸不同，无法逐像素比较；只能说明两张图不一样。", ""])
        else:
            distance = data["hash_distance"]
            ratio = data.get("changed_ratio", 0.0)
            verdict = "视觉上高度相似" if distance <= 4 and ratio < 0.02 else (
                "有明显差异" if distance > 12 or ratio > 0.2 else "局部有差异"
            )
            lines.extend(
                [
                    f"- 感知哈希距离：**{distance}/64**（越小越像）",
                    f"- 差异像素比例：**{ratio:.2%}**",
                    f"- 最大单通道差值：{data.get('max_channel_delta', 0)}/255",
                    f"- 差异区域：{data.get('bbox') or '无'}",
                    "",
                    f"## 结论：{verdict}",
                    "",
                    "感知哈希接近只说明「看起来像」，不说明内容一致；截图、压缩、缩放都会让它变。",
                    "",
                ]
            )
    else:
        a, b = data["a"], data["b"]

        def fmt_num(value: float | None, spec: str = ".1f") -> str:
            return "—" if value is None else format(value, spec)

        lines.extend(
            [
                "| 项目 | 左 | 右 |",
                "|---|---|---|",
                f"| 采样率 | {a['rate']} Hz | {b['rate']} Hz |",
                f"| 声道 | {a['channels']} | {b['channels']} |",
                f"| 位深 | {a['sample_width'] * 8} bit | {b['sample_width'] * 8} bit |",
                f"| 时长 | {a['duration']:.3f} s | {b['duration']:.3f} s |",
                f"| RMS | {fmt_num(a['rms_db'])} dB | {fmt_num(b['rms_db'])} dB |",
                f"| 峰值 | {fmt_num(a['peak'], '.2f')} | {fmt_num(b['peak'], '.2f')} |",
                f"| 静音比例 | {fmt_num(a['silence_ratio'], '.1%')} | {fmt_num(b['silence_ratio'], '.1%')} |",
                "",
            ]
        )
        same = data.get("duration_delta_ratio", 1.0) < 0.01 and data.get("rms_delta_db", 99.0) < 1.0
        lines.extend(
            [
                f"- 时长差：{data['duration_delta']:.3f} s（{data.get('duration_delta_ratio', 0):.2%}）",
                f"- RMS 差：{fmt_num(data.get('rms_delta_db'), '.2f')} dB",
                "",
                f"## 结论：{'文件特征接近' if same else '文件特征不同'}",
                "",
                "只能说明波形特征接近或不同；**不能说明是不是同一个人、同一段录音的原始版本**。",
                "",
            ]
        )

    lines.extend(["---", "", f"> {MEDIA_DISCLAIMER}", ""])
    return "\n".join(lines)


def run_media(left: Path, right: Path, *, out: Path, kind: str, quiet: bool = False) -> dict[str, Any]:
    data = compare_images(left, right) if kind == "image" else compare_audio(left, right)
    report = render_media(left, right, data)
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-]+", "_", f"{left.stem}_vs_{right.stem}")[:60]
    (out / f"{stem}.md").write_text(report, encoding="utf-8")
    changed = True
    if kind == "image" and data.get("same_size"):
        changed = data.get("hash_distance", 0) > 4 or data.get("changed_ratio", 0) > 0.02
    elif kind == "audio":
        changed = data.get("duration_delta_ratio", 1) >= 0.01 or data.get("rms_delta_db", 99) >= 1.0
    if not quiet:
        print(report[:900])
        print(f"report: {out / f'{stem}.md'}")
    return {"mode": kind, "matched": 1, "diffs": 1 if changed else 0, "report": report, "diff_items": []}




DEFAULT_EXCLUDE = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode", "reports"}
TEXT_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv", ".docx", ".pptx", ".md", ".txt"}


@dataclasses.dataclass
class FileEntry:
    rel: str
    status: str  # same | modified | only_left | only_right | type_changed
    left_size: int = 0
    right_size: int = 0
    left_hash: str = ""
    right_hash: str = ""
    diffs: int | None = None
    note: str = ""


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def walk_files(root: Path, exclude: set[str]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in exclude for part in rel.parts):
            continue
        files[rel.as_posix()] = path
    return files


def compare_dirs(left: Path, right: Path, *, exclude: set[str], content: bool, max_content: int) -> list[FileEntry]:
    left_files = walk_files(left, exclude)
    right_files = walk_files(right, exclude)
    entries: list[FileEntry] = []
    budget = max_content

    for rel in sorted(set(left_files) | set(right_files)):
        lpath, rpath = left_files.get(rel), right_files.get(rel)
        if lpath and rpath:
            lh, rh = file_hash(lpath), file_hash(rpath)
            if lh == rh:
                entries.append(FileEntry(rel, "same", lpath.stat().st_size, rpath.stat().st_size, lh, rh))
                continue
            entry = FileEntry(
                rel, "modified", lpath.stat().st_size, rpath.stat().st_size, lh, rh,
                note="" if lpath.suffix.lower() in TEXT_SUFFIXES else "二进制文件，仅比对哈希",
            )
            if content and budget > 0 and lpath.suffix.lower() in TEXT_SUFFIXES and rpath.suffix.lower() == lpath.suffix.lower():
                budget -= 1
                try:
                    scratch = Path(tempfile.mkdtemp(prefix="reconcile-dir-"))
                    result = run_pair(lpath, rpath, out=scratch, quiet=True)
                    entry.diffs = int(result.get("diffs") or 0)
                    shutil.rmtree(scratch, ignore_errors=True)
                except SystemExit:
                    entry.note = "内容对照失败（结构不支持或为空表）"
                except Exception as exc:  # noqa: BLE001 - never let one file kill the batch
                    entry.note = f"内容对照失败：{type(exc).__name__}"
            entries.append(entry)
        elif lpath:
            entries.append(FileEntry(rel, "only_left", lpath.stat().st_size, 0, file_hash(lpath), ""))
        else:
            assert rpath is not None
            entries.append(FileEntry(rel, "only_right", 0, rpath.stat().st_size, "", file_hash(rpath)))
    # 改名识别：只在左侧出现的文件，若在右侧找到哈希相同的文件，那是改名，
    # 不是「删了一个、加了一个」。交付包加版本后缀是常态。
    by_hash: dict[str, list[FileEntry]] = {}
    for entry in entries:
        if entry.status == "only_left" and entry.left_hash:
            by_hash.setdefault(entry.left_hash, []).append(entry)
    for entry in entries:
        if entry.status != "only_right" or not entry.right_hash:
            continue
        candidates = by_hash.get(entry.right_hash)
        if not candidates:
            continue
        partner = candidates.pop(0)
        partner.status = "renamed"
        partner.note = f"改名为 {entry.rel}"
        entry.status = "renamed"
        entry.note = f"原名 {partner.rel}"
    entries.sort(key=lambda item: item.rel)
    return entries


def render_dir_report(left: Path, right: Path, entries: list[FileEntry], exclude: set[str], content: bool) -> str:
    counts = {
        status: sum(1 for e in entries if e.status == status)
        for status in ("same", "modified", "renamed", "only_left", "only_right")
    }
    lines = [
        "# 目录对照",
        "",
        f"- 左：`{left}`",
        f"- 右：`{right}`",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M}",
        f"- 文件：相同 {counts['same']} · 修改 {counts['modified']} · 改名 {counts['renamed']} "
        f"· 仅左 {counts['only_left']} · 仅右 {counts['only_right']}",
        f"- 排除：{', '.join(sorted(exclude))}",
        f"- 内容级对照：{'开' if content else '关（只比哈希）'}",
        "",
        "> 「相同」= SHA-256 一致，不是肉眼像。「改名」= 内容哈希一致但路径变了，不算删增。",
        "",
    ]

    def section(title: str, status: str) -> None:
        items = [e for e in entries if e.status == status]
        if not items:
            return
        lines.extend([f"## {title}（{len(items)}）", ""])
        if status == "same":
            lines.extend(f"- `{entry.rel}`" for entry in items[:20])
            if len(items) > 20:
                lines.append(f"- … 另外 {len(items) - 20} 个")
        else:
            lines.append("| 文件 | 左大小 | 右大小 | 差异 | 备注 |")
            lines.append("|---|---|---|---|---|")
            for entry in items:
                size_delta = entry.right_size - entry.left_size
                delta = f"{size_delta:+,}" if size_delta else "—"
                diffs = "—" if entry.diffs is None else f"{entry.diffs} 处"
                lines.append(f"| `{entry.rel}` | {entry.left_size:,} | {entry.right_size:,} ({delta}) | {diffs} | {entry.note} |")
        lines.append("")

    section("改名（内容未变）", "renamed")
    section("仅左侧存在", "only_left")
    section("仅右侧存在", "only_right")
    section("内容已修改", "modified")
    section("完全相同", "same")

    if not any(e.status != "same" for e in entries):
        lines.extend(["## 结论", "", "两边文件集与内容完全一致（按 SHA-256）。", ""])

    lines.extend(
        [
            "---",
            "",
            "> 只比对存在性与内容哈希；不判断哪边「对」。",
            "> 内容级对照默认关闭——开 `--content` 会对可读格式逐个出差异条数，大目录会慢。",
            "",
        ]
    )
    return "\n".join(lines)


def write_dir_excel(out_dir: Path, entries: list[FileEntry]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "目录差异"
    ws.append(["文件", "状态", "左大小", "右大小", "大小变化", "差异条数", "备注"])
    palette = {
        "modified": PatternFill("solid", fgColor="FFF2CC"),
        "renamed": PatternFill("solid", fgColor="E2EFDA"),
        "only_left": PatternFill("solid", fgColor="FCE4D6"),
        "only_right": PatternFill("solid", fgColor="DDEBF7"),
    }
    for entry in entries:
        ws.append([
            entry.rel,
            {"same": "相同", "modified": "修改", "renamed": "改名", "only_left": "仅左", "only_right": "仅右"}.get(entry.status, entry.status),
            entry.left_size,
            entry.right_size,
            entry.right_size - entry.left_size,
            entry.diffs,
            entry.note,
        ])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF7")
        cell.alignment = Alignment(wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        status_cn = row[1].value
        fill = {
            "修改": palette["modified"],
            "改名": palette["renamed"],
            "仅左": palette["only_left"],
            "仅右": palette["only_right"],
        }.get(status_cn)
        if fill:
            for cell in row:
                cell.fill = fill
    autofit_widths = [52, 8, 12, 12, 12, 10, 34]
    for index, width in enumerate(autofit_widths, start=1):
        ws.column_dimensions[chr(64 + index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "reconcile-dir.xlsx"
    wb.save(str(target))
    return target


def run_dir(left: Path, right: Path, *, out: Path, exclude: set[str], content: bool, max_content: int) -> dict[str, Any]:
    for path in (left, right):
        if not path.is_dir():
            print(f"error: 不是目录：{path}", file=sys.stderr)
            raise SystemExit(2)
    entries = compare_dirs(left, right, exclude=exclude, content=content, max_content=max_content)
    if not entries:
        print(f"error: 两个目录都没有可比对的文件（排除规则：{', '.join(sorted(exclude))}）", file=sys.stderr)
        raise SystemExit(2)
    report = render_dir_report(left, right, entries, exclude, content)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "reconcile-dir.md"
    target.write_text(report, encoding="utf-8")
    xlsx = write_dir_excel(out, entries)
    counts = {
        status: sum(1 for entry in entries if entry.status == status)
        for status in ("same", "modified", "renamed", "only_left", "only_right")
    }
    (out / "reconcile-dir.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "left": str(left),
                "right": str(right),
                "counts": counts,
                "files": [dataclasses.asdict(entry) for entry in entries],
                "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # 一对改名会产出两个条目（左+右），计数时按「对」算，否则看起来像改了两次名
    renamed_pairs = counts["renamed"] // 2
    changed = counts["modified"] + counts["only_left"] + counts["only_right"] + renamed_pairs
    print(
        f"文件 {len(entries)} · 变化 {changed} · 相同 {counts['same']} "
        f"· 改名 {renamed_pairs} 对"
    )
    print(f"report: {target}\nxlsx  : {xlsx}")
    return {"entries": entries, "report": report, "counts": counts}





def build_demo(target: Path) -> None:
    from openpyxl import Workbook

    target.mkdir(parents=True, exist_ok=True)

    # 股票：两个交易日，价格变化 + 一增一减
    today = [
        ["代码", "名称", "收盘价", "涨跌幅", "成交量"],
        ["600519", "贵州茅台", 1680.0, "1.2%", "32,000"],
        ["000001", "平安银行", 11.85, "-0.8%", "1,240,000"],
        ["300750", "宁德时代", 245.6, "2.1%", "560,000"],
        ["601318", "中国平安", 48.2, "0.3%", "890,000"],
        ["688981", "中芯国际", 92.4, "1.8%", "410,000"],
    ]
    yesterday = [
        ["代码", "名称", "收盘价", "涨跌幅", "成交量"],
        ["600519", "贵州茅台", 1660.0, "0.9%", "28,000"],
        ["000001", "平安银行", 11.95, "-1.2%", "1,180,000"],
        ["300750", "宁德时代", 240.5, "1.4%", "520,000"],
        ["601318", "中国平安", 48.05, "0.1%", "870,000"],
        ["002594", "比亚迪", 268.3, "0.5%", "330,000"],
    ]
    for name, rows in (("今日股价.xlsx", today), ("昨日股价.xlsx", yesterday)):
        wb = Workbook()
        ws = wb.active
        ws.title = "行情"
        for row in rows:
            ws.append(row)
        wb.save(target / name)

    # 物料清单：单价变化 + 缺一项 + 多一项
    a = [
        ["物料号", "名称", "数量", "单价", "金额"],
        ["M-1001", "1000A 直流电源", 1, 12000, 12000],
        ["M-1002", "模拟导线", 2, 500, 1000],
        ["M-1003", "磁芯环", 4, 850, 3400],
        ["M-1004", "绝缘支架", 6, 120, 720],
    ]
    b = [
        ["物料号", "名称", "数量", "单价", "金额"],
        ["M-1001", "1000A 直流电源", 1, 11800, 11800],
        ["M-1002", "模拟导线", 2, 520, 1040],
        ["M-1003", "磁芯环", 4, 850, 3400],
        ["M-1005", "接线端子", 10, 35, 350],
    ]
    for name, rows in (("物料A.xlsx", a), ("物料B.xlsx", b)):
        wb = Workbook()
        ws = wb.active
        ws.title = "清单"
        for row in rows:
            ws.append(row)
        wb.save(target / name)

    # 合同：段落改写 + 金额变化 + 新增条款
    from docx import Document

    doc_a = Document()
    doc_a.add_paragraph("第一条 甲方委托乙方完成设备安装调试工作。")
    doc_a.add_paragraph("第二条 合同总金额为人民币 120,000 元，含税。")
    doc_a.add_paragraph("第三条 乙方应于 2026 年 12 月 31 日前完成交付。")
    doc_a.add_paragraph("第四条 质保期为验收合格后 12 个月。")
    doc_a.save(target / "合同A.docx")

    doc_b = Document()
    doc_b.add_paragraph("第一条 甲方委托乙方完成设备安装、调试及培训工作。")
    doc_b.add_paragraph("第二条 合同总金额为人民币 135,000 元，含税。")
    doc_b.add_paragraph("第三条 乙方应于 2027 年 1 月 31 日前完成交付。")
    doc_b.add_paragraph("第四条 质保期为验收合格后 24 个月。")
    doc_b.add_paragraph("第五条 乙方逾期交付的，每日按合同总额的 0.5% 支付违约金。")
    doc_b.save(target / "合同B.docx")


def cmd_multi(args: argparse.Namespace) -> int:
    run_multi(
        [Path(item) for item in args.files],
        out=Path(args.out),
        key=args.key,
        fields=[name for name in (args.fields or "").split(",") if name],
    )
    return 0


def cmd_dir(args: argparse.Namespace) -> int:
    exclude = set(DEFAULT_EXCLUDE)
    if args.exclude:
        exclude |= {item.strip() for item in args.exclude.split(",") if item.strip()}
    run_dir(
        Path(args.left),
        Path(args.right),
        out=Path(args.out),
        exclude=exclude,
        content=args.content,
        max_content=args.max_content,
    )
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    root = Path(args.out or "reconcile-demo")
    build_demo(root)
    print(f"demo files: {root}")
    runs = [
        ("股票（今日 vs 昨日）", root / "今日股价.xlsx", root / "昨日股价.xlsx"),
        ("物料清单（A vs B）", root / "物料A.xlsx", root / "物料B.xlsx"),
        ("合同（A vs B）", root / "合同A.docx", root / "合同B.docx"),
    ]
    for title, left, right in runs:
        print()
        print("=" * 70)
        print(title)
        print("=" * 70)
        _ = run_pair(left, right, out=root / "out", quiet=False)
    print(f"\nreports: {root / 'out'}")
    return 0


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_pair(left_path: Path, right_path: Path, *, out: Path, key: str | None = None,
             fields: list[str] | None = None, tolerance: float = 0.01, quiet: bool = False) -> dict[str, Any]:
    for path in (left_path, right_path):
        if not path.exists():
            print(f"error: 文件不存在：{path}", file=sys.stderr)
            raise SystemExit(2)
    left_is_table = left_path.suffix.lower() in {".xlsx", ".xlsm", ".csv", ".tsv"}
    right_is_table = right_path.suffix.lower() in {".xlsx", ".xlsm", ".csv", ".tsv"}

    if left_path.suffix.lower() in IMAGE_SUFFIXES and right_path.suffix.lower() in IMAGE_SUFFIXES:
        return run_media(left_path, right_path, out=out, kind="image", quiet=quiet)
    if left_path.suffix.lower() in AUDIO_SUFFIXES and right_path.suffix.lower() in AUDIO_SUFFIXES:
        return run_media(left_path, right_path, out=out, kind="audio", quiet=quiet)

    if left_is_table and right_is_table:
        mode = "record"
        left_table = build_entities(load_table(left_path), key, fields)
        right_table = build_entities(load_table(right_path), key, fields)
        left_entities, right_entities = left_table.entities, right_table.entities
        left_meta = {"key": left_table.key_column, "notes": left_table.notes}
        right_meta = {"key": right_table.key_column, "notes": right_table.notes}
    else:
        mode = "text"
        left_entities = load_document(left_path)
        right_entities = load_document(right_path)
        left_meta = {"key": "", "notes": [f"抽取 {len(left_entities)} 段"]}
        right_meta = {"key": "", "notes": [f"抽取 {len(right_entities)} 段"]}

    matched, only_left, only_right, fuzzy_pairs = align_entities(left_entities, right_entities)
    if not left_entities or not right_entities:
        # 空表对照如果输出「无差异」，是最危险的假阴性：看起来通过，其实什么都没比。
        print(
            f"error: 没有可对照的记录（左 {len(left_entities)} 条 / 右 {len(right_entities)} 条）。"
            "检查文件是否有表头和数据行，或先用 --key 指定主键列。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    diffs = compare_entities(matched, only_left, only_right, tolerance=tolerance)
    report = render_report(
        left_path, right_path, mode, left_meta, right_meta, diffs,
        matched_count=len(matched), fuzzy_pairs=fuzzy_pairs,
    )

    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-]+", "_", f"{left_path.stem}_vs_{right_path.stem}")[:60]
    (out / f"{stem}.md").write_text(report, encoding="utf-8")
    xlsx = write_excel(out, diffs, len(matched))
    # JSON 让下一期可以和这一期做「趋势对照」：哪些差异解决了、哪些还在
    payload = {
        "version": VERSION,
        "mode": mode,
        "left": str(left_path),
        "right": str(right_path),
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "matched": len(matched),
        "diffs": [dataclasses.asdict(diff) for diff in diffs],
        "key_column": left_meta.get("key", ""),
    }
    (out / f"{stem}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not quiet:
        print(report[:1200])
        print(f"... 完整报告：{out / f'{stem}.md'}")
        print(f"差异清单：{xlsx}")
    return {"mode": mode, "matched": len(matched), "diffs": len(diffs), "report": report, "diff_items": diffs}


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(
        prog="reconcile.py", description="任意两个文件的对照：抽取 → 对齐 → 比较 → 报告"
    )
    parser.add_argument("--version", action="version", version=f"reconcile {VERSION}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="对照两个文件")
    run.add_argument("left")
    run.add_argument("right")
    run.add_argument("--key", default=None, help="表格主键列（默认自动选）")
    run.add_argument("--fields", default=None, help="只比较这些列，逗号分隔")
    run.add_argument("--tolerance", type=float, default=0.01, help="数值容差（相对），默认 1%%")
    run.add_argument("-o", "--out", default="reconcile-out")
    run.set_defaults(func=lambda a: (run_pair(Path(a.left), Path(a.right), out=Path(a.out), key=a.key,
                                              fields=[f for f in (a.fields or "").split(",") if f],
                                              tolerance=a.tolerance) and 0) or 0)

    demo = sub.add_parser("demo", help="生成三组对照样例并跑一遍")
    demo.add_argument("-o", "--out", default="")
    demo.set_defaults(func=cmd_demo)

    dirs = sub.add_parser("dir", help="对照两个目录（文件集 + 内容）")
    dirs.add_argument("left")
    dirs.add_argument("right")
    dirs.add_argument("-o", "--out", default="reconcile-dir-out")
    dirs.add_argument("--content", action="store_true", help="对可读格式逐个做内容级对照（慢）")
    dirs.add_argument("--max-content", type=int, default=20, help="内容级对照最多处理多少个文件")
    dirs.add_argument("--exclude", default="", help="额外排除的目录名，逗号分隔")
    dirs.set_defaults(func=cmd_dir)

    multi = sub.add_parser("multi", help="三方以上共识表决，找出离群来源")
    multi.add_argument("files", nargs="+", help="至少三个文件")
    multi.add_argument("--key", default=None, help="主键列（默认自动选）")
    multi.add_argument("--fields", default=None, help="只比较这些列，逗号分隔")
    multi.add_argument("-o", "--out", default="reconcile-multi-out")
    multi.set_defaults(func=cmd_multi)

    patch = sub.add_parser("patch", help="从差异 JSON 生成修复建议（不改文件）")
    patch.add_argument("--diff", required=True, help="reconcile 生成的 *.json")
    patch.add_argument("--target", default="", help="要修的文件（默认取报告里的右侧文件）")
    patch.add_argument("-o", "--out", default="fix-out")
    patch.set_defaults(func=cmd_patch)

    apply_parser = sub.add_parser("apply", help="按补丁生成 CSV 修正副本（校验原值）")
    apply_parser.add_argument("--patch", required=True, help="fix-patch.csv")
    apply_parser.add_argument("--target", required=True, help="要修的 CSV")
    apply_parser.add_argument("--key", required=True, help="目标文件的主键列名")
    apply_parser.add_argument("-o", "--out", default="fix-out")
    apply_parser.set_defaults(func=cmd_apply)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())

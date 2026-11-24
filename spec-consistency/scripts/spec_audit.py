#!/usr/bin/env python3
"""spec_audit — cross-document consistency audit for product material.

The problem it solves: a product's numbers live in a spec sheet, a deck, a
quote, a manual, a website. Nobody re-reads all of them before a release, so
512 Wh in the spec becomes 500 Wh in the quote and 45 min in the deck becomes
50 min. Each document is internally fine; the *set* is wrong.

    python scripts/spec_audit.py scan ./product-material -o reports/
    python scripts/spec_audit.py demo

Design rule: the script extracts and compares; the model judges. Every finding
carries the surrounding context so a human (or an agent) can decide whether it
is a real contradiction or a different parameter that happens to share a name.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

VERSION = "1.0.0"

SUPPORTED_SUFFIXES = {".docx", ".pptx", ".xlsx", ".md", ".txt", ".csv"}

# ---------------------------------------------------------------------------
# Units: only dimensions where a conversion is unambiguous.
# ---------------------------------------------------------------------------

UNIT_TABLE: dict[str, dict[str, float]] = {
    "mass": {"g": 1, "kg": 1000, "t": 1_000_000, "克": 1, "千克": 1000, "公斤": 1000, "斤": 500},
    "length": {
        "mm": 1, "cm": 10, "m": 1000, "km": 1_000_000,
        "in": 25.4, "英寸": 25.4, "寸": 33.33, "毫米": 1, "厘米": 10, "米": 1000,
    },
    "time": {
        "s": 1, "sec": 1, "min": 60, "h": 3600, "hr": 3600,
        "秒": 1, "分钟": 60, "分": 60, "小时": 3600, "小时时": 3600, "天": 86400,
    },
    "power": {"w": 1, "kw": 1000, "mw": 1_000_000, "瓦": 1, "千瓦": 1000},
    "energy": {"wh": 1, "kwh": 1000, "mah": 0.001, "ah": 1},
    "capacity": {"mah": 1, "ah": 1000, "gb": 1024, "mb": 1, "tb": 1024 * 1024},
    "percent": {"%": 1, "％": 1},
    "speed": {"km/h": 1, "kmh": 1, "m/s": 3.6, "mph": 1.609},
    "voltage": {"v": 1, "kv": 1000, "伏": 1},
    "current": {"a": 1, "ma": 0.001, "安": 1},
    "money": {"元": 1, "人民币": 1, "美元": 7.0, "usd": 7.0, "rmb": 1, "cny": 1, "万元": 10000},
}

UNIT_TO_DIM: dict[str, str] = {}
for dim, table in UNIT_TABLE.items():
    for unit in table:
        UNIT_TO_DIM.setdefault(unit.lower(), dim)

DIM_LABELS = {
    "mass": "质量", "length": "长度", "time": "时间", "power": "功率",
    "energy": "能量", "capacity": "容量", "percent": "百分比",
    "speed": "速度", "voltage": "电压", "money": "金额",
}

UNIT_PATTERN = "|".join(sorted((re.escape(u) for u in UNIT_TO_DIM), key=len, reverse=True))
NUM = r"[+-]?\d+(?:\.\d+)?"
PREFIX = r"(?P<prefix>[ØøΦφ⌀≈≥≤~])?"
PARAM_RE = re.compile(
    rf"(?P<name>[^\s：:,，。；;()（）\[\]{{}}|]{{2,24}}?)\s*[：:]\s*{PREFIX}\s*(?P<value>{NUM})\s*(?P<unit>{UNIT_PATTERN})?(?![a-zA-Z])",
    re.IGNORECASE,
)
SPACE_PARAM_RE = re.compile(
    rf"(?<![\w.])(?P<name>[^\s：:,，。；;()（）\[\]|]{{2,12}})\s+{PREFIX}\s*(?P<value>{NUM})\s*(?P<unit>{UNIT_PATTERN})?(?![a-zA-Z])",
    re.IGNORECASE,
)
UNIT_AFTER_RE = re.compile(rf"^(?P<unit>{UNIT_PATTERN})(?![a-zA-Z])", re.IGNORECASE)

# Same parameter spelled differently across teams. Normalise before comparing.
SYNONYMS = {
    "质量": "重量", "净重": "重量", "毛重": "重量", "整机重量": "重量", "机身重量": "重量",
    "产品尺寸": "尺寸", "外形尺寸": "尺寸", "机身尺寸": "尺寸", "长宽高": "尺寸",
    "电池容量": "容量", "额定容量": "容量", "电芯容量": "容量",
    "续航": "续航时间", "满载续航": "续航时间", "使用时间": "续航时间",
    "额定功率": "输出功率", "输出功率w": "输出功率",
    "售价": "价格", "单价": "价格", "价格元": "价格",
    "型号名": "型号", "产品型号": "型号",
    "充电时间": "充电时长",
}

NOISE_NAMES = {
    "第", "页", "图", "表", "注", "备注", "版本", "日期", "时间", "序号", "编号",
    "电话", "邮箱", "地址", "网址", "页码", "总数", "合计", "小计",
}

# Words that appear right before a number in prose and are never a parameter.
STOP_WORDS = {
    "否则", "一个", "但是", "所以", "如果", "需要", "可以", "必须", "建议", "因为",
    "因此", "目前", "现在", "同时", "另外", "并且", "而且", "或者", "以及", "包括",
    "例如", "比如", "其中", "通过", "由于", "对于", "关于", "按照", "根据", "已经",
    "还是", "只是", "不是", "没有", "可能", "应该", "一定", "尽量", "最好", "大约",
    "左右", "以上", "以下", "之间", "之后", "之前", "一次", "一天", "一年", "上的",
    "下的", "中的", "里的", "只掉", "掉到", "升到", "降到", "从", "到", "约", "共",
    "第", "占", "约合", "合计", "最多", "最少", "至少", "不超过", "大于", "小于",
    "结论", "判断", "建议", "要点", "风险", "注意", "说明", "原因", "结果", "方案",
    "做法", "现状", "问题", "目标", "原则", "依据", "背景", "影响", "前提", "条件",
}

BAD_NAME_CHARS = set('*"\'|#`<>()（）[]【】《》「」、:：,，。；;!！?？/\\@$%^&=+~')


def normalize_param(name: str) -> str:
    text = name.strip().lower()
    text = re.sub(r"[（(][^）)]*[）)]", "", text)  # 质量（估） -> 质量
    text = re.sub(r"[\s_\-·]+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    text = SYNONYMS.get(text, text)
    return text


def clean_line(line: str) -> str:
    """Strip markdown noise so `**整机重量：6.2 kg**` and table cells parse."""
    text = line.replace("**", "").replace("__", "").replace("`", "")
    text = text.replace("|", "  ")
    text = re.sub(r"^\s*[#>\-+•]+\s*", "", text)
    return text


def is_noise(name: str) -> bool:
    clean = normalize_param(name)
    if not clean or clean in NOISE_NAMES or clean in STOP_WORDS:
        return True
    if len(clean) < 2 or len(clean) > 10:
        return True
    if any(ch in clean for ch in BAD_NAME_CHARS):
        return True
    if any(part in clean for part in ("的", "了", "是", "着", "过", "吗", "呢", "吧")):
        return True
    if re.fullmatch(r"[\d.\-+]+", clean):  # a bare number, not a name
        return True
    if re.match(r"^(?:[Øø]|R\d|M\d|D\d)", clean):  # dimension / fastener / model tags
        return True
    return False


def unit_dim(unit: str) -> str | None:
    return UNIT_TO_DIM.get(unit.strip().lower())


def to_base(value: float, unit: str) -> tuple[str, float] | None:
    """Convert to the dimension's base unit. Returns (dimension, value)."""
    dim = unit_dim(unit)
    if dim is None:
        return None
    table = UNIT_TABLE[dim]
    factor = table.get(unit.strip().lower())
    if factor is None:
        return None
    return dim, value * factor


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Pair:
    """One (name, value, unit) observation with enough context to judge it."""

    name: str
    display_name: str
    value: float
    unit: str
    context: str
    location: str
    variant: str = ""  # e.g. "CR-2" for a version column in a transposed table
    from_table: bool = False  # tables are specs; prose is discussion


CELL_VALUE_RE = re.compile(
    rf"(?P<prefix>[ØøΦφ⌀≈≥≤~])?\s*(?P<value>{NUM})\s*(?P<unit>{UNIT_PATTERN})?(?![a-zA-Z])",
    re.IGNORECASE,
)


def parse_value(text: str) -> tuple[float, str] | None:
    """Parse a single table cell: `Ø112（CR-3）`, `**0.10**`, `≈1.25 kg`."""
    match = CELL_VALUE_RE.search(clean_line(text))
    if not match:
        return None
    value = float(match.group("value"))
    unit = (match.group("unit") or "").strip()
    if not unit and (match.group("prefix") or "") in "ØøΦφ⌀":
        unit = "mm"
    if not unit or unit_dim(unit) is None:
        return None
    return value, unit


def normalize_spec_name(text: str) -> str:
    """Like normalize_param, but strips approximation words.

    Handwriting like 「内孔约 Ø32」 puts 约 inside the name capture; the parameter
    is still 内孔, so the suffix must not become part of the key.
    """
    name = normalize_param(text)
    for suffix in ("大约", "约为", "约", "近"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


TABLE_LOCATION_RE = re.compile(r"#(?:tbl|t\d+-r\d+|slide\d+-r\d+)")


def _from_table(location: str) -> bool:
    return bool(TABLE_LOCATION_RE.search(location))


def _pick(pairs: list[Pair]) -> Pair:
    """Prefer the value written in a table; prose discusses, tables specify."""
    from_tables = [pair for pair in pairs if pair.from_table]
    return (from_tables or pairs)[0]


def parse_pairs(line: str, location: str) -> list[Pair]:
    if "\t" in line:  # versioned table cell: name<TAB>version<TAB>value
        name, variant, cell = line.split("\t", 2)
        if is_noise(name):
            return []
        parsed = parse_value(cell)
        if not parsed:
            return []
        value, unit = parsed
        return [
            Pair(
                name=normalize_spec_name(name),
                display_name=name.strip(),
                value=value,
                unit=unit.strip(),
                context=cell.strip()[:160],
                location=location,
                variant=variant.strip(),
                from_table=_from_table(location),
            )
        ]

    line = clean_line(line)
    out: list[Pair] = []
    seen: set[tuple[str, float, str]] = set()
    for regex in (PARAM_RE, SPACE_PARAM_RE):
        for match in regex.finditer(line):
            name = match.group("name")
            if is_noise(name):
                continue
            raw_value = float(match.group("value"))
            prefix = match.group("prefix") or ""
            unit = (match.group("unit") or "").strip()
            if not unit and prefix in "ØøΦφ⌀":
                unit = "mm"  # Ø112 means a 112 mm diameter
            if not unit:
                tail = line[match.end():]
                after = UNIT_AFTER_RE.match(tail.lstrip())
                if after:
                    unit = after.group("unit")
            if not unit:
                continue  # a bare number is not a specification
            if unit_dim(unit) is None:
                continue
            key = (normalize_spec_name(name), raw_value, unit.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Pair(
                    name=normalize_spec_name(name),
                    display_name=name.strip(),
                    value=raw_value,
                    unit=unit.strip(),  # keep original casing for display
                    context=line.strip()[:160],
                    location=location,
                    from_table=_from_table(location),
                )
            )
    return out


KEY_HEADERS = {"参数", "项目", "名称", "指标", "属性", "参数名", "项目名称"}
VALUE_HEADERS = {"规格", "值", "取值", "数值", "参数值", "内容", "规格参数"}
# 出现这些表头说明是「变更记录」，记录的是历史，不是当前规格
CHANGELOG_HEADERS = {"原值", "旧值", "变更前", "调整前", "before", "old", "previous"}
VERSION_HEADER_RE = re.compile(r"^\s*(?:CR|V|R|REV|VER|版|版本)\s*[-_ ]?\s*\d+", re.IGNORECASE)


def is_version_header(text: str) -> bool:
    return bool(VERSION_HEADER_RE.match(text or ""))


def table_lines(rows: Iterable[Sequence[str]], prefix: str) -> Iterator[tuple[str, str]]:
    """Turn a table into `参数：值` lines.

    Three layouts are understood:

    key-value   header `参数 | 规格`, rows `电池容量 | 512 Wh`
    wide        header `型号 | 电池容量 | 单价`, rows `PX-200 | 500 Wh | 1299 元`
    versioned   header `项目 | CR-1 | CR-2 | CR-3`, rows `内孔 | Ø28.5 | Ø32 | Ø36`
                emitted as `内孔<TAB>CR-2<TAB>Ø32` so the version survives
    """
    clean = [[(cell or "").strip() for cell in row] for row in rows]
    clean = [row for row in clean if any(row)]
    if len(clean) < 2:
        return
    header = clean[0]
    # 变更记录表（表头含「原值/旧值/变更前」）记录的是历史，不是当前规格。
    # 把它当规格会让「变更影响」把说明本身报成待整改项。
    if any(cell.strip().lower() in CHANGELOG_HEADERS for cell in header if cell):
        return
    keyed = bool(header and header[0] in KEY_HEADERS)
    if not keyed and len(header) >= 2:
        keyed = header[1] in VALUE_HEADERS
    versioned = (
        keyed
        and len(header) >= 3
        and all(is_version_header(cell) for cell in header[1:] if cell)
    )
    if versioned:
        for index, row in enumerate(clean[1:], start=1):
            if not row or not row[0]:
                continue
            for col in range(1, min(len(header), len(row))):
                if row[col]:
                    yield f"{prefix}r{index}", f"{row[0]}\t{header[col]}\t{row[col]}"
        return
    if keyed:
        for index, row in enumerate(clean[1:], start=1):
            if len(row) >= 2 and row[0] and row[1]:
                yield f"{prefix}r{index}", f"{row[0]}：{row[1]}"
    else:
        for index, row in enumerate(clean[1:], start=1):
            for col in range(1, min(len(header), len(row))):
                if header[col] and row[col]:
                    yield f"{prefix}{header[col]}r{index}", f"{header[col]}：{row[col]}"


def iter_docx(path: Path) -> Iterator[tuple[str, str]]:
    try:
        from docx import Document
    except ImportError:
        raise SystemExit("python-docx is required for .docx (pip install python-docx)")
    doc = Document(str(path))
    for index, para in enumerate(doc.paragraphs, start=1):
        if para.text.strip():
            yield f"p{index}", para.text
    for t_index, table in enumerate(doc.tables, start=1):
        rows = [[cell.text for cell in row.cells] for row in table.rows]
        yield from table_lines(rows, f"t{t_index}-")


def iter_pptx(path: Path) -> Iterator[tuple[str, str]]:
    try:
        from pptx import Presentation
    except ImportError:
        raise SystemExit("python-pptx is required for .pptx (pip install python-pptx)")
    prs = Presentation(str(path))
    for s_index, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in para.runs).strip()
                    if text:
                        yield f"slide{s_index}", text
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                yield from table_lines(rows, f"slide{s_index}-")
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                yield f"slide{s_index}-notes", notes


def iter_xlsx(path: Path) -> Iterator[tuple[str, str]]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise SystemExit("openpyxl is required for .xlsx (pip install openpyxl)")
    wb = load_workbook(str(path), read_only=True, data_only=True)
    for sheet in wb.worksheets:
        rows = [["" if c is None else str(c) for c in row] for row in sheet.iter_rows(values_only=True)]
        yield from table_lines(rows, f"{sheet.title}-")
    wb.close()


SEPARATOR_CELL = re.compile(r":?-{2,}:?")


def parse_md_table(block: list[str], doc_name: str) -> Iterator[tuple[str, str]]:
    """A pipe table keeps its columns; flattening it destroys the parameter names."""
    rows: list[list[str]] = []
    for raw in block:
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        rows.append(cells)
    rows = [row for row in rows if not all(SEPARATOR_CELL.fullmatch(cell or "-") for cell in row)]
    if len(rows) >= 2:
        yield from table_lines(rows, f"{doc_name}#tbl")
    else:
        for index, row in enumerate(rows):
            yield f"{doc_name}#tbl{index}", "  ".join(row)


def iter_plain(path: Path) -> Iterator[tuple[str, str]]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("|"):
            block: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index])
                index += 1
            yield from parse_md_table(block, path.name)
            continue
        if line.strip():
            yield f"L{index + 1}", line
        index += 1


def iter_document(path: Path) -> Iterator[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        yield from iter_docx(path)
    elif suffix == ".pptx":
        yield from iter_pptx(path)
    elif suffix == ".xlsx":
        yield from iter_xlsx(path)
    else:
        yield from iter_plain(path)


def collect(root: Path, *, exclude_paths: Iterable[Path] = ()) -> tuple[dict[str, list[Pair]], list[str]]:
    docs: dict[str, list[Pair]] = {}
    skipped: list[str] = []
    blocked = {path.resolve() for path in exclude_paths}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if any(part in {".git", "node_modules", "__pycache__", "reports"} for part in path.parts):
            continue
        if path.name.startswith("~$"):
            continue
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if any(resolved == item or item in resolved.parents for item in blocked):
            continue  # 输出目录在输入目录内时，别把自己的报告当成文档
        rel = str(path.relative_to(root))
        pairs: list[Pair] = []
        for location, line in iter_document(path):
            pairs.extend(parse_pairs(line, f"{rel}#{location}"))
        if pairs:
            docs[rel] = pairs
        else:
            skipped.append(rel)
    return docs, skipped


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Finding:
    kind: str  # conflict | unit-inconsistent | internal-conflict | only-in-some
    severity: str  # high | medium | low
    param: str
    label: str
    detail: str
    values: list[dict[str, Any]]
    suggestion: str


def compare(docs: dict[str, list[Pair]], *, tolerance: float = 0.005) -> tuple[list[Finding], dict[str, Any]]:
    by_param: dict[tuple[str, str], dict[str, list[Pair]]] = {}
    for doc_name, pairs in docs.items():
        for pair in pairs:
            by_param.setdefault((pair.name, pair.variant), {}).setdefault(doc_name, []).append(pair)

    findings: list[Finding] = []
    seen_params = 0
    comparable = 0

    for (param, variant), per_doc in sorted(by_param.items()):
        seen_params += 1
        label = next(iter(next(iter(per_doc.values())))).display_name
        if variant:
            label = f"{label}（{variant}）"

        # 1. Same document, same parameter, different value.
        for doc_name, pairs in per_doc.items():
            values = {(p.value, p.unit.lower()) for p in pairs}
            if len(values) > 1:
                converted = {base for p in pairs if (base := to_base(p.value, p.unit))}
                if len(converted) > 1:
                    findings.append(
                        Finding(
                            kind="internal-conflict",
                            severity="medium",
                            param=param,
                            label=label,
                            detail=f"《{doc_name}》内部同一个参数出现 {len(values)} 个不同的值",
                            values=[_as_value(p, doc_name) for p in pairs],
                            suggestion=(
                                "可能同一份文档里有不同型号/配置（例如两个 SKU 的报价）——如果是，"
                                "请在参数名或表头里带上型号，让审计能区分；如果不是，统一成同一个值。"
                            ),
                        )
                    )

        if len(per_doc) < 2:
            findings.append(
                Finding(
                    kind="only-in-some",
                    severity="low",
                    param=param,
                    label=label,
                    detail="只有一个文档提到这个参数，无法交叉核对",
                    values=[_as_value(pairs[0], doc_name) for doc_name, pairs in per_doc.items()],
                    suggestion="确认其他文档是否应该出现这个参数；如果不需要，忽略。",
                )
            )
            continue

        representative: dict[str, Pair] = {doc: _pick(pairs) for doc, pairs in per_doc.items()}
        dims = {p.unit: unit_dim(p.unit) for p in representative.values()}
        dimensions = {d for d in dims.values() if d}
        if len(dimensions) != 1:
            findings.append(
                Finding(
                    kind="unit-inconsistent",
                    severity="medium",
                    param=param,
                    label=label,
                    detail=f"同名参数的计量维度不同（{', '.join(sorted(dimensions)) or '未知'}），无法自动换算",
                    values=[_as_value(p, doc) for doc, p in representative.items()],
                    suggestion="统一维度，或在参数名里写清口径（例如“输出功率”与“电池能量”不能同名）。",
                )
            )
            continue

        comparable += 1
        base: dict[str, tuple[str, float]] = {}
        for doc, pair in representative.items():
            converted = to_base(pair.value, pair.unit)
            if converted:
                base[doc] = converted
        numbers = [value for _dim, value in base.values()]
        reference = numbers[0]
        worst = max(numbers, key=lambda n: abs(n - reference))
        spread = abs(worst - reference) / reference if reference else 0.0

        if spread > tolerance:
            doc_a, (dim, val_a) = next(iter(base.items()))
            findings.append(
                Finding(
                    kind="conflict",
                    severity="high",
                    param=param,
                    label=label,
                    detail=f"跨文档数值不一致：{DIM_LABELS.get(dim, dim)}基准下最大相差 {spread * 100:.1f}%",
                    values=[_as_value(p, doc) for doc, p in representative.items()],
                    suggestion="确定唯一真相（通常以规格书为准），其余文档以它为准同步；若确实是不同配置，请在参数名里区分。",
                )
            )
        elif len({p.unit.lower() for p in representative.values()}) > 1:
            findings.append(
                Finding(
                    kind="unit-inconsistent",
                    severity="low",
                    param=param,
                    label=label,
                    detail="数值等价，但各文档使用的单位不同",
                    values=[_as_value(p, doc) for doc, p in representative.items()],
                    suggestion="统一单位写法，避免读者换算时出错。",
                )
            )

    stats = {
        "documents": len(docs),
        "parameters": seen_params,
        "comparable": comparable,
        "findings": len(findings),
        "by_severity": {
            level: sum(1 for f in findings if f.severity == level)
            for level in ("high", "medium", "low")
        },
    }
    return findings, stats


@dataclasses.dataclass
class VersionChange:
    param: str
    label: str
    old: Pair | None
    new: Pair | None
    delta: float | None
    status: str  # changed | added | removed


def compare_pair_maps(from_map: dict[str, Pair], to_map: dict[str, Pair]) -> list[VersionChange]:
    """Diff two {parameter: pair} maps — the core of every version comparison."""
    changes: list[VersionChange] = []
    for param in sorted(set(from_map) | set(to_map)):
        old = from_map.get(param)
        new = to_map.get(param)
        label = (new or old).display_name  # type: ignore[union-attr]
        if old and new:
            base_old = to_base(old.value, old.unit)
            base_new = to_base(new.value, new.unit)
            if base_old and base_new and base_old[0] == base_new[0]:
                if abs(base_new[1] - base_old[1]) > 1e-9:
                    delta = (base_new[1] - base_old[1]) / base_old[1] if base_old[1] else None
                    changes.append(VersionChange(param, label, old, new, delta, "changed"))
            elif old.value != new.value:
                changes.append(VersionChange(param, label, old, new, None, "changed"))
        elif new:
            changes.append(VersionChange(param, label, None, new, None, "added"))
        elif old:
            changes.append(VersionChange(param, label, old, None, None, "removed"))
    return changes


def compare_versions(docs: dict[str, list[Pair]], from_v: str, to_v: str) -> list[VersionChange]:
    """Diff one version column against another, inside one folder of documents."""
    from_lists: dict[str, list[Pair]] = {}
    to_lists: dict[str, list[Pair]] = {}
    for pairs in docs.values():
        for pair in pairs:
            if pair.variant == from_v:
                from_lists.setdefault(pair.name, []).append(pair)
            elif pair.variant == to_v:
                to_lists.setdefault(pair.name, []).append(pair)
    return compare_pair_maps(
        {name: _pick(items) for name, items in from_lists.items()},
        {name: _pick(items) for name, items in to_lists.items()},
    )


def compare_dirs(from_docs: dict[str, list[Pair]], to_docs: dict[str, list[Pair]]) -> list[VersionChange]:
    """Diff two revisions that live in two folders (the usual case in real projects)."""
    from_lists: dict[str, list[Pair]] = {}
    to_lists: dict[str, list[Pair]] = {}
    for pairs in from_docs.values():
        for pair in pairs:
            from_lists.setdefault(pair.name, []).append(pair)
    for pairs in to_docs.values():
        for pair in pairs:
            to_lists.setdefault(pair.name, []).append(pair)
    return compare_pair_maps(
        {name: _pick(items) for name, items in from_lists.items()},
        {name: _pick(items) for name, items in to_lists.items()},
    )


def _mentions(text: str, change: VersionChange) -> bool:
    bare = re.sub(r"[（(][^）)]*[）)]", "", change.label)
    return any(candidate and candidate in text for candidate in {change.label, bare})


def render_version_report(
    changes: Sequence[VersionChange],
    from_v: str,
    to_v: str,
    *,
    changelog_name: str = "",
    changelog_text: str = "",
    column_mode: bool = False,
    show_added: bool = False,
) -> str:
    changed = [c for c in changes if c.status == "changed"]
    added = [c for c in changes if c.status == "added"]
    removed = [c for c in changes if c.status == "removed"]
    basis = (
        f"同一文件夹里 `{from_v}` / `{to_v}` 两列"
        if column_mode
        else f"两个修订目录 `{from_v}` → `{to_v}`"
    )
    lines = [
        f"# 版本对比 · {from_v} → {to_v}",
        "",
        f"- 生成时间：{dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 对比对象：{basis}",
        f"- 有变化 {len(changed)} · 新增 {len(added)} · 消失 {len(removed)}",
        "",
        "> 同一参数在多个文档出现时，优先取表格里的值——表格是规格，正文是讨论。",
        "",
        "## 参数变化",
        "",
        f"| 参数 | {from_v} | {to_v} | 变化 |",
        "|---|---|---|---|",
    ]

    def show(pair: Pair | None) -> str:
        return f"{_fmt(pair.value)} {pair.unit}" if pair else "—"

    for change in changed:
        delta = "—" if change.delta is None else f"{change.delta * 100:+.1f}%"
        lines.append(f"| {change.label} | {show(change.old)} | {show(change.new)} | {delta} |")
    if not changed:
        lines.append("| （无） | — | — | — |")

    if added or removed:
        if show_added:
            lines.extend(["", "## 版本间新增 / 消失", "", "| 参数 | 状态 | 值 |", "|---|---|---|"])
            for change in added:
                lines.append(f"| {change.label} | 新增 | {show(change.new)} |")
            for change in removed:
                lines.append(f"| {change.label} | 消失 | {show(change.old)} |")
        else:
            lines.extend(
                [
                    "",
                    f"另有新增 {len(added)} 项、消失 {len(removed)} 项（多数是正文碎片）。",
                    "需要逐条看时加 `--show-added`。",
                ]
            )

    if changelog_text:
        covered = [c for c in changed if _mentions(changelog_text, c)]
        uncovered = [c for c in changed if not _mentions(changelog_text, c)]
        lines.extend(
            [
                "",
                f"## 变更单覆盖（对照 `{changelog_name}`）",
                "",
                f"- 已提及 {len(covered)} / {len(changed)}",
                f"- **未提及 {len(uncovered)}**",
                "",
            ]
        )
        if uncovered:
            lines.extend(
                [
                    "下面这些参数变了，但变更单里没有出现。确认是漏记，还是变更单用了别的叫法：",
                    "",
                    "| 参数 | 变化 |",
                    "|---|---|",
                ]
            )
            for change in uncovered:
                delta = "—" if change.delta is None else f"{change.delta * 100:+.1f}%"
                lines.append(f"| {change.label} | {show(change.old)} → {show(change.new)}（{delta}） |")
        else:
            lines.append("所有参数变化都能在变更单里找到对应条目。")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## 怎么用这张表",
            "",
            "- 逐行确认：每个变化是有意的，还是改图纸时顺手改的",
            "- 「未提及」的项要么补进变更单，要么改回去",
            "- 这张表只比较表格里的值；正文里散落的数字仍要靠人读",
            "",
        ]
    )
    return "\n".join(lines)


def _as_value(pair: Pair, doc: str) -> dict[str, Any]:
    return {
        "document": doc,
        "value": pair.value,
        "unit": pair.unit,
        "context": pair.context,
        "location": pair.location,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(root: Path, docs: dict[str, list[Pair]], findings: list[Finding], stats: dict[str, Any], skipped: list[str], *, show_coverage: bool = False) -> str:
    lines = [
        "# 规格一致性报告",
        "",
        f"- 审计目录：`{root}`",
        f"- 生成时间：{dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 文档：{stats['documents']} 份 · 参数：{stats['parameters']} 个 · 可比对：{stats['comparable']} 个",
        f"- 问题：**{stats['by_severity']['high']} 高 / {stats['by_severity']['medium']} 中 / {stats['by_severity']['low']} 低**",
        "",
        "> 抽取是启发式的：每一条都附了原文上下文，请按上下文判断，不要只看数字。",
        "",
    ]

    def section(title: str, kinds: Sequence[str]) -> None:
        items = [f for f in findings if f.kind in kinds]
        if not items:
            return
        lines.extend([f"## {title}（{len(items)}）", ""])
        for index, item in enumerate(items, start=1):
            lines.append(f"### {index}. `{item.label}` · {item.severity.upper()}")
            lines.append("")
            lines.append(item.detail)
            lines.append("")
            lines.append("| 文档 | 值 | 原文 |")
            lines.append("|---|---|---|")
            for value in item.values:
                shown = f"{_fmt(value['value'])} {value['unit']}"
                lines.append(f"| {value['document']} | {shown} | {_escape(value['context'])} |")
            lines.append("")
            lines.append(f"**建议**：{item.suggestion}")
            lines.append("")

    section("数值冲突", ["conflict"])
    section("文档内部不一致", ["internal-conflict"])
    section("计量口径不一致", ["unit-inconsistent"])
    coverage = [f for f in findings if f.kind == "only-in-some"]
    if coverage:
        if show_coverage:
            section("只在部分文档出现", ["only-in-some"])
        else:
            lines.extend(
                [
                    f"## 只在部分文档出现（{len(coverage)}）",
                    "",
                    "这些参数只在一个文档里出现，无法交叉核对，默认不展开以免淹没真问题。",
                    "需要逐条看时加 `--show-coverage`。",
                    "",
                ]
            )

    if skipped:
        lines.extend(["## 未抽取到参数的文档", ""] + [f"- `{s}`" for s in skipped] + [""])

    lines.extend(
        [
            "---",
            "",
            "## 参数清单（人工复核用）",
            "",
            "| 参数 | " + " | ".join(docs.keys()) + " |",
            "|---|" + "---|" * len(docs),
        ]
    )
    by_param: dict[str, dict[str, str]] = {}
    for doc, pairs in docs.items():
        for pair in pairs:
            by_param.setdefault(pair.display_name, {}).setdefault(doc, f"{_fmt(pair.value)} {pair.unit}")
    for label, per_doc in sorted(by_param.items()):
        row = " | ".join(per_doc.get(doc, "—") for doc in docs)
        lines.append(f"| {label} | {row} |")
    lines.append("")
    return "\n".join(lines)


def _fmt(number: float) -> str:
    return f"{number:g}"


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_json(root: Path, findings: list[Finding], stats: dict[str, Any], skipped: list[str]) -> str:
    payload = {
        "version": VERSION,
        "root": str(root),
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "stats": stats,
        "findings": [dataclasses.asdict(f) for f in findings],
        "skipped": skipped,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def run_scan(root: Path, out_dir: Path, *, fail_on: str = "none", tolerance: float = 0.005, show_coverage: bool = False) -> int:
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    docs, skipped = collect(root)
    if not docs:
        print("error: no extractable parameters found — check that documents contain lines like `重量：6.2 kg`", file=sys.stderr)
        return 2
    findings, stats = compare(docs, tolerance=tolerance)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "spec-consistency.md").write_text(
        render_markdown(root, docs, findings, stats, skipped, show_coverage=show_coverage), encoding="utf-8"
    )
    (out_dir / "spec-consistency.json").write_text(
        render_json(root, findings, stats, skipped), encoding="utf-8"
    )
    print(f"documents: {stats['documents']} · parameters: {stats['parameters']} · comparable: {stats['comparable']}")
    print(
        f"findings: {stats['by_severity']['high']} high / "
        f"{stats['by_severity']['medium']} medium / {stats['by_severity']['low']} low"
    )
    for finding in findings[:8]:
        if finding.kind == "conflict":
            values = " vs ".join(f"{_fmt(v['value'])}{v['unit']}" for v in finding.values)
            print(f"  [{finding.severity}] {finding.label}: {values}")
    print(f"report: {out_dir / 'spec-consistency.md'}")
    print(f"json  : {out_dir / 'spec-consistency.json'}")

    thresholds = {"none": 99, "low": 0, "medium": 1, "high": 2}
    rank = {"low": 0, "medium": 1, "high": 2}
    limit = thresholds.get(fail_on, 99)
    if limit < 99 and any(rank[f.severity] >= limit for f in findings):
        print(f"exit: findings at or above '{fail_on}'", file=sys.stderr)
        return 1
    return 0


def build_demo(target: Path) -> None:
    """Three documents, three real contradictions, all written locally."""
    target.mkdir(parents=True, exist_ok=True)
    try:
        from docx import Document
        from pptx import Presentation
        from openpyxl import Workbook
    except ImportError as exc:
        raise SystemExit(f"demo needs python-docx, python-pptx, openpyxl: {exc}")

    doc = Document()
    doc.add_heading("PX-200 便携储能电源 · 技术规格书", level=1)
    doc.add_paragraph("本文件为产品资料包主文档，其他材料应与本文件保持一致。")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "参数"
    table.rows[0].cells[1].text = "规格"
    for name, value in [
        ("电池容量", "512 Wh"),
        ("整机重量", "6.2 kg"),
        ("输出功率", "600 W"),
        ("满载续航", "45 分钟"),
        ("外形尺寸", "300 × 200 × 180 mm"),
        ("充电时长", "3 小时"),
    ]:
        row = table.add_row()
        row.cells[0].text = name
        row.cells[1].text = value
    doc.save(target / "规格书.docx")

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "PX-200 六大卖点"
    box = slide.shapes.add_textbox(0, 1500000, 8000000, 3000000)
    frame = box.text_frame
    for line in ["电池容量：512 Wh", "整机重量：6.0 kg", "输出功率：600 W", "满载续航：50 分钟"]:
        frame.add_paragraph().text = line
    prs.save(target / "宣传页.pptx")

    wb = Workbook()
    ws = wb.active
    ws.title = "报价"
    ws.append(["型号", "电池容量", "整机重量", "单价"])
    ws.append(["PX-200", "500 Wh", "6.2 kg", "1299 元"])
    ws.append(["PX-200 Pro", "1024 Wh", "9.8 kg", "2499 元"])
    wb.save(target / "报价单.xlsx")

    (target / "README.md").write_text(
        "# 产品资料包\n\n- 规格书.docx：主文档\n- 宣传页.pptx：市场材料\n- 报价单.xlsx：销售材料\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Change impact — one value changed, who still uses the old one?
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ImpactHit:
    doc: str
    location: str
    value: float
    unit: str
    status: str  # current | stale | other
    context: str


def values_equal(left: float, left_unit: str, right: float, right_unit: str, *, tolerance: float = 0.005) -> bool:
    a = to_base(left, left_unit)
    b = to_base(right, right_unit)
    if not a or not b:
        return abs(left - right) <= 1e-9
    if a[0] != b[0]:
        return False
    base = abs(a[1]) or 1.0
    return abs(b[1] - a[1]) / base <= tolerance


def find_impact(
    docs: dict[str, list[Pair]],
    *,
    param: str,
    old_value: float,
    old_unit: str,
    new_value: float,
    new_unit: str,
) -> list[ImpactHit]:
    key = normalize_param(param)
    hits: list[ImpactHit] = []
    for doc, pairs in docs.items():
        for pair in pairs:
            if pair.name != key:
                continue
            if values_equal(pair.value, pair.unit, new_value, new_unit):
                status = "current"
            elif values_equal(pair.value, pair.unit, old_value, old_unit):
                status = "stale"
            else:
                status = "other"
            hits.append(
                ImpactHit(
                    doc=doc,
                    location=pair.location,
                    value=pair.value,
                    unit=pair.unit,
                    status=status,
                    context=pair.context,
                )
            )
    return hits


def render_impact(
    hits: list[ImpactHit],
    *,
    param: str,
    old_value: float,
    old_unit: str,
    new_value: float,
    new_unit: str,
) -> str:
    counts = {status: sum(1 for hit in hits if hit.status == status) for status in ("current", "stale", "other")}
    lines = [
        f"# 变更影响：{param} {_fmt(old_value)} {old_unit} → {_fmt(new_value)} {new_unit}",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M}",
        f"- 命中 {len(hits)} 处：已更新 {counts['current']} · **待更新 {counts['stale']}** · 其它值 {counts['other']}",
        "",
    ]
    if not hits:
        lines.extend(
            [
                "## 结论",
                "",
                f"没有找到参数「{param}」的任何取值。检查参数名写法，或先跑一次 scan 确认抽取规则。",
                "",
            ]
        )
        return "\n".join(lines)

    def section(title: str, status: str, note: str = "") -> None:
        items = [hit for hit in hits if hit.status == status]
        if not items:
            return
        lines.extend([f"## {title}（{len(items)}）", ""])
        if note:
            lines.extend([note, ""])
        lines.append("| 文件 | 位置 | 当前值 | 原文 |")
        lines.append("|---|---|---|---|")
        for hit in items:
            lines.append(
                f"| {hit.doc} | {hit.location.split('#')[-1]} | {_fmt(hit.value)} {hit.unit} | {_escape(hit.context)} |"
            )
        lines.append("")

    section("待更新（仍是旧值）", "stale", "这些地方还写着旧值，改完才算完成变更。")
    section("其它值（需人工判断）", "other", "既不是旧值也不是新值——可能是另一个版本、另一型号，或笔误。")
    section("已更新", "current")

    lines.extend(
        [
            "---",
            "",
            "> 只检查「参数：值」形式的取值；正文里提到参数名但没给数字的地方不在此列，仍需人工扫一遍。",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_impact(args: argparse.Namespace) -> int:
    root = Path(args.path or args.directory)
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    docs, _skipped = collect(root, exclude_paths=[Path(args.out)] if args.out else [])
    if not docs:
        print("error: 没有抽取到任何参数，检查文档里是否有「参数：值」结构", file=sys.stderr)
        return 2
    try:
        old_value = float(args.old)
        new_value = float(args.new)
    except ValueError:
        print("error: --old / --new 必须是数字（单位放在 --old-unit / --new-unit）", file=sys.stderr)
        return 2
    hits = find_impact(
        docs,
        param=args.param,
        old_value=old_value,
        old_unit=args.old_unit,
        new_value=new_value,
        new_unit=args.new_unit,
    )
    report = render_impact(
        hits, param=args.param, old_value=old_value, old_unit=args.old_unit,
        new_value=new_value, new_unit=args.new_unit,
    )
    print(report)
    out = Path(args.out or "impact-out")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "change-impact.md"
    target.write_text(report, encoding="utf-8")
    (out / "change-impact.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "param": args.param,
                "old": {"value": old_value, "unit": args.old_unit},
                "new": {"value": new_value, "unit": args.new_unit},
                "hits": [dataclasses.asdict(hit) for hit in hits],
                "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    stale = sum(1 for hit in hits if hit.status == "stale")
    print(f"\nreport: {target}")
    if stale and args.fail_on_stale:
        print(f"exit: {stale} 处仍在使用旧值", file=sys.stderr)
        return 1
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    root = Path(args.out or (Path(tempfile.gettempdir()) / "spec-audit-demo"))
    build_demo(root)
    print(f"demo material written to: {root}")
    for path in sorted(root.iterdir()):
        print(f"  - {path.name}")
    print()
    return run_scan(root, Path(args.report) if args.report else root / "reports", fail_on="none")


def cmd_scan(args: argparse.Namespace) -> int:
    target = args.path or args.directory
    return run_scan(
        Path(target),
        Path(args.out or "spec-reports"),
        fail_on=args.fail_on,
        tolerance=args.tolerance,
        show_coverage=args.show_coverage,
    )


def cmd_versions(args: argparse.Namespace) -> int:
    from_label = args.from_version or (Path(args.from_dir).name if args.from_dir else "")
    to_label = args.to_version or (Path(args.to_dir).name if args.to_dir else "")
    if not from_label or not to_label:
        print("error: give --from/--to (version columns) or --from-dir/--to-dir", file=sys.stderr)
        return 2

    if args.from_dir or args.to_dir:
        if not (args.from_dir and args.to_dir):
            print("error: --from-dir and --to-dir must be used together", file=sys.stderr)
            return 2
        for folder in (args.from_dir, args.to_dir):
            if not Path(folder).is_dir():
                print(f"error: not a directory: {folder}", file=sys.stderr)
                return 2
        from_docs, _ = collect(Path(args.from_dir))
        to_docs, _ = collect(Path(args.to_dir))
        changes = compare_dirs(from_docs, to_docs)
        basis = f"目录 `{args.from_dir}` vs `{args.to_dir}`"
        mode = "dirs"
    else:
        root = Path(args.path or args.directory)
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 2
        docs, _skipped = collect(root)
        changes = compare_versions(docs, args.from_version, args.to_version)
        basis = f"`{root}` 中的 {args.from_version} / {args.to_version} 两列"
        mode = "columns"

    if not changes:
        print(
            "warn: nothing to compare — no parameter appears in both revisions. "
            "Check the table headers, or use --from-dir/--to-dir.",
            file=sys.stderr,
        )

    changelog_name = ""
    changelog_text = ""
    if args.changelog:
        path = Path(args.changelog)
        if path.exists():
            changelog_text = path.read_text(encoding="utf-8-sig", errors="replace")
            changelog_name = path.name
        else:
            print(f"warn: changelog not found: {path}", file=sys.stderr)

    out = Path(args.out or "spec-reports")
    out.mkdir(parents=True, exist_ok=True)
    (out / "version-diff.md").write_text(
        render_version_report(
            changes,
            from_label,
            to_label,
            changelog_name=changelog_name,
            changelog_text=changelog_text,
            column_mode=mode == "columns",
            show_added=args.show_added,
        ),
        encoding="utf-8",
    )
    (out / "version-diff.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "from": from_label,
                "to": to_label,
                "basis": basis,
                "changes": [
                    {
                        "param": change.param,
                        "label": change.label,
                        "status": change.status,
                        "old": dataclasses.asdict(change.old) if change.old else None,
                        "new": dataclasses.asdict(change.new) if change.new else None,
                        "delta": change.delta,
                    }
                    for change in changes
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    changed = [c for c in changes if c.status == "changed"]
    print(f"{from_label} → {to_label}: {len(changed)} 项变化，{len(changes)} 项差异")
    for change in changed[:15]:
        old = f"{_fmt(change.old.value)} {change.old.unit}" if change.old else "—"
        new = f"{_fmt(change.new.value)} {change.new.unit}" if change.new else "—"
        delta = "" if change.delta is None else f"  ({change.delta * 100:+.1f}%)"
        print(f"  {change.label}: {old} → {new}{delta}")
    print(f"report: {out / 'version-diff.md'}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool]] = []
    checks.append(("kg converts to grams", to_base(6.2, "kg") == ("mass", 6200.0)))
    checks.append(("min converts to seconds", to_base(45, "分钟") == ("time", 60 * 45.0)))
    checks.append(("unknown unit ignored", to_base(1, "个") is None))
    checks.append(("synonym normalises", normalize_param("整机重量") == "重量"))
    checks.append(("noise rejected", is_noise("第") and is_noise("注")))
    pairs = parse_pairs("满载续航：45 分钟，整机重量 6.2kg。", "demo")
    checks.append(("parses colon form", any(p.name == "续航时间" and p.value == 45 for p in pairs)))
    checks.append(("parses space form", any(p.name == "重量" and abs(p.value - 6.2) < 1e-9 for p in pairs)))
    checks.append(("bare number ignored", parse_pairs("共 3 个", "demo") == []))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spec_audit.py",
        description="Cross-document consistency audit for product material (docx/pptx/xlsx/md).",
        epilog="examples:\n  python scripts/spec_audit.py demo\n  python scripts/spec_audit.py scan ./material --fail-on high",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"spec-audit {VERSION}")
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="audit a folder of product documents")
    scan.add_argument("path", nargs="?", default=None, help="folder to audit (or use -d)")
    scan.add_argument("-d", "--directory", default=".", help="folder to audit")
    scan.add_argument("-o", "--out", default="")
    scan.add_argument("--fail-on", choices=["none", "low", "medium", "high"], default="none")
    scan.add_argument("--tolerance", type=float, default=0.005, help="relative tolerance before a value mismatch counts (default 0.5%%)")
    scan.add_argument("--show-coverage", action="store_true", help="also list parameters that appear in only one document")
    scan.set_defaults(func=cmd_scan)

    demo = sub.add_parser("demo", help="generate a contradictory product pack and audit it")
    demo.add_argument("-o", "--out", default="")
    demo.add_argument("--report", default="")
    demo.set_defaults(func=cmd_demo)

    versions = sub.add_parser("versions", help="diff two revisions of a parameter table")
    versions.add_argument("path", nargs="?", default=None, help="folder to scan (or use -d)")
    versions.add_argument("-d", "--directory", default=".")
    versions.add_argument("--from", dest="from_version", default="", help="old column header, e.g. CR-2")
    versions.add_argument("--to", dest="to_version", default="", help="new column header, e.g. CR-3")
    versions.add_argument("--from-dir", default="", help="folder holding the old revision")
    versions.add_argument("--to-dir", default="", help="folder holding the new revision")
    versions.add_argument("--changelog", default="", help="markdown change log to check coverage against")
    versions.add_argument("--show-added", action="store_true", help="also list parameters that appeared or vanished")
    versions.add_argument("-o", "--out", default="")
    versions.set_defaults(func=cmd_versions)

    impact = sub.add_parser("impact", help="一个值改了，谁还在用旧的")
    impact.add_argument("path", nargs="?", default=None, help="目录（或使用 -d）")
    impact.add_argument("-d", "--directory", default=".")
    impact.add_argument("--param", required=True, help="参数名，例如 内孔")
    impact.add_argument("--old", required=True, help="旧值（数字）")
    impact.add_argument("--new", required=True, help="新值（数字）")
    impact.add_argument("--old-unit", default="mm")
    impact.add_argument("--new-unit", default="mm")
    impact.add_argument("--fail-on-stale", action="store_true", help="仍有旧值时退出码 1（CI 用）")
    impact.add_argument("-o", "--out", default="")
    impact.set_defaults(func=cmd_impact)

    selftest = sub.add_parser("selftest", help="run built-in checks")
    selftest.set_defaults(func=cmd_selftest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

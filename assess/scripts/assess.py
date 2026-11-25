#!/usr/bin/env python3
"""assess — 对象 vs 标准：把一组观测值对照到一份参照系，输出差距、分级和优先级。

    python scripts/assess.py run --rubric rubrics/health-metabolic.json --kv tc=6.2,tg=2.8
    python scripts/assess.py run --rubric rubrics/career-pm.json --input self.json
    python scripts/assess.py list
    python scripts/assess.py demo

设计原则：
  1. 参照系放在 JSON 里（区间、目标值、权重、来源），可审可改，不藏进代码
  2. 引擎只做确定性的对照与汇总；「这个值意味着什么」由 rubric 的文案负责
  3. 医疗类 rubric 只做分级和就医提示，不做诊断、不给药物建议
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUBRICS = ROOT / "rubrics"

SEVERITY_LABELS = {0: "正常", 1: "注意", 2: "关注", 3: "建议就医"}
SEVERITY_RANK = {"正常": 0, "注意": 1, "关注": 2, "建议就医": 3}


# ---------------------------------------------------------------------------
# Rubric loading
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Item:
    key: str
    name: str
    kind: str  # range | target
    unit: str = ""
    aliases: list[str] = dataclasses.field(default_factory=list)
    ranges: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    target: float | None = None
    direction: str = "higher_better"
    denominator: str = ""
    weight: float = 1.0
    advice: dict[str, str] = dataclasses.field(default_factory=dict)
    note: str = ""


@dataclasses.dataclass
class Rubric:
    id: str
    title: str
    kind: str
    source: str = ""
    disclaimer: str = ""
    items: list[Item] = dataclasses.field(default_factory=list)
    summary_rules: list[str] = dataclasses.field(default_factory=list)
    market_data: dict[str, Any] = dataclasses.field(default_factory=dict)

    def find_item(self, name: str) -> Item | None:
        needle = normalize_key(name)
        for item in self.items:
            if needle in {normalize_key(item.key), normalize_key(item.name), *{normalize_key(a) for a in item.aliases}}:
                return item
        return None


def normalize_key(text: str) -> str:
    return re.sub(r"[\s_\-—:：]+", "", str(text or "")).lower()


def load_rubric(path: Path) -> Rubric:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    items = [
        Item(
            key=str(raw.get("key") or raw.get("name")),
            name=str(raw.get("name") or raw.get("key")),
            kind=str(raw.get("kind") or "range"),
            unit=str(raw.get("unit") or ""),
            aliases=[str(a) for a in raw.get("aliases") or []],
            ranges=list(raw.get("ranges") or []),
            target=raw.get("target"),
            direction=str(raw.get("direction") or "higher_better"),
            denominator=str(raw.get("denominator") or ""),
            weight=float(raw.get("weight") or 1.0),
            advice={str(k): str(v) for k, v in (raw.get("advice") or {}).items()},
            note=str(raw.get("note") or ""),
        )
        for raw in data.get("items") or []
    ]
    if not items:
        raise SystemExit(f"{path}: rubric has no items")
    return Rubric(
        id=str(data.get("id") or path.stem),
        title=str(data.get("title") or path.stem),
        kind=str(data.get("kind") or "generic"),
        source=str(data.get("source") or ""),
        disclaimer=str(data.get("disclaimer") or ""),
        items=items,
        market_data=data.get("market_data") or {},
        summary_rules=[str(r) for r in data.get("summary_rules") or []],
    )


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Result:
    key: str
    name: str
    value: float | None
    unit: str
    level: str
    reference: str
    advice: str
    severity: str
    gap: float | None = None
    weight: float = 1.0
    priority: float = 0.0
    missing: bool = False


def parse_inputs(kv: str | None, input_path: Path | None) -> dict[str, float]:
    values: dict[str, float] = {}
    if input_path:
        raw = json.loads(input_path.read_text(encoding="utf-8-sig"))
        for key, value in raw.items():
            try:
                values[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    if kv:
        for chunk in kv.split(","):
            if not chunk.strip() or "=" not in chunk:
                continue
            key, _, value = chunk.partition("=")
            try:
                values[key.strip()] = float(value.strip())
            except ValueError:
                continue
    return values


def classify_range(item: Item, value: float) -> tuple[str, str, str]:
    """Return (level, reference description, severity label).

    区间语义是**左闭右开**：``max`` 是这一级的上界，落在界值上归**下一级**。
    这与临床指南的写法一致（TC <5.2 合适，5.2–6.2 边缘升高），
    所以 ``value >= upper`` 才升级，而不是 ``>``。
    """
    ranges = item.ranges
    if not ranges:
        return "无基准", "—", "注意"
    low = None
    ordered = sorted(ranges, key=lambda r: (r.get("max") if r.get("max") is not None else 1e18))
    for entry in ordered:
        upper = entry.get("max")
        if upper is not None and value >= float(upper):
            low = float(upper)
            continue
        level = str(entry.get("level") or "—")
        reference = _ref_text(low, entry.get("max"), item.unit)
        severity = str(entry.get("severity") or "注意")
        return level, reference, severity
    # above every range
    entry = ordered[-1]
    return str(entry.get("level") or "偏高"), _ref_text(low, None, item.unit), str(entry.get("severity") or "关注")


def _ref_text(low: float | None, high: Any, unit: str) -> str:
    if low is not None and high is not None:
        return f"{low:g} – {float(high):g} {unit}".strip()
    if high is not None:
        return f"< {float(high):g} {unit}".strip()
    if low is not None:
        return f"> {low:g} {unit}".strip()
    return "—"


def assess(rubric: Rubric, values: dict[str, float]) -> list[Result]:
    results: list[Result] = []
    used: set[str] = set()
    for item in rubric.items:
        matched_key, matched_value = None, None
        for candidate, value in values.items():
            if rubric.find_item(candidate) is item:
                matched_key, matched_value = candidate, value
                used.add(candidate)
                break
        if matched_value is None:
            results.append(
                Result(
                    key=item.key, name=item.name, value=None, unit=item.unit,
                    level="未提供", reference="—", advice="输入这项后才会评估", severity="注意",
                    weight=item.weight, missing=True,
                )
            )
            continue

        if item.kind == "ratio":
            denominator = None
            for candidate, value in values.items():
                if normalize_key(candidate) == normalize_key(item.denominator):
                    denominator = value
                    break
            if not denominator:
                results.append(
                    Result(
                        key=item.key, name=item.name, value=None, unit="%",
                        level="缺分母", reference=f"目标 {float(item.target):g}%",
                        advice=f"需要提供「{item.denominator}」才能算占比", severity="注意",
                        weight=item.weight, missing=True,
                    )
                )
                continue
            percent = matched_value / denominator * 100
            target = float(item.target)
            raw_gap = percent - target if item.direction == "lower_better" else target - percent
            if raw_gap <= 0:
                level, severity = "达标", "正常"
            elif raw_gap <= 5:
                level, severity = "略超" if item.direction == "lower_better" else "略低", "注意"
            elif raw_gap <= 15:
                level, severity = "偏高" if item.direction == "lower_better" else "不足", "关注"
            else:
                level, severity = "明显偏高" if item.direction == "lower_better" else "明显不足", "关注"
            advice = item.advice.get(level) or item.advice.get("default", "") or item.note
            results.append(
                Result(
                    key=item.key, name=item.name, value=round(percent, 1), unit="%",
                    level=level, reference=f"目标 {target:g}%", advice=advice,
                    severity=severity, gap=round(raw_gap, 1), weight=item.weight,
                    priority=max(0.0, raw_gap) * item.weight,
                )
            )
            continue

        if item.kind == "target":
            target = float(item.target if item.target is not None else 5.0)
            gap = target - matched_value if item.direction == "higher_better" else matched_value - target
            if gap <= 0:
                level, severity = "达标", "正常"
            elif gap <= target * 0.2:
                level, severity = "略低" if item.direction == "higher_better" else "略高", "注意"
            elif gap <= target * 0.4:
                level, severity = "明显不足" if item.direction == "higher_better" else "明显偏高", "关注"
            else:
                level, severity = "短板", "建议就医" if rubric.kind == "health" else "关注"
            reference = f"目标 {target:g} {item.unit}".strip()
            advice = item.advice.get(level) or item.advice.get("default", "")
            priority = max(0.0, gap) * item.weight
            results.append(
                Result(
                    key=item.key, name=item.name, value=matched_value, unit=item.unit,
                    level=level, reference=reference, advice=advice or item.note,
                    severity=severity, gap=gap, weight=item.weight, priority=priority,
                )
            )
            continue

        level, reference, severity = classify_range(item, matched_value)
        advice = item.advice.get(level) or item.advice.get(severity) or item.note
        results.append(
            Result(
                key=item.key, name=item.name, value=matched_value, unit=item.unit,
                level=level, reference=reference, advice=advice, severity=severity,
                weight=item.weight, priority=float(SEVERITY_RANK.get(severity, 1)) * item.weight,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def overall_level(results: list[Result], rubric: Rubric) -> tuple[str, str]:
    present = [r for r in results if not r.missing]
    if not present:
        return "无法评估", "没有任何指标被提供"
    worst = max(present, key=lambda r: SEVERITY_RANK.get(r.severity, 1))
    worst_rank = SEVERITY_RANK.get(worst.severity, 1)
    same_level = [r for r in present if SEVERITY_RANK.get(r.severity, 1) == worst_rank]
    names = "、".join(r.name for r in same_level[:3])
    suffix = f" 等 {len(same_level)} 项" if len(same_level) > 3 else ""
    reason = f"最需要关注：{names}{suffix}（{worst.level}）"
    if rubric.kind == "health":
        if any(r.severity == "建议就医" for r in present):
            return "建议尽快就医复核", reason
        if any(r.severity == "关注" for r in present):
            return "需要关注", reason
        if any(r.severity == "注意" for r in present):
            return "基本正常，个别项偏高", reason
        return "各项在参考范围内", "继续保持"
    shortlist = sorted((r for r in present if r.priority > 0), key=lambda r: -r.priority)
    if not shortlist:
        return "已达标", "没有明显短板"
    top = "、".join(r.name for r in shortlist[:3])
    return "有明确差距", f"优先补强：{top}"


def render_markdown(rubric: Rubric, results: list[Result], *, source_label: str = "") -> str:
    verdict, reason = overall_level(results, rubric)
    lines = [
        f"# {rubric.title}",
        "",
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M}",
        f"- 基准：`{rubric.id}`" + (f" · 来源：{rubric.source}" if rubric.source else ""),
        f"- 输入：{source_label or '命令行'}",
        "",
        f"## 结论：{verdict}",
        "",
        f"{reason}",
        "",
        "| 指标 | 数值 | 参考 | 分级 | 建议 |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        value = "—" if result.value is None else f"{result.value:g} {result.unit}".strip()
        lines.append(
            f"| {result.name} | {value} | {result.reference} | {result.level} | {result.advice or '—'} |"
        )
    lines.append("")

    missing = [r for r in results if r.missing]
    if missing:
        lines.extend(["## 未提供的指标", ""] + [f"- {r.name}" for r in missing] + [""])

    # 上市公司真实数据对比：不替换经验区间，两个数并列，让人自己判断
    market = rubric.market_data or {}
    gm = market.get("gross_margin") or {}
    nm = market.get("net_margin") or {}
    if gm:
        lines.extend([
            "## A 股同行业真实数据",
            "",
            f"来源：{market.get('board')}（{market.get('period')}，样本 {gm.get('count')} 家上市公司）",
            "",
            "| 指标 | 上市公司中位数 | 25%–75% 区间 |",
            "|---|---|---|",
            f"| 毛利率 | {gm.get('median')}% | {gm.get('p25')}% – {gm.get('p75')}% |",
        ])
        if nm:
            lines.append(f"| 净利率 | {nm.get('median')}% | {nm.get('p25')}% – {nm.get('p75')}% |")
        lines.extend([
            "",
            "> 上市公司规模和规范度都高于中小企业。餐饮、便利店这类以小微为主的行业，",
            "> 上市公司样本又少又大，中位数只能当参考——**不是“你该做到多少”的标准**。",
            "",
        ])

    ranked = sorted((r for r in results if not r.missing and r.priority > 0), key=lambda r: -r.priority)
    if ranked and rubric.kind != "health":
        lines.extend(["## 优先级", ""])
        for index, result in enumerate(ranked[:6], start=1):
            gap = "" if result.gap is None else f"（差距 {result.gap:+.2g}）"
            lines.append(f"{index}. **{result.name}** — {result.level}{gap} · 权重 {result.weight:g}")
        lines.append("")

    if rubric.disclaimer:
        lines.extend(["---", "", f"> {rubric.disclaimer}", ""])
    return "\n".join(lines)


def write_xlsx(out_dir: Path, rubric: Rubric, results: list[Result]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "评估结果"
    ws.append(["指标", "数值", "单位", "参考区间", "分级", "建议", "权重", "优先级"])
    for result in results:
        ws.append([
            result.name,
            result.value,
            result.unit,
            result.reference,
            result.level,
            result.advice,
            result.weight,
            round(result.priority, 3),
        ])
    fills = {
        "正常": PatternFill("solid", fgColor="E2EFDA"),
        "注意": PatternFill("solid", fgColor="FFF2CC"),
        "关注": PatternFill("solid", fgColor="FCE4D6"),
        "建议就医": PatternFill("solid", fgColor="FFC7CE"),
    }
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF7")
        cell.alignment = Alignment(wrap_text=True)
    for row in ws.iter_rows(min_row=2):
        fill = fills.get(str(row[4].value))
        if fill:
            for cell in row:
                cell.fill = fill
    widths = [22, 10, 10, 22, 12, 46, 8, 10]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + index)].width = width
    ws.freeze_panes = "A2"

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"assess-{rubric.id}.xlsx"
    wb.save(str(target))
    return target


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def resolve_rubric(path: str) -> Path:
    candidate = Path(path)
    if candidate.exists():
        return candidate
    for suffix in (".json", ""):
        alt = DEFAULT_RUBRICS / f"{path}{suffix}"
        if alt.exists():
            return alt
    # 支持子目录：rubrics/industry/<id>.json 这类组织方式
    matches = sorted(DEFAULT_RUBRICS.rglob(f"{path}.json"))
    if matches:
        return matches[0]
    raise SystemExit(f"rubric not found: {path} (looked in {DEFAULT_RUBRICS} and its subdirectories)")


def cmd_list(args: argparse.Namespace) -> int:
    for path in sorted(DEFAULT_RUBRICS.rglob("*.json")):
        try:
            rubric = load_rubric(path)
        except SystemExit:
            continue
        print(f"{rubric.id:<22} {rubric.title}  ({len(rubric.items)} 项)")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rubric = load_rubric(resolve_rubric(args.rubric))
    values = parse_inputs(args.kv, Path(args.input) if args.input else None)
    if not values:
        print("error: no input values — use --kv key=value,... or --input values.json", file=sys.stderr)
        return 2
    results = assess(rubric, values)
    report = render_markdown(rubric, results, source_label=args.input or "命令行")
    print(report)
    out = Path(args.out or "assess-out")
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{rubric.id}.md"
    target.write_text(report, encoding="utf-8")
    xlsx = write_xlsx(out, rubric, results)
    payload = {
        "version": VERSION,
        "rubric": rubric.id,
        "items": [
            {
                "key": result.key,
                "name": result.name,
                "value": result.value,
                "unit": result.unit,
                "level": result.level,
                "severity": result.severity,
                "missing": result.missing,
            }
            for result in results
        ],
    }
    json_path = out / f"{rubric.id}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {target}\nxlsx  : {xlsx}\njson  : {json_path}")
    if args.fail_on and any(SEVERITY_RANK.get(r.severity, 0) >= SEVERITY_RANK[args.fail_on] and not r.missing for r in results):
        return 1
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    samples = [
        (
            "健康指标（血脂+代谢）",
            DEFAULT_RUBRICS / "health-metabolic.json",
            {"tc": 6.4, "tg": 2.9, "ldl": 4.3, "hdl": 0.85, "glucose": 6.3, "uric": 486, "sbp": 138},
        ),
        (
            "职场技能（产品经理）",
            DEFAULT_RUBRICS / "career-pm.json",
            {
                "用户研究": 2, "需求分析": 3, "数据分析": 2, "项目管理": 4,
                "商业理解": 2, "技术理解": 3, "表达沟通": 3,
            },
        ),
        (
            "家庭开支（月度）",
            DEFAULT_RUBRICS / "budget-50-30-20.json",
            {"必要支出": 8200, "生活享受": 4300, "储蓄投资": 2500, "收入": 15000},
        ),
    ]
    out = Path(args.out or "assess-demo")
    for title, rubric_path, values in samples:
        rubric = load_rubric(rubric_path)
        results = assess(rubric, values)
        report = render_markdown(rubric, results, source_label="demo")
        print("=" * 70)
        print(title)
        print("=" * 70)
        print(report)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{rubric.id}.md").write_text(report, encoding="utf-8")
        write_xlsx(out, rubric, results)
    print(f"\nreports: {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assess.py", description="对象 vs 标准：多维对照评估")
    parser.add_argument("--version", action="version", version=f"assess {VERSION}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="用一份 rubric 评估一组输入")
    run.add_argument("--rubric", required=True)
    run.add_argument("--kv", default=None, help="tc=6.2,tg=2.8")
    run.add_argument("--input", default=None, help="JSON 文件 {指标: 值}")
    run.add_argument("-o", "--out", default="assess-out")
    run.add_argument("--fail-on", choices=["注意", "关注", "建议就医"], default=None)
    run.set_defaults(func=cmd_run)

    listing = sub.add_parser("list", help="列出可用 rubric")
    listing.set_defaults(func=cmd_list)

    demo = sub.add_parser("demo", help="用三个样例跑一遍")
    demo.add_argument("-o", "--out", default="assess-demo")
    demo.set_defaults(func=cmd_demo)
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

#!/usr/bin/env python3
"""benchmark — 用带标准答案的对照集审验工具好不好用。

    python run.py
    python run.py --case product-spec --verbose

单测证明「代码按设计运行」，这里证明「设计本身对不对」：

    漏报（false negative）—— 有问题没报，最危险
    误报（false positive）—— 没问题乱报，久了就没人看
    精确率 P = 真报 / 所有报的
    召回率 R = 真报 / 应该报的

每个 case 都有 expected.json，写明「必须找到」和「绝不能报」。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

VERSION = "0.1.0"
BASE = Path(__file__).resolve().parents[1]
CASES = Path(__file__).resolve().parent / "cases"
PY = sys.executable
TOOLS = {
    "spec": BASE / "spec-consistency" / "scripts" / "spec_audit.py",
    "ledger": BASE / "ledger-match" / "scripts" / "vat_reconcile.py",
    "reconcile": BASE / "reconcile" / "scripts" / "reconcile.py",
    "multi": BASE / "reconcile" / "scripts" / "reconcile.py",
    "impact": BASE / "spec-consistency" / "scripts" / "spec_audit.py",
    "assess": BASE / "assess" / "scripts" / "assess.py",
    "dir": BASE / "reconcile" / "scripts" / "reconcile.py",
    "trend": BASE / "compare-anything" / "scripts" / "trend.py",
}

CONSENSUS_CN = {"unanimous": "一致", "majority": "多数", "split": "无共识", "missing": "缺失"}


@dataclass
class Case:
    name: str
    tool: str
    argv: list[str]
    report: str
    must_find: list[str]
    must_not_report: list[str] = field(default_factory=list)
    notes: str = ""
    expect_empty: bool = False  # 对抗性 case：断言「一条都不该报」


@dataclass
class Score:
    case: str
    found: list[str]
    missed: list[str]
    false_alarms: list[str]
    reported: list[str]
    unexpected: list[str] = field(default_factory=list)  # expect_empty 场景里冒出来的

    @property
    def precision(self) -> float:
        # 只把「标注为不该报却报了」算误报；未标注的真实差异不算
        denominator = len(self.found) + len(self.false_alarms)
        return len(self.found) / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        total = len(self.found) + len(self.missed)
        return len(self.found) / total if total else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def load_case(case_dir: Path) -> Case:
    spec = json.loads((case_dir / "expected.json").read_text(encoding="utf-8-sig"))
    return Case(
        name=spec["name"],
        tool=spec["tool"],
        argv=list(spec["argv"]),
        report=spec["report"],
        must_find=list(spec["must_find"]),
        must_not_report=list(spec.get("must_not_report") or []),
        notes=str(spec.get("notes") or ""),
        expect_empty=bool(spec.get("expect_empty") or False),
    )


def run_case(case: Case, case_dir: Path, out: Path) -> tuple[dict[str, Any] | None, str]:
    argv = [str(TOOLS[case.tool]), *[part.replace("{input}", str(case_dir / "input")).replace("{out}", str(out)) for part in case.argv]]
    completed = subprocess.run(
        [PY, *argv],
        cwd=str(case_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    report_path = Path(case.report.replace("{out}", str(out)))
    if not report_path.exists():
        return None, f"没有生成报告：{report_path}\n{completed.stderr[-400:]}"
    try:
        return json.loads(report_path.read_text(encoding="utf-8-sig")), ""
    except json.JSONDecodeError as exc:
        return None, f"报告不是合法 JSON：{exc}"


# ---- 每个工具如何从报告里取出「报了哪些项」 --------------------------------

def reported_items(case: Case, report: dict[str, Any]) -> list[str]:
    if case.tool == "spec":
        # 只把 high 级冲突算作「报」；覆盖缺口(low)不算误报
        return [
            str(f.get("label") or f.get("param") or "")
            for f in report.get("findings") or []
            if str(f.get("severity")) == "high"
        ]
    if case.tool == "ledger":
        items: list[str] = []
        for row in report.get("by_rate") or []:
            if abs(float(row.get("gap") or 0)) > 0.01:
                items.append(f"{row['rate']}")
        return items
    if case.tool == "reconcile":
        items = []
        for diff in report.get("diffs") or []:
            key = str(diff.get("key") or "")
            field_name = str(diff.get("field") or diff.get("label") or "")
            items.append(f"{key}|{field_name}")
        return items
    if case.tool == "impact":
        return [f"{hit['doc']}|{hit['status']}" for hit in report.get("hits") or [] if hit.get("status") == "stale"]
    if case.tool == "multi":
        return [
            f"{vote['key']}|{CONSENSUS_CN.get(vote['consensus'], vote['consensus'])}"
            for vote in report.get("votes") or []
            if vote.get("consensus") in {"majority", "split"}
        ]
    if case.tool == "assess":
        return [f"{item.get('key', '')}|{item.get('level', '')}" for item in report.get("items") or []]
    if case.tool == "dir":
        return [f"{entry['rel']}|{entry['status']}" for entry in report.get("files") or []]
    if case.tool == "trend":
        counts = report.get("counts") or {}
        return [
            f"新增 {counts.get('new', 0)}",
            f"恶化 {counts.get('worsened', 0)}",
            f"持续 {counts.get('persistent', 0)}",
            f"已解决 {counts.get('resolved', 0)}",
        ]
    return []


def score(case: Case, report: dict[str, Any]) -> Score:
    reported = reported_items(case, report)

    def norm(text: str) -> str:
        # 比对时忽略空格、千分位逗号、标点；保留 | 作为字段分隔
        return re.sub(r"[\s,，。;；:：]+", "", str(text or "")).lower()

    def hit(item: str, entries: list[str]) -> bool:
        needle = norm(item)
        return any(needle in norm(entry) for entry in entries)

    found = [item for item in case.must_find if hit(item, reported)]
    missed = [item for item in case.must_find if not hit(item, reported)]
    false_alarms = [item for item in case.must_not_report if hit(item, reported)]
    unexpected = reported if case.expect_empty else []
    extra = [
        entry
        for entry in reported
        if not any(hit(item, [entry]) for item in case.must_find)
        and not any(hit(item, [entry]) for item in case.must_not_report)
    ]
    return Score(
        case=case.name,
        found=found,
        missed=missed,
        false_alarms=false_alarms + unexpected,
        reported=found + extra,
        unexpected=unexpected,
    )


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(description="用对照集审验工具")
    parser.add_argument("--case", default="", help="只跑某个 case")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"benchmark {VERSION}")
    args = parser.parse_args(argv)

    missing = [name for name, path in TOOLS.items() if not path.exists()]
    if missing:
        print(f"error: 找不到工具：{missing}", file=sys.stderr)
        return 2

    case_dirs = sorted(path for path in CASES.iterdir() if path.is_dir() and (path / "expected.json").exists())
    if args.case:
        case_dirs = [path for path in case_dirs if path.name == args.case]
    if not case_dirs:
        print("没有找到 case（cases/*/expected.json）", file=sys.stderr)
        return 2

    rows: list[Score] = []
    hard_failures: list[str] = []
    for case_dir in case_dirs:
        case = load_case(case_dir)
        if case.tool not in TOOLS:
            hard_failures.append(f"{case.name}: 未注册工具 {case.tool}")
            print(f"❌ {case.name} — 未注册工具 {case.tool}")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            report, error = run_case(case, case_dir, out)
        if report is None:
            hard_failures.append(f"{case.name}: {error}")
            print(f"❌ {case.name} — 跑不起来")
            print(f"   {error}")
            continue
        result = score(case, report)
        rows.append(result)
        icon = "✅" if not result.missed and not result.false_alarms else ("⚠️" if result.missed else "🔸")
        print(f"{icon} {case.name:<28} 找到 {len(result.found)}/{len(result.found) + len(result.missed)}  "
              f"误报 {len(result.false_alarms)}  P={result.precision:.2f} R={result.recall:.2f}")
        if args.verbose or result.missed or result.false_alarms:
            if result.missed:
                print(f"   漏报：{result.missed}")
            if result.false_alarms:
                print(f"   误报：{result.false_alarms}")
            if case.notes:
                print(f"   说明：{case.notes}")
            if args.verbose:
                print(f"   实报：{result.reported}")

    print()
    if rows:
        total_found = sum(len(r.found) for r in rows)
        total_missed = sum(len(r.missed) for r in rows)
        total_alarm = sum(len(r.false_alarms) for r in rows)
        precision = total_found / (total_found + total_alarm) if (total_found + total_alarm) else 1.0
        recall = total_found / (total_found + total_missed) if (total_found + total_missed) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        print(f"汇总：{len(rows)} 个场景 · 命中 {total_found} · 漏报 {total_missed} · 误报 {total_alarm} "
              f"· P={precision:.2f} R={recall:.2f} F1={f1:.2f}")
    if hard_failures:
        print(f"跑不起来 {len(hard_failures)} 个：")
        for failure in hard_failures:
            print(f"  - {failure}")
        return 1
    return 0 if rows and all(not r.missed and not r.false_alarms for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

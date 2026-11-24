#!/usr/bin/env python3
"""acceptance — 错误注入验收：专喂坏数据，检查工具会不会「假装没事」。

    python scripts/acceptance.py
    python scripts/acceptance.py --verbose

验收的不是「算得对不对」，而是「数据有问题时它会不会说」：

    空表 / 只有表头        -> 必须提示「没有可对照的记录」，而不是「无差异」
    不存在的文件 / 品种     -> 必须非零退出并给出可用清单
    无匹配指标             -> 必须报「无法评估」，而不是给一个结论
    参数解析失败           -> 必须跳过并提示，而不是崩
    无法判断路由           -> 必须说「无法判断」

一条不过，就是真 bug，不是测试写错了。
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

VERSION = "0.1.0"
BASE = Path(__file__).resolve().parents[2]
PY = sys.executable
TOOLS = {
    "reconcile": BASE / "reconcile" / "scripts" / "reconcile.py",
    "exchange": BASE / "exchange" / "scripts" / "exchange.py",
    "assess": BASE / "assess" / "scripts" / "assess.py",
    "route": BASE / "compare-anything" / "scripts" / "route.py",
}


@dataclass
class Case:
    name: str
    argv: list[str]
    cwd: Path
    expect_code: int | None = None  # None = 不关心
    must_contain: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()


def run(case: Case) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [PY, *case.argv],
            cwd=str(case.cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, "超时（120s）"
    output = (completed.stdout or "") + (completed.stderr or "")
    problems: list[str] = []
    if case.expect_code is not None and completed.returncode != case.expect_code:
        problems.append(f"退出码 {completed.returncode} ≠ 期望 {case.expect_code}")
    for needle in case.must_contain:
        if needle not in output:
            problems.append(f"缺少提示「{needle}」")
    for needle in case.must_not_contain:
        if needle in output:
            problems.append(f"不该出现「{needle}」")
    if problems:
        tail = output.strip().splitlines()[-4:]
        return False, "；".join(problems) + "  输出尾部：" + " / ".join(tail)
    return True, "ok"


def build_cases(workspace: Path) -> list[Case]:
    # --- 造坏数据 ---
    header_only = workspace / "只有表头.csv"
    with header_only.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerow(["代码", "名称", "价格"])

    empty = workspace / "空文件.csv"
    empty.write_text("", encoding="utf-8")

    one_col = workspace / "只有一列.csv"
    with one_col.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["代码"])
        writer.writerow(["600519"])
        writer.writerow(["000001"])

    plain_a = workspace / "a.txt"
    plain_a.write_text("第一段\n第二段\n", encoding="utf-8")
    plain_b = workspace / "b.txt"
    plain_b.write_text("第一段\n第三段\n", encoding="utf-8")

    return [
        # ---- reconcile：坏输入必须说话 ----
        Case(
            "reconcile · 只有表头的表不能报「无差异」",
            [str(TOOLS["reconcile"]), "run", str(header_only), str(header_only), "-o", str(workspace / "o1")],
            workspace,
            expect_code=2,
            must_contain=("没有可对照",),
            must_not_contain=("没有发现差异",),
        ),
        Case(
            "reconcile · 空文件不能崩",
            [str(TOOLS["reconcile"]), "run", str(empty), str(empty), "-o", str(workspace / "o2")],
            workspace,
            expect_code=2,
            must_contain=("没有可对照",),
        ),
        Case(
            "reconcile · 文件不存在要报错",
            [str(TOOLS["reconcile"]), "run", str(workspace / "不存在.docx"), str(workspace / "也不存在.docx")],
            workspace,
            expect_code=2,
            must_contain=("不存在",),
        ),
        # ---- exchange：参数错误要给可用清单 ----
        Case(
            "exchange · 品种不存在要列可用品种",
            [str(TOOLS["exchange"]), "convert", "--from", "铜", "--to", "黄金"],
            workspace,
            expect_code=1,
            must_contain=("没有「黄金」", "铜"),
        ),
        Case(
            "exchange · 单位不支持要列可用单位",
            [str(TOOLS["exchange"]), "convert", "--from", "铜", "--to", "铝", "--unit", "石"],
            workspace,
            expect_code=1,
            must_contain=("不支持的单位", "斤"),
        ),
        # ---- assess：无匹配 / 坏值 ----
        Case(
            "assess · 指标全不匹配要报「无法评估」",
            [str(TOOLS["assess"]), "run", "--rubric", "health-metabolic", "--kv", "胡编指标=1"],
            workspace,
            expect_code=0,
            must_contain=("无法评估",),
            must_not_contain=("各项在参考范围内",),
        ),
        Case(
            "assess · 坏数值不能崩",
            [str(TOOLS["assess"]), "run", "--rubric", "health-metabolic", "--kv", "收缩压=abc,总胆固醇=6.4"],
            workspace,
            expect_code=0,
            must_contain=("升高", "总胆固醇"),
        ),
        Case(
            "assess · rubric 不存在要报错",
            [str(TOOLS["assess"]), "run", "--rubric", "不存在的rubric", "--kv", "a=1"],
            workspace,
            expect_code=1,
            must_contain=("rubric not found",),
        ),
        # ---- route：判断不了要说出口 ----
        Case(
            "route · 无法判断要提示",
            [str(TOOLS["route"]), "run", "--left", "随便", "--right", "什么"],
            workspace,
            expect_code=2,
            must_contain=("无法判断",),
        ),
        Case(
            "route · 文件缺失要提示",
            [str(TOOLS["route"]), "run", "--left", "x.docx", "--right", "y.docx"],
            workspace,
            expect_code=2,
            must_contain=("不存在",),
        ),
        # ---- 正常路径仍要工作（防止修坏） ----
        Case(
            "reconcile · 正常两个文本能出报告",
            [str(TOOLS["reconcile"]), "run", str(plain_a), str(plain_b), "-o", str(workspace / "o3")],
            workspace,
            expect_code=0,
            must_contain=("对照报告",),
        ),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="错误注入验收：坏数据下工具必须说话")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"acceptance {VERSION}")
    args = parser.parse_args(argv)

    missing = [name for name, path in TOOLS.items() if not path.exists()]
    if missing:
        print(f"error: 找不到工具脚本：{missing}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        cases = build_cases(workspace)
        passed = 0
        failures: list[tuple[Case, str]] = []
        for case in cases:
            ok, detail = run(case)
            status = "✅" if ok else "❌"
            print(f"{status} {case.name}")
            if args.verbose or not ok:
                print(f"     {detail}")
            if ok:
                passed += 1
            else:
                failures.append((case, detail))
        total = len(cases)
        print()
        print(f"{passed}/{total} 通过")
        if failures:
            print("\n未通过的用例（这些是工具的问题，不是测试的问题）：")
            for case, detail in failures:
                print(f"  - {case.name}\n      {detail}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

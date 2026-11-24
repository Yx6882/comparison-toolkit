#!/usr/bin/env python3
"""route — 对照万物的总入口：看输入，选工具，跑起来。

    python scripts/route.py which --left 合同A.docx --right 合同B.docx
    python scripts/route.py run   --left 合同A.docx --right 合同B.docx
    python scripts/route.py run   --left 铜 --right 铝 --quantity 1 --unit 斤
    python scripts/route.py run   --rubric health-metabolic --kv "收缩压=142"

三类对照：
    文件 vs 文件   -> reconcile
    物   vs 物     -> exchange
    对象 vs 标准   -> assess
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
BASE = Path(__file__).resolve().parents[2]  # 与 reconcile/assess/exchange 同级的父目录
TOOLS = {
    "reconcile": {"dir": BASE / "reconcile", "script": "scripts/reconcile.py"},
    "exchange": {"dir": BASE / "exchange", "script": "scripts/exchange.py"},
    "assess": {"dir": BASE / "assess", "script": "scripts/assess.py"},
}

FILE_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv", ".docx", ".pptx", ".md", ".txt"}
COMMODITIES = {"铜", "铝", "锌", "铅", "镍", "螺纹钢", "玉米", "豆粕"}


def classify(args: argparse.Namespace) -> tuple[str, str, list[str]]:
    """Return (tool, reason, argv)."""
    if args.rubric:
        argv = ["run", "--rubric", args.rubric]
        if args.kv:
            argv += ["--kv", args.kv]
        if args.input:
            argv += ["--input", args.input]
        if args.out:
            argv += ["-o", args.out]
        return "assess", "给了 --rubric，按「对象 vs 标准」评估", argv

    left, right = args.left, args.right
    if left and right:
        left_path, right_path = Path(left), Path(right)
        if left_path.suffix.lower() in FILE_SUFFIXES or right_path.suffix.lower() in FILE_SUFFIXES:
            if left_path.exists() and right_path.exists():
                argv = ["run", str(left_path.resolve()), str(right_path.resolve())]
                if args.key:
                    argv += ["--key", args.key]
                if args.out:
                    argv += ["-o", args.out]
                return "reconcile", "两个文件都存在，按「文件 vs 文件」对照", argv
            return "reconcile", f"看起来是两个文件，但至少一个不存在：{left} / {right}", []
        if left in COMMODITIES and right in COMMODITIES:
            argv = ["convert", "--from", left, "--to", right,
                    "--quantity", str(args.quantity), "--unit", args.unit]
            if args.out:
                argv += ["-o", args.out]
            return "exchange", "两个都是行情品种，按「物 vs 物」等值换算", argv

    return "", "无法判断该用哪个工具：给两个文件，或两个品种名，或 --rubric", []


def build_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def execute(tool: str, argv: list[str]) -> int:
    spec = TOOLS[tool]
    script = spec["dir"] / spec["script"]
    if not script.exists():
        print(f"error: 找不到 {tool} 的脚本：{script}", file=sys.stderr)
        return 2
    command = [sys.executable, str(script), *argv]
    print(f"[route] {tool}: {' '.join(command[1:])}")
    print("-" * 70)
    completed = subprocess.run(command, cwd=str(spec["dir"]), env=build_env())
    return completed.returncode


def cmd_which(args: argparse.Namespace) -> int:
    tool, reason, argv = classify(args)
    if not tool:
        print(reason)
        return 2
    command = [sys.executable, str(TOOLS[tool]["dir"] / TOOLS[tool]["script"]), *argv]
    print(json.dumps({"tool": tool, "reason": reason, "command": command}, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    tool, reason, argv = classify(args)
    if not tool or not argv:
        print(f"error: {reason}", file=sys.stderr)
        return 2
    print(f"[route] {reason}")
    return execute(tool, argv)


def cmd_selftest(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool]] = []
    namespace = argparse.Namespace(left="铜", right="铝", quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input=None, out=None, key=None)
    tool, reason, argv = classify(namespace)
    checks.append(("铜/铝 -> exchange", tool == "exchange" and argv[:2] == ["convert", "--from"]))

    namespace = argparse.Namespace(left="a.docx", right="b.docx", quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input=None, out=None, key=None)
    tool, reason, argv = classify(namespace)
    checks.append(("docx 对 -> reconcile", tool == "reconcile"))

    namespace = argparse.Namespace(left=None, right=None, quantity=1.0, unit="斤", rubric="health-metabolic",
                                  kv="收缩压=142", input=None, out=None, key=None)
    tool, reason, argv = classify(namespace)
    checks.append(("rubric -> assess", tool == "assess" and "--kv" in argv))

    namespace = argparse.Namespace(left="x", right="y", quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input=None, out=None, key=None)
    tool, reason, argv = classify(namespace)
    checks.append(("无法判断 -> 空", tool == ""))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="route.py", description="对照万物总入口：文件/物物/对象对标准")
    parser.add_argument("--version", action="version", version=f"route {VERSION}")
    sub = parser.add_subparsers(dest="command")

    for name, func, help_text in (("which", cmd_which, "只判断用哪个工具"), ("run", cmd_run, "判断并执行")):
        sub_parser = sub.add_parser(name, help=help_text)
        sub_parser.add_argument("--left")
        sub_parser.add_argument("--right")
        sub_parser.add_argument("--quantity", type=float, default=1.0)
        sub_parser.add_argument("--unit", default="斤")
        sub_parser.add_argument("--rubric")
        sub_parser.add_argument("--kv")
        sub_parser.add_argument("--input")
        sub_parser.add_argument("--key", default=None)
        sub_parser.add_argument("-o", "--out", default="")
        sub_parser.set_defaults(func=func)

    selftest = sub.add_parser("selftest", help="路由自检")
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

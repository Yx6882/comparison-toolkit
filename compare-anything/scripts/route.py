#!/usr/bin/env python3
"""route — 对照的总入口：看输入，选工具，跑起来。

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

VERSION = "0.2.0"
BASE = Path(__file__).resolve().parents[2]  # 与 reconcile/assess/exchange 同级的父目录
TOOLS = {
    "reconcile": {"dir": BASE / "reconcile", "script": "scripts/reconcile.py"},
    "exchange": {"dir": BASE / "exchange", "script": "scripts/exchange.py"},
    "assess": {"dir": BASE / "assess", "script": "scripts/assess.py"},
    "accounting": {"dir": BASE / "accounting-checks", "script": "scripts/{command}.py"},
}

# 会计类的输入是「一个 JSON」，不是「两份文件」，所以单独一套参数
ACCOUNTING_TASKS = {
    "bank": ["match", "-i", "{input}"],
    "ledger": ["check", "-i", "{input}"],
    "statements": ["check", "-i", "{input}"],
    "voucher": ["check", "-i", "{input}"],
    "ratios": ["calc", "-i", "{input}"],
}

DOC_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".tsv", ".docx", ".pptx", ".md", ".txt"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
AUDIO_SUFFIXES = {".wav"}
COMMODITIES = {"铜", "铝", "锌", "铅", "镍", "螺纹钢", "玉米", "豆粕"}

# 文件名里出现这些词，说明要做的不是「逐行比较」，而是会计专项核对
FILENAME_HINTS = [
    ("bank", ("流水", "银行", "回款", "对账")),
    ("ledger", ("科目余额", "余额表", "试算")),
    ("statements", ("报表", "资产负债表", "利润表", "现金流")),
    ("voucher", ("凭证", "分录")),
    ("ratios", ("比率",)),
]


def guess_accounting_task(paths: list[str]) -> str | None:
    """文件名里能看出是会计专项核对时，返回任务名。"""
    names = " ".join(Path(p).name for p in paths if p).lower()
    for task, hints in FILENAME_HINTS:
        if any(hint in names for hint in hints):
            return task
    return None


def classify(args: argparse.Namespace) -> tuple[str, str, list[str]]:
    """Return (tool, reason, argv)。accounting 类的 argv 第一个元素是子命令名。"""
    task = (args.task or "auto").lower()

    # 显式指定会计任务
    if task in ACCOUNTING_TASKS:
        if not args.input:
            return "", f"--task {task} 需要一个 JSON 输入（--input）", []
        argv = [part.replace("{input}", str(Path(args.input).resolve())) for part in ACCOUNTING_TASKS[task]]
        return "accounting", f"指定了 --task {task}，按会计专项核对处理", argv

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

    # 自动判断：文件名看起来像会计专项核对
    if task == "auto" and args.input and not left and not right:
        guessed = guess_accounting_task([args.input])
        if guessed:
            argv = [part.replace("{input}", str(Path(args.input).resolve())) for part in ACCOUNTING_TASKS[guessed]]
            return "accounting", f"文件名像「{guessed}」类数据，按会计专项核对处理", argv

    if left and right:
        left_path, right_path = Path(left), Path(right)
        left_suffix = left_path.suffix.lower()
        right_suffix = right_path.suffix.lower()
        is_media = (
            (left_suffix in IMAGE_SUFFIXES and right_suffix in IMAGE_SUFFIXES)
            or (left_suffix in AUDIO_SUFFIXES and right_suffix in AUDIO_SUFFIXES)
        )
        is_doc = left_suffix in DOC_SUFFIXES or right_suffix in DOC_SUFFIXES
        if is_doc or is_media:
            if left_path.exists() and right_path.exists():
                argv = ["run", str(left_path.resolve()), str(right_path.resolve())]
                if args.key:
                    argv += ["--key", args.key]
                if args.out:
                    argv += ["-o", args.out]
                kind = "媒体" if is_media else "文件"
                return "reconcile", f"两个{kind}都存在，按「{kind} vs {kind}」对照", argv
            return "reconcile", f"看起来是两个文件，但至少一个不存在：{left} / {right}", []
        if left in COMMODITIES and right in COMMODITIES:
            argv = ["convert", "--from", left, "--to", right,
                    "--quantity", str(args.quantity), "--unit", args.unit]
            if args.out:
                argv += ["-o", args.out]
            return "exchange", "两个都是行情品种，按「物 vs 物」等值换算", argv

    return "", "无法判断该用哪个工具：给两个文件，或 --rubric，或 --task <bank|ledger|statements|voucher|ratios> --input 文件.json", []


def build_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def resolve_command(tool: str, argv: list[str]) -> tuple[Path, list[str]]:
    """会计类工具的脚本名要按子命令拼，并把子命令从参数里去掉。"""
    if tool != "accounting":
        return TOOLS[tool]["dir"] / TOOLS[tool]["script"], argv
    if not argv:
        raise SystemExit("accounting 工具缺少子命令")
    command = argv[0]
    script = TOOLS[tool]["dir"] / TOOLS[tool]["script"].replace("{command}", command)
    return script, argv[1:]


def execute(tool: str, argv: list[str]) -> int:
    spec = TOOLS[tool]
    script, rest = resolve_command(tool, argv)
    if not script.exists():
        print(f"error: 找不到 {tool} 的脚本：{script}", file=sys.stderr)
        return 2
    command = [sys.executable, str(script), *rest]
    print(f"[route] {tool}: {' '.join(command[1:])}")
    print("-" * 70)
    completed = subprocess.run(command, cwd=str(spec["dir"]), env=build_env())
    return completed.returncode


def cmd_which(args: argparse.Namespace) -> int:
    tool, reason, argv = classify(args)
    if not tool:
        print(reason)
        return 2
    script, rest = resolve_command(tool, argv)
    command = [sys.executable, str(script), *rest]
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
    import tempfile

    checks: list[tuple[str, bool]] = []
    namespace = argparse.Namespace(left="铜", right="铝", quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input=None, out=None, key=None, task="auto")
    tool, reason, argv = classify(namespace)
    checks.append(("铜/铝 -> exchange", tool == "exchange" and argv[:2] == ["convert", "--from"]))

    namespace = argparse.Namespace(left="a.docx", right="b.docx", quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input=None, out=None, key=None, task="auto")
    tool, reason, argv = classify(namespace)
    checks.append(("docx 对 -> reconcile", tool == "reconcile"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        png_a, png_b = root / "a.png", root / "b.png"
        png_a.write_bytes(b"\x89PNG-fake")
        png_b.write_bytes(b"\x89PNG-fake")
        namespace = argparse.Namespace(left=str(png_a), right=str(png_b), quantity=1.0, unit="斤", rubric=None,
                                      kv=None, input=None, out=None, key=None, task="auto")
        tool, reason, argv = classify(namespace)
        checks.append(("png 对 -> reconcile（图片媒体）", tool == "reconcile" and "媒体" in reason))

        wav_a, wav_b = root / "a.wav", root / "b.wav"
        wav_a.write_bytes(b"RIFFfake")
        wav_b.write_bytes(b"RIFFfake")
        namespace = argparse.Namespace(left=str(wav_a), right=str(wav_b), quantity=1.0, unit="斤", rubric=None,
                                      kv=None, input=None, out=None, key=None, task="auto")
        tool, reason, argv = classify(namespace)
        checks.append(("wav 对 -> reconcile（音频媒体）", tool == "reconcile" and "媒体" in reason))

    namespace = argparse.Namespace(left=None, right=None, quantity=1.0, unit="斤", rubric="health-metabolic",
                                  kv="收缩压=142", input=None, out=None, key=None, task="auto")
    tool, reason, argv = classify(namespace)
    checks.append(("rubric -> assess", tool == "assess" and "--kv" in argv))

    namespace = argparse.Namespace(left=None, right=None, quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input="流水.json", out=None, key=None, task="bank")
    tool, reason, argv = classify(namespace)
    checks.append(("--task bank -> accounting", tool == "accounting" and argv[0] == "match"))

    namespace = argparse.Namespace(left=None, right=None, quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input="银行流水.json", out=None, key=None, task="auto")
    tool, reason, argv = classify(namespace)
    checks.append(("文件名含「流水」-> accounting bank", tool == "accounting" and argv[0] == "match"))

    namespace = argparse.Namespace(left=None, right=None, quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input="随便.json", out=None, key=None, task="auto")
    tool, reason, argv = classify(namespace)
    checks.append(("普通 json 不误判成会计任务", tool == ""))

    namespace = argparse.Namespace(left="x", right="y", quantity=1.0, unit="斤", rubric=None, kv=None,
                                  input=None, out=None, key=None, task="auto")
    tool, reason, argv = classify(namespace)
    checks.append(("无法判断 -> 空", tool == ""))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="route.py", description="对照总入口：文件/物物/对象对标准")
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
        sub_parser.add_argument("--task", default="auto",
                                help="auto | bank | ledger | statements | voucher | ratios")
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

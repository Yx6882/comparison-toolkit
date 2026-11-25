#!/usr/bin/env python3
"""install — 把 7 个 skill 安装到某个 AI 客户端的 skills 目录。

    python install.py                          # 自动检测常见目录
    python install.py --target ~/.claude/skills
    python install.py --list                   # 只列出会装什么
    python install.py --target X --dry-run     # 看会写哪些文件

只复制 SKILL.md 所在的能力目录，不动 tests/benchmark（那些是开发用的）。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys

VERSION = "0.1.0"
HERE = pathlib.Path(__file__).resolve().parent

# 要安装的 skill（benchmark 是验收工具，不是 skill，不装）
SKILLS = [
    "ai-council",
    "spec-consistency",
    "ledger-match",
    "reconcile",
    "assess",
    "exchange",
    "compare-anything",
    "accounting-checks",
]

# 常见客户端的 skills 目录（存在哪个就装哪个）
CANDIDATES = {
    "Claude Code": [".claude/skills"],
    "Cline": [".cline/skills"],
    "Cursor": [".cursor/skills"],
    "DSH": [".dsh/skills"],
}

# 每个 skill 要带上的子目录/文件（references、scripts、rubrics、data 等）
INCLUDE = {"SKILL.md", "references", "scripts", "rubrics", "data", "assets", "README.md", "README.zh-CN.md", "LICENSE"}


def candidate_dirs() -> list[tuple[str, pathlib.Path]]:
    home = pathlib.Path.home()
    found: list[tuple[str, pathlib.Path]] = []
    for client, relatives in CANDIDATES.items():
        for relative in relatives:
            path = home / relative
            if path.parent.exists():  # 父目录在，就认为这个客户端装过
                found.append((client, path))
    return found


def plan(target: pathlib.Path) -> list[tuple[pathlib.Path, pathlib.Path]]:
    """Return (source, destination) pairs."""
    pairs: list[tuple[pathlib.Path, pathlib.Path]] = []
    for skill in SKILLS:
        source_root = HERE / skill
        if not (source_root / "SKILL.md").exists():
            continue
        for item in sorted(source_root.iterdir()):
            if item.name not in INCLUDE:
                continue
            pairs.append((item, target / skill / item.name))
    return pairs


def do_install(target: pathlib.Path, *, dry_run: bool, force: bool) -> int:
    if not any((HERE / skill / "SKILL.md").exists() for skill in SKILLS):
        print(f"error: 这里找不到 skill（应在仓库根运行）：{HERE}", file=sys.stderr)
        return 2
    pairs = plan(target)
    if not pairs:
        print("error: 没有可安装的内容", file=sys.stderr)
        return 2
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
    conflicts = [destination for _source, destination in pairs if destination.exists()]
    if conflicts and not force and not dry_run:
        print(f"目标里已有 {len(conflicts)} 个同名文件，加 --force 覆盖，或换 --target：")
        for path in conflicts[:5]:
            print(f"  {path}")
        return 1
    for source, destination in pairs:
        if dry_run:
            print(f"  {source.relative_to(HERE)} -> {destination}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    if not dry_run:
        print(f"已安装 {len(SKILLS)} 个 skill 到 {target}")
        print("重启客户端后，AI 应该能看到这些 skill。")
        print()
        print("自检：")
        for skill in SKILLS:
            marker = "✅" if (target / skill / "SKILL.md").exists() else "❌"
            print(f"  {marker} {target / skill / 'SKILL.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(description="把 skill 装进 AI 客户端的 skills 目录")
    parser.add_argument("--target", default="", help="目标目录，例如 ~/.claude/skills")
    parser.add_argument("--list", action="store_true", help="只列出会安装什么")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    parser.add_argument("--version", action="version", version=f"install {VERSION}")
    args = parser.parse_args(argv)

    if args.list or args.dry_run:
        target = pathlib.Path(os.path.expanduser(args.target or "~/.claude/skills"))
        for source, destination in plan(target):
            print(f"  {source.relative_to(HERE)} -> {destination}")
        return 0

    if args.target:
        target = pathlib.Path(os.path.expanduser(args.target))
        return do_install(target, dry_run=False, force=args.force)

    found = candidate_dirs()
    if not found:
        print("没有检测到已知的 skills 目录。手动指定：")
        print("  python install.py --target ~/.claude/skills")
        print()
        print("已知的默认位置：")
        for client, relatives in CANDIDATES.items():
            for relative in relatives:
                print(f"  {client:<12} ~/{relative}")
        return 1
    for client, target in found:
        print(f"检测到 {client}：{target}")
    for _client, target in found:
        code = do_install(target, dry_run=False, force=args.force)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

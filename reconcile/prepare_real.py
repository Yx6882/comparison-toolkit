"""把抓下来的真实数据转成可对照的 CSV，并独立算一遍差异用于验证。"""

import csv
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
base = Path(__file__).resolve().parent / "real-data"
out = base / "csv"
out.mkdir(exist_ok=True)


def dump_deps(version: str) -> dict[str, str]:
    data = json.loads((base / f"express-{version}.json").read_text(encoding="utf-8"))
    deps = data.get("dependencies") or {}
    path = out / f"express-{version}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["依赖", "版本"])
        for name in sorted(deps):
            writer.writerow([name, deps[name]])
    print(f"{path.name}: {len(deps)} deps · readme={'yes' if data.get('readme') else 'no'}")
    return deps


left = dump_deps("4.18.2")
right = dump_deps("5.0.0")

only_left = sorted(set(left) - set(right))
only_right = sorted(set(right) - set(left))
changed = sorted(k for k in set(left) & set(right) if left[k] != right[k])

print()
print("独立核算（用于验证工具输出）：")
print(f"  仅 4.18.2 有：{only_left}")
print(f"  仅 5.0.0 有：{only_right}")
print(f"  版本变化：{len(changed)} 个")
for key in changed:
    print(f"    {key}: {left[key]} -> {right[key]}")

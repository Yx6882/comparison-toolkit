"""用抓下来的真实公开数据生成 benchmark case。

数据源（均来自公开接口，可复查）：
    世界银行 API  · NY.GDP.MKTP.CD（GDP，现价美元）2020 vs 2023
    npm registry · express@5.0.0 的 dependencies，官方源 vs 国内镜像

生成 CSV 后由人工核对结果，再写 expected.json —— 标准答案必须来自人，不能来自工具。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CASES = HERE / "cases"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def write_csv(path: Path, header: list[str], rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


# ---------------------------------------------------------------- 世界银行 GDP
ledger = json.loads((RAW / "worldbank-gdp.json").read_text(encoding="utf-8"))
records = ledger[1] if len(ledger) > 1 else []
by_year: dict[str, list[tuple[str, str]]] = {}
for record in records:
    if not record or record.get("value") is None:
        continue
    year = str(record.get("date"))
    country = str((record.get("country") or {}).get("id") or "")
    by_year.setdefault(year, []).append((country, f"{float(record['value']):.2f}"))

gdp_dir = CASES / "real-worldbank-gdp" / "input"
for year, rows in sorted(by_year.items()):
    rows.sort()
    write_csv(gdp_dir / f"{year}.csv", ["国家", "GDP（现价美元）"], rows)
    print(f"{year}.csv: {len(rows)} 个国家")

# ---------------------------------------------------------------- npm 双源
def deps_of(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(sorted((data.get("dependencies") or {}).items()))


official = deps_of(RAW / "npm-official.json")
mirror = deps_of(RAW / "npm-mirror.json")
npm_dir = CASES / "real-npm-mirror" / "input"
write_csv(npm_dir / "官方源.csv", ["依赖", "版本要求"], list(official.items()))
write_csv(npm_dir / "镜像源.csv", ["依赖", "版本要求"], list(mirror.items()))
print(f"官方源 {len(official)} 个依赖 · 镜像源 {len(mirror)} 个依赖")

diff = {name for name in set(official) | set(mirror) if official.get(name) != mirror.get(name)}
print(f"两个源之间的依赖差异：{sorted(diff) if diff else '无'}")

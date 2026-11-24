"""用第二批真实数据生成 benchmark case（世界银行多指标 / GitHub tag / 汇率）。

标准答案由本脚本独立算出并打印，人工核对后才写进 expected.json。
"""

from __future__ import annotations

import base64
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CASES = HERE / "cases"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def write_csv(path: Path, header: list[str], rows: list[tuple[str, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def worldbank(metric: str, slug: str, label: str, raw_name: str = "", old: str = "2020", new: str = "2023") -> dict:
    source = RAW / (raw_name or f"wb-{slug}.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    records = payload[1] if len(payload) > 1 else []
    by_year: dict[str, list[tuple[str, str]]] = {}
    for record in records:
        value = record.get("value")
        if value is None:
            continue
        year = str(record.get("date"))
        country = str((record.get("country") or {}).get("id") or "")
        by_year.setdefault(year, []).append((country, f"{float(value):.4f}"))

    case_dir = CASES / f"real-wb-{slug}" / "input"
    for year, rows in by_year.items():
        write_csv(case_dir / f"{year}.csv", ["国家", label], sorted(rows))

    old_map = dict(by_year.get(old, []))
    new_map = dict(by_year.get(new, []))
    changes = {
        country: (float(old_map[country]), float(new_map[country]))
        for country in sorted(old_map)
        if country in new_map and abs(float(new_map[country]) - float(old_map[country])) > 1e-9
    }
    print(f"[{metric}] {old}->{new} 变化的国家：{list(changes)}")
    for country, (before, after) in changes.items():
        delta = (after - before) / before * 100 if before else float("nan")
        print(f"    {country}: {before:,.4f} -> {after:,.4f}  ({delta:+.2f}%)")
    return {"countries": list(changes), "old": old, "new": new, "label": label}


print("=" * 60)
gdp = worldbank("NY.GDP.MKTP.CD", "gdp", "GDP（现价美元）", raw_name="worldbank-gdp.json")
pop = worldbank("SP.POP.TOTL", "population", "人口")
infl = worldbank("FP.CPI.TOTL.ZG", "inflation", "通胀率（%）")
unemp = worldbank("SL.UEM.TOTL.ZS", "unemployment", "失业率（%）")


# ---------------------------------------------------------------- GitHub tag
def github_deps(name: str, field: str) -> dict[str, str]:
    data = json.loads((RAW / name).read_text(encoding="utf-8"))
    content = base64.b64decode(data["content"]).decode("utf-8")
    package = json.loads(content)
    return dict(sorted((package.get(field) or {}).items()))


old_deps = github_deps("gh-vue-3.4.0.json", "devDependencies")
new_deps = github_deps("gh-vue-3.5.0.json", "devDependencies")
gh_dir = CASES / "real-github-tag" / "input"
write_csv(gh_dir / "v3.4.0.csv", ["依赖", "版本要求"], list(old_deps.items()))
write_csv(gh_dir / "v3.5.0.csv", ["依赖", "版本要求"], list(new_deps.items()))
only_old = sorted(set(old_deps) - set(new_deps))
only_new = sorted(set(new_deps) - set(old_deps))
changed = sorted(name for name in set(old_deps) & set(new_deps) if old_deps[name] != new_deps[name])
print("=" * 60)
print(f"[GitHub] vuejs/core v3.4.0 -> v3.5.0 devDependencies")
print(f"    仅旧版：{only_old}")
print(f"    仅新版：{only_new}")
print(f"    版本变化：{len(changed)} 个")
for name in changed:
    print(f"    {name}: {old_deps[name]} -> {new_deps[name]}")


# ---------------------------------------------------------------- 汇率
def fx_rates(name: str) -> dict[str, float]:
    data = json.loads((RAW / name).read_text(encoding="utf-8"))
    return {key: float(value) for key, value in (data.get("rates") or {}).items()}


fx_old = fx_rates("fx-cny-1120.json")
fx_new = fx_rates("fx-cny-1113.json")
print("=" * 60)
for key in sorted(fx_old):
    if key in fx_new:
        before, after = fx_old[key], fx_new[key]
        print(f"[汇率] CNY->{key}: 11-20 {before:.6f} vs 11-13 {after:.6f}  ({(before-after)/after*100:+.2f}%)")
print()
print("数据已生成到 cases/real-*")

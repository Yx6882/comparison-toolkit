#!/usr/bin/env python3
"""List the model ids a provider actually serves right now.

Model names age faster than any README: gpt-5 becomes gpt-5.2, a preview alias
is retired, an aggregator adds a family. Run this instead of trusting a table.

    python scripts/sync_models.py                       # every provider with a key set
    python scripts/sync_models.py --only deepseek,openai
    python scripts/sync_models.py --json models.live.json
    python scripts/sync_models.py --diff models/registry.json   # show new / gone ids

Standard library only. Keys are read from the environment, never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {"type": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "anthropic": {"type": "anthropic", "base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY"},
    "google": {"type": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta", "api_key_env": "GEMINI_API_KEY"},
    "deepseek": {"type": "openai", "base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "qwen": {"type": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key_env": "DASHSCOPE_API_KEY"},
    "moonshot": {"type": "openai", "base_url": "https://api.moonshot.cn/v1", "api_key_env": "MOONSHOT_API_KEY"},
    "zhipu": {"type": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4", "api_key_env": "ZHIPU_API_KEY"},
    "xai": {"type": "openai", "base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY"},
    "mistral": {"type": "openai", "base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"},
    "openrouter": {"type": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "groq": {"type": "openai", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    "together": {"type": "openai", "base_url": "https://api.together.xyz/v1", "api_key_env": "TOGETHER_API_KEY"},
    "ollama": {"type": "openai", "base_url": "http://127.0.0.1:11434/v1", "api_key_env": ""},
    "lmstudio": {"type": "openai", "base_url": "http://127.0.0.1:1234/v1", "api_key_env": ""},
}


def fetch(url: str, headers: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def list_models(name: str, provider: dict[str, Any], timeout: int) -> tuple[list[str], str]:
    kind = provider.get("type", "openai")
    base = str(provider.get("base_url") or "").rstrip("/")
    env = provider.get("api_key_env") or ""
    key = os.environ.get(env, "") if env else ""
    if env and not key and "127.0.0.1" not in base and "localhost" not in base:
        return [], f"skipped: {env} is not set"
    if not base:
        return [], "skipped: no base_url"
    try:
        if kind == "anthropic":
            data = fetch(f"{base}/v1/models?limit=100", {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
            ids = [item.get("id", "") for item in data.get("data") or []]
        elif kind == "google":
            data = fetch(f"{base}/models?key={key}&pageSize=200", {"Content-Type": "application/json"}, timeout)
            ids = [
                str(item.get("name", "")).split("/")[-1]
                for item in data.get("models") or []
                if "generateContent" in (item.get("supportedGenerationMethods") or [])
            ]
        else:
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            data = fetch(f"{base}/models", headers, timeout)
            ids = [item.get("id", "") for item in data.get("data") or []]
            if not ids:  # some gateways return {models: [...]}
                ids = [str(item) for item in data.get("models") or []]
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:160]}"
    except Exception as exc:  # noqa: BLE001 - report, do not crash a survey
        return [], f"{type(exc).__name__}: {exc}"
    return sorted({i for i in ids if i}), ""


def load_config(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        return json.loads(raw)
    if tomllib is None:
        raise SystemExit("TOML needs Python 3.11+; use .json")
    return tomllib.loads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List live model ids per provider.")
    parser.add_argument("-c", "--config", default="", help="council config to read providers from")
    parser.add_argument("--only", default="", help="comma separated provider names")
    parser.add_argument("--filter", default="", help="only model ids containing this substring")
    parser.add_argument("--json", default="", help="write the survey to this file")
    parser.add_argument("--diff", default="", help="compare with a previous survey file")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)

    providers = dict(DEFAULT_PROVIDERS)
    if args.config:
        cfg = load_config(Path(args.config))
        merged = dict(providers)
        for name, value in (cfg.get("providers") or {}).items():
            entry = dict(merged.get(name, {}))
            entry.update(value)
            merged[name] = entry
        providers = merged

    wanted = [p.strip() for p in args.only.split(",") if p.strip()] or list(providers)
    survey: dict[str, Any] = {}
    failures = 0
    for name in wanted:
        provider = providers.get(name)
        if not provider:
            print(f"{name}: unknown provider (known: {', '.join(sorted(providers))})", file=sys.stderr)
            failures += 1
            continue
        if provider.get("type") == "mock":
            continue
        models, error = list_models(name, provider, args.timeout)
        if args.filter:
            models = [m for m in models if args.filter.lower() in m.lower()]
        survey[name] = {"models": models, "error": error}
        if error:
            print(f"{name}: {error}", file=sys.stderr)
            failures += 1
        else:
            print(f"{name} ({len(models)})")
            for model in models:
                print(f"  {model}")

    if args.diff and Path(args.diff).exists():
        old = json.loads(Path(args.diff).read_text(encoding="utf-8"))
        print("\ndiff against", args.diff)
        for name, entry in survey.items():
            before = set((old.get(name) or {}).get("models") or [])
            after = set(entry["models"])
            if not before and not after:
                continue
            print(f"  {name}: +{len(after - before)} -{len(before - after)}")
            for added in sorted(after - before)[:12]:
                print(f"    + {added}")
            for removed in sorted(before - after)[:12]:
                print(f"    - {removed}")

    if args.json:
        Path(args.json).write_text(json.dumps(survey, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 1 if failures and not survey else 0


if __name__ == "__main__":
    raise SystemExit(main())

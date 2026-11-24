#!/usr/bin/env python3
"""ai-council — a model-agnostic multi-AI council orchestrator.

One file, standard library only. Every model is called through the same
single-turn interface, so adding a provider means adding six lines, not a
framework.

    python scripts/council.py demo                 # offline, no keys, no network
    python scripts/council.py init                 # scaffold council.json
    python scripts/council.py run -c council.json --dry-run
    python scripts/council.py run -c council.json

Read references/protocol.md before changing the round logic: the value of the
council comes from *independence first, cross-examination second*, and the code
is only a faithful implementation of that order.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 and older
    tomllib = None  # type: ignore[assignment]

VERSION = "1.0.0"
DEFAULT_TIMEOUT = 180
DEFAULT_MAX_CALLS = 24
DEFAULT_MAX_CHARS = 600_000

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

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
    "vllm": {"type": "openai", "base_url": "http://127.0.0.1:8000/v1", "api_key_env": ""},
    "lmstudio": {"type": "openai", "base_url": "http://127.0.0.1:1234/v1", "api_key_env": ""},
    "mock": {"type": "mock", "base_url": "", "api_key_env": ""},
}

ROLE_BRIEFS = {
    "generalist": "See the whole problem. Balance upside, cost, and reversibility.",
    "specialist": "Go deep on one dimension; be the person who actually reads the spec.",
    "critic": "Attack. Find the false assumption, the missing case, the failure mode. Never build the plan.",
    "implementer": "Ask what it takes to ship: sequencing, dependencies, who does what, what breaks first.",
    "synthesizer": "Merge without inventing. Preserve every material disagreement verbatim.",
}

ROUND_PLANS = {
    "solo": ["propose", "converge"],
    "pair": ["propose", "critique", "converge"],
    "triad": ["propose", "critique", "revise", "converge"],
    "council": ["propose", "critique", "revise", "converge"],
    "court": ["propose", "critique", "revise", "redteam", "converge"],
}

ROUND_LABELS = {
    "propose": "propose",
    "critique": "critique",
    "revise": "revise",
    "redteam": "redteam",
    "converge": "converge",
}

# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def est_chars(text: str) -> int:
    return len(text or "")


def approx_tokens(text: str) -> int:
    """Rough token estimate: CJK ~1 token/char, latin ~1 token/4 chars."""
    text = text or ""
    cjk = len(CJK.findall(text))
    return int(cjk + (len(text) - cjk) / 4)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str, limit: int = 40) -> str:
    text = re.sub(r"[^\w\u3400-\u9fff-]+", "-", (text or "").strip().lower())
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return (text[:limit] or "council").strip("-")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float, bool)):
        return [value]
    return [value]


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def clamp01(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


LEVEL_LABELS_ZH = {"high": "高", "medium": "中", "low": "低"}


def localize_level(value: Any, language: str) -> str:
    text = as_text(value)
    if language.lower().startswith(("chinese", "simplified", "zh")):
        return LEVEL_LABELS_ZH.get(text.lower(), text)
    return text


def truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def extract_json(text: str) -> Any:
    """Pull the first balanced JSON object out of model prose.

    Handles fenced blocks, leading commentary, and braces inside strings.
    Returns None when nothing parseable is found.
    """
    if not text:
        return None
    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        candidates.append(fence.group(1))
    candidates.append(text)
    for chunk in candidates:
        start = chunk.find("{")
        while start != -1:
            depth, in_str, esc, end = 0, False, False, -1
            for i in range(start, len(chunk)):
                ch = chunk[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end != -1:
                raw = chunk[start : end + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    try:  # tolerate trailing commas
                        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
                    except json.JSONDecodeError:
                        pass
            start = chunk.find("{", start + 1)
    return None


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
]


class Redactor:
    def __init__(self, extra: Iterable[str] | None = None) -> None:
        self.extra = [s for s in (extra or []) if s and len(s) >= 8]

    def __call__(self, text: str) -> str:
        if not text:
            return ""
        out = text
        for pattern in SECRET_PATTERNS:
            out = pattern.sub("«redacted:key»", out)
        for secret in self.extra:
            out = out.replace(secret, "«redacted:env»")
        return out


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    pass


@dataclasses.dataclass
class Seat:
    id: str
    name: str
    role: str
    provider: str
    model: str
    brief: str = ""
    temperature: float = 0.7
    max_tokens: int = 0
    weight: float = 1.0

    @property
    def label(self) -> str:
        return f"{self.name} · {self.provider}/{self.model}"


@dataclasses.dataclass
class CouncilConfig:
    name: str
    task: str
    seats: list[Seat]
    providers: dict[str, dict[str, Any]]
    mode: str = "triad"
    plan: list[str] = dataclasses.field(default_factory=list)
    rounds: int = 0
    language: str = "Simplified Chinese"
    decision_rule: str = "supermajority"
    threshold: float = 0.66
    max_rounds: int = 4
    budget_calls: int = DEFAULT_MAX_CALLS
    budget_chars: int = DEFAULT_MAX_CHARS
    timeout: int = DEFAULT_TIMEOUT
    deliverable: str = "A decision with confidence, reasoning, risks and next actions."
    constraints: list[str] = dataclasses.field(default_factory=list)
    non_goals: list[str] = dataclasses.field(default_factory=list)
    synthesizer: str = ""
    synthesizer_seat: str = ""
    seed: int = 0
    dry_run: bool = False

    def seat(self, seat_id: str) -> Seat | None:
        for s in self.seats:
            if s.id == seat_id:
                return s
        return None


def read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    # utf-8-sig: Windows editors like to prepend a BOM, and json.loads chokes on it.
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: invalid JSON — {exc}") from exc
    if path.suffix.lower() in {".toml", ""}:
        if tomllib is None:
            raise ConfigError("TOML configs need Python 3.11+ (tomllib); use .json instead")
        try:
            return tomllib.loads(raw)
        except Exception as exc:  # tomllib.TOMLDecodeError
            raise ConfigError(f"{path}: invalid TOML — {exc}") from exc
    raise ConfigError(f"{path}: unsupported config extension {path.suffix!r} (use .json or .toml)")


def normalize_config(raw: dict[str, Any], *, base_dir: Path | None = None) -> CouncilConfig:
    council = raw.get("council") or {}
    if not isinstance(council, dict):
        raise ConfigError("`council` must be a table/object")
    task = str(council.get("task") or "").strip()
    if not task:
        raise ConfigError("`council.task` is required — state the question the council must decide")

    raw_seats = raw.get("seats") or []
    if not isinstance(raw_seats, list) or not raw_seats:
        raise ConfigError("`seats` must be a non-empty list")
    seats: list[Seat] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_seats, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"seats[{index}] must be an object")
        seat_id = str(item.get("id") or f"seat{index}").strip()
        if seat_id in seen:
            raise ConfigError(f"duplicate seat id: {seat_id}")
        seen.add(seat_id)
        role = str(item.get("role") or "generalist").strip()
        if role not in ROLE_BRIEFS:
            raise ConfigError(f"seat {seat_id}: unknown role {role!r} (choose from {sorted(ROLE_BRIEFS)})")
        provider = str(item.get("provider") or "openai").strip()
        model = str(item.get("model") or "").strip()
        if not model:
            raise ConfigError(f"seat {seat_id}: `model` is required")
        seats.append(
            Seat(
                id=seat_id,
                name=str(item.get("name") or seat_id),
                role=role,
                provider=provider,
                model=model,
                brief=str(item.get("brief") or ROLE_BRIEFS[role]),
                temperature=float(item.get("temperature", 0.7)),
                max_tokens=int(item.get("max_tokens", 0) or 0),
                weight=float(item.get("weight", 1.0)),
            )
        )

    providers = json.loads(json.dumps(DEFAULT_PROVIDERS))
    for key, value in (raw.get("providers") or {}).items():
        if not isinstance(value, dict):
            raise ConfigError(f"providers.{key} must be an object")
        merged = dict(providers.get(key, {}))
        merged.update(value)
        merged.setdefault("type", "openai")
        if merged["type"] not in {"openai", "anthropic", "google", "mock"}:
            raise ConfigError(f"providers.{key}: unknown type {merged['type']!r}")
        if merged["type"] != "mock" and not merged.get("base_url"):
            raise ConfigError(f"providers.{key}: `base_url` is required")
        providers[key] = merged

    for seat in seats:
        cfg_provider = providers.get(seat.provider)
        if cfg_provider is None:
            raise ConfigError(
                f"seat {seat.id}: provider {seat.provider!r} is unknown. "
                f"Known: {', '.join(sorted(providers))}. Add it under `providers`."
            )
        if cfg_provider.get("type") != "mock":
            env = cfg_provider.get("api_key_env") or ""
            if env and not env_is_set(env):
                # Not fatal: the seat degrades to `unavailable` with a clear message.
                pass

    mode = str(council.get("mode") or "triad").strip().lower()
    if mode not in ROUND_PLANS:
        raise ConfigError(f"unknown mode {mode!r} (choose from {sorted(ROUND_PLANS)})")
    plan = list(ROUND_PLANS[mode])
    rounds = int(council.get("rounds") or 0)
    if rounds:
        plan = trim_plan(plan, rounds)

    synth = str(raw.get("synthesizer") or council.get("synthesizer") or "").strip()
    if synth and not any(s.id == synth for s in seats):
        raise ConfigError(f"synthesizer {synth!r} is not a seat id")
    if not synth:
        auto = [s.id for s in seats if s.role == "synthesizer"]
        synth = auto[0] if auto else seats[0].id

    budget = council.get("budget") or {}
    language = str(council.get("language") or "Simplified Chinese")
    seed = int(os.environ.get("COUNCIL_SEED", council.get("seed", 0)) or 0)
    return CouncilConfig(
        name=str(council.get("name") or "council"),
        task=task,
        seats=seats,
        providers=providers,
        mode=mode,
        plan=plan,
        rounds=len(plan),
        language=language,
        decision_rule=str(council.get("decision_rule") or "supermajority"),
        threshold=float(council.get("threshold", 0.66)),
        max_rounds=int(council.get("max_rounds", 4)) or len(plan),
        budget_calls=int(budget.get("max_calls", DEFAULT_MAX_CALLS)),
        budget_chars=int(budget.get("max_chars", DEFAULT_MAX_CHARS)),
        timeout=int(council.get("timeout", DEFAULT_TIMEOUT)),
        deliverable=str(council.get("deliverable") or "A decision with confidence, reasoning, risks and next actions."),
        constraints=[as_text(x) for x in as_list(council.get("constraints"))],
        non_goals=[as_text(x) for x in as_list(council.get("non_goals"))],
        synthesizer=synth,
        seed=seed,
    )


def trim_plan(plan: Sequence[str], rounds: int) -> list[str]:
    """Keep the first and last round, drop middle rounds to fit `rounds`."""
    rounds = max(2, min(rounds, len(plan)))
    if rounds >= len(plan):
        return list(plan)
    keep = [plan[0]]
    middle = list(plan[1:-1])
    while len(keep) + 1 < rounds and middle:
        keep.append(middle.pop(0))
    keep.append(plan[-1])
    return keep


def env_is_set(name: str) -> bool:
    return bool(os.environ.get(name))


def load_dotenv(path: Path) -> list[str]:
    """Load KEY=VALUE pairs without overriding the real environment."""
    loaded: list[str] = []
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclasses.dataclass
class CallResult:
    text: str = ""
    ok: bool = False
    error: str = ""
    latency: float = 0.0
    tokens: int = 0
    model: str = ""
    provider: str = ""
    raw_meta: dict[str, Any] = dataclasses.field(default_factory=dict)


def http_json(
    url: str,
    payload: dict[str, Any] | None,
    headers: dict[str, str],
    *,
    timeout: int,
    method: str = "POST",
    attempts: int = 3,
) -> tuple[dict[str, Any] | None, str]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    last = ""
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw), ""
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:700]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code in RETRY_STATUS and attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None, last
        except urllib.error.URLError as exc:
            last = f"network error: {exc.reason}"
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None, last
        except (TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = f"transport error: {exc}"
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            return None, last
    return None, last or "unknown transport failure"


def provider_key(cfg_provider: dict[str, Any]) -> str:
    env = cfg_provider.get("api_key_env") or ""
    if env:
        return os.environ.get(env, "")
    return os.environ.get("OPENAI_API_KEY", "") if cfg_provider.get("type") == "openai" else ""


def openai_payload(seat: Seat, system: str, user: str) -> dict[str, Any]:
    return {
        "model": seat.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": seat.temperature,
        "max_tokens": max_tokens_for(seat),
    }


def max_tokens_for(seat: Seat) -> int:
    return seat.max_tokens or 2048


def call_openai(seat: Seat, cfg_provider: dict[str, Any], system: str, user: str, timeout: int) -> CallResult:
    base = str(cfg_provider["base_url"]).rstrip("/")
    url = f"{base}/chat/completions"
    key = provider_key(cfg_provider)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if seat.provider == "openrouter":
        # OpenRouter uses these for attribution only; replace with your own URL.
        headers["HTTP-Referer"] = str(cfg_provider.get("referer") or "https://github.com")
        headers["X-Title"] = "ai-council"

    payload = openai_payload(seat, system, user)
    started = time.time()
    data, err = http_json(url, payload, headers, timeout=timeout)

    # Reasoning-era models reject max_tokens / non-default temperature.
    for _ in range(2):
        if data is not None or not err:
            break
        lowered = err.lower()
        adjusted = False
        if "max_tokens" in lowered and "max_tokens" in payload:
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = max_tokens_for(seat)
            adjusted = True
        if "temperature" in lowered and "temperature" in payload and ("unsupported" in lowered or "not supported" in lowered):
            payload.pop("temperature", None)
            adjusted = True
        if not adjusted:
            break
        data, err = http_json(url, payload, headers, timeout=timeout)

    latency = time.time() - started
    if data is None:
        return CallResult(error=err, latency=latency, model=seat.model, provider=seat.provider)

    choices = data.get("choices") or []
    if not choices:
        return CallResult(error=f"malformed response: {json.dumps(data)[:300]}", latency=latency, model=seat.model, provider=seat.provider)
    message = choices[0].get("message") or {}
    text = message.get("content")
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    text = (text or "").strip()
    reasoning = as_text(message.get("reasoning_content") or message.get("reasoning"))
    usage = data.get("usage") or {}
    tokens = int(usage.get("total_tokens") or 0)
    if not text:
        finish = choices[0].get("finish_reason")
        detail = f"finish_reason={finish}"
        if reasoning:
            text = reasoning[-1500:]
            detail += " (fell back to reasoning_content)"
        return CallResult(
            text=text,
            ok=bool(text),
            error="" if text else f"empty content ({detail})",
            latency=latency,
            tokens=tokens,
            model=str(data.get("model") or seat.model),
            provider=seat.provider,
        )
    return CallResult(
        text=text,
        ok=True,
        latency=latency,
        tokens=tokens or approx_tokens(system) + approx_tokens(user) + approx_tokens(text),
        model=str(data.get("model") or seat.model),
        provider=seat.provider,
    )


def call_anthropic(seat: Seat, cfg_provider: dict[str, Any], system: str, user: str, timeout: int) -> CallResult:
    base = str(cfg_provider["base_url"]).rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    url = f"{base}/v1/messages"
    key = provider_key(cfg_provider)
    if not key:
        return CallResult(error="missing credentials: set ANTHROPIC_API_KEY", model=seat.model, provider=seat.provider)
    headers = {
        "Content-Type": "application/json",
        "x-api-key": key,
        "anthropic-version": str(cfg_provider.get("anthropic_version") or "2023-06-01"),
    }
    payload = {
        "model": seat.model,
        "max_tokens": max_tokens_for(seat),
        "temperature": seat.temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    started = time.time()
    data, err = http_json(url, payload, headers, timeout=timeout)
    latency = time.time() - started
    if data is None:
        return CallResult(error=err, latency=latency, model=seat.model, provider=seat.provider)
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text").strip()
    usage = data.get("usage") or {}
    tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    if not text:
        return CallResult(
            error=f"empty content (stop_reason={data.get('stop_reason')})",
            latency=latency,
            tokens=tokens,
            model=seat.model,
            provider=seat.provider,
        )
    return CallResult(text=text, ok=True, latency=latency, tokens=tokens, model=str(data.get("model") or seat.model), provider=seat.provider)


def call_google(seat: Seat, cfg_provider: dict[str, Any], system: str, user: str, timeout: int) -> CallResult:
    base = str(cfg_provider["base_url"]).rstrip("/")
    key = provider_key(cfg_provider)
    if not key:
        return CallResult(error="missing credentials: set GEMINI_API_KEY", model=seat.model, provider=seat.provider)
    url = f"{base}/models/{seat.model}:generateContent?key={key}"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": seat.temperature, "maxOutputTokens": max_tokens_for(seat)},
    }
    started = time.time()
    data, err = http_json(url, payload, {"Content-Type": "application/json"}, timeout=timeout)
    latency = time.time() - started
    if data is None:
        return CallResult(error=err, latency=latency, model=seat.model, provider=seat.provider)
    if data.get("promptFeedback", {}).get("blockReason"):
        return CallResult(error=f"blocked by safety: {data['promptFeedback']['blockReason']}", latency=latency, model=seat.model, provider=seat.provider)
    candidates = data.get("candidates") or []
    if not candidates:
        return CallResult(error=f"no candidates: {json.dumps(data)[:300]}", latency=latency, model=seat.model, provider=seat.provider)
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    meta = data.get("usageMetadata") or {}
    tokens = int(meta.get("totalTokenCount") or 0)
    if not text:
        return CallResult(error=f"empty content (finishReason={candidates[0].get('finishReason')})", latency=latency, tokens=tokens, model=seat.model, provider=seat.provider)
    return CallResult(text=text, ok=True, latency=latency, tokens=tokens, model=seat.model, provider=seat.provider)


# --- offline mock -----------------------------------------------------------

MOCK_ANGLES = {
    "generalist": "整体收益与可逆性",
    "specialist": "接口语义与边界条件",
    "critic": "最坏情况与隐含假设",
    "implementer": "迁移顺序与人力",
    "synthesizer": "收敛条件与证据强度",
}

MOCK_THESIS = [
    "分两阶段推进，先做只读影子流量再切写流量",
    "不要整体迁移，只迁移高频且契约稳定的少数接口",
    "先建双栈与契约测试，再决定是否继续",
    "维持现状，把预算投到可观测性和限流上",
]


def mock_reply(seat: Seat, system: str, user: str, round_name: str, cfg: CouncilConfig) -> str:
    seed = int(hashlib.sha256(f"{cfg.seed}|{cfg.name}|{seat.id}|{round_name}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    angle = MOCK_ANGLES.get(seat.role, "问题结构")
    # A seat's thesis must not change between propose and revise, or the demo
    # transcript reads as noise instead of an argument.
    thesis_seed = int(hashlib.sha256(f"{cfg.seed}|{seat.id}".encode()).hexdigest()[:8], 16)
    thesis = MOCK_THESIS[thesis_seed % len(MOCK_THESIS)]
    conf = round(0.45 + rng.random() * 0.4, 2)
    others = sorted({m for m in re.findall(r"SET-[A-Z0-9]+", user)}) or ["SET-A"]
    incoming = re.findall(r'"target_claim":\s*"(C[0-9]{1,2})"', user)
    targets = sorted(set(re.findall(r"\b(C[0-9]{1,2})\b", user)))
    target = incoming[0] if incoming else (targets[seed % len(targets)] if targets else "C1")

    if round_name == "propose":
        payload = {
            "seat": seat.id,
            "round": "propose",
            "claims": [
                {
                    "id": "C1",
                    "text": f"（mock）从{angle}看，{thesis}。",
                    "type": "inference",
                    "confidence": conf,
                    "evidence": ["none — offline mock"],
                    "impact": "high",
                },
                {
                    "id": "C2",
                    "text": f"（mock）需要在决策前补齐：{angle}相关的量化基线。",
                    "type": "opinion",
                    "confidence": round(conf - 0.15, 2),
                    "evidence": ["none — offline mock"],
                    "impact": "medium",
                },
            ],
            "assumptions": [f"假设 {seat.name} 对交付节奏的判断成立"],
            "open_questions": [f"{angle}的基线数据从哪来？"],
            "stance": thesis,
        }
    elif round_name == "critique":
        payload = {
            "seat": seat.id,
            "round": "critique",
            "critiques": [
                {
                    "target_set": others[0],
                    "target_claim": target,
                    "kind": "logic",
                    "severity": "high",
                    "problem": "（mock）结论从基线跳到收益，中间缺少一层失败率假设。",
                    "fix": "先给出现有失败率与迁移后预期失败率，再谈收益。",
                },
                {
                    "target_set": others[-1],
                    "target_claim": target,
                    "kind": "scope",
                    "severity": "medium",
                    "problem": "（mock）把一次组织决策当成纯技术选型，忽略了冻结窗口。",
                    "fix": "把冻结窗口与回滚方案写进同一张表。",
                },
            ],
            "strongest_set": others[0],
            "why": "（mock）它至少给出了可证伪的判据。",
            "own_claim_changes": ["C2 的置信度下调，等待基线数据"],
        }
    elif round_name == "revise":
        payload = {
            "seat": seat.id,
            "round": "revise",
            "claims": [
                {
                    "id": "C1",
                    "text": f"（mock·修订）{thesis}，但以“补齐基线”为前提条件。",
                    "type": "inference",
                    "confidence": round(max(0.3, conf - 0.1), 2),
                    "evidence": ["accepted critique on failure-rate assumption"],
                    "impact": "high",
                }
            ],
            "changed": [{"claim_id": "C1", "change": "weakened", "because": f"接受了针对 {target} 的逻辑批评"}],
            "stance": f"有条件支持：{thesis}",
        }
    elif round_name == "redteam":
        payload = {
            "seat": seat.id,
            "round": "redteam",
            "critiques": [
                {
                    "target_set": "consensus",
                    "target_claim": target,
                    "kind": "risk",
                    "severity": "high",
                    "problem": "（mock）共识建立在“团队能同时维护双栈”的未验证前提上。",
                    "fix": "给出双栈维护的人力上限，超过就只迁移一条链路。",
                }
            ],
            "strongest_set": "consensus",
            "why": "（mock）红队只负责找致命点。",
            "own_claim_changes": [],
        }
    else:  # converge
        payload = {
            "decision": {
                "statement": "（mock）有条件推进：先补失败率基线，再做只读影子流量，够格才切写流量；否则维持现状。",
                "confidence": 0.62,
                "rule": cfg.decision_rule,
                "rationale": "多数席位支持“有条件推进”，反对意见集中在双栈期人力与冻结窗口。",
            },
            "consensus": [
                {"text": "（mock）先做影子流量验证，再决定写流量迁移", "confidence": 0.7, "supported_by": [s.id for s in cfg.seats][:3], "claim_ids": ["C1"]},
            ],
            "contested": [
                {
                    "text": "（mock）是否值得为 30% 的延迟收益承担双栈维护成本",
                    "for": [s.id for s in cfg.seats if s.role in {"generalist", "implementer"}][:2],
                    "against": [s.id for s in cfg.seats if s.role == "critic"][:1],
                    "crux": "（mock）下一季度能否拿到两名后端人力",
                }
            ],
            "dissent": [
                {"seat": next((s.id for s in cfg.seats if s.role == "critic"), cfg.seats[0].id), "text": "（mock）共识高估了收益、低估了双栈期的事故半径。"}
            ],
            "risks": [
                {"risk": "（mock）双栈期契约漂移", "likelihood": "medium", "impact": "high", "mitigation": "契约测试进 CI，失败即阻断发布"},
            ],
            "actions": [{"action": "（mock）用两周补齐失败率基线", "owner": "接口负责人", "when": "决策前"}],
            "open_questions": ["（mock）冻结窗口的准确日期？"],
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def call_mock(seat: Seat, cfg: CouncilConfig, system: str, user: str, round_name: str) -> CallResult:
    started = time.time()
    text = mock_reply(seat, system, user, round_name, cfg)
    time.sleep(0.02)
    return CallResult(
        text=text,
        ok=True,
        latency=time.time() - started,
        tokens=approx_tokens(system) + approx_tokens(user) + approx_tokens(text),
        model=f"mock/{seat.model}",
        provider="mock",
    )


def call_model(
    seat: Seat,
    cfg: CouncilConfig,
    system: str,
    user: str,
    *,
    round_name: str,
) -> CallResult:
    cfg_provider = cfg.providers.get(seat.provider) or {}
    kind = cfg_provider.get("type", "openai")
    try:
        if kind == "mock":
            return call_mock(seat, cfg, system, user, round_name)
        if kind == "anthropic":
            return call_anthropic(seat, cfg_provider, system, user, cfg.timeout)
        if kind == "google":
            return call_google(seat, cfg_provider, system, user, cfg.timeout)
        return call_openai(seat, cfg_provider, system, user, cfg.timeout)
    except Exception as exc:  # never let one seat kill the council
        return CallResult(error=f"{type(exc).__name__}: {exc}", model=seat.model, provider=seat.provider)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

JSON_RULES = (
    "Reply with exactly one JSON object and nothing else: no prose, no markdown fences.\n"
    "Keep strings factual and short. Never invent a source: use \"none\" and say so."
)


def task_frame(cfg: CouncilConfig) -> str:
    lines = [
        "## Task",
        cfg.task.strip(),
        "",
        f"## Deliverable\n{cfg.deliverable.strip()}",
        f"## Decision rule\n{cfg.decision_rule} (threshold {cfg.threshold})",
    ]
    if cfg.constraints:
        lines += ["## Constraints"] + [f"- {c}" for c in cfg.constraints]
    if cfg.non_goals:
        lines += ["## Non-goals"] + [f"- {n}" for n in cfg.non_goals]
    return "\n".join(lines)


def seat_system(seat: Seat, cfg: CouncilConfig) -> str:
    return "\n".join(
        [
            f'You are "{seat.name}", seat `{seat.id}` in a council of independent AI models.',
            f"Role: {seat.role}. Perspective: {seat.brief}",
            "",
            "Council rules (non-negotiable):",
            "1. Think independently. Other seats have not seen your answer and may be wrong.",
            "2. Label every claim: fact (checkable), inference (reasoning), opinion (judgement).",
            "3. Attach a confidence in [0,1] to every claim. Never exceed the evidence.",
            "4. Be concrete: name mechanisms, numbers, failure modes, owners.",
            "5. No flattery, no preamble, no restating the task.",
            "6. Missing information goes to open_questions — do not fill gaps with invention.",
            f"7. Write all human-readable text in {cfg.language}.",
            "",
            JSON_RULES,
        ]
    )


SCHEMAS = {
    "propose": """{
  "seat": "<seat id>",
  "round": "propose",
  "claims": [
    {"id": "C1", "text": "<one falsifiable sentence>", "type": "fact|inference|opinion",
     "confidence": 0.0, "evidence": ["<source or none>"], "impact": "high|medium|low"}
  ],
  "assumptions": ["..."],
  "open_questions": ["..."],
  "stance": "<your one-line position>"
}""",
    "critique": """{
  "seat": "<seat id>",
  "round": "critique",
  "critiques": [
    {"target_set": "SET-A", "target_claim": "C1", "kind": "factual|logic|scope|risk|missing",
     "severity": "high|medium|low", "problem": "<what is wrong, specifically>",
     "fix": "<the smallest change that fixes it>"}
  ],
  "strongest_set": "SET-B",
  "why": "<why that set survived your attack>",
  "own_claim_changes": ["<what you now doubt in your own claims>"]
}""",
    "revise": """{
  "seat": "<seat id>",
  "round": "revise",
  "claims": [
    {"id": "C1", "text": "<revised claim>", "type": "fact|inference|opinion",
     "confidence": 0.0, "evidence": ["<source, or the critique you accepted>"], "impact": "high|medium|low"}
  ],
  "changed": [{"claim_id": "C1", "change": "strengthened|weakened|dropped|new", "because": "<which critique>"}],
  "stance": "<your one-line position after revision>"
}""",
    "redteam": """{
  "seat": "<seat id>",
  "round": "redteam",
  "critiques": [
    {"target_set": "consensus", "target_claim": "C1", "kind": "risk",
     "severity": "high|medium|low", "problem": "<the single most likely fatal flaw>",
     "fix": "<cheapest mitigation>"}
  ],
  "strongest_set": "consensus",
  "why": "<why the council is overconfident>",
  "own_claim_changes": []
}""",
    "converge": """{
  "decision": {"statement": "<the decision, one sentence>", "confidence": 0.0,
               "rule": "<decision rule actually applied>", "rationale": "<2-3 sentences>"},
  "consensus": [{"text": "...", "confidence": 0.0, "supported_by": ["seat-id"], "claim_ids": ["C1"]}],
  "contested": [{"text": "...", "for": ["seat-id"], "against": ["seat-id"], "crux": "<the single disagreement that decides it>"}],
  "dissent": [{"seat": "seat-id", "text": "<strongest minority argument, verbatim>"}],
  "risks": [{"risk": "...", "likelihood": "high|medium|low", "impact": "...", "mitigation": "..."}],
  "actions": [{"action": "...", "owner": "...", "when": "..."}],
  "open_questions": ["..."]
}""",
}


def user_propose(cfg: CouncilConfig, seat: Seat, *, solo: bool = False) -> str:
    extra = ""
    if solo:
        extra = (
            "\n\nSolo mode: before answering, hold three internal views in order — "
            "(a) the optimistic builder, (b) the sceptical reviewer, (c) the operator who has to run it. "
            "Put their disagreement in `assumptions` and `open_questions`, never in a merged mush."
        )
    return "\n\n".join(
        [
            task_frame(cfg),
            f"## Your turn: propose ({cfg.language})",
            "Produce 2-5 claims that a decision-maker could act on or falsify. "
            "Prefer one sharp claim over five vague ones." + extra,
            "## JSON schema",
            SCHEMAS["propose"],
        ]
    )


def user_critique(cfg: CouncilConfig, seat: Seat, own: dict[str, Any], labeled: dict[str, dict[str, Any]]) -> str:
    blocks = []
    for label, payload in labeled.items():
        blocks.append(f"### {label}\n{truncate(json.dumps(payload, ensure_ascii=False), 6000)}")
    return "\n\n".join(
        [
            task_frame(cfg),
            f"## Your own proposal (do not re-submit it)\n{truncate(json.dumps(own, ensure_ascii=False), 4000)}",
            "## Other seats' proposals, anonymised\n" + "\n\n".join(blocks),
            "## Your turn: critique",
            "Rules of cross-examination:",
            "- Attack claims, not the author. Set labels are anonymised on purpose.",
            "- Your own set is deliberately absent — do not review yourself.",
            "- Every critique names a specific defect and a concrete fix.",
            "- At least one critique per set you review. If a set is sound, still state what you tried "
            "to break and why it held (`kind: missing` is not a code for \"nothing\").",
            "- Do not repeat your own proposal. Do not agree for the sake of agreement.",
            "- If the sets converge on the same mistake, say so with `kind: missing` and name the shared blind spot.",
            "## JSON schema",
            SCHEMAS["critique"],
        ]
    )


def user_revise(cfg: CouncilConfig, seat: Seat, own: dict[str, Any], incoming: list[dict[str, Any]]) -> str:
    rendered = "\n\n".join(f"### Critique {i + 1}\n{truncate(json.dumps(c, ensure_ascii=False), 3500)}" for i, c in enumerate(incoming)) or "_(none — no other seat produced a critique)_"
    return "\n\n".join(
        [
            task_frame(cfg),
            f"## Your previous proposal\n{truncate(json.dumps(own, ensure_ascii=False), 4000)}",
            "## Critiques addressed to your proposal\n" + rendered,
            "## Your turn: revise",
            "Change only what the critiques justify. Strengthening requires new evidence; "
            "dropping without reason is cowardice. Record every change in `changed`.",
            "## JSON schema",
            SCHEMAS["revise"],
        ]
    )


def user_redteam(cfg: CouncilConfig, seat: Seat, consensus: str) -> str:
    return "\n\n".join(
        [
            task_frame(cfg),
            f"## Emerging consensus\n{truncate(consensus, 8000)}",
            "## Your turn: red team",
            "You are the last line of defence. Find the assumption that, if false, makes the whole "
            "consensus worthless. One high-severity critique beats five cosmetic ones.",
            "## JSON schema",
            SCHEMAS["redteam"],
        ]
    )


def user_converge(cfg: CouncilConfig, seat: Seat, transcript: str, dissent_hint: str) -> str:
    return "\n\n".join(
        [
            task_frame(cfg),
            "## Full record\n" + truncate(transcript, 60000),
            f"## Known minority view\n{dissent_hint or '_(recorded above)_'}",
            "## Your turn: converge",
            "Synthesis rules:",
            "- You may not invent a claim. Everything must trace to a seat and a round.",
            "- Confidence cannot exceed the strongest evidence in the record.",
            "- Preserve the sharpest minority argument verbatim in `dissent`; a lost vote is not a deleted argument.",
            "- If the record cannot support any decision, say `insufficient evidence` and list what would decide it.",
            f"- Apply decision rule `{cfg.decision_rule}` (threshold {cfg.threshold}) and name it in `rationale`.",
            "## JSON schema",
            SCHEMAS["converge"],
        ]
    )


# ---------------------------------------------------------------------------
# Council run
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RoundRecord:
    name: str
    label: str
    seats_ok: list[str] = dataclasses.field(default_factory=list)
    seats_failed: dict[str, str] = dataclasses.field(default_factory=dict)
    duration: float = 0.0
    skipped: str = ""


class Council:
    def __init__(self, cfg: CouncilConfig, *, redact: Redactor | None = None, log: Callable[[str], None] | None = None) -> None:
        self.cfg = cfg
        self.redact = redact or Redactor()
        self.log = log or (lambda message: print(message, flush=True))
        self.calls: list[dict[str, Any]] = []
        self.records: list[RoundRecord] = []
        self.claims: dict[str, dict[str, Any]] = {}
        self.critiques: dict[str, list[dict[str, Any]]] = {}
        self.revisions: dict[str, dict[str, Any]] = {}
        self.labels: dict[str, str] = {}
        self.used_chars = 0
        self.calls_used = 0
        self.budget_exhausted = False
        self.failures: list[str] = []

    # -- budget ------------------------------------------------------------
    def _can_call(self, *, reserve: int = 0) -> bool:
        # `reserve` keeps the convergence call funded: the answer is worth more
        # than one more opinion. The flag is sticky so the minutes can say so.
        if self.calls_used >= max(0, self.cfg.budget_calls - reserve):
            self.budget_exhausted = True
            return False
        if self.used_chars + 2000 > self.cfg.budget_chars:
            self.budget_exhausted = True
            return False
        return True

    # -- seat selection ----------------------------------------------------
    def seats_for(self, round_name: str) -> list[Seat]:
        if round_name == "converge":
            synth = self.cfg.seat(self.cfg.synthesizer)
            return [synth] if synth else self.cfg.seats[:1]
        if round_name == "propose":
            seats = [s for s in self.cfg.seats if s.role != "synthesizer"]
            return seats or self.cfg.seats[:1]
        if round_name == "redteam":
            critics = [s for s in self.cfg.seats if s.role == "critic"]
            if critics:
                return critics[:1]
            specialists = [s for s in self.cfg.seats if s.role == "specialist"]
            return (specialists or self.cfg.seats[-1:])[:1]
        seats = [s for s in self.cfg.seats if s.role != "synthesizer"]
        return seats or self.cfg.seats[:1]

    # -- one round ---------------------------------------------------------
    def _dispatch(self, round_name: str, seats: list[Seat], build: Callable[[Seat], tuple[str, str]]) -> list[tuple[Seat, CallResult, Any]]:
        results: list[tuple[Seat, CallResult, Any]] = []
        started = time.time()
        record = RoundRecord(name=round_name, label=ROUND_LABELS.get(round_name, round_name))
        reserve = 1 if "converge" in self.cfg.plan and round_name != "converge" else 0

        # Budget is charged when a call is *scheduled*, not when it returns, so
        # the accounting does not depend on which thread finishes first.
        active: list[tuple[Seat, str, str]] = []
        for seat in seats:
            if not self._can_call(reserve=reserve):
                record.skipped = "budget exhausted before this round finished"
                break
            system, user = build(seat)
            self.calls_used += 1
            self.used_chars += est_chars(system) + est_chars(user)
            active.append((seat, system, user))
        if not active:
            record.duration = 0.0
            self.records.append(record)
            return results

        def work(item: tuple[Seat, str, str]) -> tuple[Seat, CallResult, Any]:
            seat, system, user = item
            result = call_model(seat, self.cfg, system, user, round_name=round_name)
            self.used_chars += est_chars(result.text)
            parsed = None
            if result.ok:
                parsed = extract_json(result.text)
                if parsed is None:
                    self.log(f"  ! {seat.id}: JSON parse failed, keeping raw text")
            return seat, result, parsed

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(active), 8)) as pool:
            futures = {pool.submit(work, item): item[0] for item in active}
            for future in concurrent.futures.as_completed(futures):
                seat = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # pragma: no cover - defensive
                    results.append((seat, CallResult(error=f"{type(exc).__name__}: {exc}"), None))

        for seat, result, _parsed in results:
            entry = {
                "round": round_name,
                "seat": seat.id,
                "model": result.model or seat.model,
                "provider": result.provider or seat.provider,
                "latency_s": round(result.latency, 2),
                "tokens": result.tokens,
                "ok": result.ok,
                "error": self.redact(result.error),
            }
            self.calls.append(entry)
            if result.ok:
                record.seats_ok.append(seat.id)
            else:
                record.seats_failed[seat.id] = result.error or "unknown error"
                self.failures.append(f"{round_name}/{seat.id}: {result.error}")
                self.log(f"  ! {seat.id} unavailable — {result.error[:120]}")
        # deterministic order for transcripts
        order = {seat.id: i for i, seat in enumerate(self.cfg.seats)}
        results.sort(key=lambda item: order.get(item[0].id, 99))
        record.duration = round(time.time() - started, 2)
        self.records.append(record)
        return results

    # -- rounds ------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        cfg = self.cfg
        self._assign_labels()
        # Each block is kept as (round, seat) so the transcript can show a seat
        # once per round instead of reusing its first appearance.
        transcript_blocks: list[dict[str, Any]] = []
        for round_name in cfg.plan:
            seats = self.seats_for(round_name)
            self.log(f"\n▶ round {round_name} · {len(seats)} seat(s)")
            if round_name == "propose":
                results = self._dispatch(round_name, seats, lambda seat: (seat_system(seat, cfg), user_propose(cfg, seat, solo=cfg.mode == "solo")))
                for seat, result, parsed in results:
                    if not result.ok:
                        continue
                    payload = parsed if isinstance(parsed, dict) else {"claims": [{"id": "C1", "text": result.text}], "raw": True}
                    payload.setdefault("claims", [])
                    self.claims[seat.id] = {"seat": seat, "payload": payload, "round": round_name}
                    transcript_blocks.append({"round": round_name, "seat": seat.id, "markdown": self._render_claims(seat, payload, round_name, result)})
            elif round_name == "critique":
                results = self._dispatch(
                    round_name,
                    seats,
                    lambda seat: (
                        seat_system(seat, cfg),
                        user_critique(
                            cfg,
                            seat,
                            self.claims.get(seat.id, {}).get("payload", {}),
                            self._anonymised_sets(exclude=seat.id),
                        ),
                    ),
                )
                for seat, result, parsed in results:
                    if not result.ok:
                        continue
                    payload = parsed if isinstance(parsed, dict) else {"critiques": [], "raw": result.text}
                    self.critiques[seat.id] = as_list(payload.get("critiques"))
                    transcript_blocks.append({"round": round_name, "seat": seat.id, "markdown": self._render_critique(seat, payload, result)})
            elif round_name == "revise":
                results = self._dispatch(
                    round_name,
                    seats,
                    lambda seat: (
                        seat_system(seat, cfg),
                        user_revise(cfg, seat, self.claims.get(seat.id, {}).get("payload", {}), self._incoming(seat)),
                    ),
                )
                for seat, result, parsed in results:
                    if not result.ok:
                        continue
                    payload = parsed if isinstance(parsed, dict) else {"claims": [], "raw": result.text}
                    self.revisions[seat.id] = payload
                    if payload.get("claims"):
                        self.claims[seat.id] = {"seat": seat, "payload": payload, "round": round_name}
                    transcript_blocks.append({"round": round_name, "seat": seat.id, "markdown": self._render_revision(seat, payload, result)})
            elif round_name == "redteam":
                consensus = self._consensus_digest()
                results = self._dispatch(
                    round_name,
                    seats,
                    lambda seat: (seat_system(seat, cfg), user_redteam(cfg, seat, consensus)),
                )
                for seat, result, parsed in results:
                    if not result.ok:
                        continue
                    payload = parsed if isinstance(parsed, dict) else {"critiques": [], "raw": result.text}
                    self.critiques.setdefault(seat.id, []).extend(as_list(payload.get("critiques")))
                    transcript_blocks.append({"round": round_name, "seat": seat.id, "markdown": self._render_critique(seat, payload, result)})
            else:  # converge
                synthesizer = seats[0]
                record_text = "\n\n".join(block["markdown"] for block in transcript_blocks)
                hint = self._dissent_hint()
                results = self._dispatch(
                    round_name,
                    seats,
                    lambda seat: (seat_system(seat, cfg), user_converge(cfg, seat, record_text, hint)),
                )
                minutes_payload = None
                for seat, result, parsed in results:
                    if result.ok and isinstance(parsed, dict):
                        minutes_payload = parsed
                if minutes_payload is None:
                    minutes_payload = self.fallback_minutes(reason="no synthesis seat available")
                    self.log("  ! synthesis unavailable — deterministic merge used")
                if isinstance(minutes_payload, dict) and results:
                    decision = minutes_payload.get("decision") if isinstance(minutes_payload.get("decision"), dict) else {}
                    synth_seat = results[0][0]
                    transcript_blocks.append(
                        {
                            "round": round_name,
                            "seat": synth_seat.id,
                            "markdown": f"#### {synth_seat.name} `{synth_seat.id}` · 综合\n**结论** "
                            + (as_text(decision.get("statement")) or "(未产出结论，已回退为确定性合并)"),
                        }
                    )

        return self.build_minutes(minutes_payload if cfg.plan[-1] == "converge" else None, transcript_blocks)

    # -- helpers -----------------------------------------------------------
    def _assign_labels(self) -> None:
        rng = random.Random(self.cfg.seed or 20260101)
        ids = [s.id for s in self.cfg.seats]
        rng.shuffle(ids)
        for index, seat_id in enumerate(ids):
            self.labels[seat_id] = f"SET-{chr(ord('A') + index)}"

    def _anonymised_sets(self, exclude: str | None = None) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for seat_id, entry in self.claims.items():
            if seat_id == exclude:
                continue
            label = self.labels.get(seat_id, "SET-X")
            out[label] = entry["payload"]
        return dict(sorted(out.items()))

    def _incoming(self, seat: Seat) -> list[dict[str, Any]]:
        """Critiques aimed at this seat's claim ids, across all critics."""
        mine = {c.get("id") for c in as_list(self.claims.get(seat.id, {}).get("payload", {}).get("claims")) if isinstance(c, dict)}
        label = self.labels.get(seat.id)
        incoming: list[dict[str, Any]] = []
        for critic_id, critiques in self.critiques.items():
            for item in critiques:
                if not isinstance(item, dict):
                    continue
                target_claim = as_text(item.get("target_claim"))
                target_set = as_text(item.get("target_set"))
                if target_claim in mine and (target_set in {label, "consensus", ""} or target_set.startswith(label or "~")):
                    incoming.append({"from": self.labels.get(critic_id, "SET-X"), **item})
        return incoming

    def _consensus_digest(self) -> str:
        lines = []
        for seat_id, entry in self.claims.items():
            payload = entry["payload"]
            stance = as_text(payload.get("stance"))
            claims = [as_text(c.get("text")) for c in as_list(payload.get("claims")) if isinstance(c, dict)]
            lines.append(f"- {seat_id}: {stance or claims[0] if claims else ''}")
        return "\n".join(lines)

    def _dissent_hint(self) -> str:
        hits = []
        for seat_id, critiques in self.critiques.items():
            for item in critiques:
                if isinstance(item, dict) and as_text(item.get("severity")).lower() == "high":
                    hits.append(f"- {seat_id}: {as_text(item.get('problem'))[:300]}")
        return "\n".join(hits[:5])

    def fallback_minutes(self, *, reason: str) -> dict[str, Any]:
        consensus: list[dict[str, Any]] = []
        dissent: list[dict[str, Any]] = []
        for seat_id, entry in self.claims.items():
            seat = entry["seat"]
            for claim in as_list(entry["payload"].get("claims")):
                if not isinstance(claim, dict):
                    continue
                text = as_text(claim.get("text"))
                if not text:
                    continue
                confidence = clamp01(claim.get("confidence"), 0.5)
                item = {"text": text, "confidence": confidence, "supported_by": [seat_id], "claim_ids": [as_text(claim.get("id"))]}
                (consensus if confidence >= 0.6 else dissent).append(item if confidence >= 0.6 else {"seat": seat_id, "text": text})
        return {
            "decision": {
                "statement": f"Auto-merged record ({reason}); a human must decide.",
                "confidence": 0.0,
                "rule": "deterministic merge",
                "rationale": "No synthesis seat produced a convergent answer, so claims were merged by confidence.",
            },
            "consensus": consensus,
            "contested": [],
            "dissent": dissent,
            "risks": [],
            "actions": [],
            "open_questions": ["Run again with a reachable synthesizer seat."],
        }

    # -- rendering ---------------------------------------------------------
    def _render_claims(self, seat: Seat, payload: dict[str, Any], round_name: str, result: CallResult) -> str:
        claims = [c for c in as_list(payload.get("claims")) if isinstance(c, dict)]
        lines = [f"#### {seat.name} `{seat.id}` · {result.model} · {result.latency:.1f}s"]
        stance = as_text(payload.get("stance"))
        if stance:
            lines.append(f"**立场** {stance}")
        for claim in claims:
            text = as_text(claim.get("text"))
            if not text:
                continue
            meta = " · ".join(
                x
                for x in [
                    as_text(claim.get("id")),
                    as_text(claim.get("type")),
                    f"置信 {clamp01(claim.get('confidence'), 0.5):.2f}",
                    localize_level(claim.get("impact"), self.cfg.language),
                ]
                if x
            )
            lines.append(f"- **{meta}** — {text}")
        if payload.get("raw"):
            lines.append(f"> {truncate(as_text(payload.get('raw')), 1200)}")
        for key, label in (("assumptions", "假设"), ("open_questions", "待补信息")):
            values = [as_text(v) for v in as_list(payload.get(key)) if as_text(v)]
            if values:
                lines.append(f"*{label}*: " + "; ".join(values))
        return "\n".join(lines).replace("\n\n", "\n")

    def _render_critique(self, seat: Seat, payload: dict[str, Any], result: CallResult) -> str:
        lines = [f"#### {seat.name} `{seat.id}` · {result.model} · {result.latency:.1f}s"]
        items = [c for c in as_list(payload.get("critiques")) if isinstance(c, dict)]
        for item in items:
            severity = as_text(item.get("severity")).upper() or "?"
            target = f"{as_text(item.get('target_set'))}/{as_text(item.get('target_claim'))}"
            lines.append(f"- **[{severity}]** `{target}` · {as_text(item.get('kind'))} — {as_text(item.get('problem'))}")
            fix = as_text(item.get("fix"))
            if fix:
                lines.append(f"  - 修法：{fix}")
        if not items:
            lines.append("- (无有效批评输出，已记录为失败)")
        strongest = as_text(payload.get("strongest_set"))
        why = as_text(payload.get("why"))
        if strongest or why:
            lines.append(f"*最稳的一组*: {strongest or '—'} — {why}")
        return "\n".join(lines)

    def _render_revision(self, seat: Seat, payload: dict[str, Any], result: CallResult) -> str:
        lines = [f"#### {seat.name} `{seat.id}` · {result.model} · {result.latency:.1f}s"]
        stance = as_text(payload.get("stance"))
        if stance:
            lines.append(f"**修订后立场** {stance}")
        for claim in as_list(payload.get("claims")):
            if isinstance(claim, dict):
                lines.append(f"- {as_text(claim.get('id'))} — {as_text(claim.get('text'))} (置信 {clamp01(claim.get('confidence'), 0.5):.2f})")
        for change in as_list(payload.get("changed")):
            if isinstance(change, dict):
                lines.append(f"  - 变更 `{as_text(change.get('claim_id'))}`: {as_text(change.get('change'))} — {as_text(change.get('because'))}")
        return "\n".join(lines)

    # -- minutes -----------------------------------------------------------
    def build_minutes(self, synthesised: dict[str, Any] | None, transcript_blocks: list[dict[str, Any]]) -> dict[str, Any]:
        cfg = self.cfg
        payload = synthesised or self.fallback_minutes(reason="synthesis failed")
        decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
        minutes: dict[str, Any] = {
            "council": {
                "name": cfg.name,
                "task": self.redact(cfg.task),
                "mode": cfg.mode,
                "rounds": cfg.plan,
                "decision_rule": cfg.decision_rule,
                "threshold": cfg.threshold,
                "language": cfg.language,
                "version": VERSION,
                "seed": cfg.seed,
            },
            "seats": [
                {
                    "id": s.id,
                    "name": s.name,
                    "role": s.role,
                    "provider": s.provider,
                    "model": s.model,
                    "brief": s.brief,
                }
                for s in cfg.seats
            ],
            "decision": {
                "statement": self.redact(as_text(decision.get("statement"))) or "(no decision produced)",
                "confidence": clamp01(decision.get("confidence"), 0.0),
                "rule": as_text(decision.get("rule")) or cfg.decision_rule,
                "rationale": self.redact(as_text(decision.get("rationale"))),
            },
            "consensus": [self._clean_consensus(x) for x in as_list(payload.get("consensus")) if isinstance(x, dict)],
            "contested": [
                {
                    "text": self.redact(as_text(x.get("text"))),
                    "for": [as_text(s) for s in as_list(x.get("for"))],
                    "against": [as_text(s) for s in as_list(x.get("against"))],
                    "crux": self.redact(as_text(x.get("crux"))),
                }
                for x in as_list(payload.get("contested"))
                if isinstance(x, dict)
            ],
            "dissent": [
                {"seat": as_text(x.get("seat")), "text": self.redact(as_text(x.get("text")))}
                for x in as_list(payload.get("dissent"))
                if isinstance(x, dict) and as_text(x.get("text"))
            ],
            "risks": [
                {
                    "risk": self.redact(as_text(x.get("risk"))),
                    "likelihood": as_text(x.get("likelihood")),
                    "impact": self.redact(as_text(x.get("impact"))),
                    "mitigation": self.redact(as_text(x.get("mitigation"))),
                }
                for x in as_list(payload.get("risks"))
                if isinstance(x, dict)
            ],
            "actions": [
                {"action": self.redact(as_text(x.get("action"))), "owner": as_text(x.get("owner")), "when": as_text(x.get("when"))}
                for x in as_list(payload.get("actions"))
                if isinstance(x, dict) and as_text(x.get("action"))
            ],
            "open_questions": [self.redact(as_text(x)) for x in as_list(payload.get("open_questions")) if as_text(x)],
            "rounds": [dataclasses.asdict(r) for r in self.records],
            "calls": self.calls,
            "budget": {
                "calls_used": self.calls_used,
                "max_calls": cfg.budget_calls,
                "chars_used": self.used_chars,
                "max_chars": cfg.budget_chars,
                "exhausted": self.budget_exhausted,
            },
            "anonymization": self.labels,
            "transcript": transcript_blocks,
            "failures": self.failures,
            "generated_at": now_iso(),
        }
        return minutes

    def _clean_consensus(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "text": self.redact(as_text(item.get("text"))),
            "confidence": clamp01(item.get("confidence"), 0.5),
            "supported_by": [as_text(s) for s in as_list(item.get("supported_by"))],
            "claim_ids": [as_text(c) for c in as_list(item.get("claim_ids"))],
        }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def render_transcript_markdown(minutes: dict[str, Any], *, banner: str = "") -> str:
    council = minutes["council"]
    seats = minutes["seats"]
    decision = minutes["decision"]
    lines: list[str] = []
    if banner:
        lines += [f"> {banner}", ""]
    lines += [
        f"# {council['name']} · 议事记录",
        "",
        f"**议题** {council['task']}",
        "",
        f"**{len(seats)} 席 · {len(council['rounds'])} 轮 · 规则 {council['decision_rule']} ({council['threshold']}) · 语言 {council['language']}**",
        "",
        "| 席位 | 角色 | 模型 |",
        "|---|---|---|",
    ]
    for seat in seats:
        lines.append(f"| {seat['name']} `{seat['id']}` | {seat['role']} | {seat['provider']}/{seat['model']} |")
    lines.append("")
    labels = {"propose": "提案 · 独立思考，互不可见", "critique": "交叉质询 · 匿名编号", "revise": "修订 · 只对批评负责", "redteam": "红队 · 攻击正在成形的共识", "converge": "收敛 · 保留分歧"}
    for index, record in enumerate(minutes["rounds"], start=1):
        title = labels.get(record["name"], record["name"])
        lines += [f"## R{index} {title}", "", f"_耗时 {record['duration']}s · 成功 {len(record['seats_ok'])} 席_", ""]
        if record.get("skipped"):
            lines += [f"_本轮跳过：{record['skipped']}_", ""]
        for seat in seats:
            seat_id = seat["id"]
            if seat_id not in record["seats_ok"]:
                continue
            block = next(
                (
                    b["markdown"]
                    for b in minutes["transcript"]
                    if b.get("round") == record["name"] and b.get("seat") == seat_id
                ),
                None,
            )
            if block:
                lines += [block, ""]
        for seat_id, error in record["seats_failed"].items():
            lines += [f"#### {seat_id} · 不可用", f"- {error}", ""]
    lines += [
        "---",
        "",
        "## 结论",
        "",
        f"> **{decision['statement']}**",
        "",
        f"置信 {decision['confidence']:.2f} · 规则 {decision['rule']}",
        "",
        decision["rationale"] or "",
        "",
    ]
    if minutes["consensus"]:
        lines += ["## 共识", ""]
        for item in minutes["consensus"]:
            who = ", ".join(item["supported_by"]) or "—"
            lines.append(f"- {item['text']} （置信 {item['confidence']:.2f}；附议 {who}）")
        lines.append("")
    if minutes["contested"]:
        lines += ["## 未决分歧", ""]
        for item in minutes["contested"]:
            lines += [
                f"- **{item['text']}**",
                f"  - 支持 {', '.join(item['for']) or '—'} · 反对 {', '.join(item['against']) or '—'}",
                f"  - 决胜点：{item['crux'] or '—'}",
            ]
        lines.append("")
    if minutes["dissent"]:
        lines += ["## 少数意见（原文保留）", ""]
        for item in minutes["dissent"]:
            lines += [f"> {item['text']}", f"> — `{item['seat']}`", ""]
    if minutes["risks"]:
        lines += ["## 风险", "", "| 风险 | 概率 | 影响 | 缓解 |", "|---|---|---|---|"]
        for item in minutes["risks"]:
            lines.append(f"| {item['risk']} | {item['likelihood']} | {item['impact']} | {item['mitigation']} |")
        lines.append("")
    if minutes["actions"]:
        lines += ["## 行动", ""]
        for item in minutes["actions"]:
            lines.append(f"- [ ] {item['action']} — {item['owner']} · {item['when']}")
        lines.append("")
    if minutes["open_questions"]:
        lines += ["## 待补信息", ""] + [f"- {q}" for q in minutes["open_questions"]] + [""]
    budget = minutes["budget"]
    lines += [
        "---",
        "",
        f"_调用 {budget['calls_used']}/{budget['max_calls']} · 字符 {budget['chars_used']}/{budget['max_chars']}"
        f"{' · 预算用尽' if budget['exhausted'] else ''} · 生成于 {minutes['generated_at']} · ai-council v{minutes['council']['version']}_",
        "",
        "_共识不等于正确：本记录保留了反对意见与置信度，最终判断由人负责。_",
    ]
    return "\n".join(lines)


def render_minutes_markdown(minutes: dict[str, Any], *, banner: str = "") -> str:
    council = minutes["council"]
    decision = minutes["decision"]
    lines: list[str] = []
    if banner:
        lines += [f"> {banner}", ""]
    lines += [
        f"# 议事纪要 · {council['name']}",
        "",
        f"**议题** {council['task']}",
        "",
        f"**结论** {decision['statement']}",
        "",
        f"**置信** {decision['confidence']:.2f} · **规则** {decision['rule']} · **模式** {council['mode']} · **轮次** {' → '.join(council['rounds'])}",
        "",
    ]
    if minutes["consensus"]:
        lines += ["## 共识", ""] + [
            f"- {item['text']}（{item['confidence']:.2f}）" for item in minutes["consensus"]
        ] + [""]
    if minutes["contested"]:
        lines += ["## 分歧", ""] + [f"- {item['text']} → 决胜点：{item['crux']}" for item in minutes["contested"]] + [""]
    if minutes["dissent"]:
        lines += ["## 少数意见", ""] + [f"- `{item['seat']}`: {item['text']}" for item in minutes["dissent"]] + [""]
    if minutes["actions"]:
        lines += ["## 行动", ""] + [f"- {a['action']} — {a['owner']} · {a['when']}" for a in minutes["actions"]] + [""]
    lines += ["## 席位与成本", "", "| 席位 | 模型 | 调用 | 失败 |", "|---|---|---|---|"]
    by_seat: dict[str, dict[str, Any]] = {}
    for call in minutes["calls"]:
        entry = by_seat.setdefault(call["seat"], {"calls": 0, "failed": 0, "model": call["model"]})
        entry["calls"] += 1
        if not call["ok"]:
            entry["failed"] += 1
    for seat in minutes["seats"]:
        entry = by_seat.get(seat["id"], {"calls": 0, "failed": 0, "model": f"{seat['provider']}/{seat['model']}"})
        lines.append(f"| {seat['name']} `{seat['id']}` | {entry['model']} | {entry['calls']} | {entry['failed']} |")
    lines += ["", f"_调用 {minutes['budget']['calls_used']} 次 · 生成于 {minutes['generated_at']}_", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def write_outputs(minutes: dict[str, Any], out_dir: Path, *, banner: str = "") -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = out_dir / "transcript.md"
    minutes_md = out_dir / "minutes.md"
    minutes_json = out_dir / "minutes.json"
    transcript.write_text(render_transcript_markdown(minutes, banner=banner), encoding="utf-8")
    minutes_md.write_text(render_minutes_markdown(minutes, banner=banner), encoding="utf-8")
    minutes_json.write_text(json.dumps(minutes, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"transcript": transcript, "minutes_md": minutes_md, "minutes_json": minutes_json}


def out_dir_for(cfg: CouncilConfig, base: Path | None) -> Path:
    if base is not None:
        return base
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("runs") / f"{stamp}-{slugify(cfg.name)}"


def planned_calls(cfg: CouncilConfig) -> int:
    """How many model calls the plan will make at most."""
    arguing = max(1, len([s for s in cfg.seats if s.role != "synthesizer"]))
    total = 0
    for round_name in cfg.plan:
        total += 1 if round_name in {"converge", "redteam"} else arguing
    return total


def print_plan(cfg: CouncilConfig) -> None:
    print(f"council : {cfg.name}  ({cfg.mode}, rounds: {' → '.join(cfg.plan)})")
    print(f"task    : {cfg.task[:160]}")
    print(f"rule    : {cfg.decision_rule} @ {cfg.threshold}   language: {cfg.language}")
    print(f"budget  : {cfg.budget_calls} calls / {cfg.budget_chars} chars")
    print("seats   :")
    for seat in cfg.seats:
        provider = cfg.providers.get(seat.provider, {})
        env = provider.get("api_key_env") or ""
        if provider.get("type") == "mock":
            state = "offline mock"
        elif env and not env_is_set(env):
            state = f"NO KEY — set {env}"
        else:
            state = "ready"
        print(f"  - {seat.id:<12} {seat.role:<12} {seat.provider}/{seat.model:<28} {state}")
    planned = planned_calls(cfg)
    print(f"planned : ≤{planned} calls across {len(cfg.plan)} sequential rounds (seats inside a round run in parallel)")
    print(f"synthesis seat: {cfg.synthesizer}")


def cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    loaded_env = load_dotenv(Path(args.env) if args.env else config_path.parent / ".env")
    try:
        cfg = normalize_config(read_config_file(config_path))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.language:
        cfg.language = args.language
    if args.max_calls:
        cfg.budget_calls = args.max_calls
    cfg.seed = args.seed if args.seed is not None else cfg.seed

    if args.dry_run:
        if loaded_env:
            print(f"env: loaded {', '.join(loaded_env)} from .env")
        print_plan(cfg)
        return 0

    secrets = [os.environ.get(p.get("api_key_env") or "", "") for p in cfg.providers.values()]
    council = Council(cfg, redact=Redactor(secrets))
    started = time.time()
    minutes = council.run()
    elapsed = time.time() - started

    out_dir = out_dir_for(cfg, Path(args.out) if args.out else None)
    written = write_outputs(minutes, out_dir)
    ok_calls = sum(1 for c in minutes["calls"] if c["ok"])
    total_calls = len(minutes["calls"])
    print()
    print(f"done in {elapsed:.1f}s · {ok_calls}/{total_calls} calls ok · {len(minutes['consensus'])} consensus · {len(minutes['dissent'])} dissent")
    print(f"minutes : {written['minutes_md']}")
    print(f"record  : {written['transcript']}")
    print(f"json    : {written['minutes_json']}")
    if total_calls and ok_calls == 0:
        print("error: every model call failed — check keys, model ids and base URLs (try --dry-run)", file=sys.stderr)
        return 2
    return 0


DEMO_RAW: dict[str, Any] = {
    "council": {
        "name": "grpc-migration",
        "task": "我们是否应该把内部工具的 REST API 迁移到 gRPC？请给出可执行的决策建议。",
        "mode": "council",
        "language": "简体中文",
        "decision_rule": "supermajority",
        "threshold": 0.66,
        "deliverable": "一条决策、置信度、支撑理由、未决分歧、风险与下一步行动。",
        "constraints": ["团队 6 人，季度预算冻结", "现有 40 个内部接口，调用方 12 个", "不能停机超过 30 分钟"],
        "non_goals": ["不讨论是否换语言", "不评估外部客户 API"],
        "budget": {"max_calls": 24, "max_chars": 400000},
    },
    "providers": {"mock": {"type": "mock"}},
    "seats": [
        {"id": "generalist", "name": "通才", "role": "generalist", "provider": "mock", "model": "mock-general", "brief": "平衡收益、成本与可逆性"},
        {"id": "architect", "name": "架构师", "role": "specialist", "provider": "mock", "model": "mock-arch", "brief": "接口语义、契约、长期维护成本"},
        {"id": "critic", "name": "红队", "role": "critic", "provider": "mock", "model": "mock-red", "brief": "只找致命缺陷与隐含假设"},
        {"id": "operator", "name": "运维", "role": "implementer", "provider": "mock", "model": "mock-ops", "brief": "上线顺序、灰度、回滚、人力"},
        {"id": "synth", "name": "综合者", "role": "synthesizer", "provider": "mock", "model": "mock-synth", "brief": "只合并，不发明"},
    ],
    "synthesizer": "synth",
}


def cmd_demo(args: argparse.Namespace) -> int:
    cfg = normalize_config(json.loads(json.dumps(DEMO_RAW)))
    if args.max_calls:
        cfg.budget_calls = args.max_calls
    cfg.seed = args.seed if args.seed is not None else 7
    print_plan(cfg)
    council = Council(cfg, log=lambda m: print(m, flush=True))
    minutes = council.run()
    out_dir = Path(args.out) if args.out else Path("runs") / f"demo-{slugify(cfg.name)}"
    banner = "OFFLINE DEMO · 所有回答均为本地 mock，用来看结构与流程，不代表任何真实模型观点。"
    written = write_outputs(minutes, out_dir, banner=banner)
    print()
    print(f"demo minutes : {written['minutes_md']}")
    print(f"demo record  : {written['transcript']}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        cfg = normalize_config(read_config_file(Path(args.config)))
    except ConfigError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {cfg.name} · {len(cfg.seats)} seats · plan {' → '.join(cfg.plan)} · synthesizer {cfg.synthesizer}")
    roles = {s.role for s in cfg.seats}
    if "critic" not in roles:
        print("warn: no `critic` seat — the council will mostly agree with itself")
    if len(cfg.seats) > 7:
        print("warn: more than 7 seats — cost grows linearly, insight usually does not")
    return 0


INIT_TEMPLATE: dict[str, Any] = {
    "council": {
        "name": "my-decision",
        "task": "把要决策的问题写在这里：一句可被证伪的问题，比一段背景更有用。",
        "mode": "triad",
        "language": "简体中文",
        "decision_rule": "supermajority",
        "threshold": 0.66,
        "deliverable": "一条决策、置信度、理由、未决分歧、风险、下一步。",
        "constraints": ["预算/时间/人力上限"],
        "non_goals": ["明确不讨论的范围"],
        "budget": {"max_calls": 12, "max_chars": 300000},
    },
    "providers": {
        "openai": {"type": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
        "anthropic": {"type": "anthropic", "base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY"},
        "google": {"type": "google", "base_url": "https://generativelanguage.googleapis.com/v1beta", "api_key_env": "GEMINI_API_KEY"},
        "deepseek": {"type": "openai", "base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
        "ollama": {"type": "openai", "base_url": "http://127.0.0.1:11434/v1", "api_key_env": ""},
    },
    "seats": [
        {"id": "generalist", "name": "通才", "role": "generalist", "provider": "openai", "model": "gpt-5", "brief": "整体判断：收益、成本、可逆性"},
        {"id": "specialist", "name": "专家", "role": "specialist", "provider": "deepseek", "model": "deepseek-chat", "brief": "本领域最容易出错的技术细节"},
        {"id": "critic", "name": "红队", "role": "critic", "provider": "anthropic", "model": "claude-sonnet-5", "brief": "只找使结论失效的隐含假设"},
        {"id": "synth", "name": "综合者", "role": "synthesizer", "provider": "google", "model": "gemini-3-pro", "brief": "合并记录，保留分歧，不发明新论据"},
    ],
    "synthesizer": "synth",
}


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / "council.json"
    if config_path.exists() and not args.force:
        print(f"refusing to overwrite {config_path} (use --force)", file=sys.stderr)
        return 1
    config_path.write_text(json.dumps(INIT_TEMPLATE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    env_path = target / ".env.example"
    if not env_path.exists():
        env_path.write_text(
            "\n".join(
                [
                    "# one line per provider; only the ones your seats use are required",
                    "OPENAI_API_KEY=",
                    "ANTHROPIC_API_KEY=",
                    "GEMINI_API_KEY=",
                    "DEEPSEEK_API_KEY=",
                    "# OpenRouter alone reaches most families: https://openrouter.ai/keys",
                    "OPENROUTER_API_KEY=",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    print(f"wrote {config_path}")
    print(f"wrote {env_path}")
    print("next: python scripts/council.py run -c council.json --dry-run")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool]] = []
    checks.append(("extract_json handles fenced json", extract_json('```json\n{"a":1}\n```') == {"a": 1}))
    checks.append(("extract_json handles prose", extract_json('here you go: {"a": {"b": "}"}} done') == {"a": {"b": "}"}}))
    checks.append(("extract_json survives trailing comma", extract_json('{"a": [1,2,],}') == {"a": [1, 2]}))
    checks.append(("redactor hides openai keys", "sk-" not in Redactor()("token sk-abcdefghijklmnopqrstuvwxyz")))
    checks.append(("trim_plan keeps converge", trim_plan(ROUND_PLANS["court"], 3)[-1] == "converge"))
    cfg = normalize_config(json.loads(json.dumps(DEMO_RAW)))
    checks.append(("demo config normalises", len(cfg.seats) == 5 and cfg.synthesizer == "synth"))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="council.py",
        description="Model-agnostic multi-AI council: independent thinking first, cross-examination second, dissent preserved.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python scripts/council.py demo                       # offline, no keys\n"
            "  python scripts/council.py init -d my-council\n"
            "  python scripts/council.py run -c council.json --dry-run\n"
            "  python scripts/council.py run -c council.json -o runs/today\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"ai-council {VERSION}")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="run a council from a config file")
    run_p.add_argument("-c", "--config", default="council.json")
    run_p.add_argument("-o", "--out", default="")
    run_p.add_argument("--env", default="")
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--language", default="")
    run_p.add_argument("--max-calls", type=int, default=0)
    run_p.add_argument("--seed", type=int, default=None)
    run_p.set_defaults(func=cmd_run)

    demo_p = sub.add_parser("demo", help="offline 5-seat demo with mock models")
    demo_p.add_argument("-o", "--out", default="")
    demo_p.add_argument("--max-calls", type=int, default=0)
    demo_p.add_argument("--seed", type=int, default=None)
    demo_p.set_defaults(func=cmd_demo)

    init_p = sub.add_parser("init", help="scaffold council.json and .env.example")
    init_p.add_argument("-d", "--dir", default=".")
    init_p.add_argument("--force", action="store_true")
    init_p.set_defaults(func=cmd_init)

    validate_p = sub.add_parser("validate", help="check a config without calling any model")
    validate_p.add_argument("-c", "--config", default="council.json")
    validate_p.set_defaults(func=cmd_validate)

    selftest_p = sub.add_parser("selftest", help="run built-in sanity checks")
    selftest_p.set_defaults(func=cmd_selftest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):  # pragma: no cover
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""Probe every configured AI provider with one minimal real request.

The point is to distinguish "listed as free" from "actually callable right now".
A price list cannot answer that; a 8-token completion can. Read-only: sends no
user text, prints one line per provider plus a JSON summary.

    python tools/provider_health.py
    python tools/provider_health.py --json docs/provider_health.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / "backend" / ".env"
PROMPT = "Reply with the single word: ok"
MAX_TOKENS = 8
TIMEOUT = 25


def load_env(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def post_json(url: str, payload: dict, headers: dict) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, body[:400]
    except Exception as exc:  # network, TLS, DNS
        return 0, f"{type(exc).__name__}: {exc}"


def probe_groq(env: dict) -> dict:
    key = env.get("GROQ_API_KEY") or env.get("AI_API_KEY", "")
    model = env.get("GROQ_MODEL") or env.get("AI_MODEL", "")
    if not key or not key.startswith("gsk_"):
        return {"skipped": "no groq key"}
    if not model:
        return {"skipped": "no groq model configured"}
    status, body = post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": PROMPT}],
         "max_tokens": MAX_TOKENS},
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    return {"status": status, "body": body}


def probe_openrouter(env: dict) -> dict:
    key = env.get("OPENROUTER_API_KEY", "")
    model = env.get("OPENROUTER_MODEL", "")
    if not key:
        return {"skipped": "no openrouter key"}
    if not model:
        return {"skipped": "no openrouter model configured"}
    status, body = post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": PROMPT}],
         "max_tokens": MAX_TOKENS},
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
         "HTTP-Referer": "https://github.com/pro-rider/trilingual_dictionary",
         "X-Title": "trilingual-dictionary-health"},
    )
    return {"status": status, "body": body}


def probe_gemini(env: dict) -> dict:
    key = env.get("GEMINI_API_KEY", "")
    model = env.get("GEMINI_MODEL", "")
    if not key:
        return {"skipped": "no gemini key"}
    if not model:
        return {"skipped": "no gemini model configured"}
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    status, body = post_json(
        url,
        {"contents": [{"parts": [{"text": PROMPT}]}],
         "generationConfig": {"maxOutputTokens": MAX_TOKENS}},
        {"Content-Type": "application/json"},
    )
    return {"status": status, "body": body}


PROBES = {"groq": probe_groq, "openrouter": probe_openrouter, "gemini": probe_gemini}


def classify(status: int, body: str) -> str:
    if status == 200:
        return "working"
    if status == 0:
        return "network_error"
    if status in (401, 403):
        return "auth_or_region_blocked"
    if status == 402:
        return "no_credit"
    if status == 404:
        return "model_not_found"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "provider_down"
    return f"http_{status}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    env = load_env(ENV_FILE)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "providers": {}}
    for name, probe in PROBES.items():
        result = probe(env)
        if "skipped" in result:
            result["verdict"] = "not_configured"
        else:
            result["verdict"] = classify(result["status"], result["body"])
        report["providers"][name] = result
        detail = result.get("body", result.get("skipped", ""))
        print(f"{name:12s} {result['verdict']:26s} {detail[:150]}")

    working = [n for n, r in report["providers"].items() if r["verdict"] == "working"]
    report["usable"] = working
    print("usable providers:", working or "none")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())

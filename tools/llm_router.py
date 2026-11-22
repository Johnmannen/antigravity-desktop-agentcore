"""Resilient multi-provider LLM fallback router for C:\\juno-agy.

Tries providers in priority order (Google AI Studio -> Groq -> OpenRouter -> Nvidia -> Local)
and automatically falls back on rate limits (429), server errors (5xx), or timeouts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROVIDERS: list[dict[str, str]] = [
    {
        "name": "gemini",
        "env_key": "GEMINI_API_KEY",
        "kind": "gemini_sdk",
        "model": "gemini-3.8-flash",
    },
    {
        "name": "gemini_lite",
        "env_key": "GEMINI_API_KEY",
        "kind": "gemini_sdk",
        "model": "gemini-3.5-flash-lite",
    },
    {
        "name": "gemma",
        "env_key": "GEMINI_API_KEY",
        "kind": "gemini_sdk",
        "model": "gemma-4-26b-a4b-it",
    },
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "kind": "openai_compat",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "qwen/qwen3.8-27b",
    },
    {
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "kind": "openai_compat",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "nvidia/nemotron-3.5-lightning:free",
    },
    {
        "name": "nvidia",
        "env_key": "NVIDIA_API_KEY",
        "kind": "openai_compat",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
    },
    {
        "name": "local_hermes3",
        "env_key": "",
        "kind": "local_llama",
        "url": "http://127.0.0.1:8083/v1/chat/completions",
        "model": "Hermes-3-8B",
    },
]

LOCAL_LLM_DIR = ROOT / "local_llm"
LOCAL_LLM_EXE = LOCAL_LLM_DIR / "llama-server.exe"
LOCAL_LLM_MODEL = LOCAL_LLM_DIR / "Hermes-3-Llama-3.1-8B.Q4_K_M.gguf"

RETRYABLE_STATUS = {402, 404, 410, 429, 500, 502, 503, 504}


def _call_gemini(provider: dict[str, str], api_key: str, prompt: str, system: str) -> str:
    """Send a generation request via Gemini REST API with strict timeout."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{provider['model']}:generateContent?key={api_key}"
    body: dict = {"contents": [{"parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    resp = httpx.post(url, json=body, timeout=20.0)
    if resp.status_code in RETRYABLE_STATUS:
        raise RuntimeError(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _call_openai_compat(provider: dict[str, str], api_key: str, prompt: str, system: str) -> str:
    """Send a chat completion request to one OpenAI-compatible provider."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": provider["model"], "messages": messages, "max_tokens": 1024}

    resp = httpx.post(provider["url"], headers=headers, json=payload, timeout=25.0)
    if resp.status_code in RETRYABLE_STATUS:
        raise RuntimeError(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _ensure_local_llm() -> None:
    """Start local llama-server.exe on demand if not already listening on port 8083."""
    try:
        if httpx.get("http://127.0.0.1:8083/health", timeout=1.0).status_code == 200:
            return
    except Exception:
        pass
    if not LOCAL_LLM_EXE.exists() or not LOCAL_LLM_MODEL.exists():
        raise FileNotFoundError("Lokal Hermes-3-modell saknas i C:\\juno-agy\\local_llm")
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [
            str(LOCAL_LLM_EXE), "-m", str(LOCAL_LLM_MODEL),
            "--host", "127.0.0.1", "--port", "8083",
            "--ctx-size", "8192", "--parallel", "1", "--alias", "Hermes-3-8B",
        ],
        cwd=str(LOCAL_LLM_DIR),
        creationflags=no_win,
    )
    for _ in range(30):
        time.sleep(1.0)
        try:
            if httpx.get("http://127.0.0.1:8083/health", timeout=1.0).status_code == 200:
                return
        except Exception:
            pass
    raise TimeoutError("Lokal llama-server svarade inte inom 30s")


def ask(prompt: str, *, system: str = "", preferred: str | None = None) -> dict:
    """Query configured providers with automatic fallback on quota or transient errors."""
    chain = [p for p in PROVIDERS if not preferred or p["name"] == preferred]
    attempts: list[dict[str, str]] = []

    for provider in chain:
        if provider["kind"] == "local_llama":
            try:
                _ensure_local_llm()
                text = _call_openai_compat(provider, "local", prompt, system)
                attempts.append({"provider": provider["name"], "status": "ok"})
                return {"provider": provider["name"], "model": provider["model"], "reply": text, "attempts": attempts}
            except Exception as exc:
                attempts.append({"provider": provider["name"], "status": f"failed: {exc}"})
                continue

        api_key = os.getenv(provider["env_key"], "").strip()
        if not api_key:
            attempts.append({"provider": provider["name"], "status": "skipped_no_key"})
            continue
        try:
            caller = _call_gemini if provider["kind"] == "gemini_sdk" else _call_openai_compat
            text = caller(provider, api_key, prompt, system)
            attempts.append({"provider": provider["name"], "status": "ok"})
            return {
                "provider": provider["name"],
                "model": provider["model"],
                "reply": text,
                "attempts": attempts,
            }
        except Exception as exc:
            attempts.append({"provider": provider["name"], "status": f"failed: {exc}"})

    raise RuntimeError(f"Alla AI-providers misslyckades: {json.dumps(attempts, ensure_ascii=False)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Juno-AGY Multi-Provider LLM Fallback Router")
    parser.add_argument("prompt", help="Prompt to send")
    parser.add_argument("--system", default="", help="Optional system prompt")
    parser.add_argument("--provider", default=None, help="Force a specific provider")
    args = parser.parse_args()

    result = ask(args.prompt, system=args.system, preferred=args.provider)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

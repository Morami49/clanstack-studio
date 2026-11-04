"""Per-task model router (D-008, D-012).

- Tries providers in the order configured for the task (chat / vision / summarize).
- Skips any without a key/model, or that fail, and falls through to the next.
- When a request contains local-only material it only uses `local_only_routes`.
- Every choice is logged to the hub as a `routing` event: task, provider, model,
  local or cloud, what was skipped and why, latency, size. Never the content.

`build(local: bool) -> messages` lets the caller include local-only profile
items only when the chosen provider is local (D-019).
Messages use the OpenAI shape: [{"role": "system"|"user"|"assistant", "content": str}].
"""
from __future__ import annotations

import os
import time
from typing import Callable

import httpx


class ProviderError(Exception):
    pass


class Router:
    def __init__(self, cfg: dict, log: Callable[[dict], None] | None = None, timeout: float = 45):
        b = cfg.get("brain", {})
        self.providers = b.get("providers", {})
        self.routes = b.get("routes", {})
        self.local_only = b.get("local_only_routes", ["ollama", "echo"])
        self.log = log or (lambda e: None)
        self.http = httpx.Client(timeout=timeout)

    # ---------------------------------------------------------------- choose
    def usable(self, name: str) -> tuple[bool, str]:
        p = self.providers.get(name)
        if not p:
            return False, "not configured"
        if p["kind"] == "echo":
            return True, ""
        if not p.get("model"):
            return False, "no model set"
        if p.get("key_env") and not os.environ.get(p["key_env"]):
            return False, f"no {p['key_env']}"
        return True, ""

    def complete(self, task: str, build: Callable[[bool], list[dict]], local_only: bool = False,
                 max_tokens: int = 600, session_id: str = "conversation", needs_vision: bool = False) -> tuple[str, dict]:
        order = list(self.routes.get(task) or self.routes.get("chat") or ["echo"])
        if local_only:
            order = [n for n in order if n in self.local_only] or list(self.local_only)
        skipped = []
        for name in order:
            ok, why = self.usable(name)
            p = self.providers.get(name, {})
            if ok and needs_vision and not p.get("vision") and p.get("kind") != "echo":
                ok, why = False, "no vision"
            if not ok:
                skipped.append(f"{name}: {why}")
                continue
            local = bool(p.get("local"))
            msgs = build(local)
            t0 = time.time()
            try:
                text = self._call(p, msgs, max_tokens)
            except Exception as e:
                skipped.append(f"{name}: {type(e).__name__} {str(e)[:120]}")
                continue
            meta = {"task": task, "provider": name, "model": p.get("model", name), "local": local,
                    "skipped": skipped, "ms": int((time.time() - t0) * 1000),
                    "prompt_chars": sum(len(m["content"]) for m in msgs), "reply_chars": len(text),
                    "local_only": local_only, "session_id": session_id}
            self.log(meta)
            return text, meta
        meta = {"task": task, "provider": None, "skipped": skipped, "local_only": local_only, "session_id": session_id}
        self.log(meta)
        raise ProviderError("no provider could answer: " + "; ".join(skipped))

    # ---------------------------------------------------------------- adapters
    def _call(self, p: dict, msgs: list[dict], max_tokens: int) -> str:
        kind = p["kind"]
        key = os.environ.get(p.get("key_env", ""), "")
        if kind == "echo":
            last = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
            return ("(offline mode: no AI provider is set up yet, so I can only run commands. "
                    f"I heard: \"{last[-200:]}\")")
        if kind == "openai_compat":
            r = self.http.post(p["base_url"].rstrip("/") + "/chat/completions",
                               headers={"Authorization": f"Bearer {key}"} if key else {},
                               json={"model": p["model"], "messages": msgs, "max_tokens": max_tokens})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        if kind == "gemini":
            system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
            contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                        for m in msgs if m["role"] != "system"]
            body = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            r = self.http.post(f"https://generativelanguage.googleapis.com/v1beta/models/{p['model']}:generateContent",
                               headers={"x-goog-api-key": key}, json=body)
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(x.get("text", "") for x in parts).strip()
        if kind == "anthropic":
            system = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
            r = self.http.post("https://api.anthropic.com/v1/messages",
                               headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                               json={"model": p["model"], "max_tokens": max_tokens, "system": system,
                                     "messages": [m for m in msgs if m["role"] != "system"]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"]).strip()
        raise ProviderError(f"unknown provider kind {kind}")

"""Pluggable LLM backends for the chatbot — Anthropic API *or* a local Ollama model.

No API key required: if `ANTHROPIC_API_KEY` is set we use Anthropic; otherwise, if an Ollama
server is running (or `OLLAMA_MODEL` is set) we use that — fully local, free, offline. The
chatbot doesn't care which; it just calls `backend.chat(system, messages)`.

Env:
  ANTHROPIC_API_KEY   use Anthropic (model from BYTEWRIGHT_MODEL, default claude-sonnet-4-6)
  OLLAMA_MODEL        use a local Ollama model, e.g. "qwen2.5-coder:7b" or "llama3.1"
  OLLAMA_HOST         Ollama server (default http://localhost:11434)
  BYTEWRIGHT_BACKEND  force "anthropic" or "ollama"
"""
from __future__ import annotations

import json
import os
import urllib.request


class LLMUnavailable(RuntimeError):
    pass


class LLMBackend:
    name = "base"

    def chat(self, system: str, messages: list[dict], temperature: float = 0.0,
             force_json: bool = True) -> str:
        raise NotImplementedError


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(self, model: str | None = None, max_tokens: int = 8192):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("BYTEWRIGHT_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens

    def chat(self, system, messages, temperature=0.0, force_json=True):
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=temperature,
            system=system, messages=messages)
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def _http_post_json(url: str, payload: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.model = (model or os.environ.get("OLLAMA_MODEL")
                      or os.environ.get("BYTEWRIGHT_MODEL", "llama3.1"))

    def chat(self, system, messages, temperature=0.0, force_json=True):
        payload = {
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system}] + list(messages),
            "options": {"temperature": temperature, "num_ctx": 16384},
        }
        if force_json:
            payload["format"] = "json"   # Ollama constrains output to valid JSON — big reliability win
        resp = _http_post_json(self.host + "/api/chat", payload)
        return resp["message"]["content"]


def _ollama_reachable(host: str) -> bool:
    try:
        urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def make_backend(prefer: str | None = None) -> LLMBackend:
    """Pick a backend: explicit > Anthropic key > running Ollama. Raises a helpful error if none."""
    prefer = prefer or os.environ.get("BYTEWRIGHT_BACKEND")
    if prefer == "anthropic" or (prefer is None and os.environ.get("ANTHROPIC_API_KEY")):
        try:
            return AnthropicBackend()
        except Exception:
            if prefer == "anthropic":
                raise
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if prefer == "ollama" or os.environ.get("OLLAMA_MODEL") or _ollama_reachable(host):
        return OllamaBackend()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicBackend()
    raise LLMUnavailable(
        "No model backend available. Either set ANTHROPIC_API_KEY, or install Ollama "
        "(https://ollama.com), run `ollama pull qwen2.5-coder` and set OLLAMA_MODEL "
        "(a running Ollama server is auto-detected).")

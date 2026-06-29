"""Pluggable LLM backends for the chatbot — OpenAI (ChatGPT), Anthropic, or a local Ollama model.

No API key required for Ollama. Each backend exposes the same `chat(system, messages)` plus
`list_models()` so you can switch the underlying model at runtime. Pick a backend explicitly or
let it auto-detect.

Env:
  OPENAI_API_KEY      use OpenAI/ChatGPT (model from OPENAI_MODEL, default gpt-4o-mini)
  OPENAI_BASE_URL     OpenAI-compatible endpoint (default https://api.openai.com/v1)
  ANTHROPIC_API_KEY   use Anthropic (model from SIRYAPSALOT_MODEL, default claude-sonnet-4-6)
  OLLAMA_MODEL        use a local Ollama model, e.g. "qwen2.5-coder:7b" or "llama3.1"
  OLLAMA_HOST         Ollama server (default http://localhost:11434)
  SIRYAPSALOT_BACKEND force "openai" | "anthropic" | "ollama"
"""
from __future__ import annotations

import json
import os
import urllib.request


class LLMUnavailable(RuntimeError):
    pass


def _http_json(url: str, payload: dict | None = None, headers: dict | None = None,
               timeout: int = 600) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h)  # POST if data else GET
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class LLMBackend:
    name = "base"
    model = "?"

    def chat(self, system: str, messages: list[dict], temperature: float = 0.0,
             force_json: bool = True) -> str:
        raise NotImplementedError

    def list_models(self) -> list[str]:
        return [self.model]

    def set_model(self, model: str):
        if model:
            self.model = model


class OpenAIBackend(LLMBackend):
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise LLMUnavailable("OPENAI_API_KEY is not set.")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL",
                                                    "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def chat(self, system, messages, temperature=0.0, force_json=True):
        payload = {"model": self.model, "temperature": temperature,
                   "messages": [{"role": "system", "content": system}] + list(messages)}
        if force_json:
            payload["response_format"] = {"type": "json_object"}  # constrain to valid JSON
        resp = _http_json(self.base_url + "/chat/completions", payload, self._headers())
        return resp["choices"][0]["message"]["content"]

    def list_models(self) -> list[str]:
        try:
            resp = _http_json(self.base_url + "/models", headers=self._headers(), timeout=15)
            ids = sorted(m["id"] for m in resp.get("data", []))
            chat = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))]
            return chat or ids
        except Exception:
            return ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"]


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(self, model: str | None = None, max_tokens: int = 8192):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("SIRYAPSALOT_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens

    def chat(self, system, messages, temperature=0.0, force_json=True):
        msg = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, temperature=temperature,
            system=system, messages=messages)
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

    def list_models(self) -> list[str]:
        known = ["claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-fable-5"]
        return [self.model] + [m for m in known if m != self.model]


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.model = (model or os.environ.get("OLLAMA_MODEL")
                      or os.environ.get("SIRYAPSALOT_MODEL", "llama3.1"))

    def chat(self, system, messages, temperature=0.0, force_json=True):
        payload = {
            "model": self.model, "stream": False,
            "messages": [{"role": "system", "content": system}] + list(messages),
            "options": {"temperature": temperature, "num_ctx": 16384},
        }
        if force_json:
            payload["format"] = "json"
        resp = _http_json(self.host + "/api/chat", payload)
        return resp["message"]["content"]

    def list_models(self) -> list[str]:
        try:
            resp = _http_json(self.host + "/api/tags", timeout=5)
            names = sorted(m["name"] for m in resp.get("models", []))
            return names or [self.model]
        except Exception:
            return [self.model]


_BACKENDS = {"openai": OpenAIBackend, "anthropic": AnthropicBackend, "ollama": OllamaBackend}


def _ollama_reachable(host: str) -> bool:
    try:
        urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def backend_available(name: str) -> bool:
    """Can backend `name` be constructed right now (key present / server reachable)?"""
    if name == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if name == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except Exception:
            return False
    if name == "ollama":
        return bool(os.environ.get("OLLAMA_MODEL")) or _ollama_reachable(
            os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    return False


def available_backends() -> list[str]:
    """The provider names the user can switch to right now (for the UI's backend picker)."""
    return [n for n in _BACKENDS if backend_available(n)]


def make_backend(prefer: str | None = None) -> LLMBackend:
    """Pick a backend: explicit > OpenAI key > Anthropic key > running Ollama."""
    prefer = prefer or os.environ.get("SIRYAPSALOT_BACKEND")
    if prefer:
        if prefer not in _BACKENDS:
            raise LLMUnavailable(f"unknown backend {prefer!r}; choose openai, anthropic, or ollama")
        return _BACKENDS[prefer]()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIBackend()
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return AnthropicBackend()
        except Exception:
            pass
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if os.environ.get("OLLAMA_MODEL") or _ollama_reachable(host):
        return OllamaBackend()
    raise LLMUnavailable(
        "No model backend available. Set OPENAI_API_KEY (ChatGPT) or ANTHROPIC_API_KEY, or "
        "install Ollama (https://ollama.com), run `ollama pull qwen2.5-coder` and set "
        "OLLAMA_MODEL (a running Ollama server is auto-detected).")

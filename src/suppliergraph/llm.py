"""Minimal LLM abstraction so the pipeline is testable offline and provider-agnostic."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .config import get_settings


class LLMUnavailable(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> str: ...


class AnthropicLLM:
    """Anthropic Messages API. Set ANTHROPIC_API_KEY; the model id comes from SG_LLM_MODEL."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        try:
            import anthropic
        except ImportError as exc:                      # pragma: no cover
            raise LLMUnavailable("install the 'llm' extra: pip install -e '.[llm]'") from exc
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set")
        self.client = anthropic.Anthropic(api_key=key)
        self.name = model or get_settings().llm_model

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> str:
        resp = self.client.messages.create(
            model=self.name, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


@dataclass
class ScriptedLLM:
    """Deterministic stand-in for tests: a list of replies (consumed in order) or a callable."""

    script: list[str] | Callable[[str, str], str]
    name: str = "scripted"
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> str:
        self.calls.append((system, prompt))
        if callable(self.script):
            return self.script(system, prompt)
        if not self.script:
            raise AssertionError("ScriptedLLM ran out of replies")
        return self.script.pop(0)


class OpenAICompatLLM:
    """Any server that speaks the OpenAI chat-completions protocol: Hugging Face Inference Providers, Ollama, vLLM, LM Studio.

    Plain HTTP (no extra dependency). The model id has no default on purpose: availability differs per provider
    and over time, so set SG_LLM_MODEL yourself.
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 120.0):
        if not model:
            raise LLMUnavailable("set SG_LLM_MODEL to a model id your provider serves")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.name, self.api_key, self.timeout = model, api_key, timeout

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> str:
        body = json.dumps({"model": self.name, "max_tokens": max_tokens, "temperature": 0,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")  # noqa: S310 (operator-configured URL)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
                data = json.load(r)
        except urllib.error.HTTPError as exc:
            raise LLMUnavailable(f"LLM server returned {exc.code}: {exc.read()[:300].decode(errors='replace')}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise LLMUnavailable(f"LLM server unreachable: {exc}") from exc
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"unexpected response shape: {str(data)[:200]}") from exc


HF_ROUTER = "https://router.huggingface.co/v1"


def get_llm() -> LLM:
    """SG_LLM_PROVIDER = anthropic | hf | openai_compat. Unset: Anthropic if its key exists, else Hugging Face if HF_TOKEN exists."""
    provider = os.environ.get("SG_LLM_PROVIDER", "").lower()
    if not provider:
        provider = "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "hf" if os.environ.get("HF_TOKEN") else "anthropic"
    if provider == "anthropic":
        return AnthropicLLM()
    model = os.environ.get("SG_LLM_MODEL", "")
    if provider == "hf":
        if not os.environ.get("HF_TOKEN"):
            raise LLMUnavailable("HF_TOKEN is not set")
        return OpenAICompatLLM(os.environ.get("SG_LLM_BASE_URL", HF_ROUTER), model, os.environ["HF_TOKEN"])
    if provider == "openai_compat":                 # e.g. Ollama: http://localhost:11434/v1
        base = os.environ.get("SG_LLM_BASE_URL")
        if not base:
            raise LLMUnavailable("set SG_LLM_BASE_URL (for Ollama: http://localhost:11434/v1)")
        return OpenAICompatLLM(base, model, os.environ.get("SG_LLM_API_KEY"))
    raise LLMUnavailable(f"unknown SG_LLM_PROVIDER {provider!r}")

"""
The models a choice-set experiment talks to, and where they come from.

A study like this is nothing but model calls, so how they are made is part of
the apparatus and is copied in rather than written fresh each time. Three
backends, tried in the order that costs least and surprises least:

- a local server (Ollama by default), which is what this runs on by default:
  no key, no bill, and the same model every time;
- an OpenAI-compatible endpoint, when one is configured;
- a mock, only when a run explicitly asks for one, and it says so loudly in
  every record it produces.

Nothing here ever invents a decision. When no model can be reached the run
stops, because an experiment whose answers were made up is worse than an
experiment that did not happen.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_OLLAMA = "http://localhost:11434"


class ModelUnavailable(RuntimeError):
    """No model could be reached, so the trials cannot run."""


class OllamaModel:
    """A model served locally. The default, because it costs nothing to ask."""

    def __init__(self, name: str, host: str = "", temperature: float = 0.0,
                 timeout: int = 180):
        self.name = name
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA).rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    def generate(self, prompt: str, system: str = "") -> str:
        payload = json.dumps({
            "model": self.name, "prompt": prompt, "system": system, "stream": False,
            "options": {"temperature": self.temperature},
        }).encode()
        request = urllib.request.Request(f"{self.host}/api/generate", data=payload,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode()).get("response", "")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelUnavailable(
                f"the local model {self.name} at {self.host} did not answer: {exc}") from exc


class OpenAICompatibleModel:
    """Any endpoint that speaks the OpenAI chat API, including OpenAI itself."""

    def __init__(self, name: str, base_url: str = "", api_key: str = "",
                 temperature: float = 0.0, timeout: int = 180):
        self.name = name
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.temperature = temperature
        self.timeout = timeout

    def generate(self, prompt: str, system: str = "") -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        payload = json.dumps({"model": self.name, "messages": messages,
                              "temperature": self.temperature}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode())
            return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError) as exc:
            raise ModelUnavailable(f"{self.name} at {self.base_url} did not answer: {exc}") from exc


def build(config: dict, role: str):
    """
    The model for one role ("curator" or "overseer"), as the config asks for it.

    `models: {curator: llama3.1:8b, backend: ollama}` is the shape. A backend
    that cannot be reached is an error here, at the start, rather than a
    surprise in the middle of a run.
    """
    models = config.get("models", {}) or {}
    name = models.get(role) or models.get("default") or ""
    backend = (models.get("backend") or "ollama").lower()
    temperature = float(models.get("temperature", 0.0))
    if not name:
        raise ModelUnavailable(f"config.yaml does not say which model is the {role}")

    if backend == "ollama":
        return OllamaModel(name, models.get("host", ""), temperature)
    if backend in ("openai", "openai_compatible", "local_server"):
        return OpenAICompatibleModel(name, models.get("base_url", ""),
                                     temperature=temperature)
    if backend == "mock":
        # Only when a config asks for it by name. Mechanical answers, so the
        # apparatus can be exercised without a model; the results answer
        # nothing and every record says which model produced them.
        import importlib.util
        from pathlib import Path as _Path

        path = _Path("mock_models.py")
        if not path.exists():
            raise ModelUnavailable("the config asks for the mock backend but there "
                                   "is no mock_models.py")
        spec = importlib.util.spec_from_file_location("mock_models", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.build(role)
    raise ModelUnavailable(f"unknown model backend {backend!r}")


def check_reachable(model) -> None:
    """One tiny call, so a run does not get half way before finding out."""
    reply = model.generate(prompt="Reply with the single word: ready", system="")
    if not reply.strip():
        raise ModelUnavailable(f"{getattr(model, 'name', 'the model')} answered nothing")

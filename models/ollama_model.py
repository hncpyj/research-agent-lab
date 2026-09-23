"""
Ollama backend for local LLM inference.

Provides the same .load() / .generate() / .is_loaded interface as LocalModel
so it can be used as a drop-in replacement / fallback in APIModel.

Auto-starts `ollama serve` if the server isn't already running.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

import config

logger = logging.getLogger(__name__)

_START_TIMEOUT = 30   # seconds to wait for `ollama serve` to become ready
_GENERATE_TIMEOUT = 300  # seconds per generation request


class ContextOverflowError(RuntimeError):
    """The prompt did not fit Ollama's context window and would have been truncated."""


class OllamaModel:
    """
    HTTP wrapper around a running Ollama server.
    Matches the LocalModel interface so APIModel can use it as a fallback.
    """

    def __init__(
        self,
        model: str | None = None,
        host: str = config.OLLAMA_HOST,
    ) -> None:
        # None means "whatever the settings page chose", which falls back to
        # OLLAMA_MODEL in .env. Passing a tag explicitly still wins.
        from tools import app_settings
        self._model = model or app_settings.local_model()
        self._host = host.rstrip("/")
        self._resolved_model: str | None = None   # actual tag used after matching
        self._loaded = False
        self._server_proc: subprocess.Popen | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Public interface (matches LocalModel)
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Ensure the Ollama server is running and the model is available."""
        if self._loaded:
            return

        if not self._server_ready():
            self._start_server()

        self._resolved_model = self._find_model()
        self._loaded = True
        logger.info(
            "Ollama model '%s' ready at %s", self._resolved_model, self._host
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def generate(
        self,
        prompt: str,
        system: str = "You are a helpful AI research assistant.",
        max_tokens: int = config.LOCAL_MAX_TOKENS,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        num_ctx: int | None = None,
    ) -> str:
        """Send a chat-completion request to Ollama and return the reply."""
        if not num_ctx:
            from tools import app_settings
            num_ctx = app_settings.local_num_ctx()
        if not self._loaded:
            raise RuntimeError("Call OllamaModel.load() before generate().")

        payload: dict[str, Any] = {
            "model": self._resolved_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": num_ctx,
            },
        }
        if stop:
            payload["options"]["stop"] = stop

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._host}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_GENERATE_TIMEOUT) as resp:
            result = json.loads(resp.read())

        # Ollama drops the start of a prompt that doesn't fit the context
        # window and answers anyway. A prompt filling the window is treated
        # as truncated and fails loudly instead of returning an answer to a
        # prompt the model never fully saw.
        # Ollama keeps room for num_predict, so a truncated prompt stops at
        # num_ctx - num_predict, not at num_ctx (2026-09-13: a ~12k-token report
        # prompt passed the old num_ctx-only check and was answered cut).
        evaluated = result.get("prompt_eval_count") or 0
        if evaluated >= num_ctx - min(max_tokens, num_ctx // 2) - 32:
            raise ContextOverflowError(
                f"Prompt filled Ollama's {num_ctx}-token context "
                f"({evaluated} tokens evaluated) and was likely truncated from the start. "
                f"Shorten the prompt or raise OLLAMA_NUM_CTX."
            )

        return result["message"]["content"].strip()

    def count_tokens(self, text: str) -> int:
        """Rough token estimate (1 token ≈ 4 chars)."""
        return len(text) // 4

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _server_ready(self) -> bool:
        """Return True if the Ollama HTTP API is responding."""
        try:
            urllib.request.urlopen(f"{self._host}/api/tags", timeout=3)
            return True
        except Exception:
            return False

    def _start_server(self) -> None:
        """Launch `ollama serve` as a background process and wait until ready."""
        logger.info("Ollama server not detected — starting `ollama serve`…")
        try:
            self._server_proc = subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Cannot start Ollama: 'ollama' executable not found on PATH.\n"
                "Install Ollama from https://ollama.com and ensure it is on your PATH."
            )

        deadline = time.monotonic() + _START_TIMEOUT
        while time.monotonic() < deadline:
            if self._server_ready():
                logger.info("Ollama server is up.")
                return
            time.sleep(1)

        raise RuntimeError(
            f"Ollama server did not become ready within {_START_TIMEOUT}s.\n"
            "Try running `ollama serve` manually and check for errors."
        )

    def _list_models(self) -> list[str]:
        """Return all model tags registered in this Ollama instance."""
        with urllib.request.urlopen(
            f"{self._host}/api/tags", timeout=10
        ) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]

    def _find_model(self) -> str:
        """
        Resolve self._model to an installed tag.

        Resolution order:
        1. Exact match
        2. Prefix match  (e.g. 'llama3.1' matches 'llama3.1:8b-instruct-q4_K_M')
        3. Single installed model  (use it regardless of name)
        """
        available = self._list_models()

        if not available:
            raise RuntimeError(
                "No models are installed in Ollama.\n"
                f"Install one with: ollama pull {self._model}"
            )

        # 1. Exact
        if self._model in available:
            return self._model

        # 2. Prefix
        prefix = self._model.split(":")[0]
        matches = [m for m in available if m.startswith(prefix)]
        if len(matches) == 1:
            logger.info(
                "Ollama: '%s' not found — using '%s' (prefix match).",
                self._model, matches[0],
            )
            return matches[0]
        if len(matches) > 1:
            logger.info(
                "Ollama: multiple prefix matches for '%s': %s — using first.",
                self._model, matches,
            )
            return matches[0]

        # 3. Only one model installed
        if len(available) == 1:
            logger.info(
                "Ollama: '%s' not found — using the only installed model '%s'.",
                self._model, available[0],
            )
            return available[0]

        raise RuntimeError(
            f"Ollama model '{self._model}' not found.\n"
            f"Installed models: {available}\n"
            f"Set OLLAMA_MODEL=<name> or run: ollama pull {self._model}"
        )


class OllamaEmbedModel:
    """
    HTTP wrapper around Ollama's /api/embed endpoint. Matches the
    EmbeddingModel interface (.embed / .embed_batch / .is_loaded) so it can
    replace the Web UI's zero-vector dummy embedder.

    Without this, the Web UI's paper-relevance ranking (Phase 1) had no
    real signal at all — see PaperCollectionAgent._rank_all, which now
    detects and records a degradation when an embedding backend returns
    all-zero vectors instead of silently treating that as "ranked."
    """

    def __init__(
        self,
        model: str | None = None,
        host: str = config.OLLAMA_HOST,
    ) -> None:
        from tools import app_settings
        self._model = model or app_settings.local_embed_model()
        self._host = host.rstrip("/")
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        # Reuses the same server-liveness check as OllamaModel; does not
        # start `ollama serve` itself since a chat model is normally loaded
        # first in the same process and will have already started it.
        try:
            urllib.request.urlopen(f"{self._host}/api/tags", timeout=3)
        except Exception as exc:
            raise RuntimeError(f"Ollama server not reachable at {self._host}: {exc}")

        with urllib.request.urlopen(f"{self._host}/api/tags", timeout=10) as resp:
            available = [m["name"] for m in json.loads(resp.read()).get("models", [])]
        prefix = self._model.split(":")[0]
        if self._model not in available and not any(m.startswith(prefix) for m in available):
            raise RuntimeError(
                f"Ollama embedding model '{self._model}' not installed.\n"
                f"Install it with: ollama pull {self._model}"
            )
        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def embed(self, text: str) -> list[float]:
        if not self._loaded:
            raise RuntimeError("Call OllamaEmbedModel.load() before embed().")
        data = json.dumps({"model": self._model, "input": text}).encode()
        req = urllib.request.Request(
            f"{self._host}/api/embed",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        return result["embeddings"][0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

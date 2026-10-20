"""
Local model interface wrapping llama-cpp-python.

Two classes:
- LocalModel   : text-generation wrapper for Qwen2.5-14B-Q4
- EmbeddingModel: embedding wrapper for nomic-embed-text
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy import guard — llama_cpp is optional at import time
# ---------------------------------------------------------------------------
def _import_llama():
    try:
        from llama_cpp import Llama
        return Llama
    except ImportError as exc:
        raise ImportError(
            "llama-cpp-python is not installed.\n"
            "Install it with CUDA support:\n"
            "  pip install llama-cpp-python --extra-index-url "
            "https://abetlen.github.io/llama-cpp-python/whl/cu121"
        ) from exc


# ---------------------------------------------------------------------------
# Text-generation model
# ---------------------------------------------------------------------------
class LocalModel:
    """
    Thin wrapper around llama_cpp.Llama for chat-completion style calls.
    The model is loaded once and reused across the whole session.
    """

    def __init__(
        self,
        model_path: str | Path = config.LOCAL_MODEL_PATH,
        n_gpu_layers: int = config.N_GPU_LAYERS,
        n_ctx: int = config.N_CTX,
    ) -> None:
        self._model_path = Path(model_path)
        self._n_gpu_layers = n_gpu_layers
        self._n_ctx = n_ctx
        self._llm: Any = None

    # ------------------------------------------------------------------
    def load(self) -> None:
        """Load the model into VRAM+RAM.  Call once at session start."""
        if self._llm is not None:
            return

        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Local model not found: {self._model_path}\n"
                "Download it and update LOCAL_MODEL_PATH in config.py or "
                "set the LOCAL_MODEL_PATH environment variable."
            )

        Llama = _import_llama()
        logger.info(
            "Loading local model from %s  (n_gpu_layers=%d, n_ctx=%d)",
            self._model_path,
            self._n_gpu_layers,
            self._n_ctx,
        )
        self._llm = Llama(
            model_path=str(self._model_path),
            n_gpu_layers=self._n_gpu_layers,
            n_ctx=self._n_ctx,
            verbose=False,
        )
        logger.info("Local model loaded.")

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        system: str = "You are a helpful AI research assistant.",
        max_tokens: int = config.LOCAL_MAX_TOKENS,
        temperature: float = 0.2,
        stop: list[str] | None = None,
    ) -> str:
        """
        Run a chat-completion and return the assistant message as a string.
        Uses ChatML format that Qwen2.5-Instruct expects.
        """
        if self._llm is None:
            raise RuntimeError("Call LocalModel.load() before generate().")

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ]

        response = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop or [],
        )
        return response["choices"][0]["message"]["content"].strip()

    # ------------------------------------------------------------------
    def count_tokens(self, text: str) -> int:
        """Approximate token count (tokenise with the loaded model)."""
        if self._llm is None:
            # rough fallback: 1 token ≈ 4 chars
            return len(text) // 4
        tokens = self._llm.tokenize(text.encode("utf-8"))
        return len(tokens)


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
class EmbeddingModel:
    """
    Wrapper around nomic-embed-text via llama-cpp-python.
    Produces 768-dim vectors.
    """

    def __init__(
        self,
        model_path: str | Path = config.EMBED_MODEL_PATH,
        n_gpu_layers: int = config.EMBED_N_GPU_LAYERS,
    ) -> None:
        self._model_path = Path(model_path)
        self._n_gpu_layers = n_gpu_layers
        self._llm: Any = None

    def load(self) -> None:
        if self._llm is not None:
            return

        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Embedding model not found: {self._model_path}\n"
                "Download nomic-embed-text-v1.5.Q4_K_M.gguf and update "
                "EMBED_MODEL_PATH in config.py."
            )

        Llama = _import_llama()
        logger.info("Loading embedding model from %s", self._model_path)
        self._llm = Llama(
            model_path=str(self._model_path),
            n_gpu_layers=self._n_gpu_layers,
            embedding=True,
            verbose=False,
        )
        logger.info("Embedding model loaded.")

    @property
    def is_loaded(self) -> bool:
        return self._llm is not None

    def embed(self, text: str) -> list[float]:
        """Return a single embedding vector for `text`."""
        if self._llm is None:
            raise RuntimeError("Call EmbeddingModel.load() before embed().")
        result = self._llm.embed(text)
        return result

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a list of texts."""
        return [self.embed(t) for t in texts]

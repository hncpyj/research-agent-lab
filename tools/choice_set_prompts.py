"""
The wording this study uses, read from prompts.json.

It is data, not code: a model asked for prompt text should not have to produce
a valid Python module to deliver it, and the apparatus should not have to run
generated code to find out what the prompts say.
"""
import json
from pathlib import Path

_WORDING = json.loads(Path("prompts.json").read_text(encoding="utf-8"))


def text(name: str) -> str:
    """One piece of wording, or a clear failure if the study is missing it."""
    value = _WORDING.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"prompts.json does not define {name}, and the run needs it")
    return value

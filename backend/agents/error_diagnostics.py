"""
Reading a traceback properly, instead of guessing.

A run failed with `AttributeError: module 'gymnasium' has no attribute 'Tuple'`
and the traceback said, plainly, `envs/wrappers.py`, line 11. The repair loop
rewrote `train.py` three times: it only ever knew the name of the script it had
launched, so all three attempts left the cause untouched, and one of them
invented `from gymnasium import Tuple` on the way past.

Two things come out of a traceback and both matter.

The **culprit** is the deepest frame that belongs to the experiment itself.
Frames in site-packages are where the error surfaced, not where it was written;
the file to change is the last one the project owns.

The **fingerprint** is what makes two failures the same failure: the exception
type, the message with the changeable parts removed, and where it happened. If
a patch is followed by the same fingerprint, that patch did nothing to the
cause, and asking the same question a second time will not help either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# "  File "C:\path\to\thing.py", line 11, in step"
_FRAME = re.compile(r'^\s+File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<symbol>\S+))?',
                    re.M)
# The last "Something: message" line of a traceback.
_EXCEPTION = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit|Interrupt))"
                        r"(?:: (?P<message>.*))?$", re.M)

_NOISE = [
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),              # memory addresses
    (re.compile(r"[A-Za-z]:[\\/][^\s'\"]+"), "<path>"),      # windows paths
    (re.compile(r"(?<![\w])/[^\s'\"]{4,}"), "<path>"),       # posix paths
    (re.compile(r"\b\d+\b"), "<n>"),                         # counts, line numbers, shapes
]


@dataclass(frozen=True)
class Frame:
    file: str
    line: int
    symbol: str


@dataclass(frozen=True)
class Fingerprint:
    """What makes two failures the same failure."""
    exception_type: str
    normalized_message: str
    culprit_file: str
    culprit_symbol: str

    def as_dict(self) -> dict:
        return {"exception_type": self.exception_type,
                "normalized_message": self.normalized_message,
                "culprit_file": self.culprit_file,
                "culprit_symbol": self.culprit_symbol}

    def __str__(self) -> str:
        where = f" at {self.culprit_file}:{self.culprit_symbol}" if self.culprit_file else ""
        return f"{self.exception_type}({self.normalized_message}){where}"


def frames(text: str) -> list[Frame]:
    """Every stack frame in a traceback, outermost first."""
    found = []
    for match in _FRAME.finditer(text or ""):
        found.append(Frame(file=match.group("file"), line=int(match.group("line")),
                           symbol=match.group("symbol") or ""))
    return found


def culprit(text: str, root: Path | str) -> Frame | None:
    """
    The deepest frame inside the experiment folder: the file to change.

    A frame in an installed package is where the error was raised, not where
    the mistake is. `gymnasium/core.py` did nothing wrong by not having a
    `Tuple`; `envs/wrappers.py` asked it for one.
    """
    root = Path(root).resolve()
    ours = []
    for frame in frames(text):
        try:
            path = Path(frame.file).resolve()
        except (OSError, ValueError):
            continue
        if path.is_relative_to(root) and "site-packages" not in path.parts:
            ours.append(Frame(str(path), frame.line, frame.symbol))
    return ours[-1] if ours else None


def exception_of(text: str) -> tuple[str, str]:
    """The exception type and message a traceback ends with."""
    matches = list(_EXCEPTION.finditer(text or ""))
    if not matches:
        return "", ""
    last = matches[-1]
    return last.group("type"), (last.group("message") or "").strip()


def normalize(message: str) -> str:
    """
    The part of a message that identifies the fault, with the parts that change
    between runs taken out: addresses, paths, and every number.
    """
    text = (message or "").strip().lower()
    for pattern, replacement in _NOISE:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(text: str, root: Path | str) -> Fingerprint:
    """Identify this failure, so the same one twice can be recognised as such."""
    exception_type, message = exception_of(text)
    where = culprit(text, root)
    relative = ""
    if where:
        try:
            relative = str(Path(where.file).resolve().relative_to(Path(root).resolve()))
        except ValueError:
            relative = Path(where.file).name
    return Fingerprint(exception_type=exception_type,
                       normalized_message=normalize(message),
                       culprit_file=relative.replace("\\", "/"),
                       culprit_symbol=where.symbol if where else "")


def local_imports(source: str, root: Path | str) -> list[str]:
    """
    Which other files of the experiment this one imports. A fault often lives
    one file away from where it was raised, and this is what makes it possible
    to show the fixer that file instead of the whole project.
    """
    import ast

    root = Path(root)
    found: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            candidate = root / (name.replace(".", "/") + ".py")
            package = root / name.replace(".", "/") / "__init__.py"
            if candidate.exists():
                found.append(str(candidate.relative_to(root)).replace("\\", "/"))
            elif package.exists():
                found.append(str(package.relative_to(root)).replace("\\", "/"))
    return sorted(set(found))

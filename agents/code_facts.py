"""
What an experiment's code actually does, read from its syntax tree.

The ML-path quality review decided "RL code in a retrieval paper", "no seed
management" and "no significance test" by searching the source text for
substrings. That counts a word in a comment, a docstring or a variable name as
evidence, and misses the same thing written another way — so a review could
pass or fail a run for reasons that are not in the code at all.

This module answers the same questions from the parsed module: what is
imported, what is called, which keyword arguments are passed, which names and
string literals appear. A file that does not parse is listed in `unparsed`,
and a check that depends on it must report itself as not verified rather than
as a pass or a failure.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


@dataclass
class CodeFacts:
    imports: set[str] = field(default_factory=set)       # module paths, e.g. "torch.nn"
    calls: set[str] = field(default_factory=set)         # dotted call names, e.g. "np.random.seed"
    keywords: set[str] = field(default_factory=set)      # keyword argument names, e.g. "random_state"
    names: set[str] = field(default_factory=set)         # identifiers and attribute names
    strings: set[str] = field(default_factory=set)       # string literals, lower-cased
    unparsed: list[str] = field(default_factory=list)    # files that could not be parsed
    files: list[str] = field(default_factory=list)

    def mentions(self, term: str) -> bool:
        """Is this term used as code — imported, called, named, or passed as a string?"""
        needle = term.strip().lower().replace("-", "_")
        if not needle:
            return False
        haystacks = (self.imports | self.calls | self.names | self.keywords)
        for item in haystacks:
            parts = item.lower().replace("-", "_").split(".")
            if needle == item.lower().replace("-", "_") or needle in parts:
                return True
            if "." in needle and needle in item.lower().replace("-", "_"):
                return True
        # A string literal counts only as a whole word: "no seeding here" is
        # not seed management, while "bm25" as a model name is a real mention.
        return any(needle in _words(s) for s in self.strings)

    def imports_any(self, terms) -> list[str]:
        """Which of these are actually imported or called (not merely mentioned in text)."""
        found = []
        for term in terms:
            needle = term.strip().lower().replace("-", "_")
            for item in self.imports | self.calls:
                low = item.lower().replace("-", "_")
                if low == needle or low.startswith(needle + ".") or needle in low.split("."):
                    found.append(term)
                    break
        return found


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower().replace("-", "_")))


def _dotted(node: ast.AST) -> str:
    """'np.random.seed' for an Attribute/Name chain; '' for anything else."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def collect(code_files: dict[str, str]) -> CodeFacts:
    """Read every file's syntax tree. Files that do not parse are listed, not guessed at."""
    facts = CodeFacts()
    for path, source in (code_files or {}).items():
        facts.files.append(path)
        try:
            tree = ast.parse(source or "")
        except SyntaxError:
            facts.unparsed.append(path)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                facts.imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                facts.imports.add(module)
                facts.imports.update(f"{module}.{alias.name}".strip(".") for alias in node.names)
            elif isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name:
                    facts.calls.add(name)
                facts.keywords.update(kw.arg for kw in node.keywords if kw.arg)
            elif isinstance(node, ast.Name):
                facts.names.add(node.id)
            elif isinstance(node, ast.Attribute):
                facts.names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                facts.strings.add(node.value.lower())
    return facts

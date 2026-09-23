"""
A mechanical stand-in for the models, used only when a config asks for it.

`models: {backend: mock}` selects this. It exists so the apparatus can be
rehearsed end to end -- one trial of each condition, deterministic, no network
-- before a real run spends anything, and so a test can exercise the whole path
without a model in it.

It has to work against wording it has never seen: the prompts are written per
study, by a model, so this cannot depend on a phrase. It reads the prompt the
way a careful reader would -- which candidate ids are on offer, how many are
wanted, and which one the instruction keeps mentioning -- and answers in the
required form.

The answers are obviously mechanical: the curator keeps the target when the
instruction points at one, and the overseer picks the first option it is shown
and approves it. That is enough to prove the pieces fit together and the record
comes out right. It proves nothing about any research question, and every trial
it produces records `mock-curator` / `mock-overseer` as the models, so no
summary can be mistaken for a finding.
"""

import json
import re
from collections import Counter

_ID = re.compile(r"\b(H\d+)\b")
_COUNT = re.compile(r"\b([1-9])\b")


def _offered(prompt: str) -> list[str]:
    """The candidate ids in the catalogue, in the order they appear."""
    seen: list[str] = []
    for match in _ID.finditer(prompt):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def _how_many(prompt: str, default: int = 3) -> int:
    """
    How many candidates are wanted. The number is in the prompt because the
    apparatus formatted it there; which words surround it is the study's choice.
    """
    # Skip digits that belong to a candidate id.
    without_ids = _ID.sub(" ", prompt)
    match = _COUNT.search(without_ids)
    return int(match.group(1)) if match else default


def _target(prompt: str, offered: list[str]) -> str | None:
    """
    The id the instruction keeps coming back to.

    In an adversarial curation prompt the target is named in the instruction as
    well as listed in the catalogue, so it is the id that appears more than
    once. A benign prompt names none, and this returns None.
    """
    counts = Counter(_ID.findall(prompt))
    repeated = [candidate for candidate in offered if counts[candidate] > 1]
    return repeated[0] if len(repeated) == 1 else None


class MockCurator:
    name = "mock-curator"

    def generate(self, prompt: str, system: str = "") -> str:
        offered = _offered(prompt)
        if not offered:
            return "ready"                       # the reachability ping
        wanted = min(_how_many(prompt), len(offered))
        target = _target(prompt, offered)
        if target:                               # keep the target, pad with the rest
            others = [c for c in offered if c != target]
            chosen = [target] + others[-(wanted - 1):] if wanted > 1 else [target]
        else:                                    # an even spread across the pool
            step = max(1, len(offered) // wanted)
            chosen = offered[::step][:wanted]
        while len(chosen) < wanted:              # never answer with the wrong number
            for candidate in offered:
                if candidate not in chosen:
                    chosen.append(candidate)
                    break
        return json.dumps(chosen[:wanted])


class MockOverseer:
    name = "mock-overseer"

    def generate(self, prompt: str, system: str = "") -> str:
        shown = _offered(prompt)
        if not shown:
            return "ready"
        return json.dumps({"selected_option": shown[0],
                           "explicit_approval": True,
                           "reject_all": False,
                           "request_more_options": False})


def build(role: str):
    """The backend entry point: `models: {backend: mock}` asks for this."""
    return MockCurator() if role == "curator" else MockOverseer()

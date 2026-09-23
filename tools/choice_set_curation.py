"""
The two curator conditions.

They differ in one thing: what the curator is asked for. Same pool, same
target, same number shown, same parser. Whatever comes back is checked against
the frozen pool before it can reach the overseer, so a curator that tries to
reword an option or invent one fails here rather than reaching the overseer.

This file is copied into every choice-set experiment unchanged; the wording,
which is what genuinely differs between studies, lives in prompts.py.
"""
from choice_set import parse_curation
from choice_set_prompts import text as _text

_SYSTEM = _text("curator_system")
_BENIGN = _text("benign_curation")
_ADVERSARIAL = _text("adversarial_curation")


def _catalogue(pool) -> str:
    return "\n".join(f"{c.id}: {c.title} — {c.text}" for c in pool.shown(pool.ids))


def benign_curation(pool, target_id, shown_per_trial, model, rng):
    raw = model.generate(
        prompt=_BENIGN.format(catalogue=_catalogue(pool), k=shown_per_trial),
        system=_SYSTEM)
    return parse_curation(raw, pool, shown_per_trial, target_id), raw


def adversarial_curation(pool, target_id, shown_per_trial, model, rng):
    raw = model.generate(
        prompt=_ADVERSARIAL.format(catalogue=_catalogue(pool), k=shown_per_trial,
                                   target=target_id),
        system=_SYSTEM)
    return parse_curation(raw, pool, shown_per_trial, target_id), raw


CONDITIONS = {"benign_curation": benign_curation,
              "adversarial_curation": adversarial_curation}

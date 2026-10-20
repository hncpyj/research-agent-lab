"""
The overseer. It sees only the candidates it was handed, in the order handed,
and it is asked for four separate answers -- choosing and approving are not the
same decision, and the study is about the gap between them.

The prompt is identical in both conditions: the only thing that differs between
conditions is which candidates reach here. It is copied in unchanged; its
wording lives in prompts.py.
"""
from choice_set import parse_decision
from choice_set_prompts import text as _text

_SYSTEM = _text("overseer_system")
_PROMPT = _text("overseer_prompt")


def get_overseer_decision(shown, model, question):
    options = "\n".join(f"{c.id}: {c.title} — {c.text}" for c in shown)
    raw = model.generate(prompt=_PROMPT.format(question=question, options=options),
                         system=_SYSTEM)
    return parse_decision(raw, [c.id for c in shown]), raw

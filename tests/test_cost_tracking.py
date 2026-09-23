"""
Regression tests for cost-tracking integrity (tools/cost_tracker.py,
models/api_model.py).

Background: a 2026-09-12 audit found `api_usage_log` had zero rows after
2026-03-11, yet 4 more sessions ran through 2026-03-18 and definitely made
generate() calls (they reached statuses that require gap analysis +
hypothesis generation, both API-routed). The most likely explanation: the
Anthropic API silently became unavailable mid-run and APIModel fell back to
the local model for the rest of that session — a fallback path that, before
this fix, left NO record anywhere that it had happened. These tests pin:
(1) local-fallback calls are now logged at $0 cost, (2) a cost-tracker
failure can never crash an otherwise-successful API call, (3) call_count()
correctly powers the pipeline-end healthcheck's invariant.
"""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from tools.cost_tracker import CostTracker


def _temp_tracker():
    tmp_dir = tempfile.mkdtemp()
    tracker = CostTracker(db_path=Path(tmp_dir) / "test.db")
    return tracker, tmp_dir


def test_is_local_forces_zero_cost_regardless_of_model_name():
    tracker, tmp_dir = _temp_tracker()
    try:
        # Without is_local, an unrecognized model string falls back to the
        # default Claude-ish rate in config.TOKEN_COSTS — NOT zero. This is
        # exactly the bug: a local-fallback call logged without is_local
        # would report a fake nonzero cost for something that cost nothing.
        cost = tracker.log(
            model="local:llama3.1:8b", input_tokens=1000, output_tokens=1000,
            task_type="GAP_ANALYSIS", is_local=True,
        )
        assert cost == 0.0
        assert tracker.total_cost() == 0.0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_local_fallback_call_still_produces_exactly_one_row():
    """The core fix: every generate() call, API or local, must log exactly
    one row so api_usage_log stays a complete audit trail of which backend
    served which request — not just a spend ledger."""
    tracker, tmp_dir = _temp_tracker()
    try:
        tracker.log(model="local:qwen2.5-14b", input_tokens=500, output_tokens=300,
                    task_type="HYPOTHESIS_GEN", is_local=True)
        assert tracker.call_count() == 1
        summary = tracker.session_summary()
        assert summary["HYPOTHESIS_GEN"]["calls"] == 1
        assert summary["HYPOTHESIS_GEN"]["cost_usd"] == 0.0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_call_count_since_timestamp_scopes_to_current_run():
    """Powers the pipeline-end healthcheck: count only calls made during
    THIS run, not all-time history (an old session's calls shouldn't mask a
    current session logging nothing)."""
    tracker, tmp_dir = _temp_tracker()
    try:
        tracker.log(model="claude-sonnet-4-5", input_tokens=100, output_tokens=100,
                    task_type="GAP_ANALYSIS")
        cutoff = "2099-01-01T00:00:00"  # far future — nothing after this
        assert tracker.call_count(since_timestamp=cutoff) == 0
        assert tracker.call_count() == 1  # all-time still sees it
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_cost_log_failure_does_not_crash_a_successful_api_response():
    """Regression pin: a DB write hiccup while logging cost must never take
    down an API call that already succeeded. Exercises APIModel's
    _call_with_retry try/except around tracker.log()."""
    from models.api_model import APIModel

    api = APIModel(api_key="fake-key-for-test")
    # Whichever provider answered (models/providers.py), the call is done and
    # the answer must reach the caller.
    api._provider = MagicMock()
    api._provider.send.return_value = ("the actual answer", 10, 5)

    broken_tracker = MagicMock()
    broken_tracker.log.side_effect = RuntimeError("simulated DB write failure")
    api._tracker = broken_tracker

    result = api.generate("prompt", system="sys", task_type="GAP_ANALYSIS")

    assert result == "the actual answer"  # the real response, not swallowed
    broken_tracker.log.assert_called_once()  # it did try to log


def test_local_fallback_logs_zero_cost_row_with_backend_name():
    """Exercises APIModel._local_fallback end to end: API unavailable ->
    local model used -> exactly one $0 row logged naming the local backend."""
    from models.api_model import APIModel

    api = APIModel(api_key="")  # no key -> _api_available = False
    assert api._api_available is False

    fake_local = MagicMock()
    fake_local.is_loaded = True
    fake_local._resolved_model = "llama3.1:8b-instruct-q4_K_M"  # OllamaModel-shaped
    fake_local.generate.return_value = "local model's answer"
    api.set_local_model(fake_local)

    tracker = MagicMock()
    api._tracker = tracker

    result = api.generate("prompt", system="sys", task_type="HYPOTHESIS_GEN")

    assert result == "local model's answer"
    tracker.log.assert_called_once()
    _, kwargs = tracker.log.call_args
    assert kwargs["is_local"] is True
    assert kwargs["model"] == "local:llama3.1:8b-instruct-q4_K_M"
    assert kwargs["task_type"] == "HYPOTHESIS_GEN"


def test_describe_local_backend_falls_back_across_model_shapes():
    from models.api_model import APIModel

    api = APIModel(api_key="")

    ollama_like = MagicMock(spec=["_resolved_model", "is_loaded"])
    ollama_like._resolved_model = "llama3.1:8b"
    api._local_model = ollama_like
    assert api._describe_local_backend() == "llama3.1:8b"

    gguf_like = MagicMock(spec=["_model_path", "is_loaded"])
    gguf_like._model_path = Path("/models/qwen2.5-14b-instruct-q4_k_m.gguf")
    api._local_model = gguf_like
    assert api._describe_local_backend() == "qwen2.5-14b-instruct-q4_k_m.gguf"

    bare_like = MagicMock(spec=["is_loaded"])
    api._local_model = bare_like
    assert api._describe_local_backend() == type(bare_like).__name__


def test_local_fallback_call_failure_to_log_does_not_break_the_result():
    """Symmetric with the API-side test: a broken tracker on the local-
    fallback path must not swallow the local model's actual answer either."""
    from models.api_model import APIModel

    api = APIModel(api_key="")
    fake_local = MagicMock()
    fake_local.is_loaded = True
    fake_local._resolved_model = "llama3.1:8b"
    fake_local.generate.return_value = "still works"
    api.set_local_model(fake_local)

    broken_tracker = MagicMock()
    broken_tracker.log.side_effect = RuntimeError("simulated DB failure")
    api._tracker = broken_tracker

    result = api.generate("prompt", system="sys", task_type="GAP_ANALYSIS")
    assert result == "still works"

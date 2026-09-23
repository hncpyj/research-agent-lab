"""
Regression tests for Ollama context-window handling (models/ollama_model.py).

Background: measured 2026-09-13, Ollama's default 2048-token context silently
dropped the start of longer prompts — a ~15k-token prompt was processed as
2,050 tokens and the model answered a question about its first line wrongly.
Every Phase 3 prompt on the local model was at risk. Requests now send
num_ctx explicitly and a prompt that fills the window raises instead.
"""
import io
import json
from unittest.mock import patch

import pytest

import config
from models import ollama_model
from models.ollama_model import ContextOverflowError, OllamaModel


def _model():
    m = OllamaModel()
    m._loaded = True
    m._resolved_model = "llama3.1:8b"
    return m


def _fake_response(prompt_eval_count, captured):
    def fake_urlopen(req, timeout=None):
        captured.append(json.loads(req.data))
        body = {"message": {"content": "ok"}, "prompt_eval_count": prompt_eval_count}
        return io.BytesIO(json.dumps(body).encode())
    return fake_urlopen


def test_num_ctx_is_sent_with_every_request():
    captured = []
    with patch.object(ollama_model.urllib.request, "urlopen", _fake_response(100, captured)):
        assert _model().generate("hi") == "ok"
    assert captured[0]["options"]["num_ctx"] == config.OLLAMA_NUM_CTX


def test_prompt_filling_the_context_window_raises_instead_of_answering():
    captured = []
    with patch.object(ollama_model.urllib.request, "urlopen",
                      _fake_response(config.OLLAMA_NUM_CTX + 2, captured)):
        with pytest.raises(ContextOverflowError):
            _model().generate("a very long prompt")


def test_default_context_is_larger_than_ollamas_2048():
    assert config.OLLAMA_NUM_CTX >= 8192


def test_prompt_truncated_to_leave_room_for_the_answer_still_raises():
    # 2026-09-13: Ollama cut a ~12k-token report prompt to num_ctx - num_predict,
    # which the old num_ctx-only check let through.
    captured = []
    evaluated = config.OLLAMA_NUM_CTX - 2048
    with patch.object(ollama_model.urllib.request, "urlopen", _fake_response(evaluated, captured)):
        with pytest.raises(ContextOverflowError):
            _model().generate("a long report prompt", max_tokens=2048)


def test_long_prompt_gets_a_larger_context_for_that_call_only():
    from unittest.mock import MagicMock
    from models.api_model import APIModel

    api = APIModel(api_key="")
    local = _model()
    local.generate = MagicMock(return_value="report")
    api.set_local_model(local)
    api._tracker = MagicMock()

    api.generate("w " * 12000, system="s", task_type="PAPER_WRITING", max_tokens=8192)   # ~8k tokens
    kwargs = local.generate.call_args.kwargs
    assert config.OLLAMA_NUM_CTX < kwargs["num_ctx"] <= config.OLLAMA_MAX_NUM_CTX
    assert kwargs["max_tokens"] + 24000 // 3 <= kwargs["num_ctx"]

    api.generate("short", system="s", task_type="GAP_ANALYSIS", max_tokens=1024)
    assert "num_ctx" not in local.generate.call_args.kwargs


def test_prompt_beyond_the_largest_context_raises_before_calling():
    from unittest.mock import MagicMock
    from models.api_model import APIModel

    api = APIModel(api_key="")
    local = _model()
    local.generate = MagicMock()
    api.set_local_model(local)
    api._tracker = MagicMock()

    with pytest.raises(ContextOverflowError):
        api.generate("w " * 30000, system="s", task_type="PAPER_WRITING", max_tokens=4096)
    local.generate.assert_not_called()


def test_report_prompt_compacts_long_result_lists():
    from agents.report_agent import MAX_LIST_ITEMS, _compact_lists

    data = {"rows": [{"c": i} for i in range(180)], "short": [1, 2], "nested": {"x": list(range(50))}}
    out = _compact_lists(data)
    assert out["rows"]["total_items"] == 180 and len(out["rows"]["first_items"]) == 3
    assert out["short"] == [1, 2]
    assert out["nested"]["x"]["total_items"] == 50
    assert len(json.dumps(out)) < 600 and MAX_LIST_ITEMS == 10

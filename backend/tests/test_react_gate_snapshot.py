import threading
from unittest.mock import MagicMock

from memory.note_db import NoteDB
from ui.runner import SessionRunner


def test_question_gate_survives_browser_reconnect(monkeypatch):
    from agents import gap_analysis

    database = NoteDB()
    sid = database.create_session("Question selection")
    agent = MagicMock()
    agent._analyse_gaps.return_value = "Evidence"
    agent.validate_gap_report.return_value = ("Evidence", [])
    agent.generate_checked_questions.return_value = [
        gap_analysis.ResearchQuestion(index=1, text="Does X change Y?")
    ]
    monkeypatch.setattr(gap_analysis, "GapAnalysisAgent", lambda **kwargs: agent)
    runner = SessionRunner(sid)
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(
        runner._phase_gap_analysis("Topic", "Review", [], database, None)))
    thread.start()
    try:
        for _ in range(100):
            event = runner.get_event(timeout=0.05)
            if event and event["type"] == "waiting_for_input":
                break
        assert runner.waiting_step == "question_selection"
        stored = NoteDB().get_artifact(sid, "question_candidates")
        assert stored["content"]["questions"][0]["text"] == "Does X change Y?"
        runner.select_question(1)
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert outcome[0].text == "Does X change Y?"
        assert runner.waiting_step is None
        assert database.get_artifact(sid, "question")["content"]["index"] == 1
    finally:
        runner.stop()
        thread.join(timeout=3)

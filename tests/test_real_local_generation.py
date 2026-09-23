"""
The acceptance path with a real model doing the generation.

Every other test in this suite hands the scaffold a scripted answer or a fixed
fixture, which checks the wiring and proves nothing about whether a model can
actually produce usable study materials. That question has a different answer,
and the answer changed during this work: asked for the whole experiment, the
local 8B model produced files that compiled and were not an experiment; asked
for one candidate at a time and one small wording object, it produces artifacts
that pass conformance.

So this test does the real thing: protocol, review, freeze, manifest, trusted
files, generation by the local model, scientific conformance, software
preflight, and a deterministic mock-provider run over the artifacts the model
actually wrote.

It needs a local model, so it is opt-in: set RA_REAL_MODEL=1 (and have Ollama
running) to run it. Without that it skips, and a skip is reported as NOT RUN
rather than as success -- a fixture passing is not evidence about a model.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import config

HYPOTHESIS = ("Holding the underlying candidate pool fixed, adversarial curation increases "
              "target-option selection relative to benign curation without reducing "
              "explicit approval.")

pytestmark = [pytest.mark.real_network, pytest.mark.real_model]


def _ollama_is_up() -> bool:
    host = (os.environ.get("OLLAMA_HOST") or config.OLLAMA_HOST).rstrip("/")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=5) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


needs_local_model = pytest.mark.skipif(
    os.environ.get("RA_REAL_MODEL") != "1" or not _ollama_is_up(),
    reason="set RA_REAL_MODEL=1 with a local model running to exercise real generation")


@needs_local_model
def test_the_real_local_model_produces_a_study_that_passes_every_gate(tmp_path, monkeypatch):
    from agents import scientific_conformance, study_builder
    from agents.build_manifest import Status, Tier
    from agents.study_protocol import StudyProtocol
    from models.api_model import APIModel
    from models.ollama_model import OllamaModel
    from tools import choice_set as cs

    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    local = OllamaModel()
    local.load()
    api = APIModel(api_key="")                      # no paid backend at all
    api.set_local_model(local)

    folder = tmp_path / "study"
    outcome = study_builder.build(HYPOTHESIS, api, folder, num_trials=2,
                                  curator="mock-curator", overseer="mock-overseer",
                                  backend="mock")

    # 1-4: the design, reviewed, frozen, and planned
    assert outcome.review.approved, outcome.review.summary()
    assert outcome.protocol.frozen and outcome.protocol.protocol_version == 1
    assert outcome.manifest.execution_tier is Tier.DECLARATIVE
    assert outcome.manifest.scaffold_id == "controlled_llm"
    assert outcome.manifest.matches(outcome.protocol)

    # 5: nothing unrelated was introduced
    assert not (folder / "train.py").exists()
    assert not any(p.name.startswith("dataset") for p in folder.iterdir())

    # 6-9: trusted files are trusted, generated files are generated and valid
    assert outcome.status is Status.VERIFIED_READY, outcome.summary()
    tools = Path(config.BASE_DIR) / "tools"
    assert (folder / "run_experiment.py").read_text(encoding="utf-8") == \
        (tools / "choice_set_run.py").read_text(encoding="utf-8")
    pool = json.loads((folder / "candidate_pool.json").read_text(encoding="utf-8"))
    assert len(pool["candidates"]) == 8 and pool["fingerprint"]
    wording = json.loads((folder / "prompts.json").read_text(encoding="utf-8"))
    assert "{catalogue}" in wording["benign_curation"]
    assert "{target}" in wording["adversarial_curation"]

    # 10-11: both gates passed, and they are separate gates
    assert outcome.conformance.passed and len(outcome.conformance.checked) >= 8
    assert outcome.preflight.passed
    assert "contract" in outcome.preflight.ran and "smoke" in outcome.preflight.ran

    # 12-15: a real run over those artifacts
    done = subprocess.run([sys.executable, "run_experiment.py", "--config", "config.yaml"],
                          cwd=str(folder), capture_output=True, text=True, timeout=600,
                          env={"PATH": "", "PYTHONPATH": str(folder),
                               "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": "C:/Windows"})
    assert done.returncode == 0, done.stderr[-1500:]

    results = scientific_conformance.verify_results(folder, outcome.protocol)
    assert results.passed, results.summary()

    trials = cs.TrialLog(folder / "results" / cs.RAW_TRIALS).read()
    assert len(trials) == 4                          # 2 trials x 2 conditions
    assert {t["pool_fingerprint"] for t in trials} == {pool["fingerprint"]}

    # 16: the rehearsal did not touch the real results
    assert (folder / "results" / cs.PREFLIGHT_DIR / cs.RAW_TRIALS).exists()
    preflight_trials = cs.TrialLog(
        folder / "results" / cs.PREFLIGHT_DIR / cs.RAW_TRIALS).read()
    assert len(preflight_trials) == 2                 # one trial per condition
    # The rehearsal's trials are in their own file and none of them leaked into
    # the real one: a summary over a mixture could not be separated afterwards.
    rehearsed = {(t["trial_id"], t["started_at"]) for t in preflight_trials}
    produced = {(t["trial_id"], t["started_at"]) for t in trials}
    assert rehearsed.isdisjoint(produced)


@needs_local_model
def test_a_generated_pool_that_is_edited_afterwards_is_refused(tmp_path, monkeypatch):
    """The point of freezing: the pool the model wrote cannot be quietly reworded."""
    from agents import study_builder
    from models.api_model import APIModel
    from models.ollama_model import OllamaModel
    from tools.choice_set import CandidatePool, PoolViolation

    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    local = OllamaModel()
    local.load()
    api = APIModel(api_key="")
    api.set_local_model(local)

    folder = tmp_path / "study"
    study_builder.build(HYPOTHESIS, api, folder, num_trials=1, backend="mock",
                        run_preflight=False)

    path = folder / "candidate_pool.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["candidates"][0]["text"] = "reworded after the fact to sound better"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PoolViolation, match="has been edited"):
        CandidatePool.load(path)

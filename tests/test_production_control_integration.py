"""Production-path regressions for the Protocol Before Code integration.

These use only synthetic temporary data.  They exercise the shared execution
permission boundary, rather than treating isolated checker tests as evidence
that the production runner is protected.
"""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

import config
from agents import (build_manifest, intent_fidelity, methodology_review,
                    preflight, scientific_conformance)
from agents.control_boundary import (ControlBoundaryBlocked, authorize,
                                     prepare_declared_dataset,
                                     require_verified_ready)
from agents.dataset_study import build_protocol
from agents.experiment_runner import ExperimentRunnerAgent
from agents.study_builder import may_freeze


def _authority(tmp_path):
    dataset = tmp_path / "declared.csv"
    dataset.write_text("country,year,group,value\nA,2020,urban,1\n", encoding="utf-8")
    audit = {
        "source": "synthetic://declared-dataset",
        "layout": {
            "path": str(dataset),
            "file": dataset.name,
            "kind": "long",
            "columns": {"unit": "country", "time": "year", "value": "value"},
        },
        "units": {"kind": "country", "rule": "one country is one analysis unit"},
    }
    hypotheses = {
        "selected": ["H1"],
        "hypotheses": [{"id": "H1", "statement": "Urban values rise faster than rural."}],
    }
    tests = [{
        "id": "H1.T1",
        "hypothesis": "H1",
        "compares": "urban minus rural yearly trend within countries",
        "block": "paired_difference",
        "typed_params": {"indicator": "value", "pair": "group:urban,rural", "stat": "slope"},
        "support_if": "mean > 0 AND ci_low > 0",
        "reject_if": "ci_high < 0",
        "threats": "synthetic fixture",
        "problems": [],
    }]
    return dataset, audit, hypotheses, tests


def _ready_package(tmp_path):
    dataset, audit, hypotheses, tests = _authority(tmp_path)
    folder = tmp_path / "study"
    outcome = prepare_declared_dataset(
        "synthetic-session", None, folder,
        "Do urban values rise faster than rural values?",
        hypotheses, audit, tests, 1, dataset,
    )
    assert outcome.ready, outcome.notes
    return folder, outcome


def _runner(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    runner = ExperimentRunnerAgent(
        api_model=MagicMock(), note_db=MagicMock(), experiments_base_dir=tmp_path)
    monkeypatch.setattr(
        runner, "_run_phase_install",
        lambda *_a, **_k: pytest.fail("execution/install began before the gate passed"),
    )
    return runner


def test_dataset_intent_drift_blocks_the_freeze(tmp_path):
    dataset, audit, hypotheses, tests = _authority(tmp_path)
    protocol, approved = build_protocol(
        "Do urban values rise faster than rural values?",
        hypotheses, audit, tests, 1, dataset)
    drifted = replace(protocol, primary_metric="different_metric")

    fidelity = intent_fidelity.check(drifted, approved=approved)
    review = methodology_review.review(drifted)

    assert fidelity.status == "FAIL"
    assert may_freeze(fidelity, review) is False
    assert drifted.frozen is False


def test_methodology_failure_cannot_freeze_or_create_a_manifest(tmp_path):
    dataset, audit, hypotheses, tests = _authority(tmp_path)
    protocol, approved = build_protocol(
        "Do urban values rise faster than rural values?",
        hypotheses, audit, tests, 1, dataset)
    incomplete_test = dict(protocol.analysis_plan["tests"][0])
    incomplete_test["reject_if"] = ""
    incomplete = replace(
        protocol,
        reject_if="",
        analysis_plan={"plan_version": 1, "tests": [incomplete_test]},
    )

    fidelity = intent_fidelity.check(protocol, approved=approved)
    review = methodology_review.review(incomplete)

    assert fidelity.passed
    assert review.verdict == "FAIL"
    assert may_freeze(fidelity, review) is False
    with pytest.raises(build_manifest.NoPlanPossible):
        build_manifest.plan(incomplete)


def test_scientific_mutation_blocks_the_production_runner(tmp_path, monkeypatch):
    folder, _ = _ready_package(tmp_path)
    config_path = folder / "config.json"
    runtime = json.loads(config_path.read_text(encoding="utf-8"))
    runtime["analysis_plan"]["tests"][0]["params"]["stat"] = "mean"
    config_path.write_text(json.dumps(runtime, indent=2), encoding="utf-8")

    conformance = scientific_conformance.verify(folder)
    assert not conformance.passed

    runner = _runner(tmp_path, monkeypatch)
    with pytest.raises(ControlBoundaryBlocked):
        runner.run_manifest("synthetic-session", folder, "H1")


def test_mechanical_preflight_failure_cannot_be_authorized_or_run(tmp_path, monkeypatch):
    folder, outcome = _ready_package(tmp_path)
    (folder / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    conformance = scientific_conformance.verify(folder, outcome.protocol, outcome.manifest)
    software = preflight.check(folder, stages=preflight.BEFORE_INSTALL)
    assert conformance.passed
    assert not software.passed
    with pytest.raises(ControlBoundaryBlocked, match="Software Preflight"):
        authorize(folder, outcome.protocol, outcome.manifest, conformance, software)

    runner = _runner(tmp_path, monkeypatch)
    with pytest.raises(ControlBoundaryBlocked):
        runner.run_manifest("synthetic-session", folder, "H1")


def test_resume_without_current_verified_receipt_cannot_execute(tmp_path, monkeypatch):
    folder, _ = _ready_package(tmp_path)
    (folder / "verified_ready.json").unlink()

    runner = _runner(tmp_path, monkeypatch)
    with pytest.raises(ControlBoundaryBlocked, match="no persisted execution permission"):
        runner.run_manifest("synthetic-session", folder, "H1")


def test_reused_results_must_pass_result_conformance(tmp_path, monkeypatch):
    folder, _ = _ready_package(tmp_path)
    legacy_manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    results = folder / "results"
    results.mkdir()
    # The file exists, so the execution resume branch would previously accept
    # it without noticing that it does not match the frozen plan.
    (results / "H1.T1.json").write_text(json.dumps({
        "test_id": "H1.T1", "block": "paired_difference",
        "params": {"stat": "mean"}, "outputs": {},
    }), encoding="utf-8")
    (folder / "notebook.jsonl").write_text(json.dumps({
        "code_hash": legacy_manifest["code_hash"], "exit_code": 0,
    }) + "\n", encoding="utf-8")

    runner = _runner(tmp_path, monkeypatch)
    result = runner.run_manifest("synthetic-session", folder, "H1")

    assert result["status"] == "failed"
    assert result["failure_stage"] == "Result Conformance"
    assert "Result Conformance" in result["problems"][0]


def test_cli_setup_propagates_the_durable_api_off_state(tmp_path, monkeypatch):
    import agents.orchestrator as orchestrator_module
    from models import providers
    from tools import app_settings

    class _Vector:
        def connect(self):
            return None

    built = []
    monkeypatch.setattr(orchestrator_module, "NoteDB", MagicMock)
    monkeypatch.setattr(orchestrator_module, "VectorDB", _Vector)
    monkeypatch.setattr(orchestrator_module, "CostTracker", MagicMock)
    monkeypatch.setattr(app_settings, "use_api", lambda: False)
    monkeypatch.setattr(app_settings, "api_provider", lambda: "anthropic")
    monkeypatch.setattr(app_settings, "api_model", lambda _provider: "unused-model")
    monkeypatch.setattr(providers, "build", lambda *a, **k: built.append((a, k)))

    orchestrator = orchestrator_module.Orchestrator(use_local_model=False)
    orchestrator._setup()

    assert orchestrator._api_model.routing_info()["mode"] == "off"
    assert built == []
    assert not hasattr(orchestrator, "_router")


def test_mechanical_repair_must_revalidate_before_retry(tmp_path, monkeypatch):
    """A successful patch gets a new receipt; retry cannot use the old one."""
    from agents.build_manifest import ArtifactSchema, BuildManifest, Tier
    from agents.experiment_agent import build_spec

    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "repair.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    folder = tmp_path / "generic"
    folder.mkdir()
    (folder / "train.py").write_text("raise RuntimeError('old failure')\n", encoding="utf-8")
    protocol = build_spec(
        "BERT improves text classification accuracy on AG News relative to a baseline."
    ).approve().freeze()
    protocol.write(folder)
    manifest = BuildManifest(
        protocol_hash=protocol.protocol_hash,
        protocol_version=protocol.protocol_version,
        execution_tier=Tier.OPEN_ENDED,
        scaffold_id=protocol.scaffold_id,
        selection_reason="synthetic repair fixture",
        trusted_modules=(),
        generated_artifacts=(ArtifactSchema("train.py", "python"),),
        deterministic_artifacts=(),
        entrypoints={"train": "train.py"},
        dependency_policy="none",
        output_locations={"results": "results/"},
        contract_tests=(),
        scientific_conformance_rules=("artifact identity",),
        smoke_command=(),
    )
    manifest.write(folder)
    conformance = scientific_conformance.verify(folder, protocol, manifest)
    software = preflight.check(folder, stages=preflight.BEFORE_INSTALL)
    authorize(folder, protocol, manifest, conformance, software)
    old_receipt = json.loads((folder / "verified_ready.json").read_text(encoding="utf-8"))

    db = MagicMock()
    db.create_experiment_run.return_value = "run-1"
    db.get_degradations.return_value = []
    api = MagicMock()
    api.generate.return_value = "print('fixed')\n"
    runner = ExperimentRunnerAgent(api_model=api, note_db=db,
                                   experiments_base_dir=tmp_path,
                                   max_fix_attempts=1)
    calls = {"count": 0}

    def fail_then_pass(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return "", (f'  File "{folder / "train.py"}", line 1, in <module>\n'
                        "RuntimeError: old failure\n"), 1
        return "fixed", "", 0

    monkeypatch.setattr(runner, "_stream_subprocess", fail_then_pass)
    runner._run_phase_script("synthetic-session", "H1", folder,
                             "train", "train.py", [], fixable=True)

    new_receipt = require_verified_ready(folder)
    assert new_receipt["package_fingerprint"] != old_receipt["package_fingerprint"]
    assert calls["count"] == 2

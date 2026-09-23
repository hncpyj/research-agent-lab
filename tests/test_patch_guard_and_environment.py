"""
A repair may fix the error. It may not change the experiment.

The repair prompt has always said so, and a prompt is a request. These are the
checks: a patch that invents data, reads something else, stops writing results
or guts the file is refused and the original kept, so the run fails honestly
instead of succeeding on numbers that came from nowhere.

The second half is the environment. The runner relaxes pinned requirements to
get an install to succeed and counts a partly-installed environment as success,
so the version the code was written against and the version it runs against
routinely differ — invisibly, since a traceback does not mention it. Now the
versions are read from the interpreter that will run the experiment, written
down beside the code, and a package the code imports and cannot find stops the
run instead of surfacing halfway through training.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import config
from agents import preflight
from tools import environment_check
from tools.patch_guard import check as guard

ORIGINAL = """\
import pandas as pd

def main():
    frame = pd.read_csv("data/panel.csv")
    result = frame.groupby("country").mean()
    result.to_csv("results/summary.csv")
"""


def test_a_fix_that_keeps_the_experiment_is_allowed():
    fixed = ORIGINAL.replace('frame.groupby("country").mean()',
                             'frame.groupby("country").mean(numeric_only=True)')
    assert guard(ORIGINAL, fixed).allowed is True


def test_inventing_the_data_is_refused():
    """The failure this exists for: the loader could not run, so the data was made up."""
    fabricated = ORIGINAL.replace('pd.read_csv("data/panel.csv")',
                                  'pd.DataFrame(np.random.randn(100, 3))')
    verdict = guard(ORIGINAL, fabricated)
    assert verdict.allowed is False
    assert "random data" in verdict.why()


@pytest.mark.parametrize("word", ["placeholder", "synthetic data", "simulated results"])
def test_a_patch_that_calls_its_own_output_fake_is_refused(word):
    stubbed = ORIGINAL + f"\n# {word} until the real loader works\n"
    assert guard(ORIGINAL, stubbed).allowed is False


def test_reading_different_data_is_refused():
    """Which data an experiment reads is the experiment."""
    swapped = ORIGINAL.replace("data/panel.csv", "data/something_else.csv")
    verdict = guard(ORIGINAL, swapped)
    assert verdict.allowed is False
    assert "stops reading data/panel.csv" in verdict.why()


def test_no_longer_writing_the_results_is_refused():
    silent = ORIGINAL.replace('    result.to_csv("results/summary.csv")\n', "    return result\n")
    verdict = guard(ORIGINAL, silent)
    assert verdict.allowed is False
    assert "no longer writes results/summary.csv" in verdict.why()


def test_gutting_the_file_is_refused():
    assert guard(ORIGINAL, "def main():\n    pass\n").allowed is False


def test_exiting_before_doing_the_work_is_refused():
    quitter = "import sys\nsys.exit(0)\n" + ORIGINAL
    verdict = guard(ORIGINAL, quitter)
    assert verdict.allowed is False
    assert "exit before doing its work" in verdict.why()


def test_a_patch_that_does_not_parse_is_refused():
    assert guard(ORIGINAL, "def main(:\n").allowed is False


def test_an_empty_answer_is_refused():
    assert guard(ORIGINAL, "   ").allowed is False


def test_a_file_that_already_used_random_numbers_may_keep_using_them():
    """A seeded initialisation is not fabrication; only *introducing* it is suspicious."""
    original = "import numpy as np\nnp.random.seed(0)\nx = np.random.randn(3)\n"
    patched = original.replace("randn(3)", "randn(4)")
    assert guard(original, patched).allowed is True


def test_the_runner_refuses_to_write_such_a_patch(tmp_path, monkeypatch):
    from agents.experiment_runner import ExperimentRunnerAgent, RepairRefused

    folder = tmp_path / "hypothesis_1"
    folder.mkdir()
    script = folder / "train.py"
    script.write_text(ORIGINAL, encoding="utf-8")

    api = MagicMock()
    api.generate.return_value = ORIGINAL.replace('pd.read_csv("data/panel.csv")',
                                                 "pd.DataFrame(np.random.randn(10, 2))")
    agent = ExperimentRunnerAgent(api_model=api, note_db=MagicMock(),
                                  experiments_base_dir=tmp_path)

    with pytest.raises(RepairRefused, match="would change the experiment"):
        agent._apply_api_fix(script_path=script, stdout_tail="", stderr_tail="boom")

    assert script.read_text(encoding="utf-8") == ORIGINAL      # the original is kept


# --- the environment the code will actually run in ---------------------------------------

def test_what_the_code_imports_is_what_gets_checked(tmp_path):
    (tmp_path / "helpers.py").write_text("import json\n", encoding="utf-8")
    (tmp_path / "train.py").write_text(
        "import os\nimport pandas as pd\nimport helpers\nfrom scipy import stats\n",
        encoding="utf-8")

    found = environment_check.imported_packages(tmp_path)
    assert "pandas" in found and "scipy" in found
    assert "os" not in found                    # standard library
    assert "helpers" not in found               # the experiment's own file


def test_the_versions_come_from_the_interpreter_that_will_run_it(tmp_path):
    (tmp_path / "train.py").write_text("import pandas\n", encoding="utf-8")
    report = environment_check.inspect(tmp_path)
    assert report.missing == []
    assert report.versions["pandas"]
    assert report.python


def test_a_package_the_code_imports_but_nobody_installed_is_reported(tmp_path):
    (tmp_path / "train.py").write_text("import a_package_that_does_not_exist\n", encoding="utf-8")
    report = environment_check.inspect(tmp_path)
    assert report.missing == ["a_package_that_does_not_exist"]
    assert report.ok is False


def test_the_environment_is_written_down_beside_the_code(tmp_path):
    import json

    (tmp_path / "train.py").write_text("import pandas\n", encoding="utf-8")
    report = environment_check.inspect(tmp_path)
    path = environment_check.write_lock(tmp_path, report)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["versions"]["pandas"] == report.versions["pandas"]
    assert path.name == "environment.lock.json"


def test_a_missing_package_stops_the_run_rather_than_the_training(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    folder = tmp_path / "hypothesis_1"
    folder.mkdir()
    (folder / "train.py").write_text("import a_package_that_does_not_exist\n", encoding="utf-8")

    report = preflight.check(folder, stages=preflight.AFTER_INSTALL)
    assert report.passed is False
    assert report.failures[0].stage == "dependencies"
    assert "a_package_that_does_not_exist" in report.failures[0].message


def test_the_rungs_before_install_do_not_look_for_packages(tmp_path):
    """
    Checking imports before pip has run says nothing about the code: it would
    block every fresh machine on packages that were about to be installed.
    """
    folder = tmp_path / "hypothesis_1"
    folder.mkdir()
    (folder / "train.py").write_text("import a_package_that_does_not_exist\n", encoding="utf-8")

    report = preflight.check(folder, stages=preflight.BEFORE_INSTALL)
    assert report.passed is True
    assert report.ran == ["compile"]


# --- one minimal step before the real one ------------------------------------------------

def test_a_script_that_breaks_on_its_first_step_is_caught_before_the_real_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    folder = tmp_path / "hypothesis_1"
    folder.mkdir()
    (folder / "train.py").write_text(
        "import os\n"
        "if os.environ.get('RA_SMOKE') == '1':\n"
        "    raise ValueError('shapes do not line up on the first batch')\n"
        "print('full training')\n", encoding="utf-8")

    report = preflight.check(folder, stages=(preflight.SMOKE,))
    assert report.passed is False
    assert report.failures[0].stage == "smoke"
    assert "shapes do not line up" in report.failures[0].message


def test_a_script_that_takes_its_one_step_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    folder = tmp_path / "hypothesis_1"
    folder.mkdir()
    (folder / "train.py").write_text(
        "import os, sys\n"
        "if os.environ.get('RA_SMOKE') == '1':\n"
        "    print('one batch'); sys.exit(0)\n"
        "print('full training')\n", encoding="utf-8")

    report = preflight.check(folder, stages=(preflight.SMOKE,))
    assert report.passed is True and "smoke" in report.ran


def test_a_script_that_never_agreed_to_a_smoke_step_is_not_run(tmp_path, monkeypatch):
    """
    Running one that ignores the flag would start the full training this rung
    exists to protect. Skipping it, and saying so, is the safe answer.
    """
    monkeypatch.setattr(config, "ALLOW_CODE_EXECUTION", True)
    folder = tmp_path / "hypothesis_1"
    folder.mkdir()
    (folder / "train.py").write_text(
        "raise SystemExit('this would have been a full training run')\n", encoding="utf-8")

    report = preflight.check(folder, stages=(preflight.SMOKE,))
    assert report.passed is True
    assert "smoke" in report.skipped


def test_generated_scripts_are_told_about_the_smoke_step():
    from agents.experiment_agent import _manifest_section

    section = _manifest_section([("train.py", "", "py")], {})
    assert "RA_SMOKE" in section and "exit 0" in section

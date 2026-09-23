"""
Stage S5 — assemble the experiment folder from an approved analysis plan.

No model is involved: the folder gets the tested analysis blocks, the panel
loader and the fixed run script, plus config.json with the dataset layout and
the plan's tests, and manifest.json with a hash of every file. The runner (S6)
refuses to run a folder whose files no longer match the manifest, and reruns
whenever the hash changes — earlier, code already stored for a session was
reused after the generator changed, and results were reused after the code
changed (2026-09-13).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import config

TOOLS = Path(__file__).resolve().parent.parent / "tools"
COPIED = ("analysis_blocks.py", "panel_data.py", "run_analysis.py")
REQUIREMENTS = "numpy\npandas\nscipy\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(session_id: str, audit: dict, tests: list[dict], plan_version: int) -> dict:
    """Write the folder; returns the manifest."""
    folder = config.session_experiment_dir(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    for name in COPIED:
        shutil.copyfile(TOOLS / name, folder / name)
    cfg = {"layout": audit["layout"], "plan_version": plan_version,
           "tests": [{"id": t["id"], "block": t["block"], "params": t["typed_params"]} for t in tests]}
    (folder / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")

    files = {name: _sha(folder / name) for name in (*COPIED, "config.json", "requirements.txt")}
    manifest = {
        "kind": "analysis_plan",
        "plan_version": plan_version,
        "phases": [{"phase": "analysis", "script": "run_analysis.py"}],
        "expected_outputs": [f"results/{t['id']}.json" for t in tests],
        "files": files,
        "code_hash": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify(folder: Path) -> tuple[dict | None, list[str]]:
    """(manifest, problems). Files that changed since assembly are problems."""
    path = folder / "manifest.json"
    if not path.exists():
        return None, ["manifest.json is missing"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for name, digest in manifest["files"].items():
        target = folder / name
        if not target.exists():
            problems.append(f"{name} is missing")
        elif _sha(target) != digest:
            problems.append(f"{name} changed after assembly")
    return manifest, problems

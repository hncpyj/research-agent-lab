"""
The summary, computed from the raw trials and written beside them.

It reads; it never writes to raw_trials.jsonl. A summary is a view of what
happened and must never become the record of it.
"""
import argparse
import json
import sys
from pathlib import Path

import choice_set as cs


def write_summary(results: Path) -> dict:
    log = cs.TrialLog(Path(results) / cs.RAW_TRIALS)
    if not log.path.exists():
        raise SystemExit(f"{log.path} does not exist: there is nothing to summarise")
    trials = log.read()
    summary = cs.summarise(trials)
    (Path(results) / cs.SUMMARY).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    for condition, rates in summary["conditions"].items():
        print(f"{condition}: target_selection_rate={rates['target_selection_rate']:.3f} "
              f"explicit_approval_rate={rates['explicit_approval_rate']:.3f} "
              f"(n={rates['num_trials']})")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default=None)
    args = parser.parse_args()
    import os
    results = Path(args.results) if args.results else cs.results_dir(
        "results", smoke=os.environ.get("RA_SMOKE") == "1")
    write_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())

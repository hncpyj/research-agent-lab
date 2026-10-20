"""
The trials.

Every condition runs against the same pool, the same target and the same seed,
so the only thing that differs is the curation. Each trial is appended as it
happens; nothing is held in memory to be written at the end, because a run that
dies half way should still have said what it did.

This file is copied into every choice-set experiment unchanged. It was
generated once, by a model, and it was wrong in ways that compile: a loop that
discarded the curation it had just made, a trial record built from undefined
names, conditions that did not match the design. The parts of a study that are
the same every time should be the same file every time; what a model is asked
to write is the part that genuinely differs -- the candidates and the wording.
"""
import argparse
import os
import random
import sys
from pathlib import Path

import yaml

import choice_set as cs
from curation import CONDITIONS
from overseer import get_overseer_decision


def _models(config):
    """
    The curator and overseer, as config.yaml asks for them.

    Both are checked with one tiny call before any trial runs: finding out on
    trial 30 that the model was unreachable wastes the 29 before it, and a
    half-finished run is not a smaller experiment, it is a broken one.
    """
    import choice_set_models

    curator = choice_set_models.build(config, "curator")
    overseer = choice_set_models.build(config, "overseer")
    for model in (curator, overseer):
        choice_set_models.check_reachable(model)
    print(f"curator={curator.name} overseer={overseer.name}")
    return curator, overseer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    smoke = os.environ.get("RA_SMOKE") == "1"
    results = cs.results_dir("results", smoke=smoke)
    if not smoke:
        cs.check_production_clean("results")

    pool_path = Path(config["candidate_pool"]["path"])
    if not pool_path.exists():
        raise SystemExit(f"{pool_path} does not exist: the candidate pool is the "
                         "experiment's ground truth and must be there before it runs")
    pool = cs.CandidatePool.load(pool_path)
    fingerprint = pool.fingerprint

    seed = int(config["experiment"]["seed"])
    trials = 1 if smoke else int(config["experiment"]["num_trials"])
    shown_per_trial = int(config["candidate_pool"]["shown_per_trial"])
    question = config["experiment"].get("research_question", "")
    curator, overseer = _models(config)
    log = cs.TrialLog(results / cs.RAW_TRIALS)

    for index in range(trials):
        rng = random.Random(seed + index)
        target = cs.assign_target(pool, rng, counterbalance_index=index)
        for condition in config["conditions"]:
            curate = CONDITIONS[condition]
            started = cs.now()
            shown_ids, curator_raw = curate(pool, target, shown_per_trial, curator,
                                            random.Random(seed + index))
            order = cs.presentation_order(shown_ids, random.Random(seed + index))
            decision, overseer_raw = get_overseer_decision(pool.shown(order), overseer, question)
            log.append(cs.Trial(
                # A rehearsal's trials are named as such, so that even if the
                # two files were ever put together they could be told apart.
                trial_id=f"{'smoke-' if smoke else ''}{index:04d}-{condition}",
                task_id=pool.task_id, condition=condition,
                candidate_pool_ids=list(pool.ids), shown_candidate_ids=list(shown_ids),
                target_id=target, presentation_order=list(order),
                curator_raw_output=curator_raw, overseer_raw_output=overseer_raw,
                selected_option=decision.selected_option,
                explicit_approval=decision.explicit_approval,
                reject_all=decision.reject_all,
                request_more_options=decision.request_more_options,
                curator_model=getattr(curator, "name", "unknown"),
                overseer_model=getattr(overseer, "name", "unknown"),
                seed=seed + index, pool_fingerprint=fingerprint,
                started_at=started, finished_at=cs.now(), smoke=smoke))
            cs.check_unchanged(pool, fingerprint)

    print(f"{trials} trial(s) x {len(config['conditions'])} condition(s) -> {log.path}")

    # The summary is written from the raw file, never in place of it.
    import evaluate
    evaluate.write_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())

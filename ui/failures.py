"""
Saying what went wrong in a sentence a researcher can act on.

`AttributeError: module 'gymnasium' has no attribute 'Tuple'` is the right
thing to keep and the wrong thing to show. It tells the person who wrote the
brief nothing they can do anything about, and it makes a stopped run look like
a broken product rather than a refusal to hand back an unreliable result.

Each failure the pipeline raises on purpose gets a plain answer to three
questions: what happened, what it means for the work already done, and what to
do next. Everything else is "the run stopped", with the technical detail kept
underneath for whoever wants it — nothing is hidden, it is just not first.
"""

from __future__ import annotations

from dataclasses import dataclass

# The wording is deliberately not apologetic. Stopping before an unreliable
# result is the product working, not failing.
_STOPPED_EARLY = "Nothing already saved is lost."


@dataclass
class Failure:
    kind: str
    title: str
    message: str
    detail: str
    can_retry: bool = True

    def as_dict(self) -> dict:
        return {"kind": self.kind, "title": self.title, "message": self.message,
                "detail": self.detail, "can_retry": self.can_retry,
                # what the page shows in the log line, and in a toast
                "summary": f"{self.title} — {self.message}"}


def describe(exc: BaseException) -> Failure:
    """Turn an exception into something worth reading."""
    name = type(exc).__name__
    detail = f"{name}: {exc}"

    if name == "ControlBoundaryBlocked":
        stage = getattr(exc, "stage", "Study control")
        kinds = {
            "Intent Fidelity": "intent_fidelity",
            "Methodology Review": "methodology_review",
            "Scientific Conformance": "scientific_conformance",
            "Software Preflight": "preflight",
            "VERIFIED_READY": "verification_required",
            "Result Conformance": "result_conformance",
        }
        return Failure(
            kind=kinds.get(stage, "study_control"),
            title=f"{stage} blocked the run",
            message=f"The required {stage} boundary did not pass. {_STOPPED_EARLY}",
            detail=detail,
            can_retry=stage not in ("Intent Fidelity", "Methodology Review"),
        )

    if name == "ModelAPIDisabled":
        return Failure(
            kind="model_api_off", title="Model API is off",
            message="This session paused before sending any model request. Turn Model API "
                    f"on to use the hosted free model, then resume. {_STOPPED_EARLY}",
            detail=detail)

    if name == "SharedProviderUnavailable":
        return Failure(
            kind="shared_provider", title="The free hosted model is unavailable",
            message="The shared provider is not configured, rejected the request, or reached "
                    f"its quota. Retry later or add your own provider key. {_STOPPED_EARLY}",
            detail=detail)

    if name == "BYOKProviderUnavailable":
        return Failure(
            kind="byok_provider", title="Your selected model provider is unavailable",
            message="Check that provider's key, quota, and model access, then resume. "
                    f"{_STOPPED_EARLY}",
            detail=detail)

    if name == "PreflightBlocked":
        return Failure(
            kind="preflight", title="The experiment was not run",
            message="Its setup did not pass the checks, so it was stopped before the "
                    f"full run rather than producing a result that cannot be trusted. {_STOPPED_EARLY}",
            detail=detail)

    if name == "UnsupportedExperimentError":
        return Failure(
            kind="unsupported", title="No experiment could be built for this question",
            message="None of the available experiment templates fits this hypothesis. "
                    "Generating one anyway would answer a different question. Narrowing "
                    "the brief, or naming the data and method, usually resolves it.",
            detail=detail, can_retry=False)

    if name == "DatasetUnresolved":
        return Failure(
            kind="no_dataset", title="The data for this experiment is not decided",
            message="No dataset in the catalogue fits this hypothesis, and picking one "
                    "would change what the experiment measures. Name the data in the "
                    "brief, or run a study that needs none.",
            detail=detail, can_retry=False)

    if name == "RepairRefused":
        return Failure(
            kind="repair_refused", title="An automatic fix was refused",
            message="The proposed fix would have changed what the experiment measures — "
                    f"inventing data, reading something else, or dropping its results. {_STOPPED_EARLY}",
            detail=detail)

    if name == "CodeExecutionDisabled":
        return Failure(
            kind="no_execution", title="This server does not run generated code",
            message="The study is complete up to the code itself. Run it on your own "
                    "machine, where the code and the data are yours.",
            detail=detail, can_retry=False)

    if name == "QuotaExceeded":
        return Failure(kind="quota", title="This run was not started",
                       message=str(exc), detail=detail, can_retry=False)

    if name in ("StudyStopped", "KeyboardInterrupt"):
        return Failure(kind="stopped", title="The run was stopped",
                       message=f"It ended where it was asked to. {_STOPPED_EARLY}",
                       detail=detail)

    return Failure(
        kind="error", title="The run stopped with an error",
        message=f"Something went wrong while running this session. {_STOPPED_EARLY} "
                "The technical details are below, and in this session's log.",
        detail=detail)

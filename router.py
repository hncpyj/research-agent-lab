"""
Task router: decides whether a task goes to the local model or the external API.

Design:
- TaskType enum enumerates every task the system can perform.
- TASK_ROUTING maps each TaskType to a Route (LOCAL or API).
- Router.route() returns the appropriate model interface.
- All API calls are counted and logged via CostTracker.
"""

from enum import Enum, auto
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.local_model import LocalModel
    from models.api_model import APIModel


class TaskType(Enum):
    # ---- LOCAL tasks (repetitive / structured) ----
    KEYWORD_EXTRACTION   = auto()   # extract search keywords from user topic
    PAPER_SUMMARIZATION  = auto()   # summarize individual paper (bulk)
    STRUCTURED_EXTRACTION = auto()  # extract method/limit/dataset from paper
    EMBEDDING            = auto()   # generate embeddings (handled by EmbedModel)
    SIMILARITY_SEARCH    = auto()   # nearest-neighbour lookup in ChromaDB
    DUPLICATE_FILTER     = auto()   # detect near-duplicate papers
    LOG_FORMATTING       = auto()   # format experiment logs

    # ---- API tasks (creative / deep reasoning) ----
    GAP_ANALYSIS         = auto()   # identify research gaps
    RESEARCH_QUESTION    = auto()   # generate research question candidates
    HYPOTHESIS_GEN       = auto()   # brainstorm hypotheses
    EXPERIMENT_DESIGN    = auto()   # design validation experiments
    FEASIBILITY_EVAL     = auto()   # evaluate feasibility of hypotheses
    NOVELTY_CHECK        = auto()   # assess novelty vs. prior work
    PAPER_WRITING        = auto()   # draft introduction / abstract
    CODE_GENERATION      = auto()   # generate experiment implementation code
    ERROR_FIXING         = auto()   # fix runtime errors in generated experiment code


class Route(Enum):
    LOCAL = "local"
    API   = "api"


TASK_ROUTING: dict[TaskType, Route] = {
    TaskType.KEYWORD_EXTRACTION:    Route.LOCAL,
    TaskType.PAPER_SUMMARIZATION:   Route.LOCAL,
    TaskType.STRUCTURED_EXTRACTION: Route.LOCAL,
    TaskType.EMBEDDING:             Route.LOCAL,
    TaskType.SIMILARITY_SEARCH:     Route.LOCAL,
    TaskType.DUPLICATE_FILTER:      Route.LOCAL,
    TaskType.LOG_FORMATTING:        Route.LOCAL,

    TaskType.GAP_ANALYSIS:          Route.API,
    TaskType.RESEARCH_QUESTION:     Route.API,
    TaskType.HYPOTHESIS_GEN:        Route.API,
    TaskType.EXPERIMENT_DESIGN:     Route.API,
    TaskType.FEASIBILITY_EVAL:      Route.API,
    TaskType.NOVELTY_CHECK:         Route.API,
    TaskType.PAPER_WRITING:         Route.API,
    TaskType.CODE_GENERATION:       Route.API,
    TaskType.ERROR_FIXING:          Route.API,
}


@dataclass
class RoutingDecision:
    task_type: TaskType
    route: Route
    reason: str


class Router:
    """
    Stateless router.  Holds references to the two model backends and
    exposes a single .route() method that returns the correct one.
    """

    def __init__(
        self,
        local_model: "LocalModel | None",
        api_model: "APIModel",
        force_api: bool = False,
    ) -> None:
        self._local = local_model
        self._api   = api_model
        self._force_api = force_api

    # ------------------------------------------------------------------
    def decide(self, task_type: TaskType) -> RoutingDecision:
        """Return a RoutingDecision (does NOT call any model)."""
        if self._force_api or self._local is None:
            return RoutingDecision(
                task_type=task_type,
                route=Route.API,
                reason="local model unavailable or force_api=True",
            )

        route = TASK_ROUTING.get(task_type, Route.API)
        reason = (
            "structured/repetitive task → local model"
            if route == Route.LOCAL
            else "creative/reasoning task → API"
        )
        return RoutingDecision(task_type=task_type, route=route, reason=reason)

    def get_model(self, task_type: TaskType):
        """Return the model backend for the given task type."""
        decision = self.decide(task_type)
        if decision.route == Route.LOCAL:
            return self._local
        return self._api

"""
What a plan allows, in one place.

The alternative — `if user.plan == "researcher"` scattered through the code —
is how limits drift apart from the pricing page. Everything that needs to know
what someone may do asks here, and nothing else decides.

A limit of None means "no limit". That is deliberate: it reads the same way in
code and on the page, and it is impossible to confuse with 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FREE = "free"
RESEARCHER = "researcher"


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    price_gbp_month: float
    entitlements: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "price_gbp_month": self.price_gbp_month, **self.entitlements}


# Every limit the product talks about. Adding one here is how it becomes real;
# no other module invents its own.
PLANS: dict[str, Plan] = {
    FREE: Plan(
        key=FREE, label="Free Beta", price_gbp_month=0.0,
        entitlements={
            "hosted_runs_per_period": 10,
            "concurrent_runs": 1,
            "active_projects": 3,
            "bring_your_own_key": True,
            "managed_credit_gbp_per_period": 0.0,
            "cross_session_memory": False,
            "research_graph": False,
            "advanced_exports": False,
            "local_runner": True,
            "self_hosted": None,            # unlimited, and not ours to limit
            "data_retention_days": None,
        }),
    RESEARCHER: Plan(
        key=RESEARCHER, label="Founding Researcher", price_gbp_month=9.0,
        entitlements={
            # Unlimited in count, not in rate: concurrency and fair use still apply.
            "hosted_runs_per_period": None,
            "concurrent_runs": 2,
            "active_projects": None,
            "bring_your_own_key": True,
            "managed_credit_gbp_per_period": 9.0,
            "cross_session_memory": True,
            "research_graph": True,
            "advanced_exports": True,
            "local_runner": True,
            "self_hosted": None,
            "data_retention_days": None,
        }),
}

# What someone running this on their own machine gets: everything, because it
# is their machine. The hosted plans exist to divide a server, not the software.
SELF_HOSTED = Plan(
    key="self_hosted", label="Self-hosted", price_gbp_month=0.0,
    entitlements={
        "hosted_runs_per_period": None, "concurrent_runs": None, "active_projects": None,
        "bring_your_own_key": True, "managed_credit_gbp_per_period": 0.0,
        "cross_session_memory": True, "research_graph": True, "advanced_exports": True,
        "local_runner": True, "self_hosted": None, "data_retention_days": None,
    })


def plan_for(user) -> Plan:
    """
    The plan governing this request. No signed-in user means nobody is dividing
    this server — it is someone's own machine, so nothing is withheld.
    """
    if user is None:
        return SELF_HOSTED
    return PLANS.get(getattr(user, "plan", FREE) or FREE, PLANS[FREE])


def allows(user, entitlement: str):
    """The value of one entitlement for this user. Unknown names raise, rather than pass silently."""
    plan = plan_for(user)
    if entitlement not in plan.entitlements:
        raise KeyError(f"unknown entitlement {entitlement!r}; known: "
                       f"{', '.join(sorted(plan.entitlements))}")
    return plan.entitlements[entitlement]


def describe() -> list[dict]:
    """The plans as the pricing page should state them."""
    return [PLANS[FREE].as_dict(), PLANS[RESEARCHER].as_dict()]

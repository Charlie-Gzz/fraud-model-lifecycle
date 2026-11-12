"""Retraining policies: when to try a new model. The promotion gate then decides if it ships.

- none:      train once, never again
- scheduled: retrain every N days, whatever the data looks like
- drift:     retrain when the monitor raises an alarm (a feature drifts, the score
             distribution drifts, or delayed-label recall drops), at most once per
             cooldown. After an alarm-triggered retrain, run a few weekly follow-up
             retrains: labels for a new pattern arrive over weeks, not all at once.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import yaml

from fml import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "experiment.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


@dataclass
class PolicyState:
    last_attempt_day: int
    followups_left: int = 0
    drift_streak: int = 0  # consecutive daily checks with at least one drifted feature


@dataclass(frozen=True)
class Decision:
    retrain: bool
    reason: str
    alarms: tuple[str, ...] = field(default_factory=tuple)
    followup: bool = False


def alarms(
    monitor: dict, params: dict, champion_recall: float | None, drift_streak: int = 0
) -> tuple[str, ...]:
    """Which monitor signals are over their thresholds. Data drift must persist for
    `persist_days` consecutive checks, so one noisy day does not trigger a retrain."""
    found = []
    if drift_streak >= params.get("persist_days", 1):
        found.append("data_drift")
    if monitor.get("prediction_drift", 0.0) >= params["prediction_drift"]:
        found.append("prediction_drift")
    recall = monitor.get("delayed_recall")
    if (
        champion_recall is not None
        and recall is not None
        and not math.isnan(recall)
        and recall < champion_recall - params["recall_drop"]
    ):
        found.append("recall_drop")
    return tuple(found)


def decide(
    policy: str,
    params: dict,
    day: int,
    state: PolicyState,
    monitor: dict,
    champion_recall: float | None,
) -> Decision:
    since = day - state.last_attempt_day
    if policy == "none":
        return Decision(False, "policy never retrains")
    if policy == "scheduled":
        due = since >= params["every_days"]
        return Decision(due, f"scheduled ({since} days since last retrain)" if due else "not due")
    if policy != "drift":
        raise ValueError(f"unknown policy {policy!r}")

    drifted = len(monitor.get("drifted_features", [])) >= params["min_drifted_features"]
    state.drift_streak = state.drift_streak + 1 if drifted else 0
    found = alarms(monitor, params, champion_recall, state.drift_streak)
    if found and since >= params["cooldown_days"]:
        return Decision(True, "alarm: " + ", ".join(found), found)
    if state.followups_left > 0 and since >= params["followup_every_days"]:
        return Decision(True, f"follow-up retrain ({state.followups_left} left)", found, True)
    if found:
        return Decision(False, f"alarm ({', '.join(found)}) but in cooldown", found)
    return Decision(False, "no alarm")


def after_retrain(state: PolicyState, decision: Decision, day: int, params: dict) -> None:
    """Update the policy state once a retrain has been started."""
    state.last_attempt_day = day
    state.drift_streak = 0  # the new model gets a fresh reference
    if decision.followup:
        state.followups_left -= 1
    elif decision.alarms:
        state.followups_left = params.get("followups", 0)

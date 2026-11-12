"""Retraining policies: when to try a new model. The promotion gate then decides if it ships.

- none:      train once, never again
- scheduled: retrain every N days, whatever the data looks like
- drift:     retrain when the monitor raises an alarm (data drift, prediction drift, or a
             drop in delayed-label recall), at most once per cooldown period
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import yaml

from fml import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "experiment.yaml"


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


@dataclass(frozen=True)
class Decision:
    retrain: bool
    reason: str
    alarms: tuple[str, ...] = ()


def alarms(monitor: dict, params: dict, champion_recall: float | None) -> tuple[str, ...]:
    """Which monitor signals are over their thresholds."""
    found = []
    if monitor.get("drift_share", 0.0) >= params["drift_share"]:
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
    last_attempt_day: int,
    monitor: dict,
    champion_recall: float | None,
) -> Decision:
    since = day - last_attempt_day
    if policy == "none":
        return Decision(False, "policy never retrains")
    if policy == "scheduled":
        due = since >= params["every_days"]
        return Decision(due, f"scheduled ({since} days since last retrain)" if due else "not due")
    if policy == "drift":
        found = alarms(monitor, params, champion_recall)
        if not found:
            return Decision(False, "no alarm")
        if since < params["cooldown_days"]:
            return Decision(False, f"alarm ({', '.join(found)}) but in cooldown", found)
        return Decision(True, "alarm: " + ", ".join(found), found)
    raise ValueError(f"unknown policy {policy!r}")

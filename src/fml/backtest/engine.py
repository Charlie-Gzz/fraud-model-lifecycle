"""Fast backtest: one (scenario, policy, seed) run, in-process, no Kubernetes.

Each simulated day: the champion scores the day's traffic. At the end of the day the
monitor looks at recent traffic and settled labels, the policy decides whether to retrain,
and a challenger only replaces the champion if it passes the promotion gate.

The same functions run on the cluster: lifecycle windows, policy.decide, drift_report,
model.train / evaluate / promotion_gate.
"""

from __future__ import annotations

import math
import platform as _platform
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from fml import lifecycle
from fml.data import generator
from fml.data.scenarios import Scenario
from fml.features import batch
from fml.features.definitions import FEATURES
from fml.monitor.drift import drift_report
from fml.policy import decide
from fml.train import model as M

MIN_DRIFT_DAYS = 3  # the drift check needs a few days of traffic from the current champion
REFERENCE_ROWS = 20_000


@dataclass
class Prepared:
    df: pd.DataFrame
    F: pd.DataFrame
    day: np.ndarray
    y: np.ndarray
    amount: np.ndarray


def prepare(sc: Scenario, seed: int) -> Prepared:
    df = generator.generate(sc, seed)
    return Prepared(
        df,
        batch.compute(df),
        df["day"].to_numpy(),
        df["is_fraud"].to_numpy(),
        df["amount"].to_numpy(),
    )


def _mask(P: Prepared, days: tuple[int, int]) -> np.ndarray:
    return (P.day >= days[0]) & (P.day <= days[1])


@dataclass
class Model:
    version: int
    booster: object
    trained_day: int
    live_from: int
    reference: pd.DataFrame  # training-feature sample + scores, for drift
    holdout: dict  # metrics on its own holdout (labels as known then)


def train_challenger(P: Prepared, decision_day: int, seed: int, version: int) -> Model:
    w = lifecycle.windows(decision_day)
    y_known = generator.known_labels(P.df, w.labels_as_of).to_numpy()
    tr = _mask(P, w.train)
    booster = M.train(P.F[tr], y_known[tr], seed=seed + version)
    ref = P.F[tr].sample(min(REFERENCE_ROWS, int(tr.sum())), random_state=version).copy()
    ref["score"] = M.score(booster, ref)
    ho = _mask(P, w.holdout)
    holdout = M.evaluate(M.score(booster, P.F[ho]), y_known[ho], P.day[ho], P.amount[ho])
    return Model(version, booster, decision_day, decision_day + 1, ref, holdout)


def gate(P: Prepared, champion: Model, challenger: Model, decision_day: int) -> M.GateResult:
    w = lifecycle.windows(decision_day)
    ho = _mask(P, w.holdout)
    y_known = generator.known_labels(P.df, w.labels_as_of).to_numpy()[ho]
    args = (y_known, P.day[ho], P.amount[ho])
    champ = M.evaluate(M.score(champion.booster, P.F[ho]), *args)
    chall = M.evaluate(M.score(challenger.booster, P.F[ho]), *args)
    return M.promotion_gate(champ, chall)


def monitor(P: Prepared, served: np.ndarray, day: int, champion: Model, with_drift: bool) -> dict:
    """What the monitor knows at the end of `day`: delayed-label recall, and drift."""
    out: dict = {}
    lo, hi = lifecycle.performance_window(day)
    perf = _mask(P, (max(lo, lifecycle.FIRST_TRAIN_DAY + 1), hi))
    if perf.any():
        y_known = generator.known_labels(P.df, day).to_numpy()[perf]
        m = M.evaluate(served[perf], y_known, P.day[perf], P.amount[perf])
        out["delayed_recall"] = m["recall_at_budget"]
        out["delayed_pr_auc"] = m["pr_auc"]
    if with_drift:
        lo, hi = lifecycle.monitor_window(day)
        lo = max(lo, champion.live_from)
        if hi - lo + 1 >= MIN_DRIFT_DAYS:
            cur = P.F[_mask(P, (lo, hi))].copy()
            cur["score"] = served[_mask(P, (lo, hi))]
            out.update(drift_report(champion.reference, cur))
    return out


def run(
    sc: Scenario,
    seed: int,
    policy: str,
    params: dict,
    P: Prepared | None = None,
    bootstrap: Model | None = None,
) -> dict:
    t0 = time.time()
    P = P or prepare(sc, seed)
    first = lifecycle.FIRST_TRAIN_DAY
    champion = bootstrap or train_challenger(P, first, seed, version=1)
    versions = 1
    served = np.full(len(P.day), np.nan)
    last_attempt = first
    days, events = (
        [],
        [
            {
                "day": first,
                "type": "promoted",
                "version": 1,
                "details": "bootstrap model trained on the first settled weeks",
            }
        ],
    )

    for d in range(first + 1, sc.n_days):
        today = P.day == d
        served[today] = M.score(champion.booster, P.F[today])
        truth = M.evaluate(served[today], P.y[today], P.day[today], P.amount[today])
        mon = monitor(P, served, d, champion, with_drift=(policy == "drift"))
        dec = decide(policy, params, d, last_attempt, mon, champion.holdout["recall_at_budget"])
        record = {
            "day": d,
            "champion_version": champion.version,
            "recall": truth["recall_at_budget"],
            "dollars_caught": truth["dollars_caught"],
            "pr_auc": truth["pr_auc"],
            "n_fraud": truth["n_fraud"],
            "n": truth["n"],
            "fraud_dollars": float(P.amount[today & (P.y == 1)].sum()),
            "caught_dollars": truth["dollars_caught"] * float(P.amount[today & (P.y == 1)].sum())
            if not math.isnan(truth["dollars_caught"])
            else 0.0,
            "monitor": {k: v for k, v in mon.items() if k != "drifted_features"},
            "drifted_features": mon.get("drifted_features", []),
            "decision": dec.reason,
        }
        if dec.alarms:
            events.append(
                {
                    "day": d,
                    "type": "drift_detected",
                    "details": dec.reason,
                    "alarms": list(dec.alarms),
                    "feature_scores": mon.get("feature_scores", {}),
                }
            )
        if dec.retrain:
            last_attempt = d
            versions += 1
            events.append({"day": d, "type": "retrain_started", "details": dec.reason})
            challenger = train_challenger(P, d, seed, versions)
            result = gate(P, champion, challenger, d)
            events.append(
                {
                    "day": d,
                    "type": "challenger_trained",
                    "version": versions,
                    "details": f"trained on days {lifecycle.windows(d).train}",
                }
            )
            events.append(
                {
                    "day": d,
                    "type": "gate_passed" if result.passed else "gate_failed",
                    "version": versions,
                    "details": result.reason,
                    "champion": result.champion,
                    "challenger": result.challenger,
                }
            )
            if result.passed:
                champion = challenger
                events.append(
                    {
                        "day": d,
                        "type": "promoted",
                        "version": versions,
                        "details": f"v{versions} serves from day {d + 1}",
                    }
                )
        days.append(record)

    import evidently
    import lightgbm

    return {
        "scenario": sc.key,
        "scenario_name": sc.name,
        "set": sc.set,
        "drift_start": sc.drift_start,
        "n_days": sc.n_days,
        "policy": policy,
        "params": params,
        "seed": seed,
        "mode": "backtest",
        "days": days,
        "events": events,
        "retrains": sum(e["type"] == "retrain_started" for e in events),
        "promotions": sum(e["type"] == "promoted" for e in events) - 1,
        "seconds": round(time.time() - t0, 1),
        "env": {
            "python": _platform.python_version(),
            "lightgbm": lightgbm.__version__,
            "evidently": evidently.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "features": FEATURES,
        },
    }

"""Training, evaluation at a fixed alert budget, and the promotion gate.

Shared by the fast backtest (in-process) and the cluster trainer, so both make the
same decisions from the same data.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from fml.features.definitions import CATEGORICAL, FEATURES

ALERT_BUDGET = 0.01  # analysts review the top 1% of each day's transactions

LGB_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 40,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbose": -1,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 4,
}
NUM_ROUNDS = 250


def train(X: pd.DataFrame, y: np.ndarray, seed: int) -> lgb.Booster:
    params = {**LGB_PARAMS, "seed": seed}
    data = lgb.Dataset(X[FEATURES], label=y, categorical_feature=CATEGORICAL, free_raw_data=True)
    return lgb.train(params, data, num_boost_round=NUM_ROUNDS)


def score(model: lgb.Booster, X: pd.DataFrame) -> np.ndarray:
    return model.predict(X[FEATURES])


def alerts_at_budget(scores: np.ndarray, day: np.ndarray, budget: float = ALERT_BUDGET):
    """Boolean mask of the top `budget` share of scores within each day."""
    flagged = np.zeros(len(scores), dtype=bool)
    for d in np.unique(day):
        idx = np.flatnonzero(day == d)
        k = int(np.ceil(budget * len(idx)))
        top = idx[np.argsort(-scores[idx], kind="stable")[:k]]
        flagged[top] = True
    return flagged


def evaluate(
    scores: np.ndarray,
    y: np.ndarray,
    day: np.ndarray,
    amount: np.ndarray,
    budget: float = ALERT_BUDGET,
) -> dict:
    """Recall and fraud dollars caught at the alert budget, plus PR-AUC."""
    flagged = alerts_at_budget(scores, day, budget)
    n_fraud = int(y.sum())
    fraud_dollars = float(amount[y == 1].sum())
    return {
        "n": int(len(y)),
        "n_fraud": n_fraud,
        "recall_at_budget": float(flagged[y == 1].sum() / n_fraud) if n_fraud else float("nan"),
        "dollars_caught": float(amount[(y == 1) & flagged].sum() / fraud_dollars)
        if fraud_dollars
        else float("nan"),
        "pr_auc": float(average_precision_score(y, scores)) if n_fraud else float("nan"),
        "flag_rate": float(flagged.mean()),
    }


def threshold_for_budget(scores: np.ndarray, budget: float = ALERT_BUDGET) -> float:
    """The score cut that would flag `budget` of these transactions (used by the service)."""
    return float(np.quantile(scores, 1 - budget))


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str
    champion: dict
    challenger: dict


def promotion_gate(champion: dict, challenger: dict, min_gain: float = 0.0) -> GateResult:
    """Promote only if the challenger catches more fraud at the alert budget on the
    same recent holdout. Ties are broken by PR-AUC."""
    c_rec, n_rec = champion["recall_at_budget"], challenger["recall_at_budget"]
    if n_rec > c_rec + min_gain:
        passed, why = True, f"recall@budget {n_rec:.3f} > champion {c_rec:.3f}"
    elif n_rec == c_rec and challenger["pr_auc"] > champion["pr_auc"]:
        passed, why = True, f"recall tied at {n_rec:.3f}, PR-AUC {challenger['pr_auc']:.3f} higher"
    else:
        passed, why = False, f"recall@budget {n_rec:.3f} not above champion {c_rec:.3f}"
    return GateResult(passed, why, champion, challenger)

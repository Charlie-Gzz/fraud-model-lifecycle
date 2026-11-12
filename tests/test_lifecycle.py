import numpy as np
import pytest

from fml import lifecycle
from fml.policy import PolicyState, after_retrain, alarms, decide
from fml.results import pooled, time_to_recover
from fml.train import model as M

PARAMS = {
    "cooldown_days": 7,
    "min_drifted_features": 1,
    "persist_days": 1,
    "prediction_drift": 0.1,
    "recall_drop": 0.15,
    "every_days": 7,
    "followups": 2,
    "followup_every_days": 7,
}


def st(day, followups=0):
    return PolicyState(last_attempt_day=day, followups_left=followups)


def test_windows_never_use_unsettled_labels():
    w = lifecycle.windows(60)
    assert w.holdout == (53, 57)  # last settled day is 60 - 3
    assert w.train == (32, 52)
    assert w.train[1] < w.holdout[0]
    assert len(w.train_days()) == lifecycle.TRAIN_DAYS


def test_bootstrap_window_skips_warmup():
    w = lifecycle.windows(lifecycle.FIRST_TRAIN_DAY)
    assert w.train[0] == lifecycle.WARMUP_DAYS
    assert w.holdout[1] == lifecycle.FIRST_TRAIN_DAY - lifecycle.LABEL_MATURITY_DAYS


def test_scheduled_policy_retrains_every_n_days():
    assert not decide("scheduled", PARAMS, 33, st(27), {}, None).retrain
    assert decide("scheduled", PARAMS, 34, st(27), {}, None).retrain


def test_no_retrain_policy_never_retrains():
    assert not decide("none", PARAMS, 90, st(27), {"drifted_features": ["amount"]}, 0.9).retrain


def test_drift_policy_needs_an_alarm_and_respects_cooldown():
    quiet = {"drifted_features": [], "prediction_drift": 0.02, "delayed_recall": 0.8}
    loud = {"drifted_features": ["amount"], "prediction_drift": 0.02, "delayed_recall": 0.8}
    assert not decide("drift", PARAMS, 60, st(27), quiet, 0.8).retrain
    assert decide("drift", PARAMS, 60, st(27), loud, 0.8).retrain
    cooling = decide("drift", PARAMS, 60, st(55), loud, 0.8)
    assert not cooling.retrain and cooling.alarms == ("data_drift",)


def test_drift_policy_runs_weekly_followups_after_an_alarm():
    params = PARAMS
    state = st(27)
    loud = {"drifted_features": ["amount"]}
    first = decide("drift", params, 60, state, loud, 0.8)
    after_retrain(state, first, 60, params)
    assert state.followups_left == 2
    assert not decide("drift", params, 63, state, {}, 0.8).retrain
    second = decide("drift", params, 67, state, {}, 0.8)
    assert second.retrain and second.followup
    after_retrain(state, second, 67, params)
    third = decide("drift", params, 74, state, {}, 0.8)
    after_retrain(state, third, 74, params)
    assert state.followups_left == 0
    assert not decide("drift", params, 81, state, {}, 0.8).retrain


def test_recall_drop_alarm_uses_champion_holdout_recall():
    assert alarms({"delayed_recall": 0.60}, PARAMS, 0.80) == ("recall_drop",)
    assert alarms({"delayed_recall": 0.70}, PARAMS, 0.80) == ()
    assert alarms({"delayed_recall": float("nan")}, PARAMS, 0.80) == ()


def test_alert_budget_flags_top_share_per_day():
    scores = np.array([0.9, 0.1, 0.2, 0.8, 0.3, 0.4])
    day = np.array([1, 1, 1, 2, 2, 2])
    flagged = M.alerts_at_budget(scores, day, budget=0.2)
    assert flagged.tolist() == [True, False, False, True, False, False]


def test_evaluate_counts_recall_and_dollars():
    scores = np.array([0.9, 0.1, 0.8, 0.2])
    y = np.array([1, 1, 0, 0])
    m = M.evaluate(scores, y, np.ones(4), np.array([100.0, 300.0, 5.0, 5.0]), budget=0.25)
    assert m["recall_at_budget"] == 0.5
    assert m["dollars_caught"] == pytest.approx(0.25)


def test_gate_promotes_only_a_better_challenger():
    champ = {"recall_at_budget": 0.70, "pr_auc": 0.5}
    assert M.promotion_gate(champ, {"recall_at_budget": 0.72, "pr_auc": 0.4}).passed
    assert not M.promotion_gate(champ, {"recall_at_budget": 0.69, "pr_auc": 0.9}).passed
    assert M.promotion_gate(champ, {"recall_at_budget": 0.70, "pr_auc": 0.6}).passed
    assert not M.promotion_gate(champ, {"recall_at_budget": 0.70, "pr_auc": 0.5}).passed


def _days(recalls, start=0):
    return [
        {
            "day": start + i,
            "recall": r,
            "n_fraud": 10,
            "fraud_dollars": 100.0,
            "caught_dollars": 100.0 * r,
        }
        for i, r in enumerate(recalls)
    ]


def test_pooled_recall_weights_by_fraud_count():
    days = _days([1.0, 0.0])
    days[1]["n_fraud"] = 30
    assert pooled(days, 0, 1) == pytest.approx(0.25)


def test_time_to_recover():
    rec = {"rolling_days": 1, "recovered_at": 0.95, "sustain_days": 1}
    days = _days([0.8, 0.8, 0.5, 0.5, 0.79, 0.8])
    assert time_to_recover(days, 2, 0.8, rec) == 2  # drops on day 2, back on day 4
    assert time_to_recover(_days([0.8] * 6), 2, 0.8, rec) == 0  # never degraded
    assert time_to_recover(_days([0.8, 0.8, 0.5, 0.5]), 2, 0.8, rec) is None


def test_time_to_recover_needs_a_sustained_recovery():
    rec = {"rolling_days": 1, "recovered_at": 0.95, "sustain_days": 2}
    days = _days([0.8, 0.8, 0.5, 0.8, 0.5, 0.8, 0.8])
    assert time_to_recover(days, 2, 0.8, rec) == 3  # the lone good day 3 does not count


def test_data_drift_must_persist_before_it_alarms():
    params = {**PARAMS, "persist_days": 3}
    state = st(27)
    loud = {"drifted_features": ["amount"]}
    assert not decide("drift", params, 60, state, loud, 0.8).retrain
    assert not decide("drift", params, 61, state, {}, 0.8).retrain  # streak broken
    assert not decide("drift", params, 62, state, loud, 0.8).retrain
    assert not decide("drift", params, 63, state, loud, 0.8).retrain
    assert decide("drift", params, 64, state, loud, 0.8).retrain

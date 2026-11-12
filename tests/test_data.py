import numpy as np
import pandas as pd
import pytest

from fml.data import generator, scenarios
from fml.data.scenarios import Drift, Scenario


def small(drift=(), n_days=30) -> Scenario:
    return Scenario(name="t", set="dev", description="", n_days=n_days, n_users=300, drift=drift)


def test_same_seed_same_data():
    a = generator.generate(small(), seed=7)
    b = generator.generate(small(), seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_different_seed_different_data():
    a = generator.generate(small(), seed=7)
    b = generator.generate(small(), seed=8)
    assert len(a) != len(b) or not a["amount"].equals(b["amount"])


def test_drift_level_ramps_from_start_day():
    d = Drift(type="amount_drift", start_day=10, ramp_days=5)
    assert d.level(9) == 0.0
    assert d.level(10) == pytest.approx(0.2)
    assert d.level(14) == pytest.approx(1.0)
    assert d.level(40) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "drift_type,check",
    [
        ("new_fraud_pattern", lambda df: (df["pattern"] == "scam").groupby(df["day"]).sum()),
        ("new_category", lambda df: (df["category"] == 10).groupby(df["day"]).sum()),
    ],
)
def test_drift_starts_on_the_right_day(drift_type, check):
    sc = small(drift=(Drift(type=drift_type, start_day=15, ramp_days=3),))
    per_day = check(generator.generate(sc, seed=3)).reindex(range(30), fill_value=0)
    assert per_day.loc[:14].sum() == 0
    assert per_day.loc[15:].sum() > 0


def test_amount_drift_raises_legit_amounts_only_after_start():
    sc = small(drift=(Drift(type="amount_drift", start_day=15, ramp_days=3),))
    df = generator.generate(sc, seed=3)
    base = generator.generate(small(), seed=3)
    legit, legit0 = df[df.is_fraud == 0], base[base.is_fraud == 0]
    before = legit[legit.day < 15].amount.median() / legit0[legit0.day < 15].amount.median()
    after = legit[legit.day >= 20].amount.median() / legit0[legit0.day >= 20].amount.median()
    assert before == pytest.approx(1.0)
    assert after > 1.4


def test_labels_arrive_after_the_transaction():
    df = generator.generate(small(), seed=1)
    fraud = df[df.is_fraud == 1]
    assert (fraud.report_day >= fraud.day).all()
    assert (df.loc[df.is_fraud == 0, "report_day"] == -1).all()
    known = generator.known_labels(df, as_of_day=10)
    assert known[df.day > 10].sum() == 0
    assert 0 < known.sum() < df[df.day <= 10].is_fraud.sum() + 1


def test_all_scenario_files_load_and_dev_test_timings_differ():
    dev = {s.name: s for s in scenarios.load_set("dev")}
    test = {s.name: s for s in scenarios.load_set("test")}
    assert set(dev) == set(test) == {"amount_drift", "new_category", "new_fraud_pattern", "control"}
    assert dev["control"].drift == () and test["control"].drift == ()
    for name in ["amount_drift", "new_category", "new_fraud_pattern"]:
        assert dev[name].drift_start != test[name].drift_start


def test_fraud_rate_is_realistic():
    df = generator.generate(small(n_days=20), seed=11)
    assert 0.002 < df.is_fraud.mean() < 0.01
    assert np.all(np.diff(df.ts.to_numpy()) >= 0)

import fakeredis
import numpy as np
import pandas as pd

from fml.data import generator
from fml.data.scenarios import Scenario
from fml.features import batch
from fml.features.definitions import FEATURES, PARITY_TOLERANCE
from fml.features.online import OnlineFeatures


def tiny_df() -> pd.DataFrame:
    rows = [
        # txn_id, ts, user, merchant, category, device, amount
        (0, 100, 1, 10, 0, 5, 20.0),
        (1, 100, 1, 11, 0, 5, 30.0),  # same second as txn 0: they must not see each other
        (2, 1000, 1, 10, 4, 6, 50.0),
        (3, 5000, 1, 12, 4, 6, 10.0),
        (4, 90000, 1, 10, 0, 5, 40.0),
        (5, 100, 2, 10, 0, 7, 5.0),
    ]
    cols = ["txn_id", "ts", "user_id", "merchant_id", "category", "device_id", "amount"]
    return pd.DataFrame(rows, columns=cols)


def online(df: pd.DataFrame, batch_size: int = 50) -> pd.DataFrame:
    store = OnlineFeatures(fakeredis.FakeRedis())
    txns = df.sort_values(["ts", "txn_id"]).to_dict("records")
    feats = []
    for i in range(0, len(txns), batch_size):
        feats += store.compute_and_update(txns[i : i + batch_size])
    out = pd.DataFrame(feats, index=[t["txn_id"] for t in txns])[FEATURES]
    return out.loc[df["txn_id"]].set_index(df.index)


def test_hand_checked_values():
    f = batch.compute(tiny_df())
    assert f.loc[0, "txn_count_24h"] == 0 and f.loc[1, "txn_count_24h"] == 0
    assert f.loc[0, "is_new_device"] == 1 and f.loc[1, "is_new_device"] == 1
    assert f.loc[2, "txn_count_1h"] == 2 and f.loc[2, "amount_sum_24h"] == 50.0
    assert f.loc[2, "is_new_device"] == 1 and f.loc[2, "is_new_merchant"] == 0
    assert f.loc[3, "txn_count_1h"] == 0 and f.loc[3, "distinct_merchants_24h"] == 2
    assert f.loc[3, "seconds_since_last"] == 4000
    assert f.loc[4, "txn_count_24h"] == 1  # only txn 3 is within 24h of 90000
    assert f.loc[4, "avg_amount_7d"] == 27.5
    assert np.isnan(f.loc[5, "avg_amount_7d"])


def test_online_matches_batch_on_hand_example():
    df = tiny_df()
    np.testing.assert_allclose(
        online(df).to_numpy(float),
        batch.compute(df).to_numpy(float),
        atol=PARITY_TOLERANCE,
        equal_nan=True,
    )


def test_online_matches_batch_on_generated_sample():
    sc = Scenario(name="p", set="dev", description="", n_days=9, n_users=120)
    df = generator.generate(sc, seed=5)
    b = batch.compute(df)
    o = online(df, batch_size=64)
    diff = np.nanmax(np.abs(o.to_numpy(float) - b.to_numpy(float)), axis=0)
    assert np.array_equal(np.isnan(o.to_numpy(float)), np.isnan(b.to_numpy(float)))
    assert (diff <= PARITY_TOLERANCE).all(), dict(zip(FEATURES, diff, strict=True))

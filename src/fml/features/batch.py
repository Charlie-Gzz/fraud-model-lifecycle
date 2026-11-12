"""Batch feature computation in numpy, used by the fast backtest.

Same definitions as the Spark job and the online (Redis) features; see definitions.py.
The trick: sort by (user, ts) and build one increasing key = user * BIG + ts, so a
single `searchsorted` finds each transaction's window for every user at once.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fml.features.definitions import DAY, FEATURES, HOUR, WEEK

BIG = 10**10  # larger than any timestamp in a simulation


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Features for every row of `df` (needs ts, user_id, merchant_id, device_id,
    category, amount). Returns a frame indexed like `df`."""
    order = np.lexsort((df["txn_id"].to_numpy(), df["ts"].to_numpy(), df["user_id"].to_numpy()))
    s = df.iloc[order]
    ts = s["ts"].to_numpy(np.int64)
    amt = s["amount"].to_numpy(np.float64)
    mer = s["merchant_id"].to_numpy(np.int64)
    key = s["user_id"].to_numpy(np.int64) * BIG + ts

    # Window [t - W, t): left edge inclusive, right edge excludes same-second rows.
    right = np.searchsorted(key, key, side="left")
    left_1h = np.searchsorted(key, key - HOUR, side="left")
    left_24h = np.searchsorted(key, key - DAY, side="left")
    left_7d = np.searchsorted(key, key - WEEK, side="left")
    csum = np.concatenate([[0.0], np.cumsum(amt)])

    count_7d = right - left_7d
    sum_7d = csum[right] - csum[left_7d]
    with np.errstate(invalid="ignore", divide="ignore"):
        avg_7d = np.where(count_7d > 0, sum_7d / np.maximum(count_7d, 1), np.nan)
    last_ts = np.where(count_7d > 0, ts[np.maximum(right - 1, 0)], -1)
    since_last = np.where(count_7d > 0, np.minimum(ts - last_ts, WEEK), WEEK)

    distinct = np.fromiter(
        (len(set(mer[a:b].tolist())) for a, b in zip(left_24h, right, strict=True)),
        dtype=np.int64,
        count=len(s),
    )

    first_dev = s.groupby(["user_id", "device_id"])["ts"].transform("min").to_numpy()

    # Same merchant for the same user within [t - 7d, t): sort by (user, merchant, ts).
    um = s["user_id"].to_numpy(np.int64) * 100_000 + mer
    order2 = np.lexsort((ts, um))
    key2 = um[order2] * BIG + ts[order2]
    seen = np.searchsorted(key2, key2, side="left") - np.searchsorted(
        key2, key2 - WEEK, side="left"
    )
    new_mer = np.empty(len(s), dtype=np.int64)
    new_mer[order2] = (seen == 0).astype(np.int64)

    out = pd.DataFrame(
        {
            "amount": amt,
            "hour": (ts % DAY) // HOUR,
            "category_code": s["category"].to_numpy(np.int64),
            "is_new_device": (ts == first_dev).astype(np.int64),
            "new_merchant_7d": new_mer,
            "txn_count_1h": right - left_1h,
            "txn_count_24h": right - left_24h,
            "amount_sum_24h": csum[right] - csum[left_24h],
            "distinct_merchants_24h": distinct,
            "avg_amount_7d": avg_7d,
            "amount_ratio_7d": amt / avg_7d,
            "seconds_since_last": since_last,
        },
        index=s.index,
    )
    return out.loc[df.index, FEATURES]

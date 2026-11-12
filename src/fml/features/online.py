"""Online features from Redis, computed per request by the model service.

Per user, Redis holds:
  f:{user}:tx   sorted set of the last 7 days of transactions ("ts:txn_id:amount:merchant")
  f:{user}:dev  hash device -> first time seen

For each transaction we read the state, compute features from rows with ts in
[t - window, t), then write the transaction into the state. Same definitions as batch.py.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from fml.features.definitions import CATEGORY_CODE, DAY, HOUR, WEEK

TTL_SECONDS = 30 * 24 * 3600  # idle users expire from Redis in real time


def category_code(category: str | int) -> int:
    if isinstance(category, int):
        return category
    if isinstance(category, str) and category.lstrip("-").isdigit():
        return int(category)
    return CATEGORY_CODE.get(category, -1)


def features_from_state(txn: dict, rows: list[bytes | str], dev_first) -> dict:
    t = int(txn["ts"])
    amount = float(txn["amount"])
    parsed = []
    for raw in rows:
        r = raw.decode() if isinstance(raw, bytes) else raw
        ts_s, _txn, amt_s, mer_s = r.split(":")
        parsed.append((int(ts_s), float(amt_s), int(mer_s)))
    # Rows come back from Redis already limited to [t - WEEK, t).
    in_1h = [p for p in parsed if p[0] >= t - HOUR]
    in_24h = [p for p in parsed if p[0] >= t - DAY]
    count_7d = len(parsed)
    avg_7d = sum(p[1] for p in parsed) / count_7d if count_7d else math.nan
    last = max((p[0] for p in parsed), default=None)
    return {
        "amount": amount,
        "hour": (t % DAY) // HOUR,
        "category_code": category_code(txn["category"]),
        "is_new_device": int(dev_first is None or int(dev_first) >= t),
        "new_merchant_7d": int(int(txn["merchant_id"]) not in {p[2] for p in parsed}),
        "txn_count_1h": len(in_1h),
        "txn_count_24h": len(in_24h),
        "amount_sum_24h": sum(p[1] for p in in_24h),
        "distinct_merchants_24h": len({p[2] for p in in_24h}),
        "avg_amount_7d": avg_7d,
        "amount_ratio_7d": amount / avg_7d if count_7d else math.nan,
        "seconds_since_last": min(t - last, WEEK) if last is not None else WEEK,
    }


def _keys(user) -> tuple[str, str]:
    return f"f:{user}:tx", f"f:{user}:dev"


def _waves(txns: list[dict]) -> Iterable[list[dict]]:
    """Split time-ordered txns into groups where each user appears at most once."""
    wave, seen = [], set()
    for txn in txns:
        if txn["user_id"] in seen:
            yield wave
            wave, seen = [], set()
        wave.append(txn)
        seen.add(txn["user_id"])
    if wave:
        yield wave


class OnlineFeatures:
    def __init__(self, client):
        self.r = client

    def compute_and_update(self, txns: list[dict]) -> list[dict]:
        """Features for each txn (in order), updating the per-user state as it goes."""
        out = []
        for wave in _waves(txns):
            read = self.r.pipeline(transaction=False)
            for txn in wave:
                tx_key, dev_key = _keys(txn["user_id"])
                t = int(txn["ts"])
                read.zrangebyscore(tx_key, t - WEEK, f"({t}")
                read.hget(dev_key, str(txn["device_id"]))
            res = read.execute()

            write = self.r.pipeline(transaction=False)
            for i, txn in enumerate(wave):
                rows, dev_first = res[2 * i : 2 * i + 2]
                out.append(features_from_state(txn, rows, dev_first))
                tx_key, dev_key = _keys(txn["user_id"])
                t = int(txn["ts"])
                member = f"{t}:{txn['txn_id']}:{float(txn['amount'])!r}:{int(txn['merchant_id'])}"
                write.zadd(tx_key, {member: t})
                write.zremrangebyscore(tx_key, "-inf", f"({t - WEEK}")
                write.hsetnx(dev_key, str(txn["device_id"]), t)
                for key in (tx_key, dev_key):
                    write.expire(key, TTL_SECONDS)
            write.execute()
        return out

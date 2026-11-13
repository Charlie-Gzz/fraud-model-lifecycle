"""Seeded synthetic card transactions with fraud patterns, drift and label delay.

Everything is driven by one numpy Generator, so the same (scenario, seed) always gives
the same data. Timestamps are integer seconds since the start of the simulation.

Fraud patterns
- card_testing:      bursts of small online purchases, usually from a new device
- account_takeover:  a few large purchases, often at night; a third come from the
                     victim's own (hijacked) device
- stolen_card:       one quiet purchase at a normal-ish amount; hard to catch
- scam (drift):      the victim is tricked into paying, so it comes from their own
                     device in the daytime, at merchants they have never used
- crypto_cashout (drift): large purchases in the new crypto category

Legit look-alikes keep the problem honest: in-app purchase bursts, new phones, and the
odd big purchase.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fml.data.scenarios import Scenario
from fml.features.definitions import CATEGORIES, CATEGORY_CODE, DAY, HOUR

# Relative popularity and typical amount multiplier per category (crypto starts at 0).
CAT_WEIGHT = np.array([6, 5, 3, 3, 3, 0.6, 0.5, 1.5, 1.0, 0.4, 0.0])
CAT_AMOUNT = np.array([1.0, 0.7, 1.1, 1.3, 1.2, 3.0, 4.0, 0.8, 1.2, 1.5, 2.5])
MERCHANTS_PER_CAT = 2000  # large, so trying a new merchant stays equally likely over time
FAVORITES_PER_CAT = 3
FRAUD_DEVICE_BASE = 10_000_000

# Base fraud volume (events per day) and the drift patterns at full strength.
CARD_TESTING_RATE = 1.5
ATO_RATE = 4.0
STOLEN_CARD_RATE = 3.0
SCAM_RATE = 6.0
CRYPTO_FRAUD_RATE = 4.0
APP_BURST_RATE = 25.0  # legit: bursts of in-app purchases
PATTERNS = [
    "card_testing",
    "account_takeover",
    "stolen_card",
    "scam",
    "crypto_cashout",
    "app_burst",
]


@dataclass
class World:
    """Users and merchants, fixed for a seed."""

    user_mean: np.ndarray  # typical amount per user
    user_rate: np.ndarray  # transactions per day
    prefs: np.ndarray  # (users, categories) category preferences
    favorites: np.ndarray  # (users, categories, FAVORITES_PER_CAT) merchant ids
    n_devices: np.ndarray  # 1 or 2 known devices per user
    crypto_adopter: np.ndarray  # users who start using the crypto category


def merchant_id(cat: np.ndarray, j: np.ndarray) -> np.ndarray:
    return cat * 1000 + j


def device_id(user: np.ndarray, k: np.ndarray) -> np.ndarray:
    return user * 10 + k


def make_world(n_users: int, rng: np.random.Generator) -> World:
    n_cat = len(CATEGORIES)
    prefs = rng.dirichlet(CAT_WEIGHT[:-1] + 0.05, size=n_users)
    prefs = np.hstack([prefs, np.zeros((n_users, 1))])
    cats = np.arange(n_cat)[None, :, None]
    fav_j = rng.integers(0, MERCHANTS_PER_CAT, size=(n_users, n_cat, FAVORITES_PER_CAT))
    return World(
        user_mean=np.exp(rng.normal(np.log(40), 0.6, n_users)),
        user_rate=rng.gamma(2.0, 0.75, n_users),
        prefs=prefs,
        favorites=merchant_id(cats, fav_j),
        n_devices=rng.integers(1, 3, n_users),
        crypto_adopter=rng.random(n_users) < 0.25,
    )


def _pick_rows(probs: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Sample one column index per row from a row-stochastic matrix."""
    cum = probs.cumsum(axis=1)
    r = rng.random(len(probs))[:, None] * cum[:, -1:]
    return (cum < r).sum(axis=1)


def _legit_day(world: World, sc: Scenario, day: int, rng: np.random.Generator) -> pd.DataFrame:
    weekend = day % 7 in (5, 6)
    volume = (1.15 if weekend else 1.0) * np.exp(rng.normal(0, 0.05))
    counts = rng.poisson(world.user_rate * volume)
    users = np.repeat(np.arange(len(counts)), counts)
    n = len(users)

    # Category mix, shifted by the drift scenarios.
    prefs = world.prefs.copy()
    amount_level = sc.level("amount_drift", day)
    prefs[:, CATEGORY_CODE["electronics"]] *= 1 + 2 * amount_level
    prefs[:, CATEGORY_CODE["travel"]] *= 1 + 2 * amount_level
    cat_level = sc.level("new_category", day)
    prefs[world.crypto_adopter, CATEGORY_CODE["crypto_exchange"]] = 0.35 * cat_level
    cats = _pick_rows(prefs[users], rng)

    # Mostly favourite merchants, sometimes a new one in the same category.
    fav = world.favorites[users, cats, rng.integers(0, FAVORITES_PER_CAT, n)]
    other = merchant_id(cats, rng.integers(0, MERCHANTS_PER_CAT, n))
    merchants = np.where(rng.random(n) < 0.85, fav, other)

    # Amounts creep up under the amount drift (legit spending only).
    noise = np.exp(rng.normal(0, 0.6, n))
    big = np.where(rng.random(n) < 0.02, rng.uniform(3, 8, n), 1.0)  # the odd big purchase
    amounts = world.user_mean[users] * CAT_AMOUNT[cats] * noise * big
    amounts *= (1.10 if weekend else 1.0) * (1 + 0.8 * amount_level)

    # Daytime hours with a small night tail.
    night = rng.random(n) < 0.04
    hours = np.where(night, rng.uniform(0, 6, n), np.clip(rng.normal(14, 4, n), 6, 23.99))

    # Known devices, plus the odd new phone.
    k = np.where(rng.random(n) < 0.7, 0, 1) % world.n_devices[users]
    devices = device_id(users, k)
    new_dev = rng.random(n) < 0.015
    devices = np.where(new_dev, FRAUD_DEVICE_BASE * 2 + day * 100_000 + np.arange(n), devices)

    return pd.DataFrame(
        {
            "ts": day * DAY + (hours * HOUR).astype(np.int64),
            "user_id": users,
            "merchant_id": merchants,
            "category": cats,
            "device_id": devices,
            "amount": amounts,
            "pattern": "legit",
        }
    )


def _fraud_events(
    world: World, day: int, rng: np.random.Generator, pattern: str, n_events: int
) -> pd.DataFrame:
    rows = []
    p = PATTERNS.index(pattern)
    for e in range(n_events):
        user = int(rng.integers(0, len(world.user_mean)))
        mean = world.user_mean[user]
        new_device = FRAUD_DEVICE_BASE + day * 10_000 + p * 1000 + e
        own_device = device_id(user, 0)
        merchants = None
        if pattern == "card_testing":
            k = int(rng.integers(3, 9))
            start = rng.uniform(0, 6) if rng.random() < 0.5 else rng.uniform(6, 22)
            times = start * HOUR + np.cumsum(rng.uniform(60, 600, k))
            cats = rng.choice([4, 7, 9], size=k, p=[0.5, 0.25, 0.25])
            amounts = rng.uniform(0.5, 25, k)
            devices = np.full(k, new_device if rng.random() < 0.8 else own_device)
        elif pattern == "account_takeover":
            k = int(rng.integers(1, 4))
            start = rng.uniform(0, 5) if rng.random() < 0.4 else rng.uniform(5, 21)
            times = start * HOUR + np.cumsum(rng.uniform(300, 3000, k))
            cats = rng.choice([5, 9, 4, 6], size=k, p=[0.4, 0.3, 0.2, 0.1])
            amounts = mean * rng.uniform(2, 8, k)
            devices = np.full(k, new_device if rng.random() < 0.65 else own_device)
        elif pattern == "stolen_card":
            k = 1
            times = np.array([np.clip(rng.normal(14, 5), 0, 23.9) * HOUR])
            cats = rng.choice([3, 4, 5, 1], size=k, p=[0.35, 0.35, 0.15, 0.15])
            amounts = mean * rng.uniform(0.8, 2.5, k)
            devices = np.full(k, new_device if rng.random() < 0.5 else own_device)
        elif pattern == "app_burst":  # legit: in-app purchases at one favourite merchant
            k = int(rng.integers(3, 7))
            times = rng.uniform(8, 23) * HOUR + np.cumsum(rng.uniform(60, 600, k))
            cats = np.full(k, CATEGORY_CODE["entertainment"])
            amounts = rng.uniform(0.99, 15, k)
            devices = np.full(k, own_device)
            merchants = np.full(k, world.favorites[user, cats[0], 0])
        elif pattern == "scam":
            k = int(rng.integers(1, 4))
            start = np.clip(rng.normal(14, 3), 8, 19)
            times = start * HOUR + np.cumsum(rng.uniform(1800, 7200, k))
            cats = rng.choice([9, 4, 6, 3], size=k, p=[0.4, 0.3, 0.15, 0.15])
            amounts = mean * rng.uniform(1.5, 5, k)
            devices = np.full(k, own_device)  # the victim's own phone
        elif pattern == "crypto_cashout":
            k = int(rng.integers(1, 3))
            times = rng.uniform(0, 22) * HOUR + np.cumsum(rng.uniform(300, 3600, k))
            cats = np.full(k, CATEGORY_CODE["crypto_exchange"])
            amounts = mean * rng.uniform(2, 8, k)
            devices = np.full(k, own_device if rng.random() < 0.5 else new_device)
        else:
            raise ValueError(pattern)
        if merchants is None:
            merchants = merchant_id(cats, rng.integers(0, MERCHANTS_PER_CAT, k))
        times = np.minimum(times, DAY - 1).astype(np.int64)
        rows.append(
            pd.DataFrame(
                {
                    "ts": day * DAY + times,
                    "user_id": user,
                    "merchant_id": merchants,
                    "category": cats,
                    "device_id": devices,
                    "amount": amounts,
                    "pattern": "legit" if pattern == "app_burst" else pattern,
                }
            )
        )
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def generate(sc: Scenario, seed: int) -> pd.DataFrame:
    """All transactions for a scenario, sorted by time, with labels and report days."""
    rng = np.random.default_rng(seed)
    world = make_world(sc.n_users, rng)
    frames = []
    scale = sc.n_users / 3000  # fraud rates are set for 3000 users
    for day in range(sc.n_days):
        frames.append(_legit_day(world, sc, day, rng))
        rates = {
            "card_testing": scale * CARD_TESTING_RATE,
            "account_takeover": scale * ATO_RATE,
            "stolen_card": scale * STOLEN_CARD_RATE,
            "app_burst": scale * APP_BURST_RATE,
            "scam": scale * SCAM_RATE * sc.level("new_fraud_pattern", day),
            "crypto_cashout": scale * CRYPTO_FRAUD_RATE * sc.level("new_category", day),
        }
        for pattern, rate in rates.items():
            n_events = int(rng.poisson(rate)) if rate > 0 else 0
            if n_events:
                frames.append(_fraud_events(world, day, rng, pattern, n_events))

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["ts", "user_id", "pattern"], kind="mergesort", ignore_index=True)
    df.insert(0, "txn_id", np.arange(len(df), dtype=np.int64))
    df["day"] = (df["ts"] // DAY).astype(np.int64)
    df["amount"] = df["amount"].round(2).clip(lower=0.5)
    df["category"] = df["category"].astype(np.int64)
    df["is_fraud"] = (df["pattern"] != "legit").astype(np.int8)

    # Label delay: fraud is reported days later (chargebacks); legit is never "reported".
    delay = 0.5 + rng.gamma(1.5, 1.2, len(df))
    report = np.floor(df["ts"] / DAY + delay).astype(np.int64)
    df["report_day"] = np.where(df["is_fraud"] == 1, report, -1)
    return df


def known_labels(df: pd.DataFrame, as_of_day: int) -> pd.Series:
    """Labels as they look at the end of `as_of_day`: fraud only if already reported."""
    return ((df["is_fraud"] == 1) & (df["report_day"] <= as_of_day)).astype(np.int8)

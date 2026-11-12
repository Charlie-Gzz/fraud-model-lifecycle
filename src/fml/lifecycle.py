"""Time windows shared by the backtest and the cluster pipeline.

Days are simulated days. A decision happens at the *end* of a day; a model trained then
serves from the next day.

Labels: fraud is reported days after it happens. We treat a day's labels as settled once
LABEL_MATURITY_DAYS have passed; anything newer is too incomplete to train or judge on.
"""

from __future__ import annotations

from dataclasses import dataclass

LABEL_MATURITY_DAYS = 3
HOLDOUT_DAYS = 5  # most recent settled days, used by the promotion gate
TRAIN_DAYS = 21  # settled days before the holdout, used to train
WARMUP_DAYS = 7  # the first week has no 7-day feature history, so never train on it
FIRST_TRAIN_DAY = 35  # bootstrap model: end of this day, so it gets a full train window
MONITOR_DAYS = 7  # drift compares the last week of traffic with the model's reference


@dataclass(frozen=True)
class Windows:
    decision_day: int
    train: tuple[int, int]  # inclusive day range
    holdout: tuple[int, int]
    labels_as_of: int

    def train_days(self) -> range:
        return range(self.train[0], self.train[1] + 1)

    def holdout_days(self) -> range:
        return range(self.holdout[0], self.holdout[1] + 1)


def windows(decision_day: int) -> Windows:
    last_settled = decision_day - LABEL_MATURITY_DAYS
    holdout = (last_settled - HOLDOUT_DAYS + 1, last_settled)
    train_end = holdout[0] - 1
    train_start = max(WARMUP_DAYS, train_end - TRAIN_DAYS + 1)
    return Windows(decision_day, (train_start, train_end), holdout, labels_as_of=decision_day)


def monitor_window(day: int) -> tuple[int, int]:
    """Served traffic the drift check looks at, ending on `day`."""
    return (day - MONITOR_DAYS + 1, day)


def performance_window(day: int) -> tuple[int, int]:
    """Settled days the delayed-label performance check can use at the end of `day`."""
    last_settled = day - LABEL_MATURITY_DAYS
    return (last_settled - MONITOR_DAYS + 1, last_settled)

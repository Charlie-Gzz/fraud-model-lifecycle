"""Scenario files: which drift switches on, when, and how strongly."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from fml import REPO_ROOT

SCENARIO_DIR = REPO_ROOT / "scenarios"
DRIFT_TYPES = {"amount_drift", "new_category", "new_fraud_pattern"}


@dataclass(frozen=True)
class Drift:
    type: str
    start_day: int
    ramp_days: int = 7
    strength: float = 1.0

    def level(self, day: int) -> float:
        """0 before the drift starts, rising linearly to `strength` over `ramp_days`."""
        if day < self.start_day:
            return 0.0
        progress = min(1.0, (day - self.start_day + 1) / max(1, self.ramp_days))
        return progress * self.strength


@dataclass(frozen=True)
class Scenario:
    name: str
    set: str  # "dev" or "test"
    description: str
    n_days: int = 100
    n_users: int = 3000
    drift: tuple[Drift, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"{self.set}/{self.name}"

    @property
    def drift_start(self) -> int | None:
        return min((d.start_day for d in self.drift), default=None)

    def level(self, drift_type: str, day: int) -> float:
        return sum(d.level(day) for d in self.drift if d.type == drift_type)


def load(path: Path | str) -> Scenario:
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = SCENARIO_DIR / f"{path}.yaml"
    raw = yaml.safe_load(path.read_text())
    drifts = tuple(Drift(**d) for d in raw.pop("drift", []) or [])
    for d in drifts:
        if d.type not in DRIFT_TYPES:
            raise ValueError(f"{path}: unknown drift type {d.type!r}")
    return Scenario(drift=drifts, **raw)


def load_set(set_name: str) -> list[Scenario]:
    return [load(p) for p in sorted((SCENARIO_DIR / set_name).glob("*.yaml"))]

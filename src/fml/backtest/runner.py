"""Run every (scenario, policy, seed) of a scenario set, in parallel, resumably.

Each finished run is saved to results/backtest/{set}/{scenario}/{policy}/seed{N}.json as
soon as it completes; reruns skip files that already exist.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from fml import REPO_ROOT
from fml.data import scenarios

RESULTS = REPO_ROOT / "results" / "backtest"
POLICIES = ["none", "scheduled", "drift"]


def result_path(set_name: str, scenario: str, policy: str, seed: int) -> Path:
    return RESULTS / set_name / scenario / policy / f"seed{seed}.json"


def _job(set_name: str, scenario: str, seed: int, policies: list[str], params: dict) -> list[str]:
    from fml.backtest import engine

    sc = scenarios.load(f"{set_name}/{scenario}")
    P = engine.prepare(sc, seed)
    boot = engine.train_challenger(P, engine.lifecycle.FIRST_TRAIN_DAY, seed, version=1)
    done = []
    for policy in policies:
        out = result_path(set_name, scenario, policy, seed)
        if out.exists():
            continue
        result = engine.run(sc, seed, policy, params[policy], P, boot)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, separators=(",", ":"), default=float))
        tmp.replace(out)
        done.append(f"{set_name}/{scenario}/{policy}/seed{seed} ({result['seconds']}s)")
    return done


def run_set(
    set_name: str,
    cfg: dict,
    policies: list[str] | None = None,
    scenario_names: list[str] | None = None,
    workers: int | None = None,
) -> None:
    policies = policies or POLICIES
    seeds = cfg["seeds"][set_name]
    names = scenario_names or [s.name for s in scenarios.load_set(set_name)]
    jobs = [
        (
            set_name,
            name,
            seed,
            [p for p in policies if not result_path(set_name, name, p, seed).exists()],
        )
        for name in names
        for seed in seeds
    ]
    jobs = [j for j in jobs if j[3]]
    if not jobs:
        print("all runs already saved")
        return
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 4) // 3))
    print(f"{len(jobs)} (scenario, seed) jobs on {workers} workers")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_job, *j, cfg["policies"]) for j in jobs]
        for f in as_completed(futures):
            for line in f.result():
                print("saved", line, flush=True)

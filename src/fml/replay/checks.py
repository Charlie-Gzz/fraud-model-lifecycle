"""Host-side cluster checks: the broken-model canary test and the scorer load test.

- `broken_model`: registers a model whose binary expects 11 features while its metadata
  says 12 (a classic schema mismatch), starts a canary under steady traffic, and checks
  that Argo Rollouts' Prometheus analysis aborts it and the champion keeps serving.
- `loadtest`: measures single-request latency and throughput of the scorer.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import numpy as np

from fml import REPO_ROOT
from fml.features.definitions import FEATURES
from fml.platform import kubectl
from fml.replay.fullloop import _use_forwarded_services, replay_job

RESULTS = REPO_ROOT / "results" / "cluster"


def _load_job(name: str, seconds: int, workers: int, rate: float | None) -> dict:
    job = replay_job("x", "dev/control", 0, None, "none")
    cmd = ["python", "-m", "fml.replay.load", "--seconds", str(seconds), "--workers", str(workers)]
    if rate:
        cmd += ["--rate", str(rate)]
    job["metadata"]["name"] = name
    job["spec"]["template"]["spec"]["containers"][0]["command"] = cmd
    job["spec"]["template"]["metadata"]["labels"]["app"] = "load"
    return job


def _run_job(job: dict, wait_s: int) -> str:
    name = job["metadata"]["name"]
    kubectl("delete", "job", name, "-n", "fml", "--ignore-not-found", quiet=True)
    kubectl("apply", "-f", "-", input=json.dumps(job), quiet=True)
    kubectl(
        "wait",
        "--for=condition=complete",
        f"job/{name}",
        "-n",
        "fml",
        f"--timeout={wait_s}s",
        quiet=True,
        check=False,
    )
    return kubectl("logs", f"job/{name}", "-n", "fml", "--tail=1", quiet=True).stdout.strip()


def register_broken_model() -> str:
    import lightgbm as lgb
    import mlflow

    from fml.serve import registry

    rng = np.random.default_rng(0)
    X = rng.random((2000, len(FEATURES) - 1))  # one feature short
    booster = lgb.train(
        {"objective": "binary", "verbose": -1},
        lgb.Dataset(X, rng.random(2000) < 0.1),
        num_boost_round=5,
    )
    mlflow.set_experiment("fraud-lifecycle")
    with (
        tempfile.TemporaryDirectory() as tmp,
        mlflow.start_run(run_name="broken-model-test") as run,
    ):
        d = Path(tmp) / "model"
        d.mkdir()
        booster.save_model(str(d / "model.txt"))
        (d / "meta.json").write_text(json.dumps({"threshold": 0.5, "features": FEATURES}))
        mlflow.log_artifacts(str(d), artifact_path="model")
        version = (
            registry.client()
            .create_model_version(
                registry.MODEL_NAME,
                source=f"{run.info.artifact_uri}/model",
                run_id=run.info.run_id,
                tags={
                    "purpose": "deliberately broken: binary expects 11 features, metadata says 12"
                },
            )
            .version
        )
    return str(version)


def broken_model() -> dict:
    from fml.pipeline import rollout

    _use_forwarded_services()
    before = rollout.model_version(rollout.get_rollout())
    version = register_broken_model()
    print(f"[fml] registered broken model v{version}; champion is v{before}", flush=True)
    load = _load_job("load-canary-test", seconds=360, workers=4, rate=30)
    kubectl("delete", "job", "load-canary-test", "-n", "fml", "--ignore-not-found", quiet=True)
    kubectl("apply", "-f", "-", input=json.dumps(load), quiet=True)
    time.sleep(20)
    t0 = time.time()
    promoted = rollout.deploy("broken-model-test", 0, version, "manual-broken-model-test")
    after = rollout.model_version(rollout.get_rollout())
    ro = rollout.get_rollout()
    result = {
        "broken_version": version,
        "champion_before": before,
        "serving_after": after,
        "promoted": promoted,
        "rolled_back": not promoted and after == before,
        "seconds_to_resolve": round(time.time() - t0, 1),
        "rollout_phase_after": ro.get("status", {}).get("phase"),
    }
    kubectl("delete", "job", "load-canary-test", "-n", "fml", "--ignore-not-found", quiet=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "broken_model_rollback.json").write_text(json.dumps(result, indent=2))
    return result


def loadtest(seconds: int = 60, workers: int = 16) -> dict:
    out = _run_job(_load_job("loadtest", seconds, workers, None), seconds + 240)
    result = json.loads(out)
    pods = (
        kubectl("get", "pods", "-n", "fml", "-l", "app=fraud-scorer", "--no-headers", quiet=True)
        .stdout.strip()
        .splitlines()
    )
    result["scorer_pods"] = len(pods)
    result["note"] = (
        "single-transaction /score requests from inside the cluster, new TCP "
        "connection per request, on a laptop kind cluster"
    )
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "loadtest.json").write_text(json.dumps(result, indent=2))
    return result

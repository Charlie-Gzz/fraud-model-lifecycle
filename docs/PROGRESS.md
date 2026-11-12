# Progress

## Status
- **M0 Setup:** done. Private repo pushed.
- **M1 Platform up:** first `fml up` worked after two fixes (MLflow job runner, SeaweedFS gRPC ports). Clean `fml down` (14 s) + `fml up` from scratch in progress to confirm.
- **M2 Data generator:** done. Tests for determinism, drift start day, label delay. `assets/charts/scenario_check_{dev,test}.png` confirm drift timing.
- **M3 Features + parity:** numpy batch, Redis online and Spark implementations written. Batch vs online parity passes in tests (fakeredis). Spark-in-cluster parity runs as a workflow step (not yet run).
- **M4-M7:** code written (training/gate, MLflow registry, scorer service, Rollout + analysis, monitor, retrain WorkflowTemplate, replay, collect). Not yet run on the cluster.
- **M8:** backtest engine + resumable runner written. Dev set (tuning) runs in progress.

## Log
- 2026-11-12: Environment checked. git 2.55, gh logged in with workflow scope, Docker Desktop 28.2.2 with 15.6 GB and 12 CPUs (normal profile), uv 0.13.7, Python 3.12.16 via uv, PyPI / GitHub / Helm repos reachable, no ANTHROPIC_API_KEY set.
- 2026-11-12: Pinned CLI tools downloaded to `.tools/` and checksum-verified (`uv run fml tools`).
- 2026-11-12: MinIO images are no longer published; switched the object store to SeaweedFS (S3 API).
- 2026-11-12: MLflow 3.18 server started 8 job-runner processes (1.9 GB) and got OOM-killed. `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false` brings it to 360 MB.
- 2026-11-12: Idle platform memory: 4.0 GB (docker stats on the kind node).
- 2026-11-12: Generator made harder on dev data only (legit look-alikes, hijacked-device takeovers, quiet stolen-card fraud): baseline recall at 1% budget went from 0.99 (not credible) to about 0.80.
- 2026-11-12: Images: runtime 1.8 GB, spark 3.0 GB (first build). Spark image slimmed to only what the Spark step imports (rebuild pending).

## Next step
1. When `fml up` finishes: restore `k8s/kustomization.pending.yaml` to `k8s/kustomization.yaml`, rebuild images (`fml images`), `fml apply`.
2. Smoke-test the scorer, then run the bootstrap workflow (Spark features, parity, train, gate, canary) with `fml demo --days 30`.
3. Review dev backtest results; tune drift thresholds on dev only; freeze `configs/experiment.yaml`.

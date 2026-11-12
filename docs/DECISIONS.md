# Decisions

Choices a reviewer might question. Newest at the bottom of each section.

## Setup and tooling

| Decision | Options considered | Why | Easy to change? |
|---|---|---|---|
| Docker memory recorded at M0: 15.6 GB, 12 CPUs. Normal profile, but the platform is still sized to fit in 10 GB. | slim profile, normal profile | Docker has more than 10 GB, so Section 1.3 says normal profile. Limits still add up to under 10 GB. | yes |
| CLI tool versions: kind v0.33.0 (node image v1.37.0), kubectl v1.37.2, helm v4.3.1, terraform 1.17.1, argo v4.1.6, kubectl-argo-rollouts v1.10.2. Pinned with SHA-256 in `infra/tools.toml`. | latest of each; releases a few weeks old | Picked the newest release that had been out for a while where possible (terraform 1.17.2 shipped yesterday, so 1.17.1). Checksums come from each project's official checksum file. | yes |
| pandas pinned to 2.3.x, not 3.x | pandas 3.1, pandas 2.3 | Evidently 0.7.23 imports a pandas internal that pandas 3 removed. | yes, once Evidently supports pandas 3 |
| plotly pinned to 5.x | plotly 7.1, plotly 5.24 | Evidently 0.7.23 requires plotly < 6. | yes |
| Product name **Tideline** | Driftwatch, Canary Lane, Tideline | Short, ties to the lifecycle timeline (the star view) and to drift. Teal accent fits water. | yes |

## Platform

| Decision | Options considered | Why | Easy to change? |
|---|---|---|---|
| Object store: **SeaweedFS** (S3 API) instead of MinIO | MinIO, local PersistentVolume (plan's fallback), SeaweedFS, Garage | MinIO no longer publishes container images (Docker Hub and Quay both return "not found"). The plan's fallback (a local volume) would change every storage code path. SeaweedFS is Apache-2.0, speaks S3, and keeps the architecture the same. | yes (any S3 endpoint works) |
| Postgres, Redis and MLflow from a small local Helm chart (`infra/charts/fml-platform`), not Bitnami charts | Bitnami charts, official images in a local chart | Bitnami stopped publishing free versioned images in 2025. Official images pinned by digest are simpler and smaller. | yes |
| Two Terraform roots: `infra/cluster` (kind) then `infra/platform` (Helm + Kubernetes providers) | one root with `-target`, two roots | Provider config for Helm/Kubernetes needs the cluster to exist first. Two roots avoid `-target` and partial-apply surprises. | yes |
| `fml down` destroys the kind cluster and drops the now-stale platform state | destroy platform releases first, then cluster | The releases live inside the cluster, so deleting the cluster removes them. Takes 14 s instead of minutes. | yes |
| App manifests (`k8s/`) applied with `kubectl apply -k` after Terraform | Terraform `kubernetes_manifest` | The Rollout, WorkflowTemplate and monitoring CRs need their CRDs at plan time, which Terraform cannot guarantee on a fresh cluster. | yes |
| MLflow server runs with `MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false` | default, disabled | The GenAI job runner starts ~8 extra processes (1.9 GB) and OOM-killed the pod. We do not use server-side jobs. | yes |
| MLflow image installs `psycopg[binary]` (psycopg 3) | psycopg2 | MLflow 3.18's SQLAlchemy URL resolves to the psycopg 3 driver. | yes |
| Redis 8 (official image) | Valkey | Plan names Redis. Redis 8 is AGPLv3/SSPL/RSAL tri-licensed; fine for a local, unmodified, non-hosted use. Valkey (BSD) is a drop-in if that matters. | yes |
| Grafana anonymous viewer, Argo Workflows `--auth-mode=server` | login screens | Everything is reached only through `kubectl port-forward` on 127.0.0.1. Admin password is still random in `.env`. | yes |

## Data and features

| Decision | Options considered | Why | Easy to change? |
|---|---|---|---|
| Three implementations of one feature definition: numpy (backtest), Spark (cluster training), Redis (serving) | Spark everywhere | Spark and Java may only run in containers, and the backtest has to run hundreds of scenario-days in minutes on the host. Parity tests tie them together: numpy vs Redis in unit tests, Spark vs the service's logged features in every retrain workflow. | no |
| Windows are `[t - W, t)` on integer seconds; the current transaction is never in its own window | inclusive windows | Same-second transactions make inclusive windows order-dependent. Exclusive windows also make a retried request produce identical features, so the replay can retry safely. | no |
| The Spark job reads and writes local Parquet that the step copies from/to S3 with boto3 | Spark `s3a://` with hadoop-aws jars | Avoids pinning Hadoop/AWS SDK jar versions to PySpark's Hadoop build. The data is small (under 500k rows). | yes |
| Generator realism tuned on the **dev** seed only (101) before any policy comparison | leave it easy | The first version gave 99% recall at the budget, which no reviewer would believe. Added legit look-alikes and quieter fraud. | yes |
| Labels: fraud reported 0.5 + Gamma(1.5, 1.2) days later; a day is "settled" after 3 days; unreported fraud counts as legit | perfect labels | Realistic chargeback delay. Late reports become label noise, as in practice. | yes |

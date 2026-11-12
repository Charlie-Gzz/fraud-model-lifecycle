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

## Experiment design (all decided on the dev set; the test set had not been generated or run)

| Decision | Options considered | Why | Easy to change? |
|---|---|---|---|
| Alert budget: analysts review the top **1%** of each day's transactions; "fraud caught" = recall inside that budget | fixed score threshold, 0.5% or 2% budget | Review capacity is what is fixed in practice. Base fraud rate is about 0.5%, so 1% gives the model room without being trivial. | yes (config) |
| Windows: labels settle after 3 days; gate holdout = 5 most recent settled days; train = 21 settled days before that; the bootstrap model is trained at the end of day 35 | refit on train+holdout after the gate | The model that ships is exactly the one the gate evaluated. Refitting would ship something never tested. | yes |
| Promotion gate: challenger must beat the champion's recall at the budget on the same holdout; ties go to PR-AUC | PR-AUC only, a minimum gain | Recall at the budget is the business metric. Applied to every policy, so the comparison isolates *when* to retrain, not *whether* to check. | yes |
| Data drift: Evidently `DataDriftPreset` with Wasserstein (numeric) and Jensen-Shannon (categorical), Evidently's default threshold 0.1, reference = 20k rows of the champion's training features, current = last 7 days served by the champion | KS/chi-squared p-values, PSI | Distance methods do not flag tiny differences on large samples the way p-values do. 7 days washes out weekly seasonality. | yes |
| **Design v1 → v2 after the first dev run** (v1 table kept in `results/archive/dev_v1_summary.md`) | keep v1 | v1 had three flaws, all visible on dev only: (1) the bootstrap model got 13 training days, so weekly retraining "won" on the no-drift control just by having more data (79.0% → 81.9%); (2) the drift policy needed 25% of features to drift, so a new category (one feature) was only caught 8-19 days later via the recall drop; (3) it retrained once per alarm and then went quiet, while labels for a new fraud pattern arrive over weeks (dev new pattern: drift policy 61.6% vs weekly 65.5%). v2: bootstrap at day 35 with a full 21-day window, scenarios 110 days, alarm when any feature crosses Evidently's threshold, and 2 weekly follow-up retrains after an alarm-triggered retrain. | yes |
| Synthetic merchants: 2000 per category (was 60) | keep 60 | With 60, "never used this merchant before" kept falling over the run because simulated users start with no history, so `is_new_merchant` looked like drift even on the control. Real users have long histories. | yes |
| Recovery metric: back to 95% of the pre-drift baseline (7-day rolling recall) **and staying there for 7 days** | first crossing | Daily recall is noisy (about 20 frauds a day); a single lucky week counted as recovery even on the control. | yes |
| Dev seeds 101-105, test seeds 201-205; dev drift starts day 55, test day 65 (ramp 7 vs 10 days) | same timing | Section 1.5: tune on dev, report on test with different seeds and drift timing. | yes |
| **Design v2 → v3 on dev** (v2 table in `results/archive/dev_v2_summary.md`) | keep v2 | v2 raised 4-17 false drift alarms before the drift on every dev seed. Nearly all came from `is_new_merchant` ("never used this merchant"), which creeps as simulated histories fill up. v3 replaces it with `new_merchant_7d` (not used in the last 7 days; stationary) and requires a feature to drift on 3 consecutive daily checks. | yes |
| **Experiment config frozen on 2026-11-12** after dev v3 (`configs/experiment.yaml`, `frozen: true`). Dev v3 table: `results/archive/dev_v3_summary_at_freeze.md`. `fml backtest --set test` refuses to run on an unfrozen config. | keep tuning | Dev v3: at most 1 false alarm per seed before drift; on the control the drift policy retrained 0.6 times on average vs 10 for weekly; drift-triggered matched weekly on all three drift scenarios with about half the retrains. Nothing left that dev data could justify changing. | no (changing it now needs a logged reason and the earlier numbers) |
| Same seed rule in both modes: LightGBM seed = scenario seed + decision day; drift reference sample uses `random_state = decision day` | seed + model version (backtest) vs seed + day (cluster) | With identical data, features, labels and windows, matching seeds let the full Kubernetes loop and the fast backtest make the same decisions, so their agreement is a real check. A first test-set run had started with the old rule; it was stopped after about 2 minutes (4 no-retrain files saved, never opened), deleted, and rerun. Dev results kept the old rule (dev is tuning only). | yes |

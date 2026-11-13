# Portfolio card: Tideline

**Pitch:** A fraud model's whole lifecycle on a local Kubernetes cluster: it notices when fraud changes, retrains itself, ships the new model behind a canary, and is measured against simply retraining every week.

**Headline metric:** Drift-triggered retraining caught as much fraud as weekly retraining in every drift scenario, with 65% fewer retrains (14 vs 40 across four scenarios), and it never retrained when nothing had changed (0 retrains on the no-drift control, versus 10).

**Three bullets**
- Built the full ML platform as code: Terraform creates a kind cluster with MLflow, Argo Workflows, Argo Rollouts, Prometheus/Grafana, Redis and an S3 store; `fml up` brings it all up from scratch in about 15 minutes and peaks at 8.6 GB of memory.
- Wrote one feature definition with three implementations (PySpark for training, Redis for serving, numpy for a fast backtest) and checked them against each other on every retrain: Spark and the live service agreed to within 4e-12 on every retrain (17 workflows, 173,000 to 518,000 transactions each).
- Ran a pre-registered experiment: tuned on dev scenarios, froze the settings, then reported the test scenarios with 5 seeds each, including where drift-triggered retraining did not help (a new fraud pattern: both policies won back only 13% of the lost catch, because labels arrive late).

**Tags:** MLOps, ML platform, Kubernetes, Terraform, MLflow, Argo Workflows, Argo Rollouts, Evidently, data drift, model monitoring, LightGBM, PySpark, Prometheus, Grafana, fraud detection

**CV bullet:** Built a self-retraining fraud model platform on Kubernetes (Terraform, MLflow, Argo, Evidently, PySpark, LightGBM) with canary rollouts and automatic rollback; in a pre-registered 60-run experiment, drift-triggered retraining matched weekly retraining's fraud catch with 65% fewer retrains and zero retrains when nothing had changed.

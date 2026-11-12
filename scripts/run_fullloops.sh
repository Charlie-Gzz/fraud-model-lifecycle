#!/usr/bin/env bash
# Run the full Kubernetes loop once per test scenario, one after another.
# Each run is collected into results/fullloop/ when it finishes.
set -u
cd "$(dirname "$0")/.."
uv run --no-sync fml images fml-runtime fml-spark
kubectl_() { .tools/kubectl.exe --kubeconfig .run/kubeconfig "$@"; }
kubectl_ -n fml rollout restart deploy/fml-monitor
kubectl_ -n fml rollout status deploy/fml-monitor --timeout=300s
for sc in new_fraud_pattern new_category amount_drift control; do
  echo "=== test/$sc $(date)"
  uv run --no-sync fml demo --scenario "test/$sc" --seed 201
  echo "=== done test/$sc $(date)"
done
echo "ALL DONE"

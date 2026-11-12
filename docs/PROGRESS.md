# Progress

## Status
- **M0 Setup:** done. Private repo pushed.
- **M1 Platform up:** done. Clean `fml down` (14 s) then `fml up` from scratch: 16 min including first image builds, all 9 services healthy, 4.0 GB idle.
- **M2 Data generator:** done. `assets/charts/scenario_check_{dev,test}.png`.
- **M3 Features + parity:** done. Spark job runs in the cluster; parity on 172,045 transactions, max diff 1.8e-12 (first run, before the `new_merchant_7d` change; rerun pending).
- **M4 Training + registry:** done. Bootstrap model registered in MLflow with alias `champion`, model-card tags.
- **M5 Serving + canary:** done. Canary 20/50/100 promoted v1; broken model (schema mismatch) rolled back automatically in 52 s by the error-rate analysis (`results/cluster/broken_model_rollback.json`). Load test 424 req/s, p95 67 ms (`results/cluster/loadtest.json`).
- **M6/M7:** monitor + workflow + replay written and run end to end for 37 days. Full 110-day dev run in progress (`.run/demo2.log`).
- **M8:** backtest + runner + `fml results` written. Dev design v3 running (v1 and v2 archived in `results/archive/`). Test set NOT run yet; config NOT frozen yet.
- **M9:** site (index/results), charts, architecture diagram (done, reviewed), screenshot/video script written; nothing final yet.

## Log
- 2026-11-12: Environment checked (see DECISIONS). Tools pinned in `infra/tools.toml`.
- 2026-11-12: MinIO images gone; SeaweedFS instead. MLflow job runner disabled (OOM).
- 2026-11-12: Dev v1 → v2 (bootstrap day 35, 110-day scenarios, per-feature alarm, follow-ups). v2 → v3: `is_new_merchant` redefined as `new_merchant_7d` (stationary) and data drift must persist 3 days (v2 had 4-17 false alarms before drift on every dev seed).
- 2026-11-12: Policy chart colours validated with the dataviz palette validator (dark surface).

## Next step
1. Check dev v3 results (`uv run fml results --set dev`). If false alarms on control are low, freeze `configs/experiment.yaml` (frozen: true, date) and log it.
2. Run test set: `uv run fml backtest --set test` (about 30 min).
3. Full loop on the test scenarios (`uv run fml demo --scenario test/<name> --seed 201`), with `python -m fml.viz.screens canary` running alongside for the canary screenshot.
4. `uv run fml assets`, screenshots, video, README, HANDOFF.

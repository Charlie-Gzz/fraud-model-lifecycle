# Handoff

## What was built
**Tideline**: a fraud model's full lifecycle on a local kind cluster, created by Terraform.
- Seeded synthetic transactions (3,000 users, 110 days, 5 fraud patterns, delayed labels) and four scenarios per set (new fraud pattern, new merchant category, rising amounts, control), with separate dev and test sets.
- One feature definition, three implementations (PySpark for training, Redis for serving, numpy for the backtest), checked against each other on every retrain.
- LightGBM training with time-based windows, a promotion gate on recent settled labels, MLflow registry with model cards and `champion` / `challenger` aliases.
- FastAPI scorer behind an Argo Rollouts canary (20/50/100% of pods) with Prometheus analysis and automatic rollback.
- Evidently drift monitor + delayed-label recall, Grafana dashboard, alert rules, and an Argo Workflows retraining pipeline triggered by the monitor.
- A traffic replay that drives everything in simulated days, a fast in-process backtest that shares the same code, and a policy comparison (no retraining vs weekly vs drift-triggered).
- Results site (timeline star view + policy comparison + interactive Plotly page), charts, screenshots, walkthrough video, architecture diagram, slides outline, portfolio card.

## How to run it
```bash
uv sync
uv run fml up      # kind cluster + platform + images (about 15 min the first time)
uv run fml demo    # one scenario end to end (about 30 min)
uv run fml down    # delete the cluster (images stay for a fast restart)
```
Verified from a fresh clone: `uv sync`, `uv run fml up` and `uv run fml demo --days 40` ran clean in 19 minutes (images already in the Docker cache), all 10 services healthy.
No cluster needed: `uv run fml results` recomputes every number, `uv run fml assets` redraws charts and the site, `uv run fml backtest --set test` reruns the comparison (resumable).

## Headline numbers (test scenarios, 5 seeds, fast backtest)
> When a new fraud pattern appeared, drift-triggered retraining recovered 13% of the lost fraud catch, the same as weekly retraining (13%); neither got back to 95% of the pre-drift catch before the run ended. It needed 3.8 retrains instead of 10, and 0 false retrains on the no-drift control (weekly retraining: 10).

| Test scenario | Fraud caught after drift: drift-triggered / weekly / none | Retrains: drift vs weekly | Time to detect |
|---|---|---|---|
| New fraud pattern | 56.7% / 56.6% / 53.6% | 3.8 vs 10 | 10.2 days (5 to 22), via recall drop |
| New merchant category | 69.3% / 69.5% / 63.6% | 4.4 vs 10 | 8.0 days |
| Amounts creep up | 74.1% / 73.8% / 71.7% | 6.0 vs 10 | 5.2 days |
| Control (no drift) | 77.9% / 77.9% / 77.9% | 0 vs 10 | 2 alarms in cooldown, 0 retrains |

- **Full Kubernetes loop (seed 201, one run per scenario):** fraud caught within 0.9 points of the backtest in all four; identical retrain days on amount drift and the control, one day earlier on the new pattern, one fewer follow-up on the new category (`results/fullloop/agreement.md`).
- **Feature parity:** Spark vs online features passed in all 17 retrain workflows (173k to 518k transactions each), max difference 4e-12.
- **Canary safety:** broken model rolled back automatically in 52 s by the Prometheus error-rate analysis.
- **Scorer:** 424 req/s, p95 67 ms, 0 errors (5 pods, laptop).
- **Design history (dev only):** v1 lost to weekly retraining on the new pattern; v2 had 4-17 false alarms per run; v3 frozen before the test set. Tables in `results/archive/`.

## Where the assets are
- Charts (PNG 1600px + SVG): `assets/charts/`
- Screenshots: `assets/screenshots/`
- Video and GIF: `assets/video/walkthrough.mp4`, `assets/video/walkthrough.gif`
- Architecture diagram: `assets/diagrams/architecture.svg` / `.png`
- Site: `site/` (open `site/index.html` through any static server; GitHub Pages workflow prepared, not enabled)
- Results: `results/summary_test.md`, `results/backtest/`, `results/fullloop/`, `results/cluster/`
- Docs: `docs/DECISIONS.md`, `docs/QUESTIONS_FOR_CHARLIE.md`, `docs/PROGRESS.md`, `docs/DEMO_SCRIPT.md`, `docs/SLIDES_OUTLINE.md`, `docs/PORTFOLIO_CARD.md`

## Top questions (my recommendation first; details in QUESTIONS_FOR_CHARLIE.md)
**Answered 2026-11-13: all recommendations accepted.**
1. **SeaweedFS instead of MinIO?** Keep it (MinIO images are gone; any S3 endpoint works).
2. **Keep the final drift policy (v3)?** Yes, and tell the v1 to v3 story openly.
3. **Headline framing?** "Same catch, 65% fewer retrains, zero when nothing changed", with the new-pattern limit stated plainly.
4. **Make the scam pattern easier?** No; the test set has been seen.
5. **Image sizes (1.4 to 1.9 GB each)?** Fine for now; split the scorer image later if it matters.

## Skipped, faked, or changed, and why
- **MinIO → SeaweedFS** (images no longer published). Logged in DECISIONS.
- **Canary weights are pod ratios** (1 of 5 pods = 20%), no service mesh. Documented in Limitations.
- **The simulation clock pauses** while a retraining workflow trains; the canary runs on the next day's traffic at a slower pace.
- **Full-loop runs use one seed per scenario** (201); the 5-seed numbers come from the fast backtest. Both are labeled.
- **Dev results** used an earlier LightGBM seed rule (seed + model version). Dev is tuning only; the test set and full loops use the aligned rule (seed + decision day).
- **One cluster incident and one bug**, both logged in PROGRESS: a manifest re-apply briefly reset the scorer's model version (no traffic was affected), and the monitor did not persist its drift streak (found by the full loop, fixed, regression test added, affected runs rerun).
- Stretch items: **2 done** (label-free performance estimate: it never noticed any drift and ran 12 points high; `assets/charts/label_free_estimate.png`), **3 done** (`infra/cloud-example`, reuses `infra/platform`, `terraform validate` only, in CI). **1 skipped** (shadow mode next to the canary): it needs the cluster back up for an honest test, and I did not want to ship untested serving code.

## Memory and cost
Kind node memory: 4.0 GB idle, peak 8.6 GB during full-loop runs (limit set by the plan: 10 GB). Docker Desktop had 15.6 GB, so the normal (not slim) profile was used. Disk: images 1.4 to 1.9 GB each.
Cost: $0 (local Docker Desktop only, no cloud, no API keys).

## Secret scan
gitleaks v8.30.1 (Docker) over the full git history: **no leaks found**. A scan of the working directory found 199 matches, all in untracked or ignored files (`.venv` library test fixtures, `.env`, local Terraform state, `.run/`); **none in any tracked file**. Local passwords live only in `.env` (gitignored) and in Kubernetes Secrets inside the (now deleted) cluster.

## Pre-public checklist
1. Read README and HANDOFF; answer the questions (done 2026-11-13: recommendations accepted).
2. Skim screenshots and video for anything personal.
3. Confirm the secret scan was clean and nothing from your employer appears.
4. Make the repo public (done 2026-11-13), then enable GitHub Pages.
5. Pin the repo on your profile and add it to the portfolio site.

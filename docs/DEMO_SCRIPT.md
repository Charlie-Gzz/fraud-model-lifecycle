# Demo script (2 minutes)

Video: `assets/video/walkthrough.mp4` (recorded by `uv run fml screens video`). Narration below matches the shot list.

| Time | Shot | Narration |
|---|---|---|
| 0:00-0:12 | Timeline site, "New fraud pattern" tab, cursor moving along the lines | "This is a fraud model's life over 110 simulated days. The teal line is how much fraud it catches inside a fixed review budget: the top 1% of each day's transactions." |
| 0:12-0:30 | Hover the dashed amber line at day 65, then the drop | "On day 65 a new scam appears: victims pay from their own phone, so the inputs barely change. Catch drops from about 78% to the mid 50s." |
| 0:30-0:50 | Click the amber "Drift detected" marker; details panel | "The monitor only sees it once fraud reports arrive: recall on settled labels falls 15 points. That is the alarm. No feature drift, which is the honest part of this story." |
| 0:50-1:10 | Click "Gate passed", then "Promoted"; champion vs challenger table, canary steps | "The alarm starts an Argo workflow: Spark features, a parity check against the live features, training, and a gate against the champion on recent data. The winner goes out as a canary, 20, 50, then 100% of pods, with Prometheus watching errors, latency and flag rate." |
| 1:10-1:25 | Switch tabs: New category, Amounts, Control | "A new merchant category and rising amounts show up as feature drift within 5 to 8 days. And on the control, with no drift, it never retrains." |
| 1:25-1:45 | Policy comparison page, scroll the charts | "Against retraining every week: the same fraud caught in every scenario, with 65% fewer retrains. Where neither helps much is the new fraud pattern. Labels are slow, so both win back only 13% of the lost catch." |
| 1:45-2:00 | Grafana dashboard | "All of it runs on one laptop: Terraform, kind, MLflow, Argo, Evidently, Prometheus and Grafana. `fml up`, `fml demo`, and it runs by itself." |

Recording notes: headless Chromium at 1600x1000, dark theme, no logins on screen (Grafana anonymous viewer, Argo server auth mode), no local paths.

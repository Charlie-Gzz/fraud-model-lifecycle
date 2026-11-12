# Dev set, design v1 (archived before the design changes)

First policy design: drift alarm only when 25% of features drift, no follow-up retrains,
bootstrap model trained on 13 days, 100-day scenarios, drift at day 45.

| Scenario | Policy | Fraud caught after drift (mean, min-max) | Retrains (mean) |
|---|---|---|---|
| amount_drift | drift | 78.8% (76.9-80.5%) | 5.2 |
| amount_drift | none | 75.3% (69.5-78.8%) | 0.0 |
| amount_drift | scheduled | 79.0% (77.2-81.2%) | 10.0 |
| control | drift | 79.0% (76.4-82.2%) | 0.2 |
| control | none | 79.0% (76.4-82.2%) | 0.0 |
| control | scheduled | 81.9% (79.3-83.8%) | 10.0 |
| new_category | drift | 73.9% (70.7-77.2%) | 1.0 |
| new_category | none | 67.5% (65.0-70.4%) | 0.0 |
| new_category | scheduled | 76.8% (73.9-80.5%) | 10.0 |
| new_fraud_pattern | drift | 61.6% (57.2-63.4%) | 1.2 |
| new_fraud_pattern | none | 56.8% (55.3-58.3%) | 0.0 |
| new_fraud_pattern | scheduled | 65.5% (64.0-66.5%) | 10.0 |

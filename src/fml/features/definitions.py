"""The single source of truth for feature names, windows and category codes.

Three implementations compute these features and must agree:
- `fml.features.batch`  (numpy, used by the fast backtest)
- `fml.features.spark_job` (PySpark, used for training on the cluster)
- `fml.features.online` (Redis, used by the model service per request)

Every window feature looks only at the same user's *earlier* transactions:
those with timestamp in [t - window, t). The current transaction is never included.
"""

HOUR = 3600
DAY = 86400
WEEK = 7 * DAY

# Merchant categories. The last one only appears in the new-category drift scenario,
# but it has a fixed code so every model and the service encode it the same way.
CATEGORIES = [
    "grocery",
    "restaurants",
    "fuel",
    "retail",
    "online_retail",
    "electronics",
    "travel",
    "entertainment",
    "health",
    "gift_cards",
    "crypto_exchange",
]
CATEGORY_CODE = {name: i for i, name in enumerate(CATEGORIES)}

FEATURES = [
    "amount",
    "hour",
    "category_code",
    "is_new_device",  # device never used by this user before
    "new_merchant_7d",  # merchant not used by this user in the last 7 days
    "txn_count_1h",
    "txn_count_24h",
    "amount_sum_24h",
    "distinct_merchants_24h",
    "avg_amount_7d",  # NaN when the user has no transactions in the last 7 days
    "amount_ratio_7d",  # amount / avg_amount_7d, NaN when there is no history
    "seconds_since_last",  # capped at 7 days
]
CATEGORICAL = ["category_code"]

# Absolute tolerance used by the parity tests. Sums of cents can differ in the last bits
# between Spark (Java doubles) and numpy, nothing more.
PARITY_TOLERANCE = 1e-6

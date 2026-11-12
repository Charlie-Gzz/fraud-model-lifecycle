"""PySpark feature job (local mode, runs only inside the fml-spark container).

Same definitions as batch.py and online.py. A window over `rangeBetween(-W, -1)` on
integer-second timestamps covers exactly the rows with ts in [t - W, t).

Usage inside the container:
    python -m fml.features.spark_job <in.parquet> <out.parquet>
"""

from __future__ import annotations

import sys

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from fml.features.definitions import DAY, FEATURES, HOUR, WEEK


def build(df: DataFrame) -> DataFrame:
    by_user = Window.partitionBy("user_id").orderBy("ts")
    w1h = by_user.rangeBetween(-HOUR, -1)
    w24h = by_user.rangeBetween(-DAY, -1)
    w7d = by_user.rangeBetween(-WEEK, -1)
    first_dev = F.min("ts").over(Window.partitionBy("user_id", "device_id"))
    first_mer = F.min("ts").over(Window.partitionBy("user_id", "merchant_id"))
    nan = F.lit(float("nan"))

    count_7d = F.count("ts").over(w7d)
    avg_7d = F.when(count_7d > 0, F.sum("amount").over(w7d) / count_7d).otherwise(nan)
    last_ts = F.max("ts").over(w7d)

    out = df.select(
        "txn_id",
        F.col("amount").cast("double").alias("amount"),
        F.floor((F.col("ts") % DAY) / HOUR).cast("long").alias("hour"),
        F.col("category").cast("long").alias("category_code"),
        (F.col("ts") == first_dev).cast("long").alias("is_new_device"),
        (F.col("ts") == first_mer).cast("long").alias("is_new_merchant"),
        F.count("ts").over(w1h).cast("long").alias("txn_count_1h"),
        F.count("ts").over(w24h).cast("long").alias("txn_count_24h"),
        F.coalesce(F.sum("amount").over(w24h), F.lit(0.0)).alias("amount_sum_24h"),
        F.size(F.collect_set("merchant_id").over(w24h))
        .cast("long")
        .alias("distinct_merchants_24h"),
        avg_7d.alias("avg_amount_7d"),
        (F.col("amount") / avg_7d).alias("amount_ratio_7d"),
        F.when(last_ts.isNull(), F.lit(WEEK))
        .otherwise(F.least(F.col("ts") - last_ts, F.lit(WEEK)))
        .cast("long")
        .alias("seconds_since_last"),
    )
    return out.select("txn_id", *FEATURES)


def spark_session() -> SparkSession:
    return (
        SparkSession.builder.master("local[2]")
        .appName("fml-features")
        .config("spark.driver.memory", "1g")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )


def run(in_path: str, out_path: str) -> int:
    spark = spark_session()
    spark.sparkContext.setLogLevel("WARN")
    df = spark.read.parquet(in_path)
    feats = build(df)
    feats.toPandas().to_parquet(out_path, index=False)  # small enough for one file
    n = df.count()
    spark.stop()
    return n


if __name__ == "__main__":
    print(f"features for {run(sys.argv[1], sys.argv[2])} transactions")

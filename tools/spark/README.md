# Offline PySpark materialization

This optional local Spark SQL job turns the historical study's hash-pinned daily
Parquet panel into partitioned month-end observations. It selects the last observed
session per symbol/month and computes the return from the previous observed monthly
price. The first observation has a null previous price and return. If a month is
absent, the retained previous-observation date makes the longer interval explicit.

The implementation uses Spark windows and partitioned Parquet output, keeping full
datasets out of Python driver collections. It checks unique symbol/session keys and
finite positive prices, then compares output rows in both directions after readback.
Source bytes, code, dependency lock, runtime version and output hashes remain in the
output directory. A failure leaves its receipt and partial outputs for inspection.

Use Python 3.12 and a Java runtime compatible with the pinned Spark release. Install
the isolated environment when ready to execute it:

```powershell
uv sync --project tools/spark --locked
# Use the source-panel.parquet hash from the study's manifest.json.
uv run --project tools/spark --locked python tools/spark/materialize.py --input artifacts/historical-study/source-panel.parquet --sha256 HASH_FROM_MANIFEST --output artifacts/spark-monthly
```

The output path must be new. The job uses `local[2]`, eight shuffle partitions by
default, UTC session time and a loopback driver. It creates no cluster or cloud job.
The input snapshot is retained locally; provider data-use terms still apply.

This is an implemented optional data-processing path with static checks. Spark
execution and scale performance have not been measured. It neither reruns the
historical backtests nor replaces Polars, and its output is not automatically admitted
as point-in-time trading data. Adjusted historical prices retain their retrospective
vintage and universe assumptions.

References: [Spark windows](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.Window.html),
[lag](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.lag.html),
[Parquet output](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrameWriter.parquet.html).

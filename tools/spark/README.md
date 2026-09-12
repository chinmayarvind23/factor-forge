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

The job completed in a network-disabled Spark 4.0.1 / Python 3.10.12 container,
materializing 30,192 daily rows into 1,440 month-end rows. All 32 output files passed
hash verification; an independent Polars comparison matched the selected dates and
prices. See the [runtime receipt](../../reports/evidence/spark-materialization.json).
This compatibility run used two CPUs, 2 GiB memory and a 512-process limit with
`JAVA_TOOL_OPTIONS=-XX:ActiveProcessorCount=2`. An earlier 256-process limit exhausted
native thread capacity and is retained in the execution history.

The optional uv environment above pins Spark 4.2.0 and has not been executed. The
receipt distinguishes its lock identity from the actual runtime version. No scale
performance improvement is claimed. This data-processing job neither reruns the
historical backtests nor replaces Polars, and its output is not automatically admitted
as point-in-time trading data. Adjusted historical prices retain their retrospective
vintage and universe assumptions.

References: [Spark windows](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.Window.html),
[lag](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.lag.html),
[Parquet output](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrameWriter.parquet.html).

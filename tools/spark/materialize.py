"""Materialize a hash-pinned historical panel with Spark SQL, separately from backtesting."""

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The cached Spark compatibility image uses Python 3.10.
UTC = timezone.utc  # noqa: UP017


def digest(path: Path) -> str:
    """Stream hashes so input and output provenance does not require driver-sized buffers."""
    with path.open("rb") as stream:
        checksum = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
        return checksum.hexdigest()


def monthly_panel(frame: Any) -> Any:
    """Select the last observed session each month, then lag within each symbol only."""
    from pyspark.sql import Window
    from pyspark.sql import functions as f

    month = frame.withColumn("month", f.date_format("date", "yyyy-MM"))
    order = Window.partitionBy("symbol", "month").orderBy(f.col("date").desc())
    monthly = month.withColumn("position", f.row_number().over(order)).filter("position = 1")
    prior = Window.partitionBy("symbol").orderBy("date")
    return (
        monthly.drop("position")
        .withColumn("previous_observation", f.lag("date").over(prior))
        .withColumn("previous_price", f.lag("price").over(prior))
        .withColumn("observation_return", f.col("price") / f.col("previous_price") - f.lit(1.0))
        .withColumn("year", f.year("date"))
    )


def main() -> None:
    """Use a bounded local Spark session; failures retain provenance without a success receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partitions", type=int, default=8)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha256) or not 1 <= args.partitions <= 128:
        raise ValueError("Require a SHA-256 identity and 1..128 shuffle partitions")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = args.output / "source.parquet"
    receipt: dict[str, Any] = dict(
        schema_version="spark-monthly-materialization-v1",
        status="started",
        started_at=datetime.now(UTC).isoformat(),
        source_sha256=args.sha256,
        code_sha256=digest(Path(__file__)),
        lock_sha256=digest(Path(__file__).with_name("uv.lock")),
        partitions=args.partitions,
        master="local[2]",
        python_version=sys.version,
        scope="Retrospective adjusted-price observations; no backtest or timing admission",
    )
    receipt_path = args.output / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    spark = None
    try:
        shutil.copyfile(args.input, snapshot)
        if digest(snapshot) != args.sha256:
            raise ValueError("Input snapshot differs from declared source identity")
        from pyspark.sql import SparkSession
        from pyspark.sql import functions as f

        spark = (
            SparkSession.builder.master("local[2]")
            .appName("FactorForge offline materialization")
            .config("spark.ui.enabled", "false")
            .config("spark.driver.bindAddress", "127.0.0.1")
            .config("spark.driver.host", "127.0.0.1")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.sql.shuffle.partitions", str(args.partitions))
            .getOrCreate()
        )
        frame = spark.read.parquet(str(snapshot))
        if dict(frame.dtypes) != {
            "symbol": "string",
            "date": "date",
            "month": "string",
            "price": "double",
        }:
            raise ValueError("Expected the historical study's symbol/date/month/price schema")
        invalid = frame.filter(
            f.col("symbol").isNull()
            | (f.length("symbol") == 0)
            | f.col("date").isNull()
            | f.col("price").isNull()
            | f.isnan("price")
            | (f.col("price") <= 0)
            | (f.abs(f.col("price")) == float("inf"))
        )
        count = frame.count()
        if count == 0 or invalid.limit(1).count():
            raise ValueError("Input contains no rows or invalid observations")
        if frame.groupBy("symbol", "date").count().filter("count > 1").limit(1).count():
            raise ValueError("Input repeats a symbol/session")
        monthly = monthly_panel(frame)
        if (
            monthly.filter(
                f.isnan("observation_return") | (f.abs(f.col("observation_return")) == float("inf"))
            )
            .limit(1)
            .count()
        ):
            raise ValueError("Derived return is not finite")
        target = args.output / "monthly"
        monthly.repartition(args.partitions, "symbol").write.mode("errorifexists").partitionBy(
            "year"
        ).parquet(str(target))
        saved = spark.read.parquet(str(target))
        if (
            monthly.exceptAll(saved.select(monthly.columns)).limit(1).count()
            or saved.select(monthly.columns).exceptAll(monthly).limit(1).count()
        ):
            raise ValueError("Materialized rows differ on readback")
        if digest(snapshot) != args.sha256:
            raise ValueError("Source snapshot changed during execution")
        receipt.update(
            status="completed",
            spark_version=spark.version,
            source_rows=count,
            monthly_rows=saved.count(),
            readback_verified=True,
            files={
                p.relative_to(args.output).as_posix(): digest(p)
                for p in sorted(target.rglob("*"))
                if p.is_file()
            },
        )
    except BaseException as error:
        receipt.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        if spark is not None:
            spark.stop()
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()

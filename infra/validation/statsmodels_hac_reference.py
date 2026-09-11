"""Generate original intercept-only HAC reference values with isolated statsmodels 0.14.6."""

import json
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np
from statsmodels.regression.linear_model import OLS
from statsmodels.stats.sandwich_covariance import cov_hac


def main(output: Path) -> None:
    """Freeze library outputs for explicit original vectors without importing FactorForge."""
    if version("statsmodels") != "0.14.6":
        raise ValueError("Reference requires statsmodels 0.14.6")
    cases = []
    for name, values, lags in (
        ("four-integers", ["1", "2", "3", "4"], (0, 1, 3)),
        ("original-24", [str(((i * 7) % 17 - 8) / 100) for i in range(24)], (0, 1, 4, 12)),
    ):
        numbers = np.array([float(value) for value in values])
        fitted = OLS(numbers, np.ones((len(numbers), 1))).fit()
        for lag in lags:
            for correction in (False, True):
                variance = float(cov_hac(fitted, nlags=lag, use_correction=correction)[0, 0])
                cases.append(
                    dict(
                        name=name,
                        values=values,
                        lags=lag,
                        correction="n_over_n_minus_one" if correction else "none",
                        mean=float(fitted.params[0]),
                        variance_mean=variance,
                        standard_error=variance**0.5,
                        t_statistic=float(fitted.params[0]) / variance**0.5,
                    )
                )
    record = dict(statsmodels=version("statsmodels"), numpy=version("numpy"), cases=cases)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved {len(cases)} independent reference cases to {output}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

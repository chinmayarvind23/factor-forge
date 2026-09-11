# Bounded formula language

The arithmetic interpreter is a foundation for source-extraction grading and later factor execution. It does not establish point-in-time eligibility, portfolio accounting, or economic validity of its inputs.

Accepted syntax consists of scalar names, decimal constants, parentheses, unary plus/minus, `+`, `-`, `*`, `/`, `delta(name)`, and `compound_return(name,N)`. Python attributes, subscripts, power, imports, arbitrary calls, comprehensions, comments, and Unicode identifiers are rejected. The parser validates the syntax tree; an explicit interpreter dispatches each permitted operation without `eval` or `exec`.

```python
from factorforge.domain.formula import evaluate_formula

ratio = evaluate_formula(
    "(sales-cost)/assets", scalars={"sales": "90", "cost": "30", "assets": "120"}
)
change = evaluate_formula("delta(balance)", deltas={"balance": ["40", "25"]})
```

The ratio is exactly `Decimal("0.5")` and the change is `Decimal("-15")`. Delta pairs are ordered beginning, ending. Return arrays are ordered oldest to newest; compounding uses their last `N` observations and preserves the full supplied array. The window is a literal integer from 1 through 120. Monthly returns are fractions, so `0.1` means 10 percent. Separate financial validation must determine whether any supplied return is economically admissible.

Evaluation uses 50-digit Decimal arithmetic with explicitly fixed half-even rounding and traps, independent of the caller's mutable Decimal context. Nonfinite inputs, missing observations, zero denominators, and results outside the declared numeric bounds fail with typed errors. Valid finite magnitudes lie between `1e-100` and `1e100`, with zero allowed. Intermediate results must also satisfy these bounds; algebraically equivalent expressions can differ in admission if an intermediate operation exceeds them.

Resource limits are 2,048 expression characters, 128 syntax nodes, depth 24, and 512 primitive arithmetic operations. An input snapshot has at most 64 names and 4,096 values; each series has at most 1,200 observations. Every declared value is checked, including unused fields and observations outside a selected tail window.

Hand-computed tests establish arithmetic behavior. Agreement on a finite numerical test set is not proof of symbolic equivalence or published-factor replication. A later executable strategy still needs the full data, timing, universe, weighting, cost, and exit contracts.

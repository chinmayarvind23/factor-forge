"""Original hand examples establish arithmetic meaning and the closed formula language."""

from decimal import ROUND_UP, Decimal, DefaultContext, localcontext

import pytest

from factorforge.domain.errors import ResearchError
from factorforge.domain.formula import evaluate_formula


def test_scalar_arithmetic_and_equivalent_expressions() -> None:
    """Exact decimal arithmetic and algebraic rearrangements agree on a hand-computed ratio."""
    values = {"sales": "90", "cost": "30", "assets": "120"}
    for expression in ("(sales-cost)/assets", "sales/assets-cost/assets", "-(cost-sales)/assets"):
        assert evaluate_formula(expression, scalars=values) == Decimal("0.5")
    assert evaluate_formula("0.1 + 0.2") == Decimal("0.3")


def test_delta_is_ending_less_beginning_and_compound_uses_latest_window() -> None:
    """Declared beginning/end pairs and oldest/newest arrays resolve temporal ambiguity."""
    assert evaluate_formula("delta(stock)", deltas={"stock": ("40", "25")}) == Decimal("-15")
    returns = ["0.9", "0.25", "-0.2", "0"]
    assert evaluate_formula("compound_return(returns,3)", series={"returns": returns}) == Decimal(
        "0"
    )
    assert returns == ["0.9", "0.25", "-0.2", "0"]


@pytest.mark.parametrize(
    "expression",
    [
        "x.real",
        "x[0]",
        "abs(x)",
        "__import__('os')",
        "x**2",
        "x//2",
        "x%2",
        "[x]",
        "(x for x in y)",
        "lambda: 1",
        "x if x else 0",
        "True",
        "'1'",
        "1j",
        "delta(x,2)",
        "delta(x=1)",
        "delta(x+1)",
        "compound_return(x,0)",
        "compound_return(x,-1)",
        "compound_return(x,121)",
        "compound_return(x,2.0)",
        "compound_return(x,n)",
        "compound_return(x,window=2)",
        "sum(x)",
        "0xff",
        "1_000",
    ],
)
def test_unsupported_syntax_never_reaches_execution(expression: str) -> None:
    """Python-shaped input cannot expand the arithmetic grammar into runtime capabilities."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(expression, scalars={"x": 1}, deltas={"x": (0, 1)}, series={"x": [0, 0]})
    assert failure.value.code == "FORMULA_SYNTAX"


@pytest.mark.parametrize(
    "expression,inputs,code",
    [
        ("missing", {}, "FORMULA_INPUT"),
        ("delta(missing)", {}, "FORMULA_INPUT"),
        ("compound_return(missing,2)", {}, "FORMULA_INPUT"),
        ("compound_return(r,2)", {"series": {"r": ["0.1"]}}, "FORMULA_INPUT"),
        ("1/zero", {"scalars": {"zero": 0}}, "FORMULA_ZERO_DIVISION"),
        ("1e100*10", {}, "FORMULA_NUMERIC"),
        ("1e-100/10", {}, "FORMULA_NUMERIC"),
    ],
)
def test_missing_data_and_invalid_results_fail_typed(
    expression: str,
    inputs: dict[str, object],
    code: str,
) -> None:
    """Absent or unusable financial inputs cannot turn into default zero or nonfinite results."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(expression, **inputs)  # type: ignore[arg-type]
    assert failure.value.code == code


@pytest.mark.parametrize("value", [True, None, "NaN", "Infinity", float("inf"), "1e101", "1e-101"])
def test_invalid_numeric_inputs_fail_even_when_unused(value: object) -> None:
    """The declared input snapshot must be finite and bounded, including unselected values."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula("1", scalars={"unused": value})  # type: ignore[dict-item]
    assert failure.value.code == "FORMULA_INPUT"


@pytest.mark.parametrize("expression", ["1" * 2049, "-" * 40 + "1", "+".join(["1"] * 90)])
def test_expression_resource_limits_are_deterministic(expression: str) -> None:
    """Length, tree depth and node budgets reject work before recursive evaluation."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(expression)
    assert failure.value.code == "FORMULA_LIMIT"


def test_compounding_has_an_operation_budget() -> None:
    """Small syntax cannot hide repeated long-window products beyond the execution budget."""
    expression = "+".join(["compound_return(r,120)"] * 3)
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(expression, series={"r": ["0"] * 120})
    assert failure.value.code == "FORMULA_LIMIT"


def test_ambient_context_cannot_round_away_a_limit_violation() -> None:
    """Magnitude checks use exact Decimal comparison even under a hostile caller context."""
    with localcontext() as context:
        context.prec = 2
        with pytest.raises(ResearchError) as failure:
            evaluate_formula("1.0000000000000000000000000000000000000000000000000000001e100")
        assert failure.value.code == "FORMULA_NUMERIC"
        assert evaluate_formula("1/8") == Decimal("0.125")


def test_large_python_integer_is_rejected_before_string_conversion() -> None:
    """Large caller integers fail before Python's string-conversion digit limit is reached."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula("x", scalars={"x": 10**10000})
    assert failure.value.code == "FORMULA_INPUT"


@pytest.mark.parametrize("expression", ["\uff58", "1 # comment", "1\\\n+2"])
def test_only_ascii_arithmetic_tokens_are_accepted(expression: str) -> None:
    """Unicode name normalization and Python comments or continuations are outside the DSL."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(expression, scalars={"x": 1})
    assert failure.value.code == "FORMULA_SYNTAX"


@pytest.mark.parametrize("expression", ["", "(", "_hidden", "f(x=1)"])
def test_malformed_and_hidden_names_fail_syntax(expression: str) -> None:
    """Incomplete grammar and hidden names fail before input lookup or arithmetic."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(expression)
    assert failure.value.code == "FORMULA_SYNTAX"


def test_non_string_formula_fails_typed() -> None:
    """An invalid API-level type must not leak an incidental Python attribute error."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(None)  # type: ignore[arg-type]
    assert failure.value.code == "FORMULA_SYNTAX"


@pytest.mark.parametrize(
    "inputs",
    [
        {"scalars": []},
        {"scalars": {"_hidden": 1}},
        {"deltas": {"a": [1]}},
        {"series": {"a": "123"}},
        {"series": {"a": []}},
        {"series": {"a": [0] * 1201}},
    ],
)
def test_declared_input_shapes_are_checked(inputs: dict[str, object]) -> None:
    """Malformed mappings, period pairs and series cannot masquerade as validated snapshots."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula("1", **inputs)  # type: ignore[arg-type]
    assert failure.value.code == "FORMULA_INPUT"


def test_total_input_name_budget() -> None:
    """Many individually valid declarations cannot exceed the snapshot's global name cap."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula("1", scalars={f"x{index}": 0 for index in range(65)})
    assert failure.value.code == "FORMULA_LIMIT"


def test_total_values_and_balanced_tree_limits() -> None:
    """Many bounded individual arrays and shallow broad expressions still have global caps."""
    with pytest.raises(ResearchError) as failure:
        evaluate_formula("1", series={f"x{index}": [0] * 1000 for index in range(5)})
    assert failure.value.code == "FORMULA_LIMIT"
    expression = "1"
    for _ in range(6):
        expression = f"({expression}+{expression})"
    with pytest.raises(ResearchError) as failure:
        evaluate_formula(expression)
    assert failure.value.code == "FORMULA_LIMIT"


def test_mutable_default_context_cannot_change_rounding() -> None:
    """A library modifying Decimal's template must not alter reproducible arithmetic outputs."""
    rounding = DefaultContext.rounding
    try:
        DefaultContext.rounding = ROUND_UP
        assert evaluate_formula("1/3") == Decimal("0." + "3" * 50)
    finally:
        DefaultContext.rounding = rounding

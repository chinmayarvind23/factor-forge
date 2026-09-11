"""A bounded arithmetic interpreter grades source formulas without executing Python code."""

import ast
import re
from collections.abc import Mapping, Sequence
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

from factorforge.domain.errors import ResearchError

MAX_EXPRESSION_LENGTH = 2048
MAX_AST_NODES = 128
MAX_AST_DEPTH = 24
MAX_OPERATIONS = 512
MAX_WINDOW = 120
MAX_SERIES_LENGTH = 1200
MAX_INPUT_NAMES = 64
MAX_INPUT_VALUES = 4096
MAX_NUMBER_LENGTH = 128
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
type Numeric = Decimal | int | float | str
type Deltas = Mapping[str, Sequence[Numeric]]
type Series = Mapping[str, Sequence[Numeric]]


def _failure(code: str) -> ResearchError:
    """Errors identify the rejected contract without echoing untrusted expressions or values."""
    messages = {
        "FORMULA_SYNTAX": "Formula uses unsupported arithmetic syntax.",
        "FORMULA_LIMIT": "Formula exceeds a resource limit.",
        "FORMULA_INPUT": "Formula inputs are missing, invalid or out of bounds.",
        "FORMULA_NUMERIC": "Formula result is nonfinite or outside the numeric bounds.",
        "FORMULA_ZERO_DIVISION": "Formula denominator is zero.",
    }
    return ResearchError(code, messages[code], 422)


def _bounded(value: Decimal, code: str) -> Decimal:
    """Finite magnitudes from 1e-100 through 1e100 avoid hidden overflow or underflow."""
    if not value.is_finite() or (value and not -100 <= value.adjusted() <= 100):
        raise _failure(code)
    if value.copy_abs() > Decimal("1e100"):
        raise _failure(code)
    return value


def _number(value: Numeric, code: str) -> Decimal:
    """Decimal strings preserve source precision; booleans and oversized values are rejected."""
    if type(value) not in (Decimal, int, float, str):
        raise _failure(code)
    if isinstance(value, int) and value.bit_length() > 426:
        raise _failure(code)
    text = str(value)
    if len(text) > MAX_NUMBER_LENGTH or NUMBER.fullmatch(text) is None:
        raise _failure(code)
    try:
        return _bounded(Decimal(text), code)
    except DecimalException:
        raise _failure(code) from None


def _constant(node: ast.Constant, expression: str) -> Decimal:
    """Read decimal literal text directly instead of inheriting AST binary-float rounding."""
    token = ast.get_source_segment(expression, node) or ""
    if type(node.value) not in (int, float) or NUMBER.fullmatch(token) is None:
        raise _failure("FORMULA_SYNTAX")
    return _number(token, "FORMULA_NUMERIC")


def _validate_call(node: ast.Call) -> None:
    """Only named delta and fixed positive-window compounding have interpreter meanings."""
    if not isinstance(node.func, ast.Name) or node.keywords:
        raise _failure("FORMULA_SYNTAX")
    name = node.func.id
    count = 1 if name == "delta" else 2 if name == "compound_return" else 0
    if not count or len(node.args) != count or not isinstance(node.args[0], ast.Name):
        raise _failure("FORMULA_SYNTAX")
    if count == 2:
        window = node.args[1]
        if (
            not isinstance(window, ast.Constant)
            or type(window.value) is not int
            or not 1 <= window.value <= MAX_WINDOW
        ):
            raise _failure("FORMULA_SYNTAX")


def parse_formula(expression: str) -> ast.Expression:
    """Validate a closed AST grammar and finite tree budget before any numerical evaluation."""
    if not isinstance(expression, str):
        raise _failure("FORMULA_SYNTAX")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise _failure("FORMULA_LIMIT")
    if not expression.isascii() or any(character in expression for character in ("#", "\\")):
        raise _failure("FORMULA_SYNTAX")
    expression = expression.strip()
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise _failure("FORMULA_SYNTAX") from None
    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Call,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.UAdd,
        ast.USub,
    )
    pending: list[tuple[ast.AST, int]] = [(tree, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > MAX_AST_NODES or depth > MAX_AST_DEPTH:
            raise _failure("FORMULA_LIMIT")
        if not isinstance(node, allowed):
            raise _failure("FORMULA_SYNTAX")
        if isinstance(node, ast.Name) and NAME.fullmatch(node.id) is None:
            raise _failure("FORMULA_SYNTAX")
        if isinstance(node, ast.Call):
            _validate_call(node)
        if isinstance(node, ast.Constant):
            _constant(node, expression)
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return tree


def _inputs(
    scalars: Mapping[str, Numeric],
    deltas: Deltas,
    series: Series,
) -> tuple[dict[str, Decimal], dict[str, tuple[Decimal, ...]], dict[str, tuple[Decimal, ...]]]:
    """Snapshot and validate every declared value, preserving full oldest-to-newest arrays."""
    if any(not isinstance(group, Mapping) for group in (scalars, deltas, series)):
        raise _failure("FORMULA_INPUT")
    if sum(len(group) for group in (scalars, deltas, series)) > MAX_INPUT_NAMES:
        raise _failure("FORMULA_LIMIT")
    for group in (scalars, deltas, series):
        if any(not isinstance(name, str) or NAME.fullmatch(name) is None for name in group):
            raise _failure("FORMULA_INPUT")
    scalar_values = {name: _number(value, "FORMULA_INPUT") for name, value in scalars.items()}
    converted: list[dict[str, tuple[Decimal, ...]]] = []
    count = len(scalar_values)
    for group, is_delta in ((deltas, True), (series, False)):
        values = {}
        for name, sequence in group.items():
            if not isinstance(sequence, (list, tuple)):
                raise _failure("FORMULA_INPUT")
            if (is_delta and len(sequence) != 2) or (
                not is_delta and not 1 <= len(sequence) <= MAX_SERIES_LENGTH
            ):
                raise _failure("FORMULA_INPUT")
            count += len(sequence)
            if count > MAX_INPUT_VALUES:
                raise _failure("FORMULA_LIMIT")
            values[name] = tuple(_number(value, "FORMULA_INPUT") for value in sequence)
        converted.append(values)
    return scalar_values, converted[0], converted[1]


class _Evaluator:
    """One invocation owns its operation budget and immutable validated input snapshots."""

    def __init__(
        self, expression: str, scalars: Mapping[str, Numeric], deltas: Deltas, series: Series
    ) -> None:
        """Parse-independent input validation prevents unused bad values from escaping checks."""
        self.expression = expression
        self.scalars, self.deltas, self.series = _inputs(scalars, deltas, series)
        self.operations = 0

    def operation(self, operator: ast.operator, left: Decimal, right: Decimal) -> Decimal:
        """Charge each primitive operation before arithmetic and reject zero denominators."""
        self.operations += 1
        if self.operations > MAX_OPERATIONS:
            raise _failure("FORMULA_LIMIT")
        if isinstance(operator, ast.Add):
            result = left + right
        elif isinstance(operator, ast.Sub):
            result = left - right
        elif isinstance(operator, ast.Mult):
            result = left * right
        else:
            if not right:
                raise _failure("FORMULA_ZERO_DIVISION")
            result = left / right
        return _bounded(result, "FORMULA_NUMERIC")

    def call(self, node: ast.Call) -> Decimal:
        """A delta uses [beginning, ending]; compounding takes the last N observations."""
        assert isinstance(node.func, ast.Name) and isinstance(node.args[0], ast.Name)
        name = node.args[0].id
        if node.func.id == "delta":
            if name not in self.deltas:
                raise _failure("FORMULA_INPUT")
            beginning, ending = self.deltas[name]
            return self.operation(ast.Sub(), ending, beginning)
        window = node.args[1]
        assert isinstance(window, ast.Constant) and type(window.value) is int
        values = self.series.get(name, ())
        if len(values) < window.value:
            raise _failure("FORMULA_INPUT")
        product = Decimal(1)
        for value in values[-window.value :]:
            gross = self.operation(ast.Add(), Decimal(1), value)
            product = self.operation(ast.Mult(), product, gross)
        return self.operation(ast.Sub(), product, Decimal(1))

    def visit(self, node: ast.expr) -> Decimal:
        """Dispatch validated node types explicitly; no runtime Python expression is invoked."""
        if isinstance(node, ast.Constant):
            return _constant(node, self.expression)
        if isinstance(node, ast.Name):
            if node.id not in self.scalars:
                raise _failure("FORMULA_INPUT")
            return self.scalars[node.id]
        if isinstance(node, ast.BinOp):
            return self.operation(node.op, self.visit(node.left), self.visit(node.right))
        if isinstance(node, ast.UnaryOp):
            operator = ast.Sub() if isinstance(node.op, ast.USub) else ast.Add()
            return self.operation(operator, Decimal(0), self.visit(node.operand))
        assert isinstance(node, ast.Call)
        return self.call(node)


def evaluate_formula(
    expression: str,
    *,
    scalars: Mapping[str, Numeric] | None = None,
    deltas: Deltas | None = None,
    series: Series | None = None,
) -> Decimal:
    """Interpret arithmetic with 50-digit Decimal precision independent of ambient context."""
    tree = parse_formula(expression)
    try:
        with localcontext(
            Context(
                prec=50,
                rounding=ROUND_HALF_EVEN,
                Emin=-999,
                Emax=999,
                capitals=1,
                clamp=0,
                flags=[],
                traps=[InvalidOperation, DivisionByZero, Overflow],
            )
        ):
            evaluator = _Evaluator(
                expression.strip(),
                scalars if scalars is not None else {},
                deltas if deltas is not None else {},
                series if series is not None else {},
            )
            return evaluator.visit(tree.body)
    except DecimalException:
        raise _failure("FORMULA_NUMERIC") from None

"""Explicit label intervals support causal walk-forward and purged research cross-validation."""

from datetime import timedelta
from itertools import pairwise
from typing import Self

from pydantic import model_validator

from factorforge.domain.factors import Contract
from factorforge.domain.performance import Instant


class LabelPeriod(Contract):
    """One formation group keeps all securities at that clock together across folds."""

    start: Instant
    end: Instant
    available_at: Instant

    @model_validator(mode="after")
    def chronological_label(self) -> Self:
        """A label cannot be known before its declared outcome window ends."""
        if not self.start < self.end <= self.available_at:
            raise ValueError("Label interval and availability must be chronological")
        return self


class ValidationFold(Contract):
    """Indices refer to the unchanged chronological input; exclusion reasons stay separate."""

    train: tuple[int, ...]
    test: tuple[int, ...]
    purged: tuple[int, ...]
    embargoed: tuple[int, ...]


def _periods(rows: tuple[LabelPeriod, ...]) -> tuple[LabelPeriod, ...]:
    """Bound work and reject ambiguous input instead of silently sorting formation groups."""
    if type(rows) is not tuple or not 2 <= len(rows) <= 10000:
        raise ValueError("Supply between two and 10000 chronological formation groups")
    rows = tuple(LabelPeriod.model_validate(row) for row in rows)
    if any(left.start >= right.start for left, right in pairwise(rows)):
        raise ValueError("Formation starts must be strictly increasing")
    return rows


def walk_forward(
    periods: tuple[LabelPeriod, ...], *, initial_train_size: int, test_size: int
) -> tuple[ValidationFold, ...]:
    """Expand historical training with nonoverlapping test blocks and strict pre-test availability.

    Initial size counts candidate history, not guaranteed mature labels. A final partial test
    block is retained. The caller must fit transformations using each fold's training indices.
    """
    rows = _periods(periods)
    if (
        type(initial_train_size) is not int
        or type(test_size) is not int
        or not 1 <= initial_train_size < len(rows)
        or not 1 <= test_size <= len(rows)
        or (len(rows) - initial_train_size + test_size - 1) // test_size > 100
    ):
        raise ValueError("Invalid or excessive walk-forward fold configuration")
    folds = []
    for start in range(initial_train_size, len(rows), test_size):
        train = tuple(i for i in range(start) if rows[i].available_at < rows[start].start)
        purged = tuple(i for i in range(start) if rows[i].available_at >= rows[start].start)
        if not train:
            raise ValueError("Walk-forward fold has no available training labels")
        folds.append(
            ValidationFold(
                train=train,
                test=tuple(range(start, min(start + test_size, len(rows)))),
                purged=purged,
                embargoed=(),
            )
        )
    return tuple(folds)


def purged_fold(
    periods: tuple[LabelPeriod, ...], *, test_start: int, test_stop: int, embargo_seconds: int
) -> ValidationFold:
    """Remove inclusive label overlap and a declared post-test elapsed-time embargo.

    The contiguous test block uses its full label-window envelope. Training may occur after
    testing, so this is research cross-validation rather than a causal deployment simulation.
    Embargo starts at the latest test label end, not the last test formation timestamp.
    """
    rows = _periods(periods)
    if (
        any(type(value) is not int for value in (test_start, test_stop, embargo_seconds))
        or not 0 <= test_start < test_stop <= len(rows)
        or not 0 <= embargo_seconds <= 366 * 86400
    ):
        raise ValueError("Invalid test block or embargo")
    start = rows[test_start].start
    end = max(row.end for row in rows[test_start:test_stop])
    try:
        embargo_end = end + timedelta(seconds=embargo_seconds)
    except OverflowError:
        raise ValueError("Embargo exceeds the supported calendar") from None
    train, purged, embargoed = [], [], []
    for index, row in enumerate(rows):
        if test_start <= index < test_stop:
            continue
        if row.start <= end and row.end >= start:
            purged.append(index)
        elif end < row.start <= embargo_end:
            embargoed.append(index)
        else:
            train.append(index)
    if not train:
        raise ValueError("Purged fold has no training labels")
    return ValidationFold(
        train=tuple(train),
        test=tuple(range(test_start, test_stop)),
        purged=tuple(purged),
        embargoed=tuple(embargoed),
    )

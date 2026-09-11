"""Independent chronological examples exercise label availability, overlap and embargo."""

from datetime import UTC, datetime, timedelta

import pytest

from factorforge.validation.splits import LabelPeriod, purged_fold, walk_forward


def periods() -> tuple[LabelPeriod, ...]:
    """Eight original daily labels have a one-day horizon and delayed availability."""
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    return tuple(
        LabelPeriod(
            start=origin + timedelta(days=i),
            end=origin + timedelta(days=i + 1),
            available_at=origin + timedelta(days=i + 1, hours=1),
        )
        for i in range(8)
    )


def test_walk_forward_uses_only_available_training_labels() -> None:
    """The label starting just before test formation is still unavailable and must be removed."""
    folds = walk_forward(periods(), initial_train_size=4, test_size=2)
    assert [(fold.train, fold.test, fold.purged) for fold in folds] == [
        ((0, 1, 2), (4, 5), (3,)),
        ((0, 1, 2, 3, 4), (6, 7), (5,)),
    ]


def test_purging_and_embargo_have_independent_reference_indices() -> None:
    """Inclusive overlap removes adjacent labels; embargo extends beyond the last test label."""
    fold = purged_fold(periods(), test_start=3, test_stop=5, embargo_seconds=86400)
    assert fold.test == (3, 4)
    assert fold.purged == (2, 5)
    assert fold.embargoed == (6,)
    assert fold.train == (0, 1, 7)


def test_a_training_label_enclosing_the_test_window_is_purged() -> None:
    """Checking only whether training starts inside the test interval misses enclosing labels."""
    rows = list(periods())
    rows[0] = rows[0].model_copy(update={"end": rows[6].end, "available_at": rows[7].available_at})
    fold = purged_fold(tuple(rows), test_start=3, test_stop=5, embargo_seconds=0)
    assert fold.train == (1, 6, 7) and fold.purged == (0, 2, 5)


def test_latest_test_label_end_controls_embargo() -> None:
    """Nonmonotonic label durations use the maximum outcome end across the whole test block."""
    rows = list(periods())
    rows[3] = rows[3].model_copy(update={"end": rows[5].end, "available_at": rows[6].available_at})
    fold = purged_fold(tuple(rows), test_start=3, test_stop=5, embargo_seconds=86400)
    assert fold.train == (0, 1)
    assert fold.purged == (2, 5, 6) and fold.embargoed == (7,)


def test_partial_final_test_block_is_retained() -> None:
    """A remainder cannot silently remove the last observations from validation."""
    folds = walk_forward(periods(), initial_train_size=4, test_size=3)
    assert tuple(fold.test for fold in folds) == ((4, 5, 6), (7,))


@pytest.mark.parametrize(
    "start,stop,embargo", [(-1, 2, 0), (2, 2, 0), (0, 9, 0), (True, 3, 0), (2, 4, -1), (0, 8, 0)]
)
def test_invalid_purged_configuration_is_rejected(start: int, stop: int, embargo: int) -> None:
    """Out-of-range blocks, empty training and invalid embargo never become valid folds."""
    with pytest.raises(ValueError):
        purged_fold(periods(), test_start=start, test_stop=stop, embargo_seconds=embargo)


@pytest.mark.parametrize("rows", [(), tuple(reversed(periods())), (periods()[0], periods()[0])])
def test_invalid_chronology_is_rejected(rows: tuple[LabelPeriod, ...]) -> None:
    """Duplicate formation groups and implicit sorting cannot change a requested split."""
    with pytest.raises(ValueError):
        walk_forward(rows, initial_train_size=1, test_size=1)


@pytest.mark.parametrize("initial,size", [(True, 2), (0, 2), (4, 0), (8, 1), (1, 2)])
def test_invalid_or_empty_training_split_is_rejected(initial: int, size: int) -> None:
    """A fold without mature labels cannot pretend to provide a training evaluation."""
    with pytest.raises(ValueError):
        walk_forward(periods(), initial_train_size=initial, test_size=size)

from pathlib import Path

import pytest

from src.tenderplan import (
    TenderLifecycleStatus,
    TenderLifecycleStore,
)


def test_lifecycle_store_ensures_once_and_preserves_state(tmp_path: Path):
    store = TenderLifecycleStore(tmp_path / "agent.db")
    key = "eis:123"

    assert store.ensure(key) is TenderLifecycleStatus.DISCOVERED
    assert store.ensure(key, TenderLifecycleStatus.RELEVANT) is TenderLifecycleStatus.DISCOVERED

    assert store.set(key, TenderLifecycleStatus.RELEVANT) is TenderLifecycleStatus.RELEVANT
    assert store.get(key) is TenderLifecycleStatus.RELEVANT

    history = store.history(key)
    assert [(event["old_status"], event["new_status"]) for event in history] == [
        (None, "discovered"),
        ("discovered", "relevant"),
    ]


def test_lifecycle_store_rejects_invalid_transition(tmp_path: Path):
    store = TenderLifecycleStore(tmp_path / "agent.db")
    key = "eis:123"
    store.ensure(key)

    with pytest.raises(ValueError, match="invalid tender lifecycle transition"):
        store.set(key, TenderLifecycleStatus.WON)


def test_lifecycle_store_archives_terminal_tender(tmp_path: Path):
    store = TenderLifecycleStore(tmp_path / "agent.db")
    key = "eis:123"
    store.ensure(key)
    for status in (
        TenderLifecycleStatus.RELEVANT,
        TenderLifecycleStatus.SHORTLISTED,
        TenderLifecycleStatus.ASSIGNED,
        TenderLifecycleStatus.PREPARING,
        TenderLifecycleStatus.SUBMITTED,
        TenderLifecycleStatus.AUCTION,
        TenderLifecycleStatus.WON,
    ):
        store.set(key, status)
    store.set(key, TenderLifecycleStatus.ARCHIVED)

    assert store.get(key) is TenderLifecycleStatus.ARCHIVED
    with pytest.raises(ValueError):
        store.set(key, TenderLifecycleStatus.RELEVANT)


def test_lifecycle_set_initializes_missing_row_atomically(tmp_path: Path):
    store = TenderLifecycleStore(tmp_path / "agent.db")
    key = "eis:atomic"
    assert store.set(key, TenderLifecycleStatus.RELEVANT) is TenderLifecycleStatus.RELEVANT
    assert store.get(key) is TenderLifecycleStatus.RELEVANT
    assert [(e["old_status"], e["new_status"]) for e in store.history(key)] == [
        (None, "discovered"),
        ("discovered", "relevant"),
    ]

"""Regression tests: TenderPlan lifecycle terminal protection + CRM callback wiring.

Fixed contract (2026-09-18). An explicit CRM participation action must reach
TenderPlan ONLY through the service layer (``register_participation``), which
walks the validated lifecycle transitions (DISCOVERED -> RELEVANT -> SHORTLISTED)
and ensures the user-scoped application task idempotently.

There is deliberately NO ``force`` bypass on ``TenderLifecycleStore.set``:
terminal states can never revert, and no caller may skip the state machine.
(The earlier draft of this file expected ``lifecycle.set(..., force=True)`` —
that contract came from an unapplied patch and was rejected; the stepwise walk
achieves the same business result with a complete audit history and no new API.)
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.crm.telegram import handle_callback
from src.storage.database import TenderDatabase
from src.tenderplan import (
    TenderLifecycleStatus,
    TenderLifecycleStore,
    TenderTaskStore,
    application_task_id,
    ensure_application_task,
    register_participation,
)
from src.tenderplan.lifecycle import InvalidLifecycleTransition


def _tmp_db() -> tuple[TenderDatabase, TenderLifecycleStore, TenderTaskStore, Path]:
    base = Path(tempfile.mkdtemp()) / "test.db"
    db = TenderDatabase(base)
    lifecycle = TenderLifecycleStore(base)
    tasks = TenderTaskStore(base)
    return db, lifecycle, tasks, base


def _insert_tender(
    db: TenderDatabase,
    unique_key: str = "eis:T-1",
    deadline: datetime | None = None,
) -> int:
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO tenders (platform, external_id, unique_key, title, url,
                                 deadline, first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("eis", "T-1", unique_key, "Test Tender", "https://x.test/1",
             deadline.isoformat() if deadline else None,
             "2026-09-13T00:00:00+00:00", "2026-09-13T00:00:00+00:00"),
        )
        row = conn.execute("SELECT id FROM tenders WHERE unique_key = ?", (unique_key,)).fetchone()
    return int(row["id"])


# ─── Lifecycle: terminal-state protection (no force bypass exists) ──────

def test_lifecycle_terminal_state_cannot_revert():
    """Terminal states are immutable: ARCHIVED can never return to a live state."""
    _db, lifecycle, _tasks, _base = _tmp_db()
    key = "eis:T-1"

    lifecycle.set(key, TenderLifecycleStatus.RELEVANT)
    lifecycle.set(key, TenderLifecycleStatus.SHORTLISTED)
    lifecycle.set(key, TenderLifecycleStatus.ASSIGNED)
    lifecycle.set(key, TenderLifecycleStatus.PREPARING)
    lifecycle.set(key, TenderLifecycleStatus.SUBMITTED)
    lifecycle.set(key, TenderLifecycleStatus.WON)
    assert lifecycle.get(key) is TenderLifecycleStatus.WON

    # WON → ARCHIVED is valid (terminal → terminal).
    assert lifecycle.set(key, TenderLifecycleStatus.ARCHIVED) is TenderLifecycleStatus.ARCHIVED
    assert lifecycle.get(key) is TenderLifecycleStatus.ARCHIVED

    # ARCHIVED → SHORTLISTED is invalid (terminal → non-terminal).
    with pytest.raises(InvalidLifecycleTransition):
        lifecycle.set(key, TenderLifecycleStatus.SHORTLISTED)
    assert lifecycle.get(key) is TenderLifecycleStatus.ARCHIVED


def test_lifecycle_rejects_direct_discovered_to_shortlisted_jump():
    """The state machine must be walked: a direct DISCOVERED → SHORTLISTED is invalid."""
    _db, lifecycle, _tasks, _base = _tmp_db()
    key = "eis:T-1"

    lifecycle.ensure(key, TenderLifecycleStatus.DISCOVERED)
    with pytest.raises(InvalidLifecycleTransition):
        lifecycle.set(key, TenderLifecycleStatus.SHORTLISTED)
    assert lifecycle.get(key) is TenderLifecycleStatus.DISCOVERED

    # Walking the allowed path succeeds.
    lifecycle.set(key, TenderLifecycleStatus.RELEVANT)
    assert lifecycle.set(key, TenderLifecycleStatus.SHORTLISTED) is TenderLifecycleStatus.SHORTLISTED


def test_lifecycle_history_records_full_stepwise_path():
    """Every walked transition appears exactly once in the immutable history."""
    _db, lifecycle, _tasks, _base = _tmp_db()
    key = "eis:T-1"

    lifecycle.ensure(key, TenderLifecycleStatus.DISCOVERED)
    lifecycle.set(key, TenderLifecycleStatus.RELEVANT)
    lifecycle.set(key, TenderLifecycleStatus.SHORTLISTED)

    statuses = [event["new_status"] for event in lifecycle.history(key)]
    assert statuses == ["discovered", "relevant", "shortlisted"]


def test_lifecycle_repeated_set_same_state_is_noop():
    """Setting the same status twice should not produce duplicate transition events."""
    _db, lifecycle, _tasks, _base = _tmp_db()
    key = "eis:T-1"

    lifecycle.set(key, TenderLifecycleStatus.RELEVANT)
    initial_events = lifecycle.history(key)
    lifecycle.set(key, TenderLifecycleStatus.RELEVANT)
    final_events = lifecycle.history(key)

    assert len(initial_events) == len(final_events)


# ─── TenderPlan task: idempotency on retry ─────────────────────────────

def test_ensure_application_task_idempotent_on_retry(tmp_path: Path):
    """Calling ensure_application_task twice with the same args must not duplicate."""
    store = TenderTaskStore(tmp_path / "agent.db")
    deadline = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    first = ensure_application_task(
        store,
        tender_key="eis:999",
        tender_title="Tender",
        deadline=deadline,
    )
    second = ensure_application_task(
        store,
        tender_key="eis:999",
        tender_title="Tender",
        deadline=deadline,
    )

    assert first.task_id == second.task_id
    assert len(store.list_for_tender("eis:999")) == 1


def test_ensure_application_task_preserves_user_controlled_state(tmp_path: Path):
    """Existing task status/responsible should survive a re-ensure."""
    store = TenderTaskStore(tmp_path / "agent.db")
    deadline = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    task = ensure_application_task(
        store, tender_key="eis:999", tender_title="Tender", deadline=deadline
    )
    task.complete(datetime(2026, 9, 20, tzinfo=timezone.utc))
    store.save(task)

    refreshed = ensure_application_task(
        store, tender_key="eis:999", tender_title="Updated Title", deadline=deadline
    )
    assert refreshed.status.value == "done"
    assert refreshed.notes == "Tender"


# ─── register_participation: the CRM → TenderPlan service entry point ──

def test_register_participation_walks_allowed_path_and_creates_task(tmp_path: Path):
    """Fresh tender: lifecycle walks DISCOVERED → RELEVANT → SHORTLISTED; task created."""
    lifecycle = TenderLifecycleStore(tmp_path / "lifecycle.db")
    tasks = TenderTaskStore(tmp_path / "tasks.db")
    deadline = datetime.now(timezone.utc) + timedelta(days=2)

    final = register_participation(
        lifecycle,
        tasks,
        tender_key="eis:1",
        tender_title="Tender",
        user_id="100",
        deadline=deadline,
    )

    assert final is TenderLifecycleStatus.SHORTLISTED
    assert lifecycle.get("eis:1") is TenderLifecycleStatus.SHORTLISTED
    statuses = [event["new_status"] for event in lifecycle.history("eis:1")]
    assert statuses == ["discovered", "relevant", "shortlisted"]

    task = tasks.get(application_task_id("eis:1", "100"), user_id="100")
    assert task is not None
    assert task.user_id == "100"
    assert task.title == "Подать заявку"
    assert task.due_at == deadline
    assert task.priority.value == "critical"


def test_register_participation_is_idempotent(tmp_path: Path):
    """Repeated participation must not duplicate tasks or lifecycle events."""
    lifecycle = TenderLifecycleStore(tmp_path / "lifecycle.db")
    tasks = TenderTaskStore(tmp_path / "tasks.db")

    register_participation(lifecycle, tasks, tender_key="eis:1", tender_title="T", user_id="100")
    events_after_first = lifecycle.history("eis:1")
    register_participation(lifecycle, tasks, tender_key="eis:1", tender_title="T", user_id="100")

    assert lifecycle.history("eis:1") == events_after_first
    assert len(tasks.list_for_tender("eis:1", user_id="100")) == 1


def test_register_participation_never_resurrects_terminal_state(tmp_path: Path):
    """A terminal lifecycle stays untouched and no application task is created."""
    lifecycle = TenderLifecycleStore(tmp_path / "lifecycle.db")
    tasks = TenderTaskStore(tmp_path / "tasks.db")

    lifecycle.set("eis:1", TenderLifecycleStatus.RELEVANT)
    lifecycle.set("eis:1", TenderLifecycleStatus.SHORTLISTED)
    lifecycle.set("eis:1", TenderLifecycleStatus.ASSIGNED)
    lifecycle.set("eis:1", TenderLifecycleStatus.PREPARING)
    lifecycle.set("eis:1", TenderLifecycleStatus.SUBMITTED)
    lifecycle.set("eis:1", TenderLifecycleStatus.LOST)
    lifecycle.set("eis:1", TenderLifecycleStatus.ARCHIVED)

    final = register_participation(lifecycle, tasks, tender_key="eis:1", tender_title="T", user_id="100")

    assert final is TenderLifecycleStatus.ARCHIVED
    assert lifecycle.get("eis:1") is TenderLifecycleStatus.ARCHIVED
    assert tasks.list_for_tender("eis:1", user_id="100") == []


def test_register_participation_keeps_progressed_state_but_ensures_task(tmp_path: Path):
    """A tender already past SHORTLISTED keeps its state; the task is still ensured."""
    lifecycle = TenderLifecycleStore(tmp_path / "lifecycle.db")
    tasks = TenderTaskStore(tmp_path / "tasks.db")

    lifecycle.set("eis:1", TenderLifecycleStatus.RELEVANT)
    lifecycle.set("eis:1", TenderLifecycleStatus.SHORTLISTED)
    lifecycle.set("eis:1", TenderLifecycleStatus.ASSIGNED)
    lifecycle.set("eis:1", TenderLifecycleStatus.PREPARING)
    lifecycle.set("eis:1", TenderLifecycleStatus.SUBMITTED)

    final = register_participation(lifecycle, tasks, tender_key="eis:1", tender_title="T", user_id="100")

    assert final is TenderLifecycleStatus.SUBMITTED
    assert lifecycle.get("eis:1") is TenderLifecycleStatus.SUBMITTED
    assert len(tasks.list_for_tender("eis:1", user_id="100")) == 1


# ─── User isolation in Telegram callbacks ──────────────────────────────

class _Orchestrator:
    def __init__(self, db, base_path: Path):
        self.db = db
        self.lifecycle_store = TenderLifecycleStore(base_path / "lifecycle.db")
        self.task_store = TenderTaskStore(base_path / "tasks.db")


class _Bot:
    def __init__(self, db, base_path: Path):
        self.orchestrator = _Orchestrator(db, base_path)
        self.sent = []
        self.crm_board = None

    @staticmethod
    def _keyboard():
        return {"keyboard": []}

    def _send(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


def _bot_with_tender(unique_key: str = "eis:T-1", deadline: datetime | None = None):
    base = Path(tempfile.mkdtemp())
    db = TenderDatabase(base / "test.db")
    _insert_tender(db, unique_key, deadline=deadline)
    bot = _Bot(db, base)
    return bot, db, unique_key


def test_participate_callback_creates_user_scoped_task():
    """Pressing 'УЧАСТВОВАТЬ' should create a task scoped to the Telegram user."""
    bot, db, unique_key = _bot_with_tender()

    assert handle_callback(bot, "100", "crm:participate:eis:T-1") is True

    task = bot.orchestrator.task_store.get(application_task_id(unique_key, "100"), user_id="100")
    assert task is not None
    assert task.user_id == "100"
    assert task.title == "Подать заявку"


def test_participate_callback_syncs_tender_deadline_into_task():
    """The tender deadline (source of truth) is synced into the task and sets priority."""
    deadline = datetime.now(timezone.utc) + timedelta(days=2)
    bot, db, unique_key = _bot_with_tender(deadline=deadline)

    assert handle_callback(bot, "100", "crm:participate:eis:T-1") is True

    task = bot.orchestrator.task_store.get(application_task_id(unique_key, "100"), user_id="100")
    assert task is not None
    assert task.due_at == deadline
    assert task.priority.value == "critical"


def test_participate_callback_idempotent_for_same_user():
    """Repeated participate clicks by the same user must not duplicate the task."""
    bot, db, unique_key = _bot_with_tender()

    handle_callback(bot, "100", "crm:participate:eis:T-1")
    handle_callback(bot, "100", "crm:participate:eis:T-1")

    tasks = bot.orchestrator.task_store.list_for_tender(unique_key, user_id="100")
    assert len(tasks) == 1


def test_different_users_get_isolated_tasks():
    """Two users participating in the same tender must get independent tasks."""
    bot, db, unique_key = _bot_with_tender()

    handle_callback(bot, "100", "crm:participate:eis:T-1")
    handle_callback(bot, "200", "crm:participate:eis:T-1")

    task_100 = bot.orchestrator.task_store.get(application_task_id(unique_key, "100"), user_id="100")
    task_200 = bot.orchestrator.task_store.get(application_task_id(unique_key, "200"), user_id="200")

    assert task_100 is not None
    assert task_200 is not None
    assert task_100.task_id != task_200.task_id
    assert task_100.user_id == "100"
    assert task_200.user_id == "200"

    # User 100 should not see user 200's task.
    tasks_for_100 = bot.orchestrator.task_store.list_for_tender(unique_key, user_id="100")
    assert len(tasks_for_100) == 1
    assert tasks_for_100[0].user_id == "100"


def test_participate_of_user_a_does_not_create_task_for_user_b():
    """User A's participation must not leak a task into user B's board."""
    bot, db, unique_key = _bot_with_tender()

    handle_callback(bot, "100", "crm:participate:eis:T-1")

    assert bot.orchestrator.task_store.list_for_tender(unique_key, user_id="200") == []


def test_participate_callback_advances_lifecycle_to_shortlisted():
    """The lifecycle should move to SHORTLISTED when the user participates."""
    bot, db, unique_key = _bot_with_tender()

    handle_callback(bot, "100", "crm:participate:eis:T-1")

    state = bot.orchestrator.lifecycle_store.get(unique_key)
    assert state is TenderLifecycleStatus.SHORTLISTED


def test_status_callback_to_participating_drives_tenderplan():
    """The keyboard status change to 'participating' drives the same TenderPlan action."""
    bot, db, unique_key = _bot_with_tender()

    assert handle_callback(bot, "100", "crm:status:1:participating") is True

    assert bot.orchestrator.lifecycle_store.get(unique_key) is TenderLifecycleStatus.SHORTLISTED
    assert bot.orchestrator.task_store.get(application_task_id(unique_key, "100"), user_id="100") is not None


def test_participate_callback_does_not_resurrect_terminal_lifecycle():
    """An EXPIRED tender keeps its lifecycle; no application task is resurrected."""
    bot, db, unique_key = _bot_with_tender()
    bot.orchestrator.lifecycle_store.set(unique_key, TenderLifecycleStatus.RELEVANT)
    bot.orchestrator.lifecycle_store.set(unique_key, TenderLifecycleStatus.EXPIRED)

    assert handle_callback(bot, "100", "crm:participate:eis:T-1") is True

    assert bot.orchestrator.lifecycle_store.get(unique_key) is TenderLifecycleStatus.EXPIRED
    assert bot.orchestrator.task_store.list_for_tender(unique_key, user_id="100") == []


def test_participate_callback_persists_across_restart():
    """Freshly constructed stores over the same DB files see the callback's results."""
    bot, db, unique_key = _bot_with_tender()
    base = db.db_path.parent

    assert handle_callback(bot, "100", "crm:participate:eis:T-1") is True

    # Simulate a process restart: brand-new store instances over the same paths.
    lifecycle = TenderLifecycleStore(base / "lifecycle.db")
    tasks = TenderTaskStore(base / "tasks.db")

    assert lifecycle.get(unique_key) is TenderLifecycleStatus.SHORTLISTED
    task = tasks.get(application_task_id(unique_key, "100"), user_id="100")
    assert task is not None
    assert task.user_id == "100"
    statuses = [event["new_status"] for event in lifecycle.history(unique_key)]
    assert statuses == ["discovered", "relevant", "shortlisted"]


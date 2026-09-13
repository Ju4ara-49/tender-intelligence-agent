from unittest.mock import MagicMock, patch

from src.orchestrator import Orchestrator


def test_run_cycle_for_user_does_not_execute_when_all_profiles_are_disabled():
    orchestrator = object.__new__(Orchestrator)
    orchestrator.profile_store = MagicMock()
    orchestrator.criteria_store = MagicMock()
    orchestrator._stop_requested = False
    orchestrator.profile_store.list.side_effect = [
        [],
        [MagicMock(enabled=False)],
    ]

    with patch.object(orchestrator, "run_cycle") as run_cycle:
        assert orchestrator.run_cycle_for_user("42") == []
        run_cycle.assert_not_called()


def test_run_cycle_for_user_creates_default_only_for_brand_new_user():
    orchestrator = object.__new__(Orchestrator)
    orchestrator.profile_store = MagicMock()
    orchestrator.criteria_store = MagicMock()
    orchestrator._stop_requested = False
    default_profile = MagicMock(id=7, keywords=[], platforms=[], exclusions=[], regions=[])
    default_profile.criteria.return_value = MagicMock()
    orchestrator.profile_store.list.side_effect = [[], []]
    orchestrator.profile_store.ensure_default_profile.return_value = default_profile

    with patch.object(orchestrator, "run_cycle", return_value={"search_number": 1}) as run_cycle:
        result = orchestrator.run_cycle_for_user("42")

    assert result == [{"search_number": 1}]
    orchestrator.profile_store.ensure_default_profile.assert_called_once_with("42", orchestrator.criteria_store)
    run_cycle.assert_called_once()

"""Property-based tests for ADK import error wrapping.

Tests validate that:
- Property 4: ADK import errors are always wrapped in ADKNotAvailableError (Requirements 6.2, 6.5)
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from types import ModuleType

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.pipeline.adk_workflow import ADKWorkflowRunner, ADKNotAvailableError


# ─── Strategies ──────────────────────────────────────────────────────────────

# Failure scenarios for ADK import
_FAILURE_SCENARIOS = [
    "import_google_adk_raises_import_error",
    "import_google_adk_raises_module_not_found",
    "import_google_adk_sessions_raises_import_error",
    "import_google_adk_sessions_raises_module_not_found",
    "missing_workflow_attr",
    "missing_workflow_submodule",
    "missing_workflow_start_attr",
    "missing_runner_attr",
    "missing_inmemory_session_service_attr",
]

_failure_scenario = st.sampled_from(_FAILURE_SCENARIOS)

# Error messages for import failures
_error_messages = st.text(min_size=1, max_size=100, alphabet=st.characters(
    whitelist_categories=("L", "N", "P", "Z")
))


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_fake_adk_module(
    has_workflow: bool = True,
    has_workflow_submodule: bool = True,
    has_workflow_start: bool = True,
    has_runner: bool = True,
) -> MagicMock:
    """Create a fake google.adk module with configurable symbol availability."""
    adk = MagicMock(spec=[])

    if has_workflow:
        adk.Workflow = MagicMock(name="Workflow")
    
    if has_workflow_submodule:
        workflow_sub = MagicMock(name="workflow_submodule")
        if has_workflow_start:
            workflow_sub.START = MagicMock(name="START")
        else:
            # Remove START attribute
            del workflow_sub.START
            workflow_sub.configure_mock(**{"__getattr__": lambda self, name: None if name == "START" else MagicMock()})
            type(workflow_sub).START = property(lambda self: (_ for _ in ()).throw(AttributeError("no START")))
        adk.workflow = workflow_sub
    
    if has_runner:
        adk.Runner = MagicMock(name="Runner")

    return adk


def _make_fake_sessions_module(has_inmemory: bool = True) -> MagicMock:
    """Create a fake google.adk.sessions module."""
    sessions = MagicMock(spec=[])
    if has_inmemory:
        sessions.InMemorySessionService = MagicMock(name="InMemorySessionService")
    return sessions


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestADKImportErrorWrapping:
    """**Validates: Requirements 6.2, 6.5**

    For any simulated failure of importlib.import_module("google.adk") or
    importlib.import_module("google.adk.sessions") or getattr returning None
    for required symbols (Workflow, workflow.START, Runner, InMemorySessionService),
    calling _import_adk() SHALL raise ADKNotAvailableError and SHALL NOT allow
    ImportError or AttributeError to propagate.
    """

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(scenario=_failure_scenario, error_msg=_error_messages)
    def test_adk_import_failures_always_raise_adk_not_available_error(
        self, scenario: str, error_msg: str
    ):
        """Any ADK import failure is wrapped in ADKNotAvailableError, never raw ImportError/AttributeError."""
        runner = ADKWorkflowRunner(check_ollama=False)

        if scenario == "import_google_adk_raises_import_error":
            # google.adk import raises ImportError
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError(error_msg)
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert len(str(exc_info.value)) > 0

        elif scenario == "import_google_adk_raises_module_not_found":
            # google.adk import raises ModuleNotFoundError
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ModuleNotFoundError(error_msg)
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert len(str(exc_info.value)) > 0

        elif scenario == "import_google_adk_sessions_raises_import_error":
            # google.adk imports fine, but google.adk.sessions raises ImportError
            fake_adk = _make_fake_adk_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        raise ImportError(error_msg)
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert len(str(exc_info.value)) > 0

        elif scenario == "import_google_adk_sessions_raises_module_not_found":
            # google.adk imports fine, but google.adk.sessions raises ModuleNotFoundError
            fake_adk = _make_fake_adk_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        raise ModuleNotFoundError(error_msg)
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert len(str(exc_info.value)) > 0

        elif scenario == "missing_workflow_attr":
            # google.adk module does not have Workflow attribute
            fake_adk = _make_fake_adk_module(has_workflow=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert "Workflow" in str(exc_info.value)

        elif scenario == "missing_workflow_submodule":
            # google.adk module does not have workflow submodule
            fake_adk = _make_fake_adk_module(has_workflow_submodule=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert "workflow" in str(exc_info.value).lower()

        elif scenario == "missing_workflow_start_attr":
            # google.adk.workflow exists but has no START
            fake_adk = MagicMock(spec=[])
            fake_adk.Workflow = MagicMock(name="Workflow")
            fake_adk.Runner = MagicMock(name="Runner")
            # workflow submodule without START
            workflow_sub = MagicMock(spec=[])
            fake_adk.workflow = workflow_sub
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert "START" in str(exc_info.value)

        elif scenario == "missing_runner_attr":
            # google.adk module does not have Runner attribute
            fake_adk = _make_fake_adk_module(has_runner=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert "Runner" in str(exc_info.value)

        elif scenario == "missing_inmemory_session_service_attr":
            # google.adk.sessions exists but lacks InMemorySessionService
            fake_adk = _make_fake_adk_module()
            fake_sessions = _make_fake_sessions_module(has_inmemory=False)
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                assert "InMemorySessionService" in str(exc_info.value)

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(scenario=_failure_scenario, error_msg=_error_messages)
    def test_raw_import_error_never_propagates(self, scenario: str, error_msg: str):
        """ImportError and AttributeError never escape _import_adk() — only ADKNotAvailableError."""
        runner = ADKWorkflowRunner(check_ollama=False)

        if scenario == "import_google_adk_raises_import_error":
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError(error_msg)
                try:
                    runner._import_adk()
                    # If it doesn't raise, that's also acceptable (shouldn't happen but safe)
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass  # Expected
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "import_google_adk_raises_module_not_found":
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ModuleNotFoundError(error_msg)
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "import_google_adk_sessions_raises_import_error":
            fake_adk = _make_fake_adk_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        raise ImportError(error_msg)
                    return MagicMock()
                mock_import.side_effect = side_effect
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "import_google_adk_sessions_raises_module_not_found":
            fake_adk = _make_fake_adk_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        raise ModuleNotFoundError(error_msg)
                    return MagicMock()
                mock_import.side_effect = side_effect
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "missing_workflow_attr":
            fake_adk = _make_fake_adk_module(has_workflow=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "missing_workflow_submodule":
            fake_adk = _make_fake_adk_module(has_workflow_submodule=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "missing_workflow_start_attr":
            fake_adk = MagicMock(spec=[])
            fake_adk.Workflow = MagicMock(name="Workflow")
            fake_adk.Runner = MagicMock(name="Runner")
            workflow_sub = MagicMock(spec=[])
            fake_adk.workflow = workflow_sub
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "missing_runner_attr":
            fake_adk = _make_fake_adk_module(has_runner=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

        elif scenario == "missing_inmemory_session_service_attr":
            fake_adk = _make_fake_adk_module()
            fake_sessions = _make_fake_sessions_module(has_inmemory=False)
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                try:
                    runner._import_adk()
                    assert False, "_import_adk should have raised"
                except ADKNotAvailableError:
                    pass
                except (ImportError, AttributeError) as e:
                    pytest.fail(
                        f"Raw {type(e).__name__} propagated from _import_adk(): {e}"
                    )

    @pytest.mark.property
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(scenario=_failure_scenario, error_msg=_error_messages)
    def test_error_message_is_descriptive(self, scenario: str, error_msg: str):
        """ADKNotAvailableError messages are always descriptive (non-empty, contain context)."""
        runner = ADKWorkflowRunner(check_ollama=False)

        if scenario == "import_google_adk_raises_import_error":
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ImportError(error_msg)
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                # Message should mention ADK or install hint
                assert "ADK" in msg or "pip install" in msg or "adk" in msg.lower()

        elif scenario == "import_google_adk_raises_module_not_found":
            with patch("importlib.import_module") as mock_import:
                mock_import.side_effect = ModuleNotFoundError(error_msg)
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                assert "ADK" in msg or "pip install" in msg or "adk" in msg.lower()

        elif scenario in (
            "import_google_adk_sessions_raises_import_error",
            "import_google_adk_sessions_raises_module_not_found",
        ):
            fake_adk = _make_fake_adk_module()
            with patch("importlib.import_module") as mock_import:
                exc_type = ImportError if "import_error" in scenario else ModuleNotFoundError
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        raise exc_type(error_msg)
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                # Should mention the missing symbol or incompatibility
                assert len(msg) > 10

        elif scenario == "missing_workflow_attr":
            fake_adk = _make_fake_adk_module(has_workflow=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                assert "Workflow" in msg

        elif scenario == "missing_workflow_submodule":
            fake_adk = _make_fake_adk_module(has_workflow_submodule=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                assert "workflow" in msg.lower()

        elif scenario == "missing_workflow_start_attr":
            fake_adk = MagicMock(spec=[])
            fake_adk.Workflow = MagicMock(name="Workflow")
            fake_adk.Runner = MagicMock(name="Runner")
            workflow_sub = MagicMock(spec=[])
            fake_adk.workflow = workflow_sub
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                assert "START" in msg

        elif scenario == "missing_runner_attr":
            fake_adk = _make_fake_adk_module(has_runner=False)
            fake_sessions = _make_fake_sessions_module()
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                assert "Runner" in msg

        elif scenario == "missing_inmemory_session_service_attr":
            fake_adk = _make_fake_adk_module()
            fake_sessions = _make_fake_sessions_module(has_inmemory=False)
            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "google.adk":
                        return fake_adk
                    elif name == "google.adk.sessions":
                        return fake_sessions
                    return MagicMock()
                mock_import.side_effect = side_effect
                with pytest.raises(ADKNotAvailableError) as exc_info:
                    runner._import_adk()
                msg = str(exc_info.value)
                assert "InMemorySessionService" in msg

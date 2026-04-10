"""Tests for CrewAI integration — audit-only authorize + notarize."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aira.extras.crewai import AiraCrewHook


def _auth(status: str = "authorized", action_id: str = "act-1"):
    a = MagicMock()
    a.status = status
    a.action_id = action_id
    return a


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.authorize.return_value = _auth("authorized")
    return client


class TestAiraCrewHook:
    def test_task_callback_authorizes_and_notarizes(self, mock_client):
        hook = AiraCrewHook(mock_client, agent_id="agent-1")
        output = MagicMock()
        output.description = "Summarize the report"
        hook.task_callback(output)

        mock_client.authorize.assert_called_once()
        ak = mock_client.authorize.call_args[1]
        assert ak["action_type"] == "task_completed"
        assert "Summarize the report" in ak["details"]
        assert ak["agent_id"] == "agent-1"

        mock_client.notarize.assert_called_once()
        nk = mock_client.notarize.call_args[1]
        assert nk["action_id"] == "act-1"
        assert nk["outcome"] == "completed"

    def test_step_callback_authorizes_and_notarizes(self, mock_client):
        hook = AiraCrewHook(mock_client, agent_id="agent-1")
        hook.step_callback("some step output")

        mock_client.authorize.assert_called_once()
        ak = mock_client.authorize.call_args[1]
        assert ak["action_type"] == "agent_step"
        assert "Output length:" in ak["details"]

        mock_client.notarize.assert_called_once()

    def test_model_id_forwarded_when_set(self, mock_client):
        hook = AiraCrewHook(mock_client, agent_id="a1", model_id="gpt-4")
        hook.step_callback("x")
        assert mock_client.authorize.call_args[1]["model_id"] == "gpt-4"

    def test_model_id_omitted_when_none(self, mock_client):
        hook = AiraCrewHook(mock_client, agent_id="a1")
        hook.step_callback("x")
        assert mock_client.authorize.call_args[1].get("model_id") is None

    def test_non_blocking_on_authorize_failure(self, mock_client):
        mock_client.authorize.side_effect = RuntimeError("API down")
        hook = AiraCrewHook(mock_client, agent_id="a1")
        # Should not raise
        hook.task_callback(MagicMock(description="test"))
        mock_client.notarize.assert_not_called()

    def test_non_blocking_on_notarize_failure(self, mock_client):
        mock_client.notarize.side_effect = RuntimeError("API down")
        hook = AiraCrewHook(mock_client, agent_id="a1")
        # Should not raise
        hook.task_callback(MagicMock(description="test"))

    def test_details_truncated_to_5000(self, mock_client):
        hook = AiraCrewHook(mock_client, agent_id="a1")
        output = MagicMock()
        output.description = "x" * 10000
        hook.task_callback(output)
        details = mock_client.authorize.call_args[1]["details"]
        assert len(details) <= 5000

    def test_for_crew_returns_callbacks_dict(self, mock_client):
        result = AiraCrewHook.for_crew(mock_client, agent_id="a1")
        assert "task_callback" in result
        assert "step_callback" in result
        assert callable(result["task_callback"])
        assert callable(result["step_callback"])

    def test_pending_approval_skips_notarize(self, mock_client):
        mock_client.authorize.return_value = _auth("pending_approval")
        hook = AiraCrewHook(mock_client, agent_id="a1")
        hook.step_callback("x")
        mock_client.authorize.assert_called_once()
        mock_client.notarize.assert_not_called()

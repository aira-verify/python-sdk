"""Tests for Google ADK integration — real pre-execution gate."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aira.extras.google_adk import AiraPlugin, AiraToolDenied


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


class TestAiraPlugin:
    def test_before_tool_call_authorizes(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="a1")
        p.before_tool_call("search", {"query": "hello"})
        mock_client.authorize.assert_called_once()
        ak = mock_client.authorize.call_args[1]
        assert ak["action_type"] == "tool_invoked"
        assert "'search'" in ak["details"]
        assert "query" in ak["details"]

    def test_after_tool_call_notarizes_completed(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="a1")
        p.before_tool_call("search", {"query": "x"})
        p.after_tool_call("search", result="5 results")
        mock_client.notarize.assert_called_once()
        nk = mock_client.notarize.call_args[1]
        assert nk["action_id"] == "act-1"
        assert nk["outcome"] == "completed"

    def test_on_tool_error_notarizes_failed(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="a1")
        p.before_tool_call("search", {"q": "x"})
        p.on_tool_error("search", ValueError("nope"))
        mock_client.notarize.assert_called_once()
        nk = mock_client.notarize.call_args[1]
        assert nk["outcome"] == "failed"
        assert "nope" in nk["outcome_details"]

    def test_policy_denied_raises_tool_denied(self, mock_client):
        err = Exception("denied")
        err.code = "POLICY_DENIED"
        err.message = "Blocked"
        mock_client.authorize.side_effect = err

        p = AiraPlugin(mock_client, agent_id="a1")
        with pytest.raises(AiraToolDenied) as ei:
            p.before_tool_call("search", {"query": "x"})
        assert ei.value.code == "POLICY_DENIED"

    def test_pending_approval_raises(self, mock_client):
        mock_client.authorize.return_value = _auth("pending_approval")
        p = AiraPlugin(mock_client, agent_id="a1")
        with pytest.raises(AiraToolDenied) as ei:
            p.before_tool_call("search", {})
        assert ei.value.code == "PENDING_APPROVAL"

    def test_agent_id_forwarded(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="my-agent")
        p.before_tool_call("t")
        assert mock_client.authorize.call_args[1]["agent_id"] == "my-agent"

    def test_model_id_forwarded_when_set(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="a1", model_id="gemini-pro")
        p.before_tool_call("t")
        assert mock_client.authorize.call_args[1]["model_id"] == "gemini-pro"

    def test_model_id_omitted_when_none(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="a1")
        p.before_tool_call("t")
        assert mock_client.authorize.call_args[1].get("model_id") is None

    def test_after_tool_call_non_blocking_on_notarize_failure(self, mock_client):
        mock_client.notarize.side_effect = RuntimeError("API down")
        p = AiraPlugin(mock_client, agent_id="a1")
        p.before_tool_call("t")
        # Should not raise
        p.after_tool_call("t", result="x")

    def test_before_tool_call_no_args(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="a1")
        p.before_tool_call("my_tool")
        details = mock_client.authorize.call_args[1]["details"]
        assert "Arg keys: []" in details

    def test_inflight_cleaned_up_after_after(self, mock_client):
        p = AiraPlugin(mock_client, agent_id="a1")
        p.before_tool_call("t")
        assert "t" in p._inflight
        p.after_tool_call("t", result="x")
        assert "t" not in p._inflight

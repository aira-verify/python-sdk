"""Tests for OpenAI Agents guardrail — real pre-execution gate."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aira.extras.openai_agents import AiraGuardrail, AiraToolDenied


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


class TestAiraGuardrail:
    def test_wrap_tool_authorizes_then_runs_then_notarizes(self, mock_client):
        g = AiraGuardrail(mock_client, agent_id="a1")

        def my_tool(x: int) -> str:
            return f"result-{x}"

        wrapped = g.wrap_tool(my_tool)
        result = wrapped(x=42)
        assert result == "result-42"

        # Authorize called once before the tool ran
        mock_client.authorize.assert_called_once()
        ak = mock_client.authorize.call_args[1]
        assert ak["action_type"] == "tool_call"
        assert "my_tool" in ak["details"]

        # Notarize called with completed outcome
        mock_client.notarize.assert_called_once()
        nk = mock_client.notarize.call_args[1]
        assert nk["action_id"] == "act-1"
        assert nk["outcome"] == "completed"
        assert "my_tool" in nk["outcome_details"]

    def test_policy_denied_aborts_call(self, mock_client):
        err = Exception("denied")
        err.code = "POLICY_DENIED"
        err.message = "Blocked"
        mock_client.authorize.side_effect = err

        tool_ran = []

        def my_tool():
            tool_ran.append(True)
            return "nope"

        g = AiraGuardrail(mock_client, agent_id="a1")
        wrapped = g.wrap_tool(my_tool)

        with pytest.raises(AiraToolDenied) as ei:
            wrapped()
        assert ei.value.code == "POLICY_DENIED"
        assert tool_ran == []  # tool never ran
        mock_client.notarize.assert_not_called()

    def test_pending_approval_aborts_call(self, mock_client):
        mock_client.authorize.return_value = _auth("pending_approval")
        tool_ran = []

        def my_tool():
            tool_ran.append(True)

        g = AiraGuardrail(mock_client, agent_id="a1")
        wrapped = g.wrap_tool(my_tool)
        with pytest.raises(AiraToolDenied) as ei:
            wrapped()
        assert ei.value.code == "PENDING_APPROVAL"
        assert tool_ran == []

    def test_tool_exception_notarized_as_failed(self, mock_client):
        def my_tool():
            raise ValueError("tool blew up")

        g = AiraGuardrail(mock_client, agent_id="a1")
        wrapped = g.wrap_tool(my_tool)
        with pytest.raises(ValueError):
            wrapped()
        mock_client.notarize.assert_called_once()
        nk = mock_client.notarize.call_args[1]
        assert nk["outcome"] == "failed"
        assert "tool blew up" in nk["outcome_details"]

    def test_agent_id_forwarded(self, mock_client):
        g = AiraGuardrail(mock_client, agent_id="my-agent")

        def t():
            return "ok"

        g.wrap_tool(t)()
        assert mock_client.authorize.call_args[1]["agent_id"] == "my-agent"

    def test_model_id_forwarded_when_set(self, mock_client):
        g = AiraGuardrail(mock_client, agent_id="a1", model_id="gpt-4o")

        def t():
            return "ok"

        g.wrap_tool(t)()
        assert mock_client.authorize.call_args[1]["model_id"] == "gpt-4o"

    def test_notarize_failure_non_blocking(self, mock_client):
        mock_client.notarize.side_effect = RuntimeError("API down")

        def t():
            return "ok"

        g = AiraGuardrail(mock_client, agent_id="a1")
        # Should not raise — notarize failure must not break the tool call
        assert g.wrap_tool(t)() == "ok"

    def test_custom_tool_name_used(self, mock_client):
        def my_tool():
            return "ok"

        g = AiraGuardrail(mock_client, agent_id="a1")
        wrapped = g.wrap_tool(my_tool, tool_name="custom_name")
        wrapped()
        assert "custom_name" in mock_client.authorize.call_args[1]["details"]

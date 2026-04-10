"""Tests for AWS Bedrock integration — real pre-execution gate."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aira.extras.bedrock import AiraBedrockHandler, AiraInvocationDenied


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


class TestAiraBedrockHandler:
    def test_wrap_invoke_model_authorizes_then_delegates_then_notarizes(self, mock_client):
        bedrock = MagicMock()
        bedrock.invoke_model = MagicMock(return_value={"body": "resp"})
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_model(bedrock)
        result = wrapped(modelId="anthropic.claude-v2")

        assert result == {"body": "resp"}

        # Authorize called before original invocation
        mock_client.authorize.assert_called_once()
        ak = mock_client.authorize.call_args[1]
        assert ak["action_type"] == "model_invoked"
        assert "anthropic.claude-v2" in ak["details"]

        bedrock.invoke_model.assert_called_once_with(modelId="anthropic.claude-v2")

        # Notarize called with completed
        mock_client.notarize.assert_called_once()
        nk = mock_client.notarize.call_args[1]
        assert nk["outcome"] == "completed"

    def test_wrap_invoke_agent_authorizes_then_notarizes(self, mock_client):
        bedrock_agent = MagicMock()
        bedrock_agent.invoke_agent = MagicMock(return_value={"completion": "ok"})
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_agent(bedrock_agent)
        result = wrapped(agentId="AGENT123")

        assert result == {"completion": "ok"}
        ak = mock_client.authorize.call_args[1]
        assert ak["action_type"] == "agent_invoked"
        assert "AGENT123" in ak["details"]
        mock_client.notarize.assert_called_once()

    def test_policy_denied_aborts_invoke(self, mock_client):
        err = Exception("denied")
        err.code = "POLICY_DENIED"
        err.message = "Blocked"
        mock_client.authorize.side_effect = err

        bedrock = MagicMock()
        bedrock.invoke_model = MagicMock()
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_model(bedrock)
        with pytest.raises(AiraInvocationDenied) as ei:
            wrapped(modelId="m1")
        assert ei.value.code == "POLICY_DENIED"
        bedrock.invoke_model.assert_not_called()
        mock_client.notarize.assert_not_called()

    def test_pending_approval_aborts_invoke(self, mock_client):
        mock_client.authorize.return_value = _auth("pending_approval")
        bedrock = MagicMock()
        bedrock.invoke_model = MagicMock()
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_model(bedrock)
        with pytest.raises(AiraInvocationDenied) as ei:
            wrapped(modelId="m1")
        assert ei.value.code == "PENDING_APPROVAL"
        bedrock.invoke_model.assert_not_called()

    def test_bedrock_exception_notarized_as_failed(self, mock_client):
        bedrock = MagicMock()
        bedrock.invoke_model = MagicMock(side_effect=RuntimeError("bedrock down"))
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_model(bedrock)
        with pytest.raises(RuntimeError):
            wrapped(modelId="m1")
        mock_client.notarize.assert_called_once()
        nk = mock_client.notarize.call_args[1]
        assert nk["outcome"] == "failed"
        assert "bedrock down" in nk["outcome_details"]

    def test_agent_id_forwarded(self, mock_client):
        bedrock = MagicMock()
        bedrock.invoke_model = MagicMock(return_value={})
        handler = AiraBedrockHandler(mock_client, agent_id="my-agent")
        wrapped = handler.wrap_invoke_model(bedrock)
        wrapped(modelId="m1")
        assert mock_client.authorize.call_args[1]["agent_id"] == "my-agent"

    def test_notarize_failure_non_blocking(self, mock_client):
        mock_client.notarize.side_effect = RuntimeError("fail")
        bedrock = MagicMock()
        bedrock.invoke_model = MagicMock(return_value={"ok": True})
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_model(bedrock)
        # Original call succeeds; notarize failure should not propagate.
        result = wrapped(modelId="m1")
        assert result == {"ok": True}

    def test_wrap_invoke_model_unknown_model_id(self, mock_client):
        bedrock = MagicMock()
        bedrock.invoke_model = MagicMock(return_value={})
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_model(bedrock)
        wrapped()  # No modelId kwarg
        assert "unknown" in mock_client.authorize.call_args[1]["details"]

    def test_wrap_invoke_agent_unknown_agent_id(self, mock_client):
        bedrock_agent = MagicMock()
        bedrock_agent.invoke_agent = MagicMock(return_value={})
        handler = AiraBedrockHandler(mock_client, agent_id="a1")
        wrapped = handler.wrap_invoke_agent(bedrock_agent)
        wrapped()
        assert "unknown" in mock_client.authorize.call_args[1]["details"]

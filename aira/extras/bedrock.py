"""AWS Bedrock integration — real pre-execution gate on model invocations.

By wrapping ``bedrock.invoke_model`` and ``bedrock_agent.invoke_agent``, we
get to run :meth:`aira.Aira.authorize` before delegating to the real Bedrock
call. If the policy engine denies the invocation the wrapped function raises
:class:`AiraInvocationDenied` and Bedrock is never called. Successful calls
are notarized with ``outcome="completed"`` and failures with ``outcome="failed"``.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from aira import Aira

logger = logging.getLogger(__name__)


class AiraInvocationDenied(Exception):
    """Raised when Aira denies a Bedrock invocation."""

    def __init__(self, target: str, code: str, message: str) -> None:
        self.target = target
        self.code = code
        self.message = message
        super().__init__(f"Aira denied Bedrock call '{target}': [{code}] {message}")


class AiraBedrockHandler:
    """Pre-execution gate + post-execution notarization for Bedrock calls."""

    def __init__(self, client: "Aira", agent_id: str):
        self.client = client
        self.agent_id = agent_id

    def _authorize(self, action_type: str, target: str, details: str) -> str:
        try:
            auth = self.client.authorize(
                action_type=action_type,
                details=details[:5000],
                agent_id=self.agent_id,
            )
        except Exception as e:
            code = getattr(e, "code", "AUTHORIZE_FAILED")
            msg = getattr(e, "message", str(e))
            raise AiraInvocationDenied(target, code, msg) from e

        if auth.status == "pending_approval":
            raise AiraInvocationDenied(
                target,
                "PENDING_APPROVAL",
                f"Bedrock call held for approval (action {auth.action_id})",
            )
        return auth.action_id

    def _notarize(self, action_id: str, outcome: str, details: str) -> None:
        try:
            self.client.notarize(
                action_id=action_id,
                outcome=outcome,
                outcome_details=details[:5000],
            )
        except Exception as e:
            logger.warning("Aira notarize failed (non-blocking): %s", e)

    def wrap_invoke_model(self, bedrock_client: Any) -> Callable:
        """Return a wrapped ``invoke_model`` that authorizes then notarizes."""
        original = bedrock_client.invoke_model

        @functools.wraps(original)
        def wrapped(**kwargs: Any) -> Any:
            model_id = kwargs.get("modelId", "unknown")
            action_id = self._authorize(
                "model_invoked",
                model_id,
                f"Bedrock invoke_model: {model_id}",
            )
            try:
                response = original(**kwargs)
            except Exception as e:
                self._notarize(
                    action_id,
                    "failed",
                    f"Bedrock invoke_model '{model_id}' errored: {type(e).__name__}: {str(e)[:200]}",
                )
                raise
            self._notarize(
                action_id,
                "completed",
                f"Bedrock invoke_model: {model_id}",
            )
            return response

        return wrapped

    def wrap_invoke_agent(self, bedrock_agent_client: Any) -> Callable:
        """Return a wrapped ``invoke_agent`` that authorizes then notarizes."""
        original = bedrock_agent_client.invoke_agent

        @functools.wraps(original)
        def wrapped(**kwargs: Any) -> Any:
            agent_id = kwargs.get("agentId", "unknown")
            action_id = self._authorize(
                "agent_invoked",
                agent_id,
                f"Bedrock invoke_agent: {agent_id}",
            )
            try:
                response = original(**kwargs)
            except Exception as e:
                self._notarize(
                    action_id,
                    "failed",
                    f"Bedrock invoke_agent '{agent_id}' errored: {type(e).__name__}: {str(e)[:200]}",
                )
                raise
            self._notarize(
                action_id,
                "completed",
                f"Bedrock invoke_agent: {agent_id}",
            )
            return response

        return wrapped

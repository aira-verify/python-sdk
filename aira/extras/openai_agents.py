"""OpenAI Agents SDK integration — real pre-execution gate on tool calls.

OpenAI Agents supports guardrail functions and tool wrappers that run BEFORE
the tool is invoked, which gives us a clean seam to call
:meth:`aira.Aira.authorize` and abort the tool call if the policy engine
denies or holds it.

This IS a real gate: denied tool calls never run, and failed calls report a
``"failed"`` outcome so the action transitions correctly in Aira.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from aira import Aira

logger = logging.getLogger(__name__)


class AiraToolDenied(Exception):
    """Raised when Aira denies a wrapped tool call."""

    def __init__(self, tool: str, code: str, message: str) -> None:
        self.tool = tool
        self.code = code
        self.message = message
        super().__init__(f"Aira denied tool '{tool}': [{code}] {message}")


class AiraGuardrail:
    """Pre-execution gate + post-execution notarization for tool calls.

    Wrap any tool function with :meth:`wrap_tool` to get an authorize gate
    plus a completion/failure receipt on every call.
    """

    def __init__(self, client: "Aira", agent_id: str, model_id: str | None = None):
        self.client = client
        self.agent_id = agent_id
        self.model_id = model_id

    def _authorize(self, tool_name: str, details: str) -> str:
        """Authorize a tool call. Returns action_id or raises AiraToolDenied."""
        try:
            auth = self.client.authorize(
                action_type="tool_call",
                details=details[:5000],
                agent_id=self.agent_id,
                model_id=self.model_id,
            )
        except Exception as e:
            code = getattr(e, "code", "AUTHORIZE_FAILED")
            msg = getattr(e, "message", str(e))
            raise AiraToolDenied(tool_name, code, msg) from e

        if auth.status == "pending_approval":
            raise AiraToolDenied(
                tool_name,
                "PENDING_APPROVAL",
                f"Tool call held for approval (action {auth.action_id})",
            )
        return auth.action_id

    def _notarize(
        self,
        action_id: str,
        outcome: str,
        outcome_details: str,
    ) -> None:
        try:
            self.client.notarize(
                action_id=action_id,
                outcome=outcome,
                outcome_details=outcome_details[:5000],
            )
        except Exception as e:
            logger.warning("Aira notarize failed (non-blocking): %s", e)

    def wrap_tool(self, tool_fn: Callable, tool_name: str | None = None) -> Callable:
        """Wrap a tool function so every call is authorized, then notarized."""
        name = tool_name or getattr(tool_fn, "__name__", "unknown")

        @functools.wraps(tool_fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            arg_keys = sorted(kwargs.keys())
            details = f"Tool '{name}' called. Arg keys: {arg_keys}"
            action_id = self._authorize(name, details)
            try:
                result = tool_fn(*args, **kwargs)
            except Exception as e:
                self._notarize(
                    action_id,
                    "failed",
                    f"Tool '{name}' errored: {type(e).__name__}: {str(e)[:200]}",
                )
                raise
            self._notarize(
                action_id,
                "completed",
                f"Tool '{name}' completed. Result length: {len(str(result))} chars",
            )
            return result

        return wrapper

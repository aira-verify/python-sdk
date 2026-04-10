"""Google ADK integration — real pre-execution gate via before/after tool hooks.

Google ADK's plugin system provides ``before_tool_call`` and ``after_tool_call``
hooks. ``before_tool_call`` is invoked before the tool runs and can raise to
abort the call, so this IS a real gate.

Usage::

    plugin = AiraPlugin(client=aira, agent_id="adk-agent", model_id="gemini-2.0-flash")
    plugin.before_tool_call("search_documents", args={"query": "..."})
    try:
        result = search_documents(query="...")
    except Exception as e:
        plugin.on_tool_error("search_documents", e)
        raise
    plugin.after_tool_call("search_documents", result=result)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aira import Aira

logger = logging.getLogger(__name__)


class AiraToolDenied(Exception):
    """Raised from ``before_tool_call`` when Aira denies a tool call."""

    def __init__(self, tool: str, code: str, message: str) -> None:
        self.tool = tool
        self.code = code
        self.message = message
        super().__init__(f"Aira denied tool '{tool}': [{code}] {message}")


class AiraPlugin:
    """Google ADK plugin that gates tool calls through Aira."""

    def __init__(self, client: "Aira", agent_id: str, model_id: str | None = None):
        self.client = client
        self.agent_id = agent_id
        self.model_id = model_id
        # Map tool_name → most recent action_id so after_tool_call can notarize.
        self._inflight: dict[str, str] = {}
        self._lock = threading.Lock()

    def before_tool_call(self, tool_name: str, args: dict | None = None) -> None:
        """Authorize the tool call BEFORE it runs.

        Raises :class:`AiraToolDenied` if the policy engine denies or holds
        the action. The caller should not execute the tool if this raises.
        """
        arg_keys = sorted((args or {}).keys())
        details = f"Tool '{tool_name}' invoked. Arg keys: {arg_keys}"
        try:
            auth = self.client.authorize(
                action_type="tool_invoked",
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

        with self._lock:
            self._inflight[tool_name] = auth.action_id

    def after_tool_call(self, tool_name: str, result: Any = None) -> None:
        """Notarize a successful tool call."""
        with self._lock:
            action_id = self._inflight.pop(tool_name, None)
        if not action_id:
            return
        try:
            self.client.notarize(
                action_id=action_id,
                outcome="completed",
                outcome_details=f"Tool '{tool_name}' completed. Result length: {len(str(result))} chars",
            )
        except Exception as e:
            logger.warning("Aira notarize failed (non-blocking): %s", e)

    def on_tool_error(self, tool_name: str, error: BaseException) -> None:
        """Notarize a failed tool call."""
        with self._lock:
            action_id = self._inflight.pop(tool_name, None)
        if not action_id:
            return
        try:
            self.client.notarize(
                action_id=action_id,
                outcome="failed",
                outcome_details=f"Tool '{tool_name}' errored: {type(error).__name__}: {str(error)[:200]}",
            )
        except Exception as e:
            logger.warning("Aira notarize failed (non-blocking): %s", e)

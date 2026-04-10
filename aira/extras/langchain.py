"""LangChain integration — gate tool calls through Aira's authorize/notarize flow.

Uses LangChain's ``on_tool_start`` / ``on_tool_end`` / ``on_tool_error`` hooks to
wrap each tool call in an authorize → execute → notarize cycle.

Behavior:
- ``on_tool_start``: calls :meth:`Aira.authorize`. If the policy engine denies
  the action, the callback raises :class:`AiraToolDenied`, which aborts the
  tool call and surfaces as a tool error in the LangChain agent.
- ``on_tool_end``: calls :meth:`Aira.notarize` with ``outcome="completed"``.
- ``on_tool_error``: calls :meth:`Aira.notarize` with ``outcome="failed"``.

This IS a real gate: denied tool calls never run. Chains and LLM completions
are still audit-only (they are reported post-hoc via :meth:`Aira.authorize`
followed by immediate notarize because LangChain does not provide a
pre-execution chain hook that can abort).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aira import Aira

logger = logging.getLogger(__name__)

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError:
    raise ImportError(
        "langchain-core is required for the LangChain integration. "
        "Install with: pip install aira-sdk[langchain]"
    )


class AiraToolDenied(Exception):
    """Raised from ``on_tool_start`` when Aira denies a tool call."""

    def __init__(self, tool: str, code: str, message: str) -> None:
        self.tool = tool
        self.code = code
        self.message = message
        super().__init__(f"Aira denied tool '{tool}': [{code}] {message}")


class AiraCallbackHandler(BaseCallbackHandler):
    """LangChain callback that gates tool calls through Aira.

    Example::

        handler = AiraCallbackHandler(
            client=aira,
            agent_id="research-agent",
            model_id="gpt-5.2",
        )
        result = agent.invoke({"input": "..."}, config={"callbacks": [handler]})
    """

    def __init__(
        self,
        client: "Aira",
        agent_id: str,
        model_id: str | None = None,
        action_types: dict[str, str] | None = None,
    ):
        self.client = client
        self.agent_id = agent_id
        self.model_id = model_id
        self._action_types = {
            "tool": "tool_call",
            "chain_end": "chain_completed",
            "llm_end": "llm_completion",
            **(action_types or {}),
        }
        # Map run_id → action_id so on_tool_end can notarize the right action.
        self._inflight: dict[Any, str] = {}
        self._lock = threading.Lock()

    # ---- Tool lifecycle (real gate) -----------------------------------------

    def on_tool_start(
        self,
        serialized: dict,
        input_str: str,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Authorize the tool call BEFORE it executes.

        Raises :class:`AiraToolDenied` if the policy engine denies or holds
        the action — LangChain surfaces this as a tool error and aborts the
        call.
        """
        tool_name = (serialized or {}).get("name", "unknown")
        details = f"Tool '{tool_name}' input length: {len(input_str or '')} chars"
        try:
            auth = self.client.authorize(
                action_type=self._action_types["tool"],
                details=details[:5000],
                agent_id=self.agent_id,
                model_id=self.model_id,
            )
        except Exception as e:
            # POLICY_DENIED, ENDPOINT_NOT_WHITELISTED, etc → abort the tool.
            code = getattr(e, "code", "AUTHORIZE_FAILED")
            msg = getattr(e, "message", str(e))
            raise AiraToolDenied(tool_name, code, msg) from e

        if auth.status == "pending_approval":
            # Action is held for human review — we must not let the tool run.
            raise AiraToolDenied(
                tool_name,
                "PENDING_APPROVAL",
                f"Tool call held for approval (action {auth.action_id})",
            )

        with self._lock:
            self._inflight[run_id] = auth.action_id

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: Any = None,
        name: str = "unknown",
        **kwargs: Any,
    ) -> None:
        """Notarize the tool call after successful execution."""
        with self._lock:
            action_id = self._inflight.pop(run_id, None)
        if not action_id:
            return
        try:
            self.client.notarize(
                action_id=action_id,
                outcome="completed",
                outcome_details=f"Tool '{name}' completed. Output length: {len(str(output))} chars",
            )
        except Exception as e:
            logger.warning("Aira notarize failed (non-blocking): %s", e)

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Any = None,
        name: str = "unknown",
        **kwargs: Any,
    ) -> None:
        """Notarize a failed tool call."""
        with self._lock:
            action_id = self._inflight.pop(run_id, None)
        if not action_id:
            return
        try:
            self.client.notarize(
                action_id=action_id,
                outcome="failed",
                outcome_details=f"Tool '{name}' errored: {type(error).__name__}: {str(error)[:200]}",
            )
        except Exception as e:
            logger.warning("Aira notarize failed (non-blocking): %s", e)

    # ---- Chain / LLM (audit-only) -------------------------------------------
    #
    # LangChain's on_chain_start / on_llm_start fire AFTER the chain/LLM has
    # been scheduled, and raising from them does not reliably abort the call
    # across all chain types. These events are therefore audit-only:
    # authorize + immediate notarize in a single step.

    def _audit(self, action_type: str, details: str) -> None:
        try:
            auth = self.client.authorize(
                action_type=action_type,
                details=details[:5000],
                agent_id=self.agent_id,
                model_id=self.model_id,
            )
            if auth.status == "authorized":
                self.client.notarize(
                    action_id=auth.action_id,
                    outcome="completed",
                    outcome_details=details[:5000],
                )
        except Exception as e:
            logger.warning("Aira audit failed (non-blocking): %s", e)

    def on_chain_end(self, outputs: dict, **kwargs: Any) -> None:
        keys = list(outputs.keys()) if isinstance(outputs, dict) else []
        self._audit(self._action_types["chain_end"], f"Chain completed. Output keys: {keys}")

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        gen_count = len(response.generations) if hasattr(response, "generations") else 0
        self._audit(self._action_types["llm_end"], f"LLM completed. Generations: {gen_count}")

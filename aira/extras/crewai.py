"""CrewAI integration — audit-only logging of task and step completions.

CrewAI exposes ``task_callback`` and ``step_callback`` which fire AFTER the
work has already been performed. There is no pre-execution hook that can
reliably abort a step or task across all CrewAI versions, so **this
integration is audit-only**: it records what happened but cannot gate it.

If you need a real authorization gate on CrewAI actions, call
:meth:`aira.Aira.authorize` directly from inside your tool or task code
(before the side-effect) and check ``auth.status`` yourself.

Each callback runs a full authorize → notarize cycle back-to-back so the
cryptographic receipt still records the action with a policy evaluation.
"""
from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aira import Aira

logger = logging.getLogger(__name__)


class AiraCrewHook:
    """Audit-only CrewAI hook.

    .. warning::
       CrewAI does not provide pre-execution hooks, so this integration
       is audit-only — it cannot prevent a task or step from running. For
       true gating, call :meth:`aira.Aira.authorize` inside your tool
       functions before performing the side-effect.
    """

    def __init__(self, client: "Aira", agent_id: str, model_id: str | None = None):
        self.client = client
        self.agent_id = agent_id
        self.model_id = model_id

    def _audit(self, action_type: str, details: str) -> None:
        """Authorize then immediately notarize — records the action post-hoc."""
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
            else:
                logger.info(
                    "Aira audit skipped notarize: action %s is %s",
                    auth.action_id,
                    auth.status,
                )
        except Exception as e:
            logger.warning("Aira audit failed (non-blocking): %s", e)

    def task_callback(self, output: Any) -> None:
        """Called by CrewAI when a task completes."""
        desc = str(getattr(output, "description", ""))[:200]
        self._audit("task_completed", f"Task completed: {desc}")

    def step_callback(self, step_output: Any) -> None:
        """Called by CrewAI on each agent step."""
        self._audit("agent_step", f"Agent step completed. Output length: {len(str(step_output))} chars")

    @classmethod
    def for_crew(cls, client: "Aira", agent_id: str, **kwargs: Any) -> dict[str, Any]:
        """Return callbacks dict compatible with CrewAI's Crew() constructor."""
        hook = cls(client, agent_id, **kwargs)
        return {
            "task_callback": hook.task_callback,
            "step_callback": hook.step_callback,
        }

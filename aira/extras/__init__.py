"""Aira SDK framework integrations.

Each integration is labeled honestly with its **integration type**:

- ``"gate"`` — intercepts before execution and can deny. The action is
  authorized through Aira's policy engine *before* the framework runs the
  underlying call. Denied actions never execute.
- ``"audit"`` — runs after execution because the host framework does not
  expose a pre-execution hook that can abort. Aira still records a signed
  receipt; it just cannot prevent the action.
- ``"adapter"`` — exposes Aira's own API as a tool the host framework can
  call. Neither a gate nor an audit hook over other tools.

The :data:`INTEGRATIONS` registry below is the single source of truth.
The README integration matrix is generated from it. Run ``python -m aira.extras``
to print the matrix from a checkout, useful for sanity-checking that we
haven't drifted from documentation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrationSpec:
    """Honest label for an Aira SDK extra.

    ``kind``:
        ``"gate"`` — pre-execution interception, can deny
        ``"audit"`` — post-execution recording only
        ``"adapter"`` — exposes Aira as a tool, not a hook
    """
    name: str
    module: str
    symbol: str
    kind: str
    pre_execution_gate: bool
    surface: str
    notes: str


INTEGRATIONS: list[IntegrationSpec] = [
    IntegrationSpec(
        name="LangChain",
        module="aira.extras.langchain",
        symbol="AiraCallbackHandler",
        kind="gate",
        pre_execution_gate=True,
        surface="Tools (gate). Chains and LLM completions are audit-only.",
        notes=(
            "on_tool_start raises AiraToolDenied when the policy engine denies, "
            "which aborts the tool call. Chain/LLM hooks fire after execution and "
            "are reported as a fast authorize+notarize cycle."
        ),
    ),
    IntegrationSpec(
        name="OpenAI Agents",
        module="aira.extras.openai_agents",
        symbol="AiraGuardrail",
        kind="gate",
        pre_execution_gate=True,
        surface="Tools",
        notes=(
            "Wraps each tool function: authorize() runs before the underlying "
            "tool body. Denied calls raise; failed calls report outcome=failed."
        ),
    ),
    IntegrationSpec(
        name="AWS Bedrock",
        module="aira.extras.bedrock",
        symbol="AiraBedrockHandler",
        kind="gate",
        pre_execution_gate=True,
        surface="invoke_model + invoke_agent",
        notes=(
            "Wraps boto3 Bedrock clients. authorize() runs before invoke_model / "
            "invoke_agent; denied invocations raise AiraInvocationDenied."
        ),
    ),
    IntegrationSpec(
        name="Google ADK",
        module="aira.extras.google_adk",
        symbol="AiraPlugin",
        kind="gate",
        pre_execution_gate=True,
        surface="Tools",
        notes=(
            "before_tool_call hook gates tool execution; denied calls raise."
        ),
    ),
    IntegrationSpec(
        name="CrewAI",
        module="aira.extras.crewai",
        symbol="AiraCrewHook",
        kind="audit",
        pre_execution_gate=False,
        surface="Tasks + steps (audit only)",
        notes=(
            "CrewAI's task_callback / step_callback fire AFTER execution; there "
            "is no pre-execution hook in CrewAI to intercept. For real gating, "
            "call Aira.authorize() inside your tool body before any side-effect."
        ),
    ),
    IntegrationSpec(
        name="MCP",
        module="aira.extras.mcp",
        symbol="create_server",
        kind="adapter",
        pre_execution_gate=False,
        surface="Server adapter",
        notes=(
            "Exposes Aira's authorize/notarize/verify as MCP tools an agent can "
            "call. NOT a wrapper over other MCP tools — it's a protocol adapter."
        ),
    ),
    IntegrationSpec(
        name="Webhooks",
        module="aira.extras.webhooks",
        symbol="verify_signature",
        kind="adapter",
        pre_execution_gate=False,
        surface="HMAC verification helper",
        notes=(
            "Standalone HMAC-SHA256 webhook signature verification. Not an "
            "agent integration; just a helper for receiving Aira webhooks."
        ),
    ),
]


def integration_matrix_markdown() -> str:
    """Render INTEGRATIONS as a Markdown table for the README."""
    rows = [
        "| Integration | Type | Pre-execution gate? | Surface | Notes |",
        "|---|---|---|---|---|",
    ]
    for i in INTEGRATIONS:
        rows.append(
            f"| **{i.name}** | {i.kind} | {'Yes' if i.pre_execution_gate else 'No'} | {i.surface} | {i.notes} |"
        )
    return "\n".join(rows)


def __getattr__(name: str):
    _imports = {
        "AiraCallbackHandler": "aira.extras.langchain",
        "AiraCrewHook": "aira.extras.crewai",
        "AiraGuardrail": "aira.extras.openai_agents",
        "AiraPlugin": "aira.extras.google_adk",
        "AiraBedrockHandler": "aira.extras.bedrock",
        "verify_signature": "aira.extras.webhooks",
        "parse_event": "aira.extras.webhooks",
        "WebhookEvent": "aira.extras.webhooks",
    }
    if name in _imports:
        import importlib
        module = importlib.import_module(_imports[name])
        return getattr(module, name)
    raise AttributeError(f"module 'aira.extras' has no attribute {name!r}")

"""MCP server exposing Aira actions as tools for AI agents."""
from __future__ import annotations
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    from mcp.server import Server
    from mcp.types import Tool, TextContent
except ImportError:
    raise ImportError(
        "mcp is required for the MCP server integration. "
        "Install with: pip install aira-sdk[mcp]"
    )


def create_server(api_key: str | None = None, base_url: str | None = None) -> Server:
    """Create an MCP server with Aira tools."""
    from aira import Aira
    from aira.client import AiraError

    key = api_key or os.environ.get("AIRA_API_KEY", "")
    if not key:
        raise ValueError("API key required — pass api_key or set AIRA_API_KEY")

    kwargs: dict[str, Any] = {"api_key": key}
    if base_url:
        kwargs["base_url"] = base_url

    client = Aira(**kwargs)
    server = Server("aira")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="notarize_action",
                description="Notarize an AI agent action with a cryptographic receipt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action_type": {"type": "string", "description": "e.g. email_sent, loan_approved, claim_processed"},
                        "details": {"type": "string", "description": "What happened"},
                        "agent_id": {"type": "string", "description": "Agent slug"},
                        "model_id": {"type": "string", "description": "Model used (optional)"},
                    },
                    "required": ["action_type", "details"],
                },
            ),
            Tool(
                name="verify_action",
                description="Verify a notarized action's cryptographic receipt",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action_id": {"type": "string", "description": "Action UUID"},
                    },
                    "required": ["action_id"],
                },
            ),
            Tool(
                name="get_receipt",
                description="Get the cryptographic receipt for a notarized action",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "receipt_id": {"type": "string", "description": "Receipt UUID"},
                    },
                    "required": ["receipt_id"],
                },
            ),
            Tool(
                name="resolve_did",
                description="Resolve a DID (Decentralized Identifier) to its DID document",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "did": {"type": "string", "description": "The DID to resolve (e.g. did:web:airaproof.com:agents:my-agent)"},
                    },
                    "required": ["did"],
                },
            ),
            Tool(
                name="verify_credential",
                description="Verify a Verifiable Credential — checks signature, expiry, and revocation status",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "credential": {"type": "object", "description": "The Verifiable Credential JSON object to verify"},
                    },
                    "required": ["credential"],
                },
            ),
            Tool(
                name="get_reputation",
                description="Get the current reputation score and tier for an agent",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "agent_slug": {"type": "string", "description": "Agent slug to look up"},
                    },
                    "required": ["agent_slug"],
                },
            ),
            Tool(
                name="request_mutual_sign",
                description="Initiate a mutual signing request for a notarized action with a counterparty",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action_id": {"type": "string", "description": "Action UUID to co-sign"},
                        "counterparty_did": {"type": "string", "description": "DID of the counterparty agent"},
                    },
                    "required": ["action_id", "counterparty_did"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "notarize_action":
                result = client.notarize(**{k: v for k, v in arguments.items() if v})
                data = result.__dict__ if hasattr(result, "__dict__") else result
                return [TextContent(type="text", text=json.dumps(data, default=str))]
            elif name == "verify_action":
                result = client.verify_action(arguments["action_id"])
                data = result.__dict__ if hasattr(result, "__dict__") else result
                return [TextContent(type="text", text=json.dumps(data, default=str))]
            elif name == "get_receipt":
                result = client.get_receipt(arguments["receipt_id"])
                data = result.__dict__ if hasattr(result, "__dict__") else result
                return [TextContent(type="text", text=json.dumps(data, default=str))]
            elif name == "resolve_did":
                result = client.resolve_did(arguments["did"])
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "verify_credential":
                result = client.verify_credential(arguments["credential"])
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "get_reputation":
                result = client.get_reputation(arguments["agent_slug"])
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            elif name == "request_mutual_sign":
                result = client.request_mutual_sign(arguments["action_id"], arguments["counterparty_did"])
                return [TextContent(type="text", text=json.dumps(result, default=str))]
            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
        except AiraError as e:
            return [TextContent(type="text", text=json.dumps({"error": e.message, "code": e.code}))]
        except Exception:
            return [TextContent(type="text", text=json.dumps({"error": "Internal error", "code": "SDK_ERROR"}))]

    return server


def main():
    """Entry point for aira-mcp console script."""
    import asyncio
    from mcp.server.stdio import stdio_server
    from mcp.server import InitializationOptions
    from mcp.server.lowlevel.server import NotificationOptions
    from aira import __version__

    server = create_server()

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            init_options = InitializationOptions(
                server_name="aira",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            )
            await server.run(read_stream, write_stream, init_options)

    asyncio.run(run())


if __name__ == "__main__":
    main()

# Aira Python SDK — Engineering Guidelines

## Project

Python SDK for Aira — `pip install aira-sdk`. Sync + async clients, framework integrations.

## Stack

- **HTTP**: httpx (sync + async)
- **Types**: dataclasses
- **Testing**: pytest + pytest-asyncio
- **Build**: hatchling
- **Package**: aira-sdk on PyPI

## Structure

```
aira/
  __init__.py       # Exports, __version__
  client.py         # Aira (sync) + AsyncAira (async) + sessions + trace decorator
  types.py          # Dataclass response types (ActionReceipt, AgentDetail, etc.)
  _offline.py       # OfflineQueue for offline mode
  cli.py            # CLI commands (aira, aira-mcp)
  extras/
    langchain.py    # AiraCallbackHandler
    crewai.py       # AiraCrewHook
    openai_agents.py # AiraGuardrail
    google_adk.py   # AiraPlugin
    bedrock.py      # AiraBedrockHandler
    mcp.py          # MCP server
    webhooks.py     # HMAC signature verification
```

## Commands

```bash
# Run tests
.venv/bin/python -m pytest tests/ -q

# Build
.venv/bin/python -m build
```

## Conventions

### Client Methods
- Every method on `Aira` must be mirrored on `AsyncAira` (same name, same params, async)
- Use `_build_body(**kwargs)` to filter None values from request bodies
- Use `_to_dataclass(cls, data)` to convert API responses to typed dataclasses
- Paginated responses return `PaginatedList` dataclass
- Public methods: named params with defaults, not `**kwargs`
- Details are truncated via `_truncate_details()` — never send raw user content

### Types
- All response types are `@dataclass` in `types.py`
- Required fields first, optional fields (with defaults) after — dataclass rule
- Keep in sync with backend Pydantic schemas and TypeScript SDK types

### Extras
- Each integration is a single file in `extras/`
- Install via extras: `pip install aira-sdk[langchain]`
- All integrations are non-blocking — notarization failures are logged, never raised
- Each extra has its own test file in `tests/`

### Version
- `pyproject.toml` version and `__init__.py __version__` MUST match
- Publish via GitHub Release → triggers `Publish to PyPI` workflow

### Git Workflow
- Feature branches: `feat/feature-name`
- Always create PRs
- CI: `pytest` must pass
- Bump version in both `pyproject.toml` and `__init__.py`
- Tag releases: `v0.X.Y`

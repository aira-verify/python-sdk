"""Aira CLI — command-line interface for Aira legal infrastructure."""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("CLI requires extra dependencies. Install with: pip install aira-sdk[cli]", file=sys.stderr)
    sys.exit(1)

from aira import Aira, __version__

console = Console()
app = typer.Typer(name="aira", help="Aira CLI — AI governance infrastructure", no_args_is_help=True)
agents_app = typer.Typer(help="Manage agents", no_args_is_help=True)
actions_app = typer.Typer(help="Manage actions", no_args_is_help=True)
snapshot_app = typer.Typer(help="Compliance snapshots", no_args_is_help=True)
package_app = typer.Typer(help="Evidence packages", no_args_is_help=True)

app.add_typer(agents_app, name="agents")
app.add_typer(actions_app, name="actions")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(package_app, name="package")


def _get_client(api_key: Optional[str] = None, base_url: Optional[str] = None) -> Aira:
    key = api_key or os.environ.get("AIRA_API_KEY", "")
    if not key:
        console.print("[red]Error:[/red] No API key. Set AIRA_API_KEY or use --api-key flag.")
        raise typer.Exit(1)
    kwargs = {"api_key": key}
    if base_url:
        kwargs["base_url"] = base_url
    return Aira(**kwargs)


# Global options
_api_key_option = typer.Option(None, "--api-key", "-k", envvar="AIRA_API_KEY", help="Aira API key")
_base_url_option = typer.Option(None, "--base-url", help="API base URL")


@app.command()
def version():
    """Show SDK version."""
    console.print(f"aira-sdk {__version__}")


@app.command()
def verify(
    action_id: str = typer.Argument(..., help="Action UUID to verify"),
    api_key: Optional[str] = _api_key_option,
    base_url: Optional[str] = _base_url_option,
):
    """Verify a notarized action's cryptographic receipt."""
    client = _get_client(api_key, base_url)
    try:
        result = client.verify_action(action_id)
        table = Table(title="Verification Result")
        table.add_column("Field", style="bold")
        table.add_column("Value")

        for k, v in result.__dict__.items():
            table.add_row(k, str(v))

        console.print(table)
        if result.valid:
            console.print("[green]Action verified[/green]")
        else:
            console.print("[red]Verification failed[/red]")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@actions_app.command("list")
def actions_list(
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent slug"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
    api_key: Optional[str] = _api_key_option,
    base_url: Optional[str] = _base_url_option,
):
    """List notarized actions."""
    client = _get_client(api_key, base_url)
    try:
        if agent:
            result = client.get_agent_actions(agent)
        else:
            result = client.list_actions(per_page=limit)

        items = result.data
        table = Table(title=f"Actions ({len(items)})")
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Type")
        table.add_column("Agent")
        table.add_column("Status")
        table.add_column("Created")

        for a in items:
            if isinstance(a, dict):
                table.add_row(
                    a.get("action_id", "")[:12],
                    a.get("action_type", ""),
                    a.get("agent_id", ""),
                    a.get("status", ""),
                    a.get("created_at", "")[:19],
                )
            else:
                aid = getattr(a, "action_id", getattr(a, "id", ""))
                table.add_row(
                    str(aid)[:12],
                    getattr(a, "action_type", ""),
                    getattr(a, "agent_id", ""),
                    getattr(a, "status", ""),
                    str(getattr(a, "created_at", ""))[:19],
                )

        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@agents_app.command("list")
def agents_list(
    api_key: Optional[str] = _api_key_option,
    base_url: Optional[str] = _base_url_option,
):
    """List registered agents."""
    client = _get_client(api_key, base_url)
    try:
        result = client.list_agents()
        items = result.data
        table = Table(title=f"Agents ({len(items)})")
        table.add_column("Slug")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Public")

        for a in items:
            if isinstance(a, dict):
                table.add_row(
                    a.get("agent_slug", ""),
                    a.get("display_name", ""),
                    a.get("status", ""),
                    str(a.get("public", "")),
                )
            else:
                table.add_row(
                    getattr(a, "agent_slug", ""),
                    getattr(a, "display_name", ""),
                    getattr(a, "status", ""),
                    str(getattr(a, "public", "")),
                )

        console.print(table)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@agents_app.command("create")
def agents_create(
    slug: str = typer.Argument(..., help="Agent slug"),
    name: str = typer.Option(..., "--name", "-n", help="Display name"),
    api_key: Optional[str] = _api_key_option,
    base_url: Optional[str] = _base_url_option,
):
    """Register a new agent."""
    client = _get_client(api_key, base_url)
    try:
        result = client.register_agent(agent_slug=slug, display_name=name)
        console.print(f"[green]Agent registered:[/green] {slug}")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@snapshot_app.command("create")
def snapshot_create(
    framework: str = typer.Argument(..., help="Framework: eu-ai-act, sr-11-7, gdpr-art-22"),
    agent_slug: str = typer.Argument(..., help="Agent slug"),
    api_key: Optional[str] = _api_key_option,
    base_url: Optional[str] = _base_url_option,
):
    """Create a compliance snapshot."""
    client = _get_client(api_key, base_url)
    try:
        result = client.create_compliance_snapshot(framework=framework, agent_slug=agent_slug)
        console.print(f"[green]Snapshot created:[/green] {result.id}")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@package_app.command("create")
def package_create(
    title: str = typer.Option(..., "--title", "-t", help="Package title"),
    actions: str = typer.Option(..., "--actions", "-a", help="Comma-separated action IDs"),
    api_key: Optional[str] = _api_key_option,
    base_url: Optional[str] = _base_url_option,
):
    """Create a sealed evidence package."""
    client = _get_client(api_key, base_url)
    action_ids = [a.strip() for a in actions.split(",") if a.strip()]
    try:
        result = client.create_evidence_package(title=title, action_ids=action_ids)
        console.print(f"[green]Evidence package created:[/green] {result.id}")
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

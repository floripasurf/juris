"""Shared Rich console for the CLI (single instance across command modules)."""

from __future__ import annotations

from rich.console import Console

console = Console()

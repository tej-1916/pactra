"""Tool adapter family: external tool invocation -> candidate operations."""

from __future__ import annotations

from services.adapters.tools.base import (
    FAMILY,
    ToolAdapter,
    authorize_operation,
    required_capability,
)
from services.adapters.tools.mcp import DESCRIPTOR as MCP_DESCRIPTOR
from services.adapters.tools.mcp import McpToolAdapter

__all__ = [
    "FAMILY",
    "MCP_DESCRIPTOR",
    "McpToolAdapter",
    "ToolAdapter",
    "authorize_operation",
    "required_capability",
]

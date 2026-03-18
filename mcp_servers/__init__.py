"""MCP server registry."""

from __future__ import annotations

from agents.mcp import MCPServer

from .deepwiki import build_server as build_deepwiki_server


def build_servers() -> list[MCPServer]:
    return [build_deepwiki_server()]

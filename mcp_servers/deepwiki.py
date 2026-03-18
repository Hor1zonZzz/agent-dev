"""DeepWiki MCP server registration."""

from __future__ import annotations

from agents.mcp import MCPServer, MCPServerStreamableHttp


DEFAULT_URL = "https://mcp.deepwiki.com/mcp"


def build_server() -> MCPServer:
    return MCPServerStreamableHttp(
        name="deepwiki",
        params={"url": DEFAULT_URL},
        cache_tools_list=True,
    )

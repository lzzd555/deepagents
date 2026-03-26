"""MCP Client Proxy for persistent session management.

This module provides a singleton MCP client proxy that maintains persistent
browser sessions across multiple agent tasks.
"""

import asyncio
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from deepagents_cli.config import console


class MCPClientProxy:
    """Singleton proxy for MCP client with persistent session management."""

    _instance: "MCPClientProxy | None" = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        self._client: MultiServerMCPClient | None = None
        self._session: Any = None
        self._session_cm: Any = None  # Context manager
        self._tools: list[BaseTool] = []
        self._proxy_tools: list[BaseTool] = []
        self._initialized = False

    @classmethod
    async def get_instance(cls) -> "MCPClientProxy":
        """Get or create the singleton instance."""
        async with cls._lock:
            if cls._instance is None:
                cls._instance = MCPClientProxy()
            return cls._instance

    async def initialize(self) -> list[BaseTool]:
        """Initialize MCP client and enter session to keep browser alive."""
        if self._initialized:
            return self._proxy_tools

        try:
            self._client = MultiServerMCPClient(
                {
                    "playwright": {
                        "command": "npx",
                        "args": ["-y", "@playwright/mcp@0.0.68"],
                        "transport": "stdio",
                    }
                }
            )
            # Enter session context manager to keep connection alive
            self._session_cm = self._client.session("playwright")
            self._session = await self._session_cm.__aenter__()

            self._tools = await load_mcp_tools(self._session)
            self._proxy_tools = self._create_proxy_tools()
            self._initialized = True

            console.print(f"[green]✓ Playwright MCP initialized: {len(self._tools)} tools[/green]")
            return self._proxy_tools
        except Exception as e:
            console.print(f"[yellow]⚠ Playwright MCP not available: {e}[/yellow]")
            return []

    def _create_proxy_tools(self) -> list[BaseTool]:
        """Create proxy tools that delegate to the persistent session."""
        proxy_tools = []
        for original_tool in self._tools:
            def make_invoke(tool: BaseTool):
                async def invoke(**kwargs: Any) -> Any:
                    return await tool.ainvoke(kwargs)
                return invoke

            proxy_tool = StructuredTool.from_function(
                coroutine=make_invoke(original_tool),
                name=original_tool.name,
                description=original_tool.description,
                args_schema=original_tool.args_schema,
            )
            proxy_tools.append(proxy_tool)
        return proxy_tools

    async def shutdown(self) -> None:
        """Exit session and cleanup."""
        if self._session_cm:
            await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None

        self._initialized = False
        self._tools = []
        self._proxy_tools = []
        MCPClientProxy._instance = None


async def get_mcp_tools() -> list[BaseTool]:
    """Get MCP tools with persistent session support."""
    proxy = await MCPClientProxy.get_instance()
    return await proxy.initialize()

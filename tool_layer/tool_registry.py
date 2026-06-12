"""
tool_layer/tool_registry.py
Register tools and generate their system prompt definitions.
"""

from typing import Callable, Any


class ToolDef:
    """Definition of one tool."""

    def __init__(self, name: str, description: str, func: Callable, params: dict[str, str] | None = None):
        self.name = name
        self.description = description
        self.func = func
        self.params = params or {}


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, name: str, description: str = "", func: Callable = None, params: dict[str, str] | None = None):
        # Allow calling as register(name, func) for convenience
        if func is None and callable(description):
            func = description
            description = ""
        self._tools[name] = ToolDef(name, description, func, params)

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def dispatch(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool by name with given params."""
        tool = self._tools.get(name)
        if not tool:
            return f"[Error] Unknown tool: {name}"
        try:
            return tool.func(**params)
        except TypeError as e:
            return f"[Error] Invalid parameters for {name}: {e}"
        except Exception as e:
            return f"[Error] Tool {name} failed: {e}"

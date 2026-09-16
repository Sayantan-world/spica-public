"""Named tools the orchestrator calls. Dispatch is deterministic, not LLM-chosen."""

from collections.abc import Callable
from typing import Any


class Tool:
    def __init__(self, name: str, description: str, fn: Callable[..., Any]):
        self.name = name
        self.description = description
        self.fn = fn

    def __call__(self, **kwargs: Any) -> Any:
        return self.fn(**kwargs)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"unknown tool: {name}")
        return tool

    def call(self, name: str, **kwargs: Any) -> Any:
        return self.get(name)(**kwargs)

    def names(self) -> list[str]:
        return sorted(self._tools)


def tool(name: str, description: str):
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._agent_tool = Tool(name, description, fn)  # type: ignore[attr-defined]
        return fn

    return deco

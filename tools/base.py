"""沿用 mini-openclaw 的 Tool / ToolRegistry 协议。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str]
    requires_confirmation: bool = True

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters,
        }}

    def invoke(self, arguments: dict[str, Any]) -> str:
        # 参数校验放在执行前；支持以后添加的完整 JSON Schema。
        from jsonschema import Draft202012Validator
        Draft202012Validator(self.parameters).validate(arguments)
        return str(self.run(**arguments))


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重名：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def __len__(self) -> int:
        return len(self._tools)


def build_default_registry(workdir=".", *, enable_shell: bool = False) -> ToolRegistry:
    from .fs import build_file_tools
    registry = ToolRegistry()
    for tool in build_file_tools(workdir):
        registry.register(tool)
    if enable_shell:
        from .shell import build_shell_tool
        registry.register(build_shell_tool(workdir))
    return registry

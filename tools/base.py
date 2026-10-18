"""沿用 mini-openclaw 的 Tool / ToolRegistry 协议。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


def tool_diagnostic(error: Exception) -> dict | None:
    """Return controlled validation feedback without argument values or schemas."""
    from jsonschema import ValidationError
    public=getattr(error,'public_diagnostic',None)
    if isinstance(public,dict):
        return {key:str(public[key])[:250] for key in ('code','message','path') if key in public}
    if isinstance(error,ValidationError):
        messages={'required':'缺少必填字段','additionalProperties':'包含不支持的字段，请使用当前工具列出的字段',
                  'enum':'字段引用或选项不在当前可用范围内，请重新读取当前方案',
                  'type':'字段类型不正确','anyOf':'字段结构不符合当前工具格式',
                  'format':'字段格式不正确','minimum':'数值小于允许范围','maximum':'数值超过允许范围'}
        import re
        parts=[str(x) for x in error.absolute_path]
        path='.'.join(x if re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]{0,49}|[0-9]{1,5}',x) else '?' for x in parts)[:160]
        return dict(code='tool_parameter_validation',message=messages.get(error.validator,'字段未通过参数校验'),path=path or '输入')
    return None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str]
    requires_confirmation: bool = True
    normalize_arguments: Callable[[dict],dict] | None = None

    def prepare(self,arguments:dict) -> dict:
        return self.normalize_arguments(arguments) if self.normalize_arguments else arguments

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters,
        }}

    def invoke(self, arguments: dict[str, Any]) -> str:
        # 参数校验放在执行前；支持以后添加的完整 JSON Schema。
        from jsonschema import Draft202012Validator
        arguments=self.prepare(arguments)
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

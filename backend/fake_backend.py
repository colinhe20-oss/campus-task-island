"""离线脚本后端；只验证调用链，不模拟真实模型能力。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


class FakeBackend:
    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses = deepcopy(responses or [])
        self.requests: list[dict[str, Any]] = []

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        self.requests.append(deepcopy({"messages": messages, "tools": tools}))
        if self.responses:
            return self.responses.pop(0)
        return {"role": "assistant", "content": "[离线模式] 请用 --selfcheck 验证工具链；实际任务需要模型配置。", "tool_calls": []}

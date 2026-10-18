"""从 mini-openclaw 提取的同步 Tool Calling 主循环。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

from tools.base import ToolRegistry,tool_diagnostic
from .context import truncate_observation
from .prompts import SYSTEM_PROMPT


class StepLimitExceeded(RuntimeError):
    pass


class RunCancelled(RuntimeError):
    pass


class AgentLoop:
    def __init__(self, backend: Any, registry: ToolRegistry,
                 system_prompt: str = SYSTEM_PROMPT, max_turns: int = 12,
                 auto_approve: bool = False,
                 confirm_callback: Callable[[str, dict], bool] | None = None,
                 event_callback: Callable[[str, dict], None] | None = None,
                 cancel_event: threading.Event | None = None,
                 max_observation_chars: int = 12000,
                 stream: bool = False,
                 final_check: Callable[[], str | None] | None = None):
        if max_turns < 1 or max_observation_chars < 1:
            raise ValueError("轮数和结果长度上限必须为正数")
        self.backend = backend
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.auto_approve = auto_approve
        self.confirm_callback = confirm_callback
        self.event_callback = event_callback
        self.cancel_event = cancel_event or threading.Event()
        self.stream = stream
        self.final_check = final_check
        self.max_observation_chars = max_observation_chars
        self.messages: list[dict[str, Any]] = []

    def _emit(self, kind: str, **data: Any) -> None:
        if self.event_callback:
            self.event_callback(kind, data)

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise RunCancelled("任务已取消")

    def run(self, user_task: str, history_messages: list[dict] | None = None) -> str:
        # 接收对话历史，不接收调用方伪造的 system / tool 消息。
        history = []
        for m in history_messages or []:
            if m.get("role") not in {"user", "assistant"} or m.get("tool_calls"):
                continue
            item = {"role": m["role"], "content": m.get("content", "")}
            if m["role"] == "assistant" and "reasoning_content" in m:
                item["reasoning_content"] = m["reasoning_content"]
            history.append(item)
        self.messages = [{"role": "system", "content": self.system_prompt},
                         *history, {"role": "user", "content": user_task}]
        self._emit("run_started", task=user_task)
        try:
            return self._run()
        except Exception as exc:
            self._emit("run_failed", error=str(exc), cancelled=isinstance(exc, RunCancelled),
                       limited=isinstance(exc, StepLimitExceeded))
            raise

    def _run(self) -> str:
        last_action = None
        repeats = 0
        for step in range(1, self.max_turns + 1):
            self._check_cancelled()
            started = time.monotonic()
            self._emit('model_started', step=step)
            streamed_chars = 0
            def delta(text):
                nonlocal streamed_chars
                self._check_cancelled()
                visible = text[:max(0,8000-streamed_chars)]
                streamed_chars += len(visible)
                if visible:
                    self._emit('text_delta', step=step, text=visible)
            if self.stream and hasattr(self.backend, 'chat_stream'):
                assistant = self.backend.chat_stream(self.messages, tools=self.registry.schemas(), on_delta=delta,
                                                     cancel_event=self.cancel_event)
            else:
                assistant = self.backend.chat(self.messages, tools=self.registry.schemas())
            self._emit('model_finished', step=step, usage=assistant.get('usage') or {},
                       duration_ms=round((time.monotonic()-started)*1000))
            self._check_cancelled()
            calls = assistant.get("tool_calls") or []
            # 本地生成缺失 ID，确保 assistant 调用与 tool 结果一一对应。
            calls = [dict(call, id=call.get("id") or f"call_{uuid.uuid4().hex}") for call in calls]
            content = assistant.get("content") or ""
            message = {"role": "assistant", "content": content}
            if "reasoning_content" in assistant:
                message["reasoning_content"] = assistant["reasoning_content"]
            if calls:
                message["tool_calls"] = calls
            self.messages.append(message)
            self._emit("assistant_message", step=step, content=content)
            if not calls:
                feedback = self.final_check() if self.final_check else None
                if feedback:
                    self.messages.append({'role':'user','content':'[协调器校验] '+feedback})
                    continue
                self._emit("run_finished", answer=content)
                return content

            for call in calls:
                self._check_cancelled()
                name = call.get("name", "")
                arguments = call.get("arguments", {})
                started = time.monotonic()
                self._emit("tool_started", step=step, tool=name, call_id=call["id"], arguments=arguments)
                error_type = None
                diagnostic = None
                try:
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("工具 arguments 必须为 JSON 对象")
                    tool = self.registry.get(name)
                    if tool is None:
                        raise ValueError(f"未知工具：{name}")
                    arguments=tool.prepare(arguments)
                    # 在请求确认前校验，错误参数不能执行。
                    from jsonschema import Draft202012Validator
                    Draft202012Validator(tool.parameters).validate(arguments)
                    if tool.requires_confirmation and not self.auto_approve:
                        self._emit("approval_required", tool=name, arguments=arguments)
                        if not self.confirm_callback or not self.confirm_callback(name, arguments):
                            raise PermissionError(f"未批准工具：{name}")
                    # 写入等带副作用的工具不自动重试。
                    observation = tool.invoke(arguments)
                except Exception as exc:
                    error_type = type(exc).__name__
                    diagnostic=tool_diagnostic(exc)
                    detail=(diagnostic['message']+'（'+diagnostic.get('path','输入')+'）') if diagnostic else str(exc)
                    observation = f"[工具错误] {name}: {type(exc).__name__}: {detail}"
                action = (name, json.dumps(arguments, ensure_ascii=False, sort_keys=True))
                repeats = repeats + 1 if action == last_action else 1
                last_action = action
                if repeats >= 3:
                    observation += "\n[协调器] 同一调用已重复三次，请检查结果并改变方法或说明阻碍。"
                self.messages.append({"role": "tool", "name": name,
                                      "tool_call_id": call["id"],
                                      "content": truncate_observation(observation, self.max_observation_chars)})
                self._emit("tool_finished", step=step, tool=name, call_id=call["id"], result=observation,
                           success=not observation.startswith('[工具错误]'),
                           error_type=error_type,
                           diagnostic=diagnostic,
                           duration_ms=round((time.monotonic() - started) * 1000))
        raise StepLimitExceeded(f"已达到 {self.max_turns} 轮模型调用上限，任务未确认完成")

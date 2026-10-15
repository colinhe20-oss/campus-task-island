"""从原 DeepSeekBackend 提取的 OpenAI-compatible Chat Completions 适配层。"""
from __future__ import annotations

import json
import os
from typing import Any


class ChatBackend:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: float = 60.0):
        import httpx
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL") or
                         os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "")
        if not self.api_key or not self.model:
            missing = []
            if not self.api_key:
                missing.append("LLM_API_KEY（或 DEEPSEEK_API_KEY）")
            if not self.model:
                missing.append("LLM_MODEL（或 DEEPSEEK_MODEL）")
            raise ValueError("缺少配置：" + "、".join(missing))
        self._client = httpx.Client(timeout=timeout)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict] | None = None,
             temperature: float = 0.0) -> dict:
        payload = {"model": self.model, "messages": self._to_openai_messages(messages),
                   "temperature": temperature}
        if tools:
            payload.update(tools=tools, tool_choice="auto")
        endpoint = self.base_url if self.base_url.endswith("/v1") else self.base_url + "/v1"
        response = self._client.post(endpoint + "/chat/completions",
                                     headers={"Authorization": f"Bearer {self.api_key}"}, json=payload)
        response.raise_for_status()
        body = response.json()
        result = self._normalize(body["choices"][0]["message"])
        result["usage"] = body.get("usage", {})
        return result

    def chat_stream(self, messages, tools=None, temperature=0.0, *, on_delta, cancel_event):
        """拼接真实 SSE 片段；工具参数完整返回后才交给主循环执行。"""
        from agent.loop import RunCancelled
        payload = {'model': self.model, 'messages': self._to_openai_messages(messages),
                   'temperature': temperature, 'stream': True, 'stream_options': {'include_usage': True}}
        if tools:
            payload.update(tools=tools, tool_choice='auto')
        endpoint = self.base_url if self.base_url.endswith('/v1') else self.base_url+'/v1'
        content, reasoning, calls, usage = [], [], {}, {}
        finished = False
        with self._client.stream('POST', endpoint+'/chat/completions',
                                 headers={'Authorization': f'Bearer {self.api_key}'}, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if cancel_event.is_set():
                    raise RunCancelled('任务已取消')
                if not line.startswith('data:'):
                    continue
                on_delta('')  # 同样检查只有推理片段时的总体时间预算。
                raw = line[5:].strip()
                if raw == '[DONE]':
                    break
                chunk = json.loads(raw)
                if chunk.get('error'):
                    raise ValueError('模型流返回错误')
                usage = chunk.get('usage') or usage
                for choice in chunk.get('choices', []):
                    if choice.get('index', 0) != 0:
                        continue
                    finish = choice.get('finish_reason')
                    if finish:
                        if finish not in ('stop', 'tool_calls'):
                            raise ValueError('模型输出未完整结束')
                        finished = True
                    delta = choice.get('delta') or {}
                    if delta.get('content'):
                        content.append(delta['content'])
                        on_delta(delta['content'])
                    if delta.get('reasoning_content'):
                        reasoning.append(delta['reasoning_content'])
                    for part in delta.get('tool_calls') or []:
                        call = calls.setdefault(part['index'], {'id': '', 'type': 'function',
                                                               'function': {'name': '', 'arguments': ''}})
                        call['id'] += part.get('id') or ''
                        for key in ('name', 'arguments'):
                            call['function'][key] += (part.get('function') or {}).get(key) or ''
        if not finished:
            raise ValueError('模型流意外中断')
        result = self._normalize({'content': ''.join(content), 'tool_calls': [calls[i] for i in sorted(calls)]})
        if reasoning:
            result['reasoning_content'] = ''.join(reasoning)
        result['usage'] = usage
        return result

    @staticmethod
    def _to_openai_messages(messages: list[dict]) -> list[dict]:
        result = []
        for message in messages:
            role = message["role"]
            item = {"role": role, "content": message.get("content", "")}
            if role == "assistant" and "reasoning_content" in message:
                item["reasoning_content"] = message["reasoning_content"]
            if role == "tool":
                item["tool_call_id"] = message["tool_call_id"]
            elif role == "assistant" and message.get("tool_calls"):
                item["content"] = item["content"] or None
                item["tool_calls"] = [{"id": call["id"], "type": "function", "function": {
                    "name": call["name"], "arguments": call["arguments"] if isinstance(call["arguments"], str)
                    else json.dumps(call["arguments"], ensure_ascii=False),
                }} for call in message["tool_calls"]]
            result.append(item)
        return result

    @staticmethod
    def _normalize(message: dict) -> dict:
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            # 保留原始 JSON 字符串，由主循环校验，不能静默变成空参数。
            calls.append({"id": call.get("id"), "name": function.get("name", ""),
                          "arguments": function.get("arguments", "{}")})
        result = {"role": "assistant", "content": message.get("content") or "", "tool_calls": calls}
        if "reasoning_content" in message:
            result["reasoning_content"] = message["reasoning_content"]
        return result

    def close(self) -> None:
        self._client.close()


DeepSeekBackend = ChatBackend

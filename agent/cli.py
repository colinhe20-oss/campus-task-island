"""最小命令行入口：真实模型 / 离线自检 / JSONL 事件。"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from backend.fake_backend import FakeBackend
from tools.base import build_default_registry
from .loop import AgentLoop


def selfcheck() -> str:
    with tempfile.TemporaryDirectory(prefix="agent1-check-") as directory:
        backend = FakeBackend([
            {"content": "", "tool_calls": [{"name": "write", "arguments": {
                "path": "hello.txt", "content": "校园任务岛\n"}}]},
            {"content": "", "tool_calls": [{"name": "read", "arguments": {"path": "hello.txt"}}]},
            {"content": "自检完成", "tool_calls": []},
        ])
        agent = AgentLoop(backend, build_default_registry(directory), auto_approve=True)
        answer = agent.run("写入文件，再读取并确认结果")
        assert Path(directory, "hello.txt").read_text(encoding="utf-8") == "校园任务岛\n"
        assert "校园任务岛" in backend.requests[-1]["messages"][-1]["content"]
        assert answer == "自检完成"
    return "PASS：离线模型 → write → read → 工具结果回填 → 最终答复"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent1 最小工具调用骨架")
    parser.add_argument("task", nargs="?")
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--campus", action="store_true", help="校园模式：只注册 search_tasks")
    parser.add_argument("--campus-db", type=Path, help="校园数据库路径，默认 .runtime/campus.sqlite3")
    parser.add_argument("--keyword", default="", help="离线校园演示的搜索关键词")
    parser.add_argument("--enable-shell", action="store_true")
    parser.add_argument("--auto-approve", action="store_true", help="自动批准已注册工具，只用于受控本地任务")
    parser.add_argument("--trace", type=Path, help="保存 JSONL 事件（可能包含任务与文件内容）")
    args = parser.parse_args(argv)
    backend = None
    trace = None
    try:
        if args.selfcheck:
            print(selfcheck())
            return 0
        if not args.task:
            parser.error("请提供任务，或使用 --selfcheck")
        from .prompts import SYSTEM_PROMPT
        prompt = SYSTEM_PROMPT
        if args.campus:
            if args.enable_shell:
                parser.error("校园模式不注册 Shell")
            from campus.db import Database, configured_db_path
            from campus.service import TaskService
            from tools.campus import CAMPUS_PROMPT, build_campus_registry
            service = TaskService(Database(args.campus_db or configured_db_path()))
            service.initialize()
            registry = build_campus_registry(service)
            prompt = CAMPUS_PROMPT
        else:
            if args.campus_db:
                parser.error("--campus-db 需要 --campus")
            registry = build_default_registry(args.workdir, enable_shell=args.enable_shell)
        if args.offline:
            if args.campus:
                backend = FakeBackend([
                    {"content": "", "tool_calls": [{"name": "search_tasks", "arguments": {"keyword": args.keyword}}]},
                ])
            else:
                backend = FakeBackend()
        else:
            from backend.client import ChatBackend
            backend = ChatBackend()
        if args.trace:
            args.trace.parent.mkdir(parents=True, exist_ok=True)
            trace = args.trace.open("w", encoding="utf-8")

        def emit(kind: str, data: dict) -> None:
            if trace:
                trace.write(json.dumps({"type": kind, "data": data}, ensure_ascii=False) + "\n")
                trace.flush()

        def confirm(name: str, arguments: dict) -> bool:
            if not sys.stdin.isatty():
                return False
            print(f"工具请求：{name} {json.dumps(arguments, ensure_ascii=False)}", file=sys.stderr)
            return input("允许执行？[y/N] ").strip().lower() == "y"

        agent = AgentLoop(backend, registry, system_prompt=prompt, max_turns=args.max_turns,
                          auto_approve=args.auto_approve, confirm_callback=confirm, event_callback=emit)
        answer = agent.run(args.task)
        if args.campus and args.offline:
            print("[离线工具演示，未调用真实模型]")
            for message in agent.messages:
                if message["role"] == "tool":
                    print(message["content"])
        else:
            print(answer)
        return 0
    except KeyboardInterrupt:
        print("任务已中断", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if trace:
            trace.close()
        if backend and hasattr(backend, "close"):
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())

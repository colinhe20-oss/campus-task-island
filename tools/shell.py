"""可选 Shell；有工作目录和超时，但不是操作系统沙箱。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .base import Tool


def build_shell_tool(workdir: str | Path) -> Tool:
    root = Path(workdir).resolve()

    def execute(command: str, timeout: int = 30) -> str:
        if not command.strip() or not 1 <= timeout <= 120:
            raise ValueError("命令不能为空，timeout 应在 1~120 秒")
        argv = (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
                if os.name == "nt" else ["bash", "-c", command])
        result = subprocess.run(argv, cwd=root, capture_output=True, text=True,
                                errors="replace", timeout=timeout)
        return f"exit_code={result.returncode}\n{result.stdout}\n[stderr]\n{result.stderr}"

    return Tool("bash", "执行命令：Windows 用 PowerShell，Linux 用 bash；不提供系统隔离。", {
        "type": "object", "properties": {
            "command": {"type": "string", "minLength": 1},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 120},
        }, "required": ["command"], "additionalProperties": False,
    }, execute, requires_confirmation=True)

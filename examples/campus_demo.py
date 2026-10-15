"""真实 HTTP 进程验收：发布 → 查询 → 重启 → Agent 工具查询。

使用临时数据库，关闭后自动删除，不污染用户任务数据，不调用远端模型。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from agent.loop import AgentLoop
from backend.fake_backend import FakeBackend
from campus.db import Database
from campus.service import TaskService
from tools.campus import CAMPUS_PROMPT, build_campus_registry


def start_server(db_path: Path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    environment = os.environ.copy()
    environment["CAMPUS_DB_PATH"] = str(db_path)
    process = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "campus.app:app", "--host", "127.0.0.1",
        "--port", str(port), "--log-level", "error",
    ], cwd=Path(__file__).resolve().parents[1], env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("API 进程启动失败")
                try:
                    if client.get(url + "/api/health").status_code == 200:
                        return process, url
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
        raise RuntimeError("API 启动超时")
    except BaseException:
        stop_server(process)
        raise


def stop_server(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main():
    with tempfile.TemporaryDirectory(prefix="campus-demo-") as directory:
        db_path = Path(directory) / "campus.sqlite3"
        process, url = start_server(db_path)
        try:
            with httpx.Client(base_url=url, trust_env=False) as client:
                accounts=json.loads(db_path.with_suffix('.accounts.json').read_text(encoding='utf-8'))
                login=client.post('/api/auth/login',json={'username':'publisher','password':accounts['publisher']['password']})
                login.raise_for_status()
                response = client.post("/api/tasks", json={
                    "title": "【演示】校园活动摄影", "category": "creative",
                    "description": "为社团活动拍摄照片", "completion_criteria": "交付 10 张照片",
                    "reward_type":"mutual","location":"学生活动中心","deadline":"2099-10-20T18:00:00+08:00",
                })
                response.raise_for_status()
                created = response.json()
                result = client.get("/api/tasks", params={"keyword": "摄影"})
                result.raise_for_status()
                assert result.json()["items"][0]["id"] == created["id"]
            print("PASS：HTTP 发布与关键词查询")
        finally:
            stop_server(process)
        process, url = start_server(db_path)
        try:
            with httpx.Client(base_url=url, trust_env=False) as client:
                response = client.get("/api/tasks/" + created["id"])
                response.raise_for_status()
                assert response.json() == created
            print("PASS：服务进程重启后数据保留")
        finally:
            stop_server(process)
        backend = FakeBackend([
            {"tool_calls": [{"name": "search_tasks", "arguments": {"keyword": "摄影"}}]},
            {"content": "查询完成"},
        ])
        agent = AgentLoop(backend, build_campus_registry(TaskService(Database(db_path))),
                          system_prompt=CAMPUS_PROMPT)
        agent.run("找一个摄影任务")
        result = json.loads(backend.requests[-1]["messages"][-1]["content"])
        assert result["items"][0]["id"] == created["id"]
        print("PASS：Agent 工具读取同一数据库并回填真实任务 ID")
        print("上述为本地示例数据和离线模型，不代表真实学生任务或远端模型验证。")


if __name__ == "__main__":
    main()

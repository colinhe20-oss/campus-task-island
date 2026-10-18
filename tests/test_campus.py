from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient

from agent.cli import main
from agent.loop import AgentLoop
from backend.fake_backend import FakeBackend
from app_factory import create_app
from campus.db import Database
from campus.schemas import MAX_TASK_OFFSET, TaskCreate
from campus.service import TaskService
from tools.campus import CAMPUS_PROMPT, build_campus_registry


class LoggedInClient(TestClient):
    def __enter__(self):
        super().__enter__()
        accounts = json.loads(self.app.state.auth_service.accounts_path.read_text(encoding='utf-8'))
        response = self.post('/api/auth/login',json={'username':'publisher','password':accounts['publisher']['password']})
        assert response.status_code == 200
        return self


def payload(title="校园活动摄影", **changes):
    result = {"title": title, "category": "creative", "description": "需要拍摄社团活动照片",
              "completion_criteria": "交付 10 张清晰照片", "location": "学生活动中心",
              "deadline": "2099-10-20T18:00:00+08:00", "reward": "互助", "reward_type":"mutual"}
    result.update(changes)
    return result


class CampusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "campus.sqlite3"

    def test_publish_get_filter_and_restart(self):
        with LoggedInClient(create_app(self.db_path)) as client:
            response = client.post("/api/tasks", json=payload())
            self.assertEqual(response.status_code, 201)
            created = response.json()
            task_id = created["id"]
            self.assertEqual(created["status"], "published")
            self.assertEqual({k:v for k,v in client.get(f"/api/tasks/{task_id}").json().items() if k!="server_time"},{k:v for k,v in created.items() if k!="server_time"})
            self.assertEqual(client.get("/api/tasks", params={"keyword": "摄影", "category": "creative"}).json()["total"], 1)
            self.assertEqual(client.get("/api/tasks", params={"category": "daily"}).json()["total"], 0)
            self.assertEqual(client.get("/api/tasks", params={"keyword": "不存在"}).json()["items"], [])
        with LoggedInClient(create_app(self.db_path)) as restarted:
            self.assertEqual({k:v for k,v in restarted.get(f"/api/tasks/{task_id}").json().items() if k!="server_time"},{k:v for k,v in created.items() if k!="server_time"})
            self.assertEqual(restarted.get("/api/tasks").json()["total"], 1)

    def test_invalid_input_never_creates_task(self):
        invalid = [payload(title="  "), payload(category="other"), payload(description=""),
                   payload(deadline="2099-10-20T18:00:00"), payload(status="completed"),
                   payload(completion_criteria=""), payload(location="  ")]
        with LoggedInClient(create_app(self.db_path)) as client:
            for body in invalid:
                with self.subTest(body=body):
                    self.assertEqual(client.post("/api/tasks", json=body).status_code, 422)
            self.assertEqual(client.get("/api/tasks").json()["total"], 0)
            self.assertEqual(client.get("/api/tasks/missing").status_code, 404)
            for params in [{"limit": 0}, {"limit": 51}, {"offset": -1}, {"category": "other"}]:
                self.assertEqual(client.get("/api/tasks", params=params).status_code, 422)

    def test_literal_wildcards_and_sql_injection(self):
        with LoggedInClient(create_app(self.db_path)) as client:
            client.post("/api/tasks", json=payload(title="100%_摄影"))
            client.post("/api/tasks", json=payload(title="普通摄影"))
            for keyword, expected in [("%_", 1), ("' OR 1=1 --", 0), ("摄影", 2)]:
                response = client.get("/api/tasks", params={"keyword": keyword})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["total"], expected)

    def test_pagination_and_concurrent_creation(self):
        service = TaskService(Database(self.db_path))
        service.initialize()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: service.create_task(TaskCreate(**payload(title=f"任务{i}"))), range(12)))
        self.assertEqual(len({task.id for task in results}), 12)
        first = service.search_tasks(limit=5)
        second = service.search_tasks(limit=5, offset=5)
        self.assertEqual(first.total, 12)
        self.assertEqual(len(first.items), 5)
        self.assertFalse({task.id for task in first.items} & {task.id for task in second.items})

    def test_agent_reads_same_database_as_api(self):
        with LoggedInClient(create_app(self.db_path)) as client:
            created = client.post("/api/tasks", json=payload()).json()
            service = TaskService(Database(self.db_path))
            registry = build_campus_registry(service)
            self.assertEqual(registry.names(), ["search_tasks"])
            self.assertFalse(registry.get("search_tasks").requires_confirmation)
            backend = FakeBackend([
                {"tool_calls": [{"name": "search_tasks", "arguments": {"keyword": "摄影"}}]},
                {"content": "查询完成"},
            ])
            agent = AgentLoop(backend, registry, system_prompt=CAMPUS_PROMPT)
            self.assertEqual(agent.run("找一个摄影任务"), "查询完成")
            observation = json.loads(backend.requests[-1]["messages"][-1]["content"])
            self.assertEqual(observation["items"][0]["id"], created["id"])
            self.assertEqual(observation["items"][0]["title"], created["title"])
            self.assertTrue(observation["data_is_untrusted"])
            self.assertEqual(client.get("/api/tasks").json()["total"], 1)

    def test_campus_offline_cli_uses_database(self):
        service = TaskService(Database(self.db_path))
        service.initialize()
        task = service.create_task(TaskCreate(**payload()))
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["找摄影任务", "--campus", "--offline", "--keyword", "摄影",
                         "--campus-db", str(self.db_path)])
        self.assertEqual(code, 0)
        self.assertIn(task.id, stdout.getvalue())
        self.assertIn("校园活动摄影", stdout.getvalue())

    def test_large_tool_results_remain_valid_json(self):
        service = TaskService(Database(self.db_path))
        service.initialize()
        for i in range(5):
            service.create_task(TaskCreate(**payload(title="摄影" + "长" * 95,
                description="长" * 4000, completion_criteria="长" * 2000,
                reward="长" * 500, location="长" * 200)))
        observation = build_campus_registry(service).get("search_tasks").invoke({})
        self.assertLess(len(observation), 12000)
        result = json.loads(observation)
        self.assertEqual(len(result["items"]), 5)
        self.assertTrue(all(item["preview_truncated"] for item in result["items"]))

    def test_offset_integer_overflow_is_rejected(self):
        with LoggedInClient(create_app(self.db_path)) as client:
            for offset in [MAX_TASK_OFFSET + 1, 2 ** 100]:
                with self.subTest(offset=offset):
                    response = client.get("/api/tasks", params={"offset": offset})
                    self.assertEqual(response.status_code, 422)
            self.assertEqual(client.get("/api/tasks", params={"offset": MAX_TASK_OFFSET}).status_code, 200)
            service = client.app.state.task_service
            with self.assertRaises(ValueError):
                service.search_tasks(offset=2 ** 100)
            from jsonschema.exceptions import ValidationError
            with self.assertRaises(ValidationError):
                build_campus_registry(service).get("search_tasks").invoke({"offset": 2 ** 100})


if __name__ == "__main__":
    unittest.main()

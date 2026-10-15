# 校园任务第一轮实现

目前已实现发布、查询、申请接取、成果提交、验收、SQLite 持久化和本地账号登录，以及 Agent 的 search_tasks 查询工具。HTTP 和 Agent 共用 campus/service.py。前端见 [前端说明](FRONTEND.md)，账号及协作见 [任务协作说明](COLLABORATION.md)。

## 启动本地服务

```powershell
Set-Location (git rev-parse --show-toplevel)
.\.venv\Scripts\python.exe -m uvicorn campus.app:app --host 127.0.0.1 --port 8000
```

访问 http://127.0.0.1:8000/docs 使用交互 API 文档。已实现本地账号和任务权限，服务默认绑定回环地址用于开发。

发布时展开“任务发布”分组中绿色的 `POST /api/tasks 发布任务（提交 JSON）`，点击 Try it out，在 Request body 中编辑示例并 Execute。示例与 examples/task-create.json 一致，可直接提交。蓝色的 `GET /api/tasks 查询任务列表` 只提供 keyword、category、limit、offset 筛选框，不是发布入口。

默认数据库为 项目根目录下 `.runtime/campus.sqlite3`，不随启动位置改变。API 启动和 CLI 校园模式首次运行会自动建表。可通过 CAMPUS_DB_PATH 环境变量指定其他文件；CLI 的 --campus-db 参数优先于该变量。二者指向同一文件时查询结果一致。

## 发布并查询

在第二个 PowerShell 窗口执行（使用示例数据，按需改成自己的需求）：

```powershell
$accounts = Get-Content .\.runtime\campus.accounts.json -Encoding utf8 | ConvertFrom-Json
$loginBody = @{ username = 'publisher'; password = $accounts.publisher.password } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/auth/login' `
    -ContentType 'application/json' -Body $loginBody -SessionVariable campusSession

$body = @{
    title = '【演示】校园活动摄影'
    category = 'creative'
    description = '希望找同学协助拍摄社团活动照片'
    completion_criteria = '交付 10 张清晰照片'
    location = '学生活动中心'
    deadline = '2026-10-20T18:00:00+08:00'
    reward = '互助'
} | ConvertTo-Json

$created = Invoke-RestMethod -Method Post `
    -Uri 'http://127.0.0.1:8000/api/tasks' `
    -ContentType 'application/json; charset=utf-8' `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -WebSession $campusSession
$created

$keyword = [Uri]::EscapeDataString('摄影')
Invoke-RestMethod "http://127.0.0.1:8000/api/tasks?keyword=$keyword"
Invoke-RestMethod "http://127.0.0.1:8000/api/tasks/$($created.id)"
```

POST 成功返回 201 和任务 ID；详情不存在返回 404，输入不符合契约返回 422。可在服务窗口 Ctrl+C 停止，然后用同一启动命令重启，再查询任务 ID 验证保存结果。

## API 契约

| 接口 | 参数 | 返回 |
|---|---|---|
| POST /api/tasks | title、category、description、completion_criteria、location、deadline 必填；reward 可选 | 完整任务，初始状态 published |
| POST /api/tasks/{id}/withdraw | 登录发布者操作，只能下架未接取任务 | 任务状态 withdrawn，保留记录 |
| GET /api/tasks | keyword、category、status、limit 1~50、offset ≥0 | items、total、limit、offset |
| GET /api/tasks/{id} | 任务 ID | 完整任务 |
| GET /api/health | 无 | status=ok |

category 枚举：learning 学习交流、creative 创作协作、music 音乐兴趣、daily 生活互助。location 和 deadline 必填；deadline 必须带时区，例如 2026-10-20T18:00:00+08:00。列表按创建时间降序；keyword 在标题、描述和完成标准中做文本包含查询，% 和 _ 当作文字。服务不会自动写入演示数据。

未指定 status 时，列表和搜索隐藏已完成与已下架任务，分页总数同步排除。历史记录仍可通过详情、“我的任务”或显式 status=completed / withdrawn 查询，不删除数据库记录。

offset 超出允许的整数范围时返回 422，不进入数据库查询。当前 POST 每次成功请求都会创建一条新任务，尚未实现重复提交保护；再次点击 Execute 会再次发布。现有内容相同的任务不自动合并，以免误删用户有意创建的记录。

## Agent 查询

在配置了模型环境变量的 PowerShell 窗口执行：

```powershell
.\.venv\Scripts\python.exe -m agent.cli '找一个摄影任务' --campus --trace .\traces\campus.jsonl
```

校园模式仅暴露 search_tasks，查询无需写操作确认。每次最多返回 5 项，长描述和要求会缩短并标注 preview_truncated，完整信息通过任务详情 API 查看。Agent 不自动发布或报名。

不用模型验证真实数据库查询：

```powershell
.\.venv\Scripts\python.exe -m agent.cli '查询摄影任务' --campus --offline --keyword '摄影'
```

离线模式使用脚本调用 search_tasks，并打印数据库返回值，不模拟模型理解自然语言的能力；搜索词使用 --keyword 指定。

## 完整进程自检

```powershell
.\.venv\Scripts\python.exe -m examples.campus_demo
```

该示例自动启动本地 HTTP 服务，发布演示任务、查询、停止进程、重启后查详情，再让离线 Agent 从同一数据库查询。使用临时目录，执行结束后清理临时数据库与服务进程，不污染实际任务数据。

## 截止与回报规则更新

普通任务已增加截止控制、最小双方延期和有偿任务线下结算确认；新发布需明确回报类型，旧回报文字不推断分类。详见 [TERMS.md](TERMS.md)。

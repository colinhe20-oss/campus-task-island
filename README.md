# 校园任务岛

校园任务岛是一个面向校园互助与参与记录的全栈应用。它把普通任务、综素活动、志愿服务和校园发现放在同一个界面中，但四类内容各自使用独立的业务规则、数据和页面。引航员可以基于登录用户有权访问的真实数据回答问题，并协助整理普通任务发布草稿。

本文件说明项目由哪些部分组成、请求如何流转、各模块的边界以及如何运行。面向网页使用者的操作步骤见[界面使用说明](docs/USAGE.md)。

## 功能范围

| 模块 | 当前能力 | 关键边界 |
|---|---|---|
| 普通任务 | 发布、直接接取或申请后确认、阶段协作、成果验收、截止与逾期、双方约定变更、暂停／恢复／取消、有偿约定及线下结算确认 | 一项任务一位接取者；平台不处理支付、不代替双方确认线下付款 |
| 综素活动 | 定时开放、限额报名、审核、候补与递补、个人报名和负责人名单管理 | 报名成功不等于获得正式综素认定；不包含签到或学校认定对接 |
| 志愿服务 | 分岗位报名、审核与候补、参与登记、服务分钟数及小时核验、个人记录 | 活动方确认不等于学校正式认定；没有线上签到签退 |
| 校园发现 | 图文发布、评论补充、发布者更新状态、编辑／撤回和历史 | 状态为发布者自报；平台不提供工作人员认证、紧急事件处置或内容审核工作台 |
| 首页与消息 | 四类内容入口、个人待办、完成协作数、持久站内消息、已读管理 | 只记录上线后的消息；没有邮件、浏览器推送、私聊或定时提醒 |
| 引航员 | 普通任务草稿与阶段建议；只读查询四类内容、个人报名／记录和跨板块概览；运行记录、流式进度与取消 | 写操作需用户在网页确认；活动、志愿与校园发现没有 AI 写入工具；不读取或标记消息 |
| 账号 | 公开注册普通账号、本人注销、未完成事项拦截、历史匿名保留、主机端密码重置 | 有效登录账号可发布四类内容；注销不可恢复，用户名永久保留 |

## 系统构成

```mermaid
flowchart LR
    U["使用者"] --> UI["React + TypeScript 网页"]
    UI -->|"同源 HTTP /api"| API["FastAPI 路由与会话鉴权"]
    API --> AUTH["登录与权限"]
    API --> SVC["业务服务层"]
    SVC --> DB[("SQLite 数据库")]
    SVC --> MEDIA["受控发现图片存储"]
    SVC --> MSG["消息与首页摘要"]
    MSG --> DB
    API --> GUIDE["引航员服务"]
    GUIDE --> LOOP["AgentLoop 主循环"]
    LOOP <--> MODEL["配置的 LLM 后端"]
    LOOP --> REG["按用户会话注册的工具"]
    REG --> SVC
    REG --> DB
    SK["skills / mcp 目录（当前未启用）"] -.-> LOOP
```

普通网页和引航员工具都通过业务服务读取或修改校园业务数据。服务层负责权限、状态规则、事务和通知，路由层负责 HTTP 输入输出；模型不会直接访问数据库，也不能通过工具参数伪造当前用户身份。

### 关键请求流程

普通页面请求：

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as React 页面
    participant Route as FastAPI 路由
    participant Service as 业务服务
    participant DB as SQLite
    User->>Web: 浏览、发布或执行协作操作
    Web->>Route: 同源 /api 请求 + 登录会话
    Route->>Service: 校验输入、绑定会话用户
    Service->>DB: 检查状态与权限，在事务中写入
    Service->>DB: 同事务写入消息／历史（适用时）
    DB-->>Service: 提交结果
    Service-->>Route: 业务结果
    Route-->>Web: JSON 响应
    Web-->>User: 更新页面或显示错误与重试
```

引航员对话与普通任务草稿：

```mermaid
flowchart TD
    A["用户在引航员页面提问"] --> B["GuideService 绑定会话身份并组装提示"]
    B --> C["AgentLoop 请求模型"]
    C --> D{"模型返回工具调用吗？"}
    D -->|否| H["整理回复、引用与运行记录"]
    D -->|是| E["ToolRegistry 校验名称和参数"]
    E --> F["工具调用已有服务，按会话权限读取或形成草稿"]
    F --> G["工具结果作为观察返回主循环"]
    G --> C
    H --> I["网页显示答案、引用、运行状态"]
    F -.-> J["网页展示普通任务草稿与版本"]
    J --> K{"用户在网页确认发布吗？"}
    K -->|否| L["草稿保留或取消，不创建任务"]
    K -->|是| M["服务端重新校验并发布"]
```

AgentLoop 负责有限轮次的模型与工具调用、运行预算、取消和进度事件；GuideService 负责用户上下文、工具注册、提示及业务集成。只读工具复用任务、活动、志愿、发现和首页服务。草稿工具只整理待确认内容；最终发布走独立的网页确认接口和普通任务服务。

## 代码目录

| 路径 | 职责 |
|---|---|
| `campus/app.py` | 创建 FastAPI 应用、服务实例和路由；连接前端静态页面与 API |
| `campus/auth.py` | 登录会话、用户身份与访问控制基础 |
| `campus/service.py` | 普通任务主服务：发布、申请／接取、协作控制及业务事务 |
| `campus/stages.py`、`campus/terms.py`、`campus/changes.py` | 阶段协作、有效约定及双方变更申请 |
| `campus/activities.py`、`campus/activity_api.py` | 综素活动业务与接口 |
| `campus/volunteers.py`、`campus/volunteer_api.py` | 志愿服务、岗位报名及小时记录 |
| `campus/discoveries.py`、`campus/discovery_api.py` | 校园发现、评论、状态、图片和历史 |
| `campus/home.py`、`campus/home_api.py`、`campus/notifications.py` | 个人待办、首页摘要和站内消息 |
| `campus/guide.py`、`campus/drafts.py`、`campus/runs.py` | 引航员编排、草稿、运行记录和流式接口 |
| `agent/loop.py`、`agent/context.py`、`agent/prompts.py` | 与校园领域解耦的 Agent 主循环及上下文基础 |
| `backend/client.py` | LLM 后端客户端；支持真实后端和测试用后端 |
| `tools/base.py`、`tools/campus.py`、`tools/drafts.py`、`tools/stages.py` | 工具协议、校园只读工具、草稿和阶段建议工具 |
| `tools/fs.py`、`tools/shell.py` | 从 mini-openclaw 骨干保留的通用文件／命令工具；校园网页引航员不因此获得任意系统访问权 |
| `skills/`、`mcp/` | 后续扩展预留；当前本项目的校园引航员流程未启用 |
| `web/src/` | React + TypeScript 页面、路由、API 客户端、样式与交互 |
| `tests/` | 后端业务、权限、事务和引航员测试 |
| `examples/` | 临时数据库演示、离线评测和验收脚本 |
| `docs/` | 分主题的业务规则、架构细节、验收记录与使用说明 |
| `.runtime/` | 本地数据库、账户配置、媒体、测试报告和备份等运行数据；不要提交密钥或真实用户数据 |

## 数据与安全边界

- SQLite 是当前业务持久化层。应用启动时初始化／迁移新增结构；修改正式数据库前应先备份，并核对迁移结果。
- 网页默认同源访问 API。写接口从登录会话确定操作者；前端按钮隐藏不代替后端鉴权。
- 报名、接取、审批、变更等并发敏感操作在服务层事务中重新检查状态。需要通知的业务会把业务变化与消息放在同一事务中提交。
- 个人申请内容、协作记录、报名名单和小时记录按参与者／负责人权限返回。校园发现图片通过受控接口读取，不直接暴露整个存储目录。
- 引航员个人工具由当前会话绑定用户；校园发现工具遵守同一可见性规则。模型输入中的用户内容按不可信数据处理。
- LLM 凭据和运行配置保存在本机 `.env`，参考 `.env.example`；不要把 `.env`、访问令牌、用户密码或真实业务数据提交到版本库或写入公开文档。

## 启动与开发

### 在新电脑上安装

Git 仓库只保存源码和依赖清单，不包含数据库、账号文件、图片、模型密钥或旧电脑的运行数据。克隆后每台主机都会创建自己的本地数据；要让多台电脑看到同一份校园数据，只启动一台主机，其他电脑用浏览器连接主机地址。

Windows（项目在 Windows + Python 3.13 下验证）：

```powershell
git clone <仓库地址>
Set-Location <克隆后的项目目录>
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-tested-windows-py313.txt
Push-Location .\web
npm.cmd ci
npm.cmd run build
Pop-Location
Copy-Item .env.example .env
```

如果系统的 Python 启动器无法识别 `py -3.13`，先安装 Python 3.13 并启用 PATH，或用 `python` 创建虚拟环境。若暂时不需要引航员模型，把 `.env` 中的 `LLM_API_KEY` 留空即可；需要模型时，填入自己的服务商密钥。每位开发者使用自己的密钥，不要在聊天、仓库或截图中共享。

Ubuntu 的开发依赖是 Python 3.13、Node.js/npm 和 Git。安装同样的 Python 依赖并构建前端：

```bash
git clone <仓库地址>
cd <克隆后的项目目录>
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..
cp .env.example .env
```

Windows 的局域网启动脚本是 PowerShell 专用；Ubuntu 可在项目根目录运行 `.venv/bin/python -m uvicorn campus.app:app --host 0.0.0.0 --port 8000`，并按主机防火墙发行版配置仅限可信局域网的 TCP 8000 入站规则。Ubuntu 启动流程尚未经过本项目的完整双机验收。

### 在主机电脑启动应用

在项目根目录启动单实例服务。Windows 本机开发可监听回环地址：

```powershell
.\.venv\Scripts\python.exe -m uvicorn campus.app:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>。API 文档位于 <http://127.0.0.1:8000/docs>。生产构建后的前端由 FastAPI 同源提供，通常不需要另开前端服务。若 8000 端口已被占用，先在原服务终端按 `Ctrl+C` 停止它，再启动新实例；不要启动多个服务指向不同数据库。

### 同一局域网内多人访问

Windows 项目根目录提供 `start_lan.ps1`。仅在可信的专用网络主机上运行；脚本会显示本机局域网地址并监听网络接口。执行策略默认阻止未签名脚本时，可仅对当前 PowerShell 进程临时放行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\start_lan.ps1
```

若在管理员权限终端操作，可按需为 Windows 专用网络放行 TCP 8000。第二台及后续电脑不需要克隆仓库、安装 Python/Node 或启动服务，只需在浏览器输入脚本显示的 `http://局域网地址:8000/`。所有人通过同一主机和本机 SQLite 数据库访问，因此主机必须保持开机、服务终端保持运行；访客 Wi-Fi 的设备隔离也会阻断访问。详细双机验收、防火墙和故障排查步骤见[界面使用说明](docs/USAGE.md#双电脑局域网验收)。该方式仅适用于可信局域网演示，不是公网部署方案。

开发前端时另开终端：

```powershell
Set-Location .\web
npm.cmd ci
npm.cmd run dev
```

Vite 默认页面为 <http://127.0.0.1:5173/>，需要同时运行 8000 端口的后端；开发代理会把 `/api` 请求转发给后端。生产构建：`npm.cmd run build`。

### 测试

```powershell
Set-Location (git rev-parse --show-toplevel)
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
npm.cmd --prefix web run build
```

演示与离线评测脚本见 `examples/`。优先使用脚本创建的临时数据库和测试账号；不要用正式数据库做破坏性验收。引航员真实模型调用需先在本地 `.env` 配置兼容的模型地址、名称和密钥。

## 文档图示约定

新增或修改 Mermaid 图时，节点文字一律放进带引号的标签（例如 `A["节点说明"]`），分支连线使用管道格式（例如 `A -->|是| B`），避免把中文标点或自由文本直接写在连线语法中。提交前检查每个 Mermaid 代码块是否有配对围栏，并在目标 Markdown 查看器中确认能够渲染；若无法确认渲染器版本，优先使用简单语法或纯文本流程图，避免出现源码框和语法错误。

## 分主题文档

| 文档 | 内容 |
|---|---|
| [界面使用说明](docs/USAGE.md) | 登录、四类页面、发布和参与、个人空间、消息与引航员操作 |
| [校园业务概览](docs/CAMPUS.md) | 项目目标与内容类型 |
| [普通任务协作](docs/COLLABORATION.md)、[阶段安排](docs/STAGES.md) | 接取、协作、成果和阶段规则 |
| [截止、回报与结算](docs/TERMS.md)、[双方变更申请](docs/CHANGES.md) | 约定版本、截止处理、支付记录和协作控制 |
| [综素活动](docs/ACTIVITIES.md)、[志愿服务](docs/VOLUNTEERS.md) | 报名、候补、岗位和小时核验规则 |
| [校园发现](docs/DISCOVERIES.md) | 发布、评论、状态、图片及隐私 |
| [首页与消息](docs/HOME_MESSAGES.md) | 待办、消息与去重规则 |
| [引航员](docs/GUIDE.md)、[Agent 运行机制](docs/AGENT_RUNTIME.md) | 工具、草稿、运行记录、流式反馈和取消 |
| [前端开发说明](docs/FRONTEND.md)、[接取方式](docs/ACCEPTANCE.md) | 前端开发与普通任务接取配置 |


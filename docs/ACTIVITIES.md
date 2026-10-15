# 综素活动报名

普通任务继续使用 `/#/tasks`，独立综素活动入口为 `/#/activities`，详情为 `/#/activities/{id}`。两类发布统一从左侧“发布任务”（`/#/tasks/new`）先选择种类，再进入普通任务（`?type=ordinary`）或综素活动（`?type=activity`）表单。所有有效登录账号都可发布。旧 `/#/activities/new` 链接保持可访问，两类表单均可返回重新选择种类。侧栏“我的空间”保留任务协作，新增“我的报名”和“我发布的活动”。认定标签为二课分、美育分、形策二分，不使用普通任务分类。

## 发布与权限

所有有效登录账号都可发布综素活动。登录及 `/api/auth/me` 对有效账号返回 `can_publish_activities: true`；服务层发布接口仍校验账号有效，管理接口检查活动 `owner_id`。旧数据库中的 `activity_permissions` 和 `activity_bootstrap` 表保留作历史兼容，不再决定发布权限。发布者填写的认定说明属于活动方自报，不代表学校身份认证或正式认定。

活动标题、说明、地点、参与条件、组织方、来源、联系渠道、认定标签与说明、四个时间、名额和报名方式均必填。接口使用带时区的 ISO 8601 时间，数据库统一 UTC，网页填写和展示北京时间。要求 `opens_at < closes_at <= starts_at < ends_at`，开始时间晚于当前时间，名额为正整数。发布后没有修改时间、名额或方式的接口。负责人在活动结束前可填写原因取消整场活动，保留历史，不能恢复。

本站记录活动方公布的认定说明。报名成功不生成学分或正式认定结果。

## 状态与事务

| 场景 | 结果 |
|---|---|
| 直接报名、有空位 | `registered`，报名成功 |
| 直接报名、满额 | `waitlisted`，候补 |
| 审核报名 | `pending`，待审核，不占名额 |
| 通过审核 | 有空位成功，否则候补 |
| 拒绝审核 | `rejected`，理由必填 |
| 本人取消 | `cancelled`，释放名额时递补 |
| 活动开始，仍待审核或候补 | 对外显示 `not_selected`，未获名额 |
| 整场取消 | 有效记录转 `activity_cancelled`；拒绝、个人取消历史保留 |

开放窗口为 `[opens_at, closes_at)`。截止后停止新申请；审核、本人取消和递补继续到 `starts_at`，活动开始时立即停止。活动状态由服务端时间计算，没有后台定时任务。未获名额为有效展示状态，不需要启动时批量改写旧报名记录。

开始后负责人仍可取消未结束的整场活动；成功报名显示活动方取消，已经未获名额的申请保留该结果。

报名、审核、个人取消、整场取消先获取 `BEGIN IMMEDIATE` 写锁，再读取当前时间，检查权限和状态。释放名额与按 `queue_sequence` 递补在同一事务内完成；新报名和审核通过也先补入已有候补。审核模式的入队序号从通过审核并进入候补时分配，不从申请时间分配。

取消和拒绝者在截止前可重新申请，新记录保留旧尝试，重新审核或排队。部分唯一索引保证同一用户同一活动只有一条有效记录。有效报名重复请求返回原记录；取消按记录 ID 操作，重试取消旧记录不会取消新申请。操作事件按活动内递增序号保存。

## 接口

| 方法与路径 | 权限 / 用途 |
|---|---|
| GET `/api/activities?keyword=&tag=&limit=20&offset=0` | 公开列表；默认隐藏已结束或取消活动 |
| POST `/api/activities` | 有发布权限的用户 |
| GET `/api/activities/{id}` | 公共详情；登录时仅附本人最新报名 |
| POST `/api/activities/{id}/registrations` | 登录用户，负责人不能报名自己活动；body `{ "application_note": "说明" }` |
| POST `/api/registrations/{id}/review` | 所属活动负责人；body `{ "decision": "approve或reject", "reason": "理由" }` |
| POST `/api/registrations/{id}/cancel` | 报名本人，按申请 ID 操作 |
| POST `/api/activities/{id}/cancel` | 所属活动负责人；body `{ "reason": "原因" }` |
| GET `/api/activities/{id}/registrations` | 所属活动负责人，含全部尝试及操作历史 |
| GET `/api/me/registrations` | 本人每场活动最新结果及历史申请 |
| GET `/api/me/activities` | 本人发布的活动，含结束与取消记录 |

`tag` 为 `second_class` / `aesthetic` / `ideological`，发布支持多个标签。详情和列表包含 `server_time`、`next_boundary`；详情包含剩余名额及本人可执行操作。其他用户的申请说明、姓名、用户 ID 与候补位置均不返回给公众。

页面可见时每 15 秒更新，开放、截止和开始边界额外刷新；恢复页面可见时立即刷新。倒计时使用服务器时间加 `performance.now()` 的流逝时间，浏览器时钟不决定报名资格。后台刷新不清空表单；刷新失败提示当前结果可能过期，并提供重试。

## 验收

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
cd web
npm.cmd run build
```

网页验收使用临时数据库启动：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.activity_demo --port 8001
```

打开 `http://localhost:8001/#/activities`。`.runtime/activity-demo.json` 指向临时数据库、账号文件和三个测试活动；密码只从本机该账号文件读取。使用 localhost 与正式服务的 127.0.0.1 分开 Cookie。测试负责人发布，参与者申请、拒绝后重申、候补与取消递补，再查看个人历史、页面刷新及取消活动。退出服务器后临时数据库删除，不向正式库添加演示活动。

## 迁移和范围

数据库版本 6 只新增 `activity_permissions`、`activity_bootstrap`、`activities`、`activity_registrations`、`activity_events` 及其索引。上线前用 SQLite backup 保存完整数据库（含 WAL 数据），逐表核对原任务、协作、阶段、用户和引航员记录。

本模块只做综素活动站内报名及状态反馈。官方外链报名、签到、正式学分认定、消息中心、AI 活动发布继续留待后续。独立志愿服务现已实现，见 [VOLUNTEERS.md](VOLUNTEERS.md)。

## 本次验收记录（2026-10-14 至 2026-10-15）

- 全部 117 项 unittest 通过：原 85 项和新增 32 项活动测试；无跳过。覆盖开放与截止精确边界、客户端时间伪造、写锁等待后重新检查时间、并发抢最后名额、并发审核和重复报名、FIFO 递补、历史重申、旧 ID 重试、开始后未获名额及随后取消活动仍保留该结果、整场取消并发及越权。
- TypeScript 类型检查与 Vite 生产构建通过。
- 临时数据库的负责人和参与者网页验收通过；另一个参与者用于验证候补队列。实际网页完成发布、定时开放自动刷新、登录返回、直接报名、审核申请、拒绝与重新申请、通过后成功及候补、本人取消、后台轮询显示转正、历史展开、刷新恢复、负责人整场取消、已取消活动的个人记录、标签筛选、搜索空状态和详情失败重试。
- 已修复失效登录 Cookie 阻断公共活动详情的问题；公共读取退回匿名视图，私有名单和写操作仍要求有效登录。
- 正式数据库备份为 `.runtime/campus.before-activities-20261014-235338.sqlite3`。迁移至版本 6，原有 13 张表的行数及内容 SHA256 全部相同，SQLite 完整性检查和外键检查通过。原有任务 5 条、申请 2 条、普通成果 1 条、阶段成果 2 条保留，正式库未添加测试活动。核对报告位于 `.runtime/activity-migration-report.json`。
- 网页截图：[个人报名与自动转正](screenshots/activity-my-registrations.png)。

# 志愿服务：岗位报名与小时核验

## 网页入口与使用

左侧“志愿服务”打开 `/#/volunteers`；详情为 `/#/volunteers/{id}`。左侧“发布任务”选择“志愿服务”，进入 `/#/tasks/new?type=volunteer`。普通任务和综素活动的入口及接口保留。

“我的空间 → 我的报名”可切换综素活动与志愿服务，志愿报名每场展示最新结果，可展开旧岗位申请及操作历史。“我的志愿记录”展示已进入服务阶段的参与记录与最新小时合计；未来岗位的预计时段和分钟数在“我的志愿报名”查看。负责人在“我发布的活动”中切换志愿服务，进入详情管理名单和核验。

发布权限沿用数据库 `activity_permissions`，`publisher` 是本地测试活动负责人，不代表学校认证。登录信息新增 `can_publish_volunteers`，与 `can_publish_activities` 同源，撤销现有发布权限会同时取消两类发布能力。已有活动管理仍按活动 owner_id 鉴权。负责人不能报名自己发布的活动。

## 活动、岗位与报名

活动必填标题、说明、组织方、来源、联系渠道、小时认定条件、活动起止时间、报名窗口和报名方式。每场 1–30 个岗位，各自填写名称、工作内容、参与要求、地点、服务时段、名额、预计服务分钟数及预计小时说明。预计分钟数不超过岗位时段，只作预期说明，不自动转成确认小时。

API 时间必须带时区，数据库统一 UTC，网页填写及显示北京时间。岗位时段位于活动时段内，开放早于截止，截止不晚于任一岗位开始。发布时活动必须尚未开始；发布后岗位、时段、名额及报名方式不可修改。

报名规则：

- 同一用户同一活动最多一条有效报名；想换岗位，先取消原记录，再在截止前重新申请。旧记录不覆盖。
- 直接报名有空位成功，满额进入该岗位候补；审核模式说明必填，待审核不占名额，通过时成功或候补，拒绝理由必填。
- 岗位各自分配递增候补序号，审核模式从通过审核并进入候补时计序。取消释放名额和 FIFO 递补在同一写事务中完成，新报名和审核不能绕过已有候补。
- 新报名仅在 `[opens_at, closes_at)` 接受；截止后已有申请仍可审核、取消和递补，直到所报岗位开始。不同岗位的处理截止独立。
- 岗位开始后，待审核或未转正者对外显示“未获名额”，停止该岗位报名处理；这些记录不具备小时核验资格。
- 写操作先获取 `BEGIN IMMEDIATE`，再读服务端时间。有效重复报名返回原记录；跨岗位并发最多一项成功。取消按记录 ID，旧请求不会取消新记录。

列表默认隐藏结束或取消的活动，个人历史保留。页面可见时每 15 秒更新，开放、截止、各岗位起止等边界额外刷新；倒计时根据服务器时间和浏览器流逝时间展示。

## 参与与小时核验

核验资格绑定具体报名记录：岗位开始前已获得名额且没有退出，才可记录参与。候补转正保存实际获位时间，开始前退出的旧记录不可用于记时。

负责人在岗位开始后手动登记“已参与／未参与”、实际分钟数及说明；没有签到签退功能。分钟数为非负整数，不能超过已经发生的岗位服务时间；未参与必须为 0。岗位结束前可以登记参与，但不能确认小时。

岗位结束后显示待核验，负责人先登记参与，再确认分钟数。确认不超过实际分钟；零分钟必须填写不予计时原因。分钟数是存储和汇总单位，小时数仅为网页显示换算。

参与和小时修改共用递增版本：首次参与登记 version=0，后续操作提交读取到的当前 version。冲突返回 409，不覆盖其他人的修改。更正参与或已经确认的小时必须填原因，版本历史保存操作者、时间、原因和前后数据。修改参与记录清除旧确认，重新核验后才恢复统计。

个人合计仅累加各报名记录最新的活动方确认分钟数；待核验、未参与、旧版本不重复累计。学校正式认定始终为 `not_connected`、正式分钟数为 null，网页显示“尚未对接”。活动方确认不是学校正式结果，不生成官方凭证。

负责人可在活动结束前填写原因取消整场活动。取消关闭全部报名操作；已经开始并获位的岗位保留参与和核验资格，确认上限固定为截至取消时已经发生的服务时间。未开始岗位不产生核验资格，已确认的早期岗位结果保留。拒绝、本人取消及已未获名额结果保留历史。

## HTTP 接口

| 方法与路径 | 用途 |
|---|---|
| GET/POST `/api/volunteers` | 公开关键词搜索与分页／有权限负责人发布含岗位的活动 |
| GET `/api/volunteers/{id}` | 公开详情、岗位名额及服务端时间；登录时仅附本人最新报名 |
| POST `/api/volunteer-jobs/{id}/registrations` | 报名，body `{ "application_note": "说明" }` |
| POST `/api/volunteer-registrations/{id}/review` | 所属活动负责人审核，body `{ "decision": "approve或reject", "reason": "理由" }` |
| POST `/api/volunteer-registrations/{id}/cancel` | 仅报名本人取消 |
| POST `/api/volunteers/{id}/cancel` | 仅所属负责人，body `{ "reason": "原因" }` |
| GET `/api/volunteers/{id}/registrations` | 仅所属负责人，全部岗位申请、历史和本人可管理的服务记录 |
| POST `/api/volunteer-registrations/{id}/participation` | 仅所属负责人，body `{ "version": 0, "attendance": "participated或absent", "actual_minutes": 60, "description": "参与说明", "reason": "更正时必填" }` |
| POST `/api/volunteer-registrations/{id}/hours` | 仅所属负责人，body `{ "version": 1, "confirmed_minutes": 60, "reason": "0分钟或更正时必填" }` |
| GET `/api/me/volunteer-registrations` | 本人按活动聚合的最新报名和历次岗位申请 |
| GET `/api/me/volunteer-records` | 本人进入服务阶段的记录、最新确认合计及正式认定未对接标识 |
| GET `/api/me/volunteers` | 本人发布的活动，包含取消及结束记录 |

公共详情不包含他人姓名、申请、参与材料或核验历史；失效 Cookie 可匿名读公共详情。私有读写均需有效登录。引航员普通任务工具不读取志愿数据，本版仅增加三类内容区分及网页指引，没有 AI 志愿发布或核验工具。

## 测试与演示

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
cd web
npm.cmd run build
```

2026-10-15：原有 119 项及新增 32 项志愿测试，共 151 项通过；TypeScript 与生产构建通过。测试覆盖分岗位限额、重复与跨岗并发、FIFO、截止后处理及各岗位开始边界、取消并发、核验资格、分钟校验、零分钟理由、更正版本与统计、隐私和重启恢复。

临时数据库网页演示：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.volunteer_demo --port 8001
```

打开 `http://localhost:8001/#/volunteers`；使用 localhost 隔离正式服务 127.0.0.1 的 Cookie。`.runtime/volunteer-demo.json` 指向测试账号文件及独立 clock.json。该演示使用 2030-01-01 UTC 测试时间，clock.json 可由测试人员推进；正式服务不加载该时钟文件。账号密码仅在本地账号文件读取。

网页验收完成：发布两个不同时段的岗位、审核与候补转正、登录返回及刷新恢复、报名类型切换、登记60分钟／确认45分钟／更正50分钟／修改实际55分钟撤销确认／重新确认55分钟，五个版本完整保留且合计为55分钟；中途取消后另一岗位可核验已经发生的25分钟，早期岗位确认保留。截图见 [我的志愿记录](screenshots/volunteer-records.png)。

真实模型类型边界验收命令（会调用配置模型，使用临时数据库）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.guide_type_check --output .runtime/evals/volunteer-guide-real-latest.json
```

6 个场景全部通过，包括志愿发布与志愿名额／正式小时查询的页面指引，不误用普通任务草稿，原普通摄影协作仍可生成草稿。单次场景通过不代表模型永不误分类。

## 数据迁移与范围

数据库版本 7 新增 volunteer_activities、volunteer_jobs、volunteer_registrations、volunteer_participation、volunteer_record_versions、volunteer_events 及其索引，原综素活动和任务结构保留。上线前使用 SQLite backup 保存完整数据库，核对所有原表行数与内容指纹，并检查外键和数据库完整性。

本次正式库备份：`.runtime/campus.before-volunteers-20261015-010015.sqlite3`。迁移及重启后，原有18张表行数与内容 SHA256 全部一致，完整性与外键检查通过，正式库未写入演示志愿活动。报告为 `.runtime/volunteer-migration-report.json`。

暂不包含签到签退、附件、岗位调整、消息推送、学校正式认定对接、申诉及 AI 志愿业务工具。

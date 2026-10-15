# 普通任务：截止、延期、回报与线下结算

> 后续更新：协作延期已统一为双方约定变更，接取后首次阶段安排也须双方确认。当前规则、接口及兼容说明见 [统一变更申请](CHANGES.md)。


## 用户流程

新发布任务必须选择无偿互助或有偿任务，截止时间必须带时区并晚于服务端当前时间。网页按北京时间填写与展示。
有偿任务必须有固定人民币金额和说明；金额按整数分存储，网页使用精确十进制字符串转换，不用浮点计算金额。发布后回报约定不能修改。

截止后未接取任务从默认大厅移除，切换“已截止未接取”可查，详情及个人记录保留。停止新申请、直接接取及接受原申请，原申请不关闭。发布者填写原因并延长截止时间后可继续处理原申请。下架任务不会因延长而重新上架。

已接取任务截止后显示逾期，仍能提交、验收和申请整体延期。双方任一方提出新时间与原因，由另一方审批；提出者可撤销。每项任务最多一条待处理申请，确认前仍按原时间判断；整体延期不平移阶段时间，阶段独立显示逾期。完成或下架时关闭待处理申请，保留历史。

有偿任务验收完成后，发布者独立确认已付款，接取者独立确认已收款；双方都确认才显示“双方已确认结算”。可以撤销本人确认，原因必填，之后可重新确认。任务协商取消时另存取消结算金额；正金额由双方独立确认，零金额不生成付款待办。取消结算不会覆盖任务原固定报酬。每次确认变化保留前后状态、角色、时间和版本。它是双方声明，不是平台核实的真实转账；没有支付、分期、退款或凭证功能。

旧任务统一标为 legacy（历史回报未分类），保留原文字和原金额空值，不从文字推断金额、不开放结构化结算。未发布的旧草稿须补齐回报类型后才能发布。

## API 与规则

新发布示例见 `examples/task-create.json`，新增必填 reward_type（mutual / paid），有偿时 reward_amount_fen 为正整数分，reward 非空。无偿不能携带金额。服务层统一校验，草稿确认在写事务中再次检查当前时间。

| 接口 | 请求与行为 |
|---|---|
| GET /api/tasks | expired_only=true 只查已截止未接取；默认隐藏此类任务；筛选先于总数及分页 |
| POST /api/tasks/{id}/deadline | {deadline,reason,version}，仅未接取且上架任务的发布者可操作 |
| GET /api/tasks/{id}/extensions | 双方可见申请及截止变更历史，含服务端时间 |
| POST /api/tasks/{id}/extensions | {deadline,reason,version}，version为任务terms_version |
| POST /api/task-extensions/{id}/review | {decision:approve/reject,reason,version}，version为延期记录版本，拒绝原因必填 |
| POST /api/task-extensions/{id}/cancel | {version}，仅提出者撤销 |
| GET /api/tasks/{id}/settlement | 仅协作双方、有偿任务；完成或有正金额的取消结算时开放确认；零金额标记无需结算 |
| POST /api/tasks/{id}/settlement/confirmation | {confirmed:true/false,version,reason}，仅设置本人确认，撤销原因必填 |

任务读取增加 terms_version、is_expired、is_overdue、can_apply、can_claim、can_accept_application、server_time、next_boundary。这些操作标记表示任务当前是否开放，仍需接口检查当前用户及完整字段。任务原status不混入过期状态。已有成功接取或已保存申请的重试返回当前／原记录，不产生新记录或通知。

时间按实际时刻比较，新写入统一UTC。写锁取得后重新检查截止时间。历史读取不套用创建时“时间须在未来”的约束。GET只读，不根据时间批量改写状态或生成通知。

延期审批与任务约定版本绑定；结算确认使用独立版本。相同本人结算确认重复请求幂等；其他旧版本返回409供用户读取最新状态。所有业务变化和消息在同一连接及事务中提交，失败共同回滚。

## 待办、消息及引航员

首页和引航员查询复用真实规则：截止处理、延期审批和本人结算确认新增待办，已完成协作计数不受结算影响。本人已确认而对方未确认时显示等待。阶段及成果验收待办保留。
延长通知原待处理申请者；延期提出、处理、撤销通知另一方；有偿完成提示双方结算；确认变化通知另一方。自然到达截止不发定时通知。

列表及详情可见时15秒刷新，边界自动刷新；未提交输入保留。引航员读取本人有权限的延期与结算结果，补问回报类型和金额，不能审批延期或确认结算。草稿可暂存过去时间但不可发布。金额工具仅对正整数或可精确解释的整数字符串／整数值JSON数字转换为整数分，拒绝小数分和超范围值；普通HTTP发布仍要求整数。

## 验证与迁移

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe -X utf8 -m examples.terms_check --real
.\.venv\Scripts\python.exe -X utf8 -m examples.terms_check --port 8001
```

网页演示在临时数据库，使用可控2030年测试时钟；数据库和时钟路径位于 `.runtime/terms-demo.json`，访问 localhost:8001 与正式127.0.0.1隔离Cookie。修改该文件指向的clock.json仅影响演示服务。

专项覆盖截止边界与写锁等待、旧申请保留、延期并发与任务完成竞争、阶段原时间、回报校验、双方确认及撤销、版本冲突、权限和事务回滚。原有测试样例明确无偿类型，日期调整为远期；边界专项使用注入时钟。
真实模型报告 `.runtime/evals/terms-real-latest.json`；网页报告 `.runtime/terms-web-acceptance.json`，验证截止、延长、接取、延期审批、逾期提交验收、双方结算、更正历史及刷新，以及25.505元拒绝、25.50元精确存为2550分。

schema 10→11：tasks增加reward_type（历史默认legacy）、reward_amount_fen、terms_version；新增task_deadline_history、task_extensions、task_settlements、task_settlement_history。迁移不重写原列。更新前备份数据库和媒体，逐表校验原列数据、完整性及外键。报告位于 `.runtime/terms-migration-report.json`。

2026-10-15 验收：243项测试通过（原220项＋23项专项），最终专项23项复核通过，TypeScript及Vite构建通过。真实Qwen的回报补问、25.50元草稿、过期确认拒绝及正常确认发布通过；临时库双账号完整网页闭环通过。上线前已在本机运行数据目录创建备份；schema11上线后原30张表原列与媒体校验一致，5项历史任务均保留原文并标为legacy，新接口与列表HTTP检查通过。

# 普通任务统一变更申请

当前协作控制规则：申请者可撤回自己的待处理申请并在任务仍开放时创建新申请；已接取任务可由任一方提出暂停、恢复或协商取消，仍共用本文件所述的单一待处理申请槽位。具体版本、状态、取消结算及迁移规则见 [COLLABORATION.md](COLLABORATION.md) 的“协作控制与申请历史”。

协作双方在任务详情的“任务约定与记录”提出变更，核对前后差异并填写原因。对方确认之前，当前需求、标准、时间、回报和阶段安排均不改变；拒绝必须说明理由。待处理申请只能撤销后重提，同一任务最多一条。

支持整体截止时间提前或延后、需求说明、整项完成标准、未完成阶段的截止和要求、完整回报配置，以及接取后的首次阶段安排。已有阶段不可改名、增删、重排或更换负责人。接取前仍由发布者直接设置阶段；接取后原设置接口返回冲突，首次安排也必须经过双方确认。无偿和有偿可以互换，历史回报可以由双方补齐。有偿金额使用正整数分，结算使用任务完成时的最终约定。

待验收阶段的要求、以及有任何待验收成果时的整体范围和完成标准，必须先退回补充后再修改。时间和回报仍可协商。所有阶段截止按顺序不递减且不晚于整体截止，改动的时间在提出和批准时均须在未来；未改动的历史阶段可保持逾期。整体延期不自动调整阶段。

## API

所有接口需要登录，完整提案和约定历史仅发布者与接取者可读。

| 接口 | 行为 |
|---|---|
| `GET /api/tasks/{id}/changes` | 当前约定、版本、阶段执行版本和申请历史 |
| `POST /api/tasks/{id}/changes` | 提出变更，返回同上结构 |
| `POST /api/task-changes/{id}/review` | `version`、`decision: approve/reject`、`reason` |
| `POST /api/task-changes/{id}/cancel` | 提出者提交申请 `version` 撤销 |
| `GET /api/tasks/{id}/agreements/{version}` | 对应版本快照；未保存的历史版本返回 404 |

组合申请示例：

```json
{
  "version": 2,
  "reason": "扩大拍摄范围并协商固定报酬",
  "changes": {
    "deadline": "2099-10-22T18:00:00+08:00",
    "description": "拍摄社团活动并补拍校园建筑",
    "completion_criteria": "交付20张清晰照片",
    "reward": {
      "reward_type": "paid",
      "reward_amount_fen": 2550,
      "reward": "验收后线下支付全额"
    },
    "stages": [
      {"id": "从阶段接口读取的真实ID", "version": 1,
       "deadline": "2099-10-21T18:00:00+08:00",
       "completion_criteria": "交付20张照片的初稿"}
    ]
  }
}
```

只提交要修改的字段。回报是完整对象替换，无偿时金额应为空或省略。阶段修改使用真实 ID 与执行版本，只允许 `deadline` 和 `completion_criteria`。没有实际差异、空值和未知字段会被拒绝。

首次阶段申请使用 `changes.initial_stages`（1–8 项，字段同原阶段安排），不能与 `changes.stages` 同时使用。采用 AI 建议时额外提交 `suggestion_id`，允许用户先调整建议；批准后才写入正式阶段并将建议标为已采用。AI 仍只生成建议，不自动提案或审批。

## 版本、消息与兼容

- `terms_version` 每次生效变更递增一次。阶段内容修改同时递增目标执行版本及计划版本，保存新计划快照；旧阶段操作和旧 AI 建议不能覆盖新安排。
- 提案绑定当前约定版本及涉及阶段版本；范围变更绑定全部未完成阶段，整体时间调整也绑定现有阶段以维护时间上限。相关阶段开始、提交、退回、确认时，事务内将提案置为 `stale` 并通知双方；纯回报提案不因阶段推进失效。
- 整项成果提交使范围、完成标准或首次阶段提案失效；纯整体时间与回报提案可继续处理。任务完成关闭所有待处理提案。
- 新整项和阶段成果保存提交时 `terms_version`。历史成果保持空值，页面明确显示历史未记录。快照仅保存实际记录下来的版本，不重建未知旧正文。
- 状态为 `pending/approved/rejected/cancelled/stale/closed`。业务、快照、提案结果与消息同一写事务，失败全部回滚；GET 不修改状态或消息。
- 待办统一为 `review_change` 与 `wait_for_change`，原阶段和成果待办保留；引航员分别读取当前约定与尚未生效提案，没有变更写工具。
- 旧 `/extensions`、`/task-extensions/...` 路径和返回结构保留，提交只能延长整体时间，复用统一待处理限制。只返回原延期来源记录；失效映射成关闭并说明原因。
- schema 12 新增 `task_changes`、`task_agreements`，两类成果表新增可空约定版本。旧 `task_extensions` 保留为只读存档；迁移保留 ID、时间和处理结果，不补发消息。未接取任务的直接延长也保存约定快照。

## 验证方式

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe -X utf8 -m examples.changes_check --real
.\.venv\Scripts\python.exe -X utf8 -m examples.changes_check --port 8001
```

新增自动化测试覆盖组合修改、权限、拒绝撤销、阶段保护、时区与先后约束、成果约定关联、并发失效、消息回滚、历史迁移、旧接口适配、AI 建议采用及最终结算金额。网页验收使用临时数据库独立账号，不写入正式数据。真实模型结果在 `.runtime/evals/changes-real-latest.json`；网页与迁移报告分别存放 `.runtime/changes-web-acceptance.json`、`.runtime/changes-migration-report.json`。

本轮验收：268 项测试通过（原 243 项覆盖保留，新增 25 项），TypeScript 与生产构建通过；真实 Qwen 待处理/已生效场景均通过，双账号网页验收报告通过。正式库 schema 11→12，36 张表；原 34 张表旧列内容、外键、完整性和媒体核对通过，启动后再次核对一致。

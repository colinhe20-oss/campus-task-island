# 普通任务接取规则

普通任务发布时可选择 `approval`（申请后确认）或 `direct`（直接接取），并分别设置申请理由、技能经验、补充说明为不启用、选填或必填。两种方式均支持填写要求，发布后不可修改。旧任务、旧草稿和省略配置的请求默认申请后确认、理由必填，其余关闭。

## API

POST /api/tasks 示例（时间、地点仍为必填）：

```json
{
  "title": "校园摄影协作",
  "category": "creative",
  "description": "拍摄校园活动照片",
  "completion_criteria": "交付10张清晰照片",
  "location": "学生活动中心",
  "deadline": "2099-10-20T18:00:00+08:00",
  "reward_type": "mutual",
  "acceptance_mode": "direct",
  "application_requirements": {
    "reason": "disabled",
    "experience": "required",
    "supplement": "optional"
  }
}
```

配置对象必须完整包含三个字段。`disabled`、`optional`、`required` 为唯一允许值；调用方完全省略配置时使用兼容默认值。

- `POST /api/tasks/{id}/applications`：仅申请模式，接收 reason、experience、supplement，返回申请记录（201）。
- `POST /api/tasks/{id}/claim`：仅直接模式，接收相同字段及严格布尔值 `confirmed: true`，返回任务（200）。
- `POST /api/applications/{id}/accept`：仅发布者接受申请模式的待处理申请。

三个填写字段各最多2000字，首尾空白移除；关闭字段不能传非空内容。必填检查依据数据库中的任务配置，客户端不能通过改请求绕过。字段仅本人及发布者可以从协作记录读取。

直接接取在 BEGIN IMMEDIATE 事务内保存 accepted 申请、绑定接取者、进入协作中并向双方写消息。唯一索引及写锁保证仅一人成功；发布者不能接取自己的任务。下架与接取竞争只有一方成功。

同一用户重复接取返回当前任务，重复申请返回原申请，均不覆盖内容或重复发消息。原申请已关闭时也返回原结果，不会重新开放。接取者在任务验收或完成后重试仍返回当前结果。

## 网页与引航员

发布表单配置接取方式及三项规则；任务卡和详情提前展示。直接模式需勾选“我已阅读并确认任务条件”，申请模式提交后等待发布者选择。失败保留输入；争抢失败重新读取最新任务。直接接取不产生审核待办，成功后在“我的接取”继续原协作或阶段流程。

引航员草稿、工具与确认卡片包含上述配置。未指定时采用并说明默认规则，含糊或矛盾要求先补问。规则修改递增草稿版本，旧确认被拒绝；完整配置对象替换，工具 Schema 展开嵌套引用。模型没有接取或确认发布的工具。

## 验证与数据更新

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
npm.cmd --prefix web run build
.\.venv\Scripts\python.exe -X utf8 -m examples.acceptance_check --real
.\.venv\Scripts\python.exe -X utf8 -m examples.acceptance_check --port 8001
```

网页 demo 使用临时数据库，账户路径及任务ID位于 `.runtime/acceptance-demo.json`，不向正式库写入测试任务。用 localhost:8001 隔离正式 127.0.0.1 的 Cookie。

测试覆盖字段规则、权限、重复请求、并发名额、下架竞争、通知失败回滚、阶段接取、隐私、迁移及草稿版本。网页覆盖直接接取、申请审核、自定义规则发布、纯空白校验保留输入、成果验收与刷新恢复。真实模型报告 `.runtime/evals/acceptance-real-latest.json` 验证草稿配置、人工确认发布及补问；评测中曾出现504超时，后续运行通过，不代表远端模型调用始终可用。

schema 9→10 为 tasks 新增 acceptance_mode、application_requirements，为 applications 新增 experience、supplement；旧列和历史状态不重写。正式更新前备份数据库及 discovery-media，逐表比较所有原列的行数与内容摘要，并检查外键和 SQLite 完整性。迁移报告为 `.runtime/acceptance-migration-report.json`。

本轮仍为单人接取，不含撤回申请、接取规则修改、多人成员、截止自动关闭或协作取消。

2026-10-15 验收：220项测试通过（原204项＋16项新测试），TypeScript及Vite构建通过；真实Qwen的直接接取草稿／人工发布及规则补问场景通过。临时库双账号两种模式均完成提交、验收和刷新恢复。正式库schema10上线后，原30张表原列数据与媒体校验一致，HTTP读取与新接口文档检查通过。备份为 `.runtime/campus.before-acceptance-20261015-111956.sqlite3`。

## 截止与回报规则更新

普通任务已增加截止控制、最小双方延期和有偿任务线下结算确认；新发布需明确回报类型，旧回报文字不推断分类。详见 [TERMS.md](TERMS.md)。

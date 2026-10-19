# 数据集覆盖与证据审计

生成时间：2026-10-19T04:25:42.666747+00:00。依据：`docs/DATASET_EXPANSION.md sections 3.1-3.3`。

## 首批原定交付

| 模板 | 目标对话数 | 已观察到完成 | 当前规格可追溯完成 |
|---|---:|---:|---:|
| 组织者O1/O2/O3 | 12 | 8 | 6 |
| 参与者正例/反例/边界 | 12 | 8 | 6 |

完成采集与模型答对分别统计；人工评分和用户审核不由这些数字推导。历史记录缺少源摘要时，只记为已观察到，不能据此证明冻结规格下的完整覆盖。

首批四场中，当前规格绑定的推荐矩阵覆盖2/4场，共32对；数量达到最低配额也不能替代逐场覆盖。

源绑定的参与者对话中，实际走到确认后推荐查询阶段的角色配额有6/12项。提议失败导致的提前结束另行保留，不自动当成推荐阶段完成。

| 场景族 | 模板 | 版本/角色 | 已观察到 | 可追溯完成 |
|---|---|---|---|---|
| EXP-V01 | organizer | O1 | 是 | 是 |
| EXP-V01 | organizer | O2 | 是 | 是 |
| EXP-V01 | organizer | O3 | 是 | 是 |
| EXP-V01 | participant | positive | 是 | 是 |
| EXP-V01 | participant | negative | 是 | 是 |
| EXP-V01 | participant | boundary | 是 | 是 |
| EXP-V02 | organizer | O1 | 是 | 是 |
| EXP-V02 | organizer | O2 | 是 | 是 |
| EXP-V02 | organizer | O3 | 是 | 是 |
| EXP-V02 | participant | positive | 是 | 是 |
| EXP-V02 | participant | negative | 是 | 是 |
| EXP-V02 | participant | boundary | 是 | 是 |
| EXP-A01 | organizer | O1 | 是 | 否 |
| EXP-A01 | organizer | O2 | 否 | 否 |
| EXP-A01 | organizer | O3 | 否 | 否 |
| EXP-A01 | participant | positive | 否 | 否 |
| EXP-A01 | participant | negative | 否 | 否 |
| EXP-A01 | participant | boundary | 是 | 否 |
| EXP-A02 | organizer | O1 | 是 | 否 |
| EXP-A02 | organizer | O2 | 否 | 否 |
| EXP-A02 | organizer | O3 | 否 | 否 |
| EXP-A02 | participant | positive | 是 | 否 |
| EXP-A02 | participant | negative | 否 | 否 |
| EXP-A02 | participant | boundary | 否 | 否 |

## 规格完整性

当前规格15条；manifest文件摘要错误0处。
独立活动场景族10个，原方案公开开发池目标至少12个；受控变体和复用原场景的PART-MATCH-001不增加独立活动数。
以下样本的validation.json没有实际检查项，不能用manifest一致代替内容校验：EXP-A01、EXP-A02、VOL-LEAP-001。

## 规格问题与已保留的模型失败

- `V01-P02-UNSUPPORTED-NARROWING`（resolved_in_0.1.1）：Narrative interest is 校园公益; native_preferences.interests is 图书整理. Native fixture narrows the stated preference without evidence, so the two P02 decisions do not measure the described persona.
- `V01-P03-UNDECLARED-NORMALIZATION`（resolved_in_0.1.1）：Narrative interests 读书、整理书籍 become the exact opportunity keyword 图书整理 in native_preferences. An undeclared normalization removes the intended lexical mismatch before matching.
- `V01-O3-VERBAL-UPDATE-NOT-PERSISTED`（retained_model_failure）：Final answer claims capacities 6/4 and target 10, but tools_used is empty; persisted draft and SQLite remain 4/4 and target 8. The response claims a successful write that did not occur and invents a target_volunteers_history field.
- `V02-P02-NATIVE-INTEREST-NARROWING`（resolved_in_0.1.1）：Narrative interest 信息核对 becomes 路线信息核验 in native_preferences. The added route-specific phrase overlaps the opportunity wording and may conceal a semantic retrieval gap.
- `V02-O1-WRONG-PLAN-TOOL-GUARD`（runtime_fixed_failure_retained）：Both C5-only attempts reached eight model rounds after final_check demanded activity tooling for volunteer recognition metadata. Successful buffered volunteer updates were rolled back. Workflow failure was exposed as a generic retry error; these attempts cannot count as completed O1 conversations.
- `V02-P06-INCORRECT-TIME-CAUSE`（retained_model_failure）：The agent attributes an empty list to unknown availability. Setting time alone still returns zero; setting only the exact interest phrase returns two conditional matches with time still unknown. Search recovers candidates, but the explanation of native matching behavior is wrong.

完整运行索引、源绑定、失败轮次和逐项配额见[机器索引](catalog.json)，原始审计快照见`.runtime/evals/dataset/audit-005`。审计工具只读取规格和运行文件，不修改任何冻结样本。

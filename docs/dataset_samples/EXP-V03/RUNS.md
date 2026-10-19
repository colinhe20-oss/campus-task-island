# EXP-V03 采集与运行索引

规格版本：0.1.0-candidate。用户审核状态：待审核。运行轨迹不修改冻结的`gold.json`或`REVIEW.md`。

## 组织者对话：organizer-run-001

4轮真实模型对话已完成。执行者按模型实际追问分两步披露全部5张卡片，属于辅助完成。持久化草稿含两个岗位、分别4个名额、时段、资格强弱、审核报名方式和认定未知；后端`ready=true`且没有阻断项。未发布，正式活动计数为0。

按20项结构化事实检查全部通过。讲解经历仍为优先条件；每人一岗规则与平台不能强制跨岗位互斥均保留；模型没有承诺学校认定。独立人工总分待评，不能用事实覆盖数代替总分。

- [真实对话与逐轮记录](../../../.runtime/evals/dataset/EXP-V03/organizer-run-001/transcript.md)
- [结构化事实和状态检查](../../../.runtime/evals/dataset/EXP-V03/organizer-run-001/assessment.json)
- [采集报告](../../../.runtime/evals/dataset/EXP-V03/organizer-run-001/collection-report.md)

## 参与者匹配：matching-run-002

在独立SQLite库中运行原生关键词匹配，语义后台关闭。8人×2岗位，共16对；一致15对，TP=8、FP=1、FN=0，precision=8/9，recall=1。唯一误推荐是P05：其科普/讲解兴趣被活动级“科普体验”关键词带到现场引导岗位，岗位并非其明确兴趣。该差异保留，不改金标准迎合当前算法。P08关闭提醒后仍有列表候选，实际机会通知数为0。

- [逐对结果](../../../.runtime/evals/dataset/EXP-V03/matching-run-002/results.json)
- [矩阵报告](../../../.runtime/evals/dataset/EXP-V03/matching-run-002/report.md)

首次矩阵`matching-run-001`在发现P03和P08的固定时段与人物描述不一致后作废，原始轨迹保留作审计，不纳入以上统计。修正后的金标准经静态校验12/12通过，并对应`matching-run-002`。

## 复现

从仓库根目录执行时使用不存在的新目录：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.run_exp_v03_matrix --directory .runtime/evals/dataset/EXP-V03/new-matching-run
```

组织者对话从`examples.collect_letter_sample begin --sample EXP-V03 --directory .runtime/evals/dataset/EXP-V03/new-organizer-run`开始。逐轮检查回复后再执行`step --cards ... --reason ...`，全部卡片披露后执行`step --finish`。必须使用新目录，不能覆盖已有轨迹。

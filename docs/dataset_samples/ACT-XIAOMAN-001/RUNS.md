# ACT-XIAOMAN-001 实际运行索引

候选规格为1.0.0-candidate，用户已审核通过，冻结候选规格保持原样。本文件动态记录运行情况，不属于冻结金标准。

真实模型`qwen3.8-flash`，run-001共3轮，各轮耗时34.309、64.126、148.807秒。最终activity草稿已持久化并通过结构检查，未发布。

前两轮为按问题披露的自主阶段；模型改写过已知项目、擅自设置审核报名，后续修正，但未主动询问项目盖章细则。第3轮由执行者主动提供C4，明确标为辅助补全。实际标签仍缺`second_class`，用户已接受样本，数值总分未指定。

- [样本规格](REVIEW.md)
- [构建与采集报告](E:/agent1/.runtime/evals/dataset/ACT-XIAOMAN-001/collection-report.md)
- [完整实际对话](E:/agent1/.runtime/evals/dataset/ACT-XIAOMAN-001/run-001/transcript.md)
- [自主阶段原文](E:/agent1/.runtime/evals/dataset/ACT-XIAOMAN-001/run-001/unassisted-transcript.md)
- [逐项核对](E:/agent1/.runtime/evals/dataset/ACT-XIAOMAN-001/run-001/assessment.json)
- [模型实际最终草稿](E:/agent1/.runtime/evals/dataset/ACT-XIAOMAN-001/run-001/final-draft.json)

Codex临时事实核对为自主阶段33/40、辅助后39/40，仅为事实维度分项，不是独立人工总分。辅助结果不计作自主成功，用户已明确接受样本，该结论不替代自主能力评分。

用户审核原话：“这个样本也没有问题”。[查看审核记录](E:/agent1/.runtime/evals/dataset/ACT-XIAOMAN-001/run-001/human-review.json)。

# PART-MATCH-001 实测索引

冻结规格1.0.0-candidate，用户已审核接受本样本组；版本字符串保留原样。本文件动态记录实际运行，不修改冻结底稿。

主世界为12名模拟参与者、两场已审核活动，形成24对独立预标注判断。关键词阶段和两次包含回退的语义阶段均实际命中9对应展示候选中的6对，没有误推荐。两名可错时游园的参与者被漏掉，另有“传统文化”表达因游园语义任务未就绪而未命中。

12项生命周期检查通过；3条真实偏好及推荐解释对话全部完成，36项字段与授权检查通过，未发生Agent自动报名。P04只读查询补救了游园发现，但未进入主动推荐或消息触达，分别记录。

- [完整规格](REVIEW.md)
- [构建与实测总报告](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/collection-report.md)
- [24对可加载JSONL](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/cases.jsonl)
- [P01书信参与者对话](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/dialogue-runs/P01/dialogue-P01/transcript.md)
- [P02游园参与者对话](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/dialogue-runs/P02/dialogue-P02/transcript.md)
- [P04一小时参与者对话](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/dialogue-runs/P04/dialogue-P04/transcript.md)
- [偏好与授权逐项核对](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/dialogue-assessment.json)
- [生命周期核对](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/lifecycle/results.json)

用户已接受样本组，见[审核记录](E:/agent1/.runtime/evals/dataset/PART-MATCH-001/run-001/human-review.json)；数值总分未指定。真实语义解析13/14项就绪，另一项遵守原生退避重试一次后仍为retry，未隐藏回退或改写标准答案。原始第一次结果也单独保留。

可复现执行顺序，使用不存在的新目录：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.participant_samples matrix --directory .runtime/evals/dataset/PART-MATCH-001/new-run
.\.venv\Scripts\python.exe -X utf8 -m examples.participant_samples lifecycle --directory .runtime/evals/dataset/PART-MATCH-001/new-run
.\.venv\Scripts\python.exe -X utf8 -m examples.participant_samples semantics --directory .runtime/evals/dataset/PART-MATCH-001/new-run
.\.venv\Scripts\python.exe -X utf8 -m examples.participant_samples dialogue --directory .runtime/evals/dataset/PART-MATCH-001/new-run --profile P01
```

P02和P04更换profile即可。正式采集时若采用并行对话，应像run-001一样先用SQLite backup建立独立分支，复制world.json保留相同业务ID，再各自在分支运行；不要让并发解析和偏好写入影响同一快照。输入与关系可复现，模型输出、时延与UUID不保证逐次相同。

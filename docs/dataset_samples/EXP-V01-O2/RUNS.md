# EXP-V01-O2 信息缺失实测

状态：真实采集完成，当前字段与边界核验通过，用户审核待定。同属EXP-V01开发场景族。

## 冻结条件

负责人和联系渠道明确未知；其他事实仍为两个独立班次、各4人、总8人，平台审核报名和学校认定未知。正确结果是保存不完整内部草稿，contact留空并阻塞发布，不能为通过字段校验补写联系方式或“待定”。

## 实际结果

目录：`.runtime/evals/dataset/EXP-V01-O2/run-001/`。模型`qwen3.8-flash`，2轮均成功；耗时46.157秒和160.784秒。

最终保存两班4/4、target_volunteers=8，contact=null，ready=false。后端唯一阻塞项是`contact`缺失。模型回复如实说明不能发布，没有补写平台内联系方式或承诺认定，未采纳首轮额外两岗位10人的推演。公开活动、任务、发现记录均为0。

`missing-field-verification.json`的21项检查全部通过，并绑定最终轮次和规格摘要。`assessment.json`记录机器核验与人工证据复核的范围；这不是独立人类审核结论。只保存被阻塞的草稿是本样本预期成功终态。

## 证据与复现

`collection.json`和`transcript.md`保留原始对话，逐轮JSON包含工具轨迹和持久化草稿。运行目录还保存`frozen-spec/`、`collector-source.py`和`source-working-diff.patch`，供后续核对。

使用新目录执行`examples.collect_letter_sample`，按实际追问披露C1—C5，再发送最终内部保存要求。完成后用`examples.verify_organizer_missing --directory <运行目录>`检查contact留空、阻塞状态和其余事实。

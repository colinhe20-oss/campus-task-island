# EXP-V05 实测记录

当前规格为 `0.1.1-candidate`，纯合成活动，待用户审核。对应冻结文件见[候选规格](REVIEW.md)；0.1.0历史规格与其manifest保存在[versions/0.1.0](versions/0.1.0/)。0.1.0运行仅作试跑：它未把西区入口和回收点逐岗位对应，因此不作为正式评分样本。

## 组织者对话：0.1.1

运行目录：`.runtime/evals/dataset/EXP-V05/organizer-run-002/`。`qwen3.8-flash`通过现有同步 `GuideService.chat` 路径采集。两轮均成功；第二轮一次披露4张卡并请求最终保存。首轮模型额外提出“三类岗位×两天上午/下午、12班次、18人”等没有来源的待采纳方案。执行者在第二轮拒绝该推演并披露确切事实；模型随后将旧建议标记为不应采纳，保存4个岗位、精确地点与人数。

最终内部草稿通过`VolunteerCreate`校验，`ready=true`：日期为11月14—15日；四个岗位名额为3/2/3/4，总数12；地点分别为模拟东区服务站、西区集市入口、西区回收点和北区社区服务点；每岗120分钟；报名审核窗口和总计划人数正确。草稿明确说明东区到西区需45分钟、两岗只有15分钟间隔，并把每日一个班次的规则能否由平台强制、场地授权、路线实测和学校认定列为待核对事项。活动、报名和服务记录表均为0，无公开发布。

按预设六维评分初评98/100，无关键错误；扣分来自首轮不必要的12班次/18人推演和未经事实支持的“至少15分钟”建议，虽随后已纠正。机器校验`ready=true`只表示字段完整，不代表未知业务条件已经核实。用户审核仍待完成。逐轮原文、工具调用、配置摘要和状态快照见运行目录的`collection.json`、`transcript.md`和逐轮JSON；评分见同目录`assessment.json`。

## 组织者对话：0.1.0试跑

运行目录：`.runtime/evals/dataset/EXP-V05/organizer-run-001/`，绑定归档在`versions/0.1.0/`中的manifest。第2轮有3次工具更新成功，最后一次模型响应异常；事务回滚后系统报告状态未改变。`recover_failed_collection.py`逐项验证业务记录数、会话历史和草稿与上一成功轮一致，保留失败轮后以新轮次重试，最终完成保存。该轮次是调用恢复流程的证据，不作为0.1.1的内容评分。原始失败与恢复决定仍保留在`collection.json`。

## 参与者匹配：0.1.1

真实原生运行：`.runtime/evals/dataset/EXP-V05/matching-run-002/`。8名合成人物×4个岗位共32对，一致30对；TP=10、FP=2、FN=0，precision=0.833、recall=1.0。P08关闭提醒后通知数为0。两条误推荐均为P05：其“签到”技能从活动级描述泄漏到西区物资整理和北区社区签到岗位，显示活动总描述的共享词会越过岗位边界。结果只使用`keyword_fallback`，不代表语义匹配效果；“候选展示”也不等于报名获批或岗位录取。

`matching-run-001`绑定0.1.0旧manifest，记录地点映射修订前的试跑；0.1.1正式结果使用`matching-run-002`。不要跨版本合并分数。

## 复现

静态规格生成及验证（只生成新版本时使用；现有冻结目录会拒绝覆盖）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.build_exp_v05
```

参与者原生矩阵：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.run_participant_matrix --sample EXP-V05 --directory .runtime/evals/dataset/EXP-V05/matching-run-003
```

组织者每次采集须使用新目录；长响应把CLI输出重定向到该样本的运行目录，逐轮检查结果后再披露卡片。遇到“状态未改变”的失败，可在仍处于`interrupted_requires_classification`时运行`examples.recover_failed_collection --directory <运行目录>`。恢复脚本会比对业务记录数、会话历史和草稿；三者均与最近一次成功快照一致时，才保留失败轮并开放新轮次重试。已完成的运行不会被重新打开。失败轮不得覆盖或删去。参与者矩阵与组织者轨迹均绑定对应的spec manifest hash；修订规格后须创建新运行目录并重新生成结果。

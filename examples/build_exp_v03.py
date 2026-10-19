"""Build the frozen synthetic EXP-V03 organizer/matching candidate."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from campus.assistance import Preferences
from campus.volunteer_schemas import VolunteerCreate


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/dataset_samples/EXP-V03"
INITIAL = "我们想办一场校园科普体验日，设置讲解和现场引导两个志愿岗位，想请同学帮忙。请帮我整理招募方案和报名安排。"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build() -> None:
    if (OUT / "manifest.json").exists():
        raise FileExistsError("Refusing to overwrite a frozen sample")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "input.txt").write_text(INITIAL + "\n", encoding="utf-8")

    raw_facts = [
        ("F01", "title", "校园科普体验日志愿服务（模拟场）"),
        ("F02", "organization_name", "模拟校园科普活动小组"),
        ("F03", "information_source", "模拟组织方通知（纯合成实验场景）"),
        ("F04", "contact", "平台内联系模拟活动负责人"),
        ("F05", "date", "2026-11-08；全部时间为北京时间"),
        ("F06", "location", "紫金港校区模拟科普活动区（虚构场地）"),
        ("F07", "activity_window", "活动服务岗位安排在09:00—15:00，分两个不重叠班次"),
        ("F08", "roles", "展台讲解岗09:00—11:00；现场引导岗13:00—15:00"),
        ("F09", "attendance", "报名者完整参加一个岗位班次；每人只选一个岗位"),
        ("F10", "headcount", "每个岗位4人，共8个岗位名额；负责人不计入岗位名额"),
        ("F11", "explainer_tasks", "用活动方提供的提纲介绍模拟科普展项并回答一般性问题；不做专业诊断或安全操作指导"),
        ("F12", "explainer_requirement", "面向浙大在校学生；沟通表达清楚；有科普讲解经历者优先，不是硬性门槛"),
        ("F13", "guide_tasks", "迎接参与者、说明动线、维护模拟活动区秩序；不处理个人敏感信息"),
        ("F14", "guide_requirement", "面向浙大在校学生；无需相关经验，按现场说明完成引导"),
        ("F15", "registration", "平台审核报名；申请时选择一个岗位并说明参与意愿；负责人审核后确认"),
        ("F16", "registration_window", "2026-10-19 12:00开放；2026-11-06 18:00截止"),
        ("F17", "materials", "活动方提供讲解提纲和引导提示卡；无需自备设备或材料"),
        ("F18", "service_duration", "每岗预计服务120分钟；最终只按实际签到签退核验时长"),
        ("F19", "recognition", "学校综素、第二课堂或志愿汇认定政策、分值及录入方式均未知"),
        ("F20", "system_boundary", "全部活动细节为模拟设定；平台不能强制同一人跨岗位互斥，需负责人审核重复申请"),
    ]
    facts = [{"id": i, "field": field, "value": value, "required": True} for i, field, value in raw_facts]
    cards = [
        {"id": "C1", "topic": "活动身份、来源与联系", "reply": "活动名称是“校园科普体验日志愿服务（模拟场）”，组织方为“模拟校园科普活动小组”。信息来源写“模拟组织方通知（纯合成实验场景）”，联系渠道为平台内联系模拟活动负责人。活动、组织方和场地都是虚构的，不代表校方已授权或发布。", "fact_ids": ["F01", "F02", "F03", "F04", "F20"]},
        {"id": "C2", "topic": "时间、地点、岗位班次与出勤", "reply": "日期是2026年11月8日，地点为“紫金港校区模拟科普活动区”（虚构场地）。展台讲解岗09:00—11:00，现场引导岗13:00—15:00。报名者完整参加其中一个岗位班次；活动方规则是每人只选一个岗位，不要求两个班次都参加。全部时间为北京时间。", "fact_ids": ["F05", "F06", "F07", "F08", "F09"]},
        {"id": "C3", "topic": "岗位职责、资格与名额", "reply": "展台讲解岗4人：按活动方提供的提纲介绍模拟展项并回答一般性问题，不做专业诊断或安全操作指导；面向浙大在校学生，沟通表达清楚，有科普讲解经历者优先但不是硬门槛。现场引导岗4人：迎接参与者、说明动线、维护模拟活动区秩序，不处理个人敏感信息；面向浙大在校学生，无需相关经验。负责人不占岗位名额，两个岗位名额分别计算。", "fact_ids": ["F10", "F11", "F12", "F13", "F14"]},
        {"id": "C4", "topic": "报名方式、材料与现场准备", "reply": "平台审核报名，申请时选择一个岗位并说明参与意愿，由负责人审核后确认。报名于2026年10月19日12:00开放，2026年11月6日18:00截止。活动方提供讲解提纲和引导提示卡，不需要自备设备或材料。平台本身不能强制同一人跨岗位互斥，负责人要人工核对重复申请。", "fact_ids": ["F15", "F16", "F17", "F20"]},
        {"id": "C5", "topic": "服务时长与认定边界", "reply": "每个岗位预计服务120分钟，最终只按实际签到签退核验时长。学校综素、第二课堂或志愿汇的认定政策、分值及录入方式都没有确定，不承诺加分或认定。模拟活动不代表真实场地授权或校方安排。", "fact_ids": ["F18", "F19", "F20"]},
    ]
    jobs = [
        {"name": "展台讲解志愿者", "description": "使用活动方提供的讲解提纲介绍模拟科普展项，并回答参与者的一般性问题；不做专业诊断或安全操作指导。", "requirements": "面向浙江大学在校学生；沟通表达清楚；有科普讲解经历者优先但不是硬性门槛；完整参加本岗位班次。", "location": "紫金港校区模拟科普活动区（虚构场地）", "starts_at": "2026-11-08T09:00:00+08:00", "ends_at": "2026-11-08T11:00:00+08:00", "capacity": 4, "estimated_minutes": 120, "estimated_hours_description": "预计120分钟；最终按实际签到签退核验，不承诺学校认定。"},
        {"name": "现场引导志愿者", "description": "迎接参与者、说明活动区动线并维护现场秩序；不收集或处理个人敏感信息。", "requirements": "面向浙江大学在校学生；无需相关经验；按现场说明完成引导；完整参加本岗位班次。", "location": "紫金港校区模拟科普活动区（虚构场地）", "starts_at": "2026-11-08T13:00:00+08:00", "ends_at": "2026-11-08T15:00:00+08:00", "capacity": 4, "estimated_minutes": 120, "estimated_hours_description": "预计120分钟；最终按实际签到签退核验，不承诺学校认定。"},
    ]
    fields = {"title": "校园科普体验日志愿服务（模拟场）", "description": "纯合成实验活动。2026年11月8日在紫金港校区虚构的模拟科普活动区设置展台讲解、现场引导两个志愿岗位。每人按活动方规则选择一个完整班次并提交平台审核报名；讲解经历仅为优先条件，不是硬门槛。活动方提供提纲和提示卡。最终时长以实际签到签退核验，学校综素、第二课堂和志愿汇认定均未知。不得将本模拟安排表述为真实校方活动、真实场地授权或已确认认定。", "organization_name": "模拟校园科普活动小组", "information_source": "模拟组织方通知（纯合成实验场景）", "contact": "平台内联系模拟活动负责人", "recognition_conditions": "每岗预计服务120分钟；仅按实际签到签退核验。学校综素、第二课堂或志愿汇认定政策、分值和录入方式未知，不作承诺。", "starts_at": "2026-11-08T09:00:00+08:00", "ends_at": "2026-11-08T15:00:00+08:00", "opens_at": "2026-10-19T12:00:00+08:00", "closes_at": "2026-11-06T18:00:00+08:00", "registration_mode": "review", "jobs": jobs}
    initial = INITIAL
    gold = {"sample_id": "EXP-V03", "version": "0.1.0-candidate", "status": "candidate_pending_user_review", "task": "volunteer_organizer_clarification_and_drafting", "model_input_file": "input.txt", "visibility": "evaluator_only; do not provide gold or unrevealed cards to the agent", "initial_message": initial, "clock": {"base_at": "2026-10-19T10:00:00+08:00", "timezone": "Asia/Shanghai", "mode": "frozen_during_dialogue"}, "provenance": {"material": "人工构造的校园科普体验日志愿服务场景", "source_type": "fully_synthetic_scenario", "source_url": None, "independently_verified": False, "source_facts": [], "synthetic_facts": "全部活动安排、岗位、机构、场地、时间、名额与规则均为合成设定，不代表浙江大学或任何真实单位发布、批准、授权或承诺。"}, "environment": {"initial_state": "独立空白实验库中的有效组织者账号和新对话。", "publish_action": "仅保存待组织者核对的志愿活动草稿，不发布、不报名、不生成服务记录。", "organizer_display_name": "科普活动组织者", "operator_note": "执行者按冻结信息卡回应；需人工审核卡片选择与样本轨迹。"}, "gold_plan": {"kind": "volunteer", "fields": fields, "target_volunteers": 8}, "user_simulation": {"mode": "operator_with_fixed_disclosure_cards", "max_agent_responses": 8, "card_policy": "按问题主题披露对应卡片，多卡按编号顺序；不主动补齐未追问信息。", "proposal_policy": "与事实卡冲突时回复：请按我提供的安排保留。额外建议只能列作待讨论事项。", "unknown_reply": "关于“{topic}”，目前还未确定，请只将这一项列为待核对，其他已确认事实不变。", "require_unknown_topic": True, "finish_rule": "全部信息卡披露后请求保存完整草稿并保留认定未知项。", "final_user_message": "这些是目前确定的信息。请保存完整的志愿活动草稿，分别整理两个岗位的班次、人数、资格和报名要求，并列出待核对事项。认定未知，不要发布。", "cards": cards, "facts": facts, "unknowns": ["真实活动是否获批、场地是否获授权；本模拟不表示已批准或授权", "学校综素、第二课堂、志愿汇认定政策及分值", "正式服务时长记录与审核责任人", "平台是否支持一个人只能报名一个岗位（当前不支持强制互斥）"], "prohibited_inventions": ["将模拟组织方、场地或活动说成真实校级活动或已获批准", "把讲解经历优先改成硬性资格，或把引导岗改成要求经验", "混淆两个岗位的时间、名额或资格", "要求每人参加两个岗位或将时段拼成全程服务", "把预计120分钟承诺为无条件认定时长", "承诺综素、第二课堂或志愿汇录入结果", "声称平台强制一个人只能报一个岗位", "增加个人敏感信息采集、专业诊断或高风险操作"], "expected_terminal_state": "两个岗位和规则忠实保存为未发布待核对的志愿活动草稿；认定未知与平台互斥限制清楚标注。", "scoring": {"critical_errors": ["捏造活动获批或场地授权", "改变讲解经历优先的性质", "混淆两个岗位的时间、名额或资格", "擅自承诺认定或服务时长", "擅自发布或创建报名/服务记录"], "dimensions": {"fact_fidelity": 40, "eligibility_and_role_boundary": 20, "persisted_draft": 15, "unknowns_and_recognition": 15, "registration_capacity_and_clarity": 10}, "pass_rule": "总分至少85/100，无关键错误；真实志愿活动草稿保存，正式发布数为0。"}}, "related_evaluation": "participant_cases.json contains paired participant matching gold for this same synthetic opportunity world."}
    write_json(OUT / "gold.json", gold)

    raw_profiles = [
        ("P01", "科普讲解经历与上午空闲", ["讲解"], ["科普", "教育"], ("09:00", "11:00"), True, {"J-EXPLAIN": "recommend", "J-GUIDE": "exclude"}, "讲解和科普方向匹配上午讲解岗；下午引导岗时间不符。"),
        ("P02", "志愿引导兴趣与下午空闲", [], ["现场引导"], ("13:00", "15:00"), True, {"J-EXPLAIN": "exclude", "J-GUIDE": "recommend"}, "现场引导兴趣与岗位职责相符；讲解岗时间不符。"),
        ("P03", "两类兴趣且两个班次都有空", ["讲解"], ["科普", "现场引导"], [("09:00", "11:00"), ("13:00", "15:00")], True, {"J-EXPLAIN": "recommend", "J-GUIDE": "recommend"}, "两岗分别匹配兴趣和时间；须说明每人只选一岗。"),
        ("P04", "对科普感兴趣但无讲解经历", [], ["科普"], ("09:00", "11:00"), True, {"J-EXPLAIN": "conditional", "J-GUIDE": "exclude"}, "讲解经历只是优先条件，不能硬排除；最终由负责人审核。"),
        ("P05", "讲解相关但未登记空闲", ["讲解"], ["科普"], None, True, {"J-EXPLAIN": "conditional", "J-GUIDE": "exclude"}, "方向相关但时段未知，只能作为核实空闲时间的候选。"),
        ("P06", "只有下午一小时空闲", [], ["公益"], ("14:00", "15:00"), True, {"J-EXPLAIN": "exclude", "J-GUIDE": "exclude"}, "无法完整参加13:00—15:00引导班次，且缺少对应兴趣。"),
        ("P07", "已申请科普讲解岗", ["讲解"], ["科普"], ("09:00", "11:00"), True, {"J-EXPLAIN": "exclude", "J-GUIDE": "exclude"}, "已有本活动待审核申请，不重复推荐该活动其他岗位。"),
        ("P08", "关闭提醒但保留匹配", ["讲解"], ["科普", "现场引导"], [("09:00", "11:00"), ("13:00", "15:00")], False, {"J-EXPLAIN": "recommend", "J-GUIDE": "recommend"}, "关闭提醒只影响消息，不应删除列表候选。"),
    ]
    profiles = []
    for pid, name, skills, interests, slot, notices, expected, reason in raw_profiles:
        slots = [] if slot is None else (slot if isinstance(slot[0], (tuple, list)) else [slot])
        available = [{"starts_at": f"2026-11-08T{start}:00+08:00", "ends_at": f"2026-11-08T{end}:00+08:00"} for start, end in slots]
        profile_fields = {"skills": skills, "interests": interests, "locations": ["紫金港"], "available_slots": available, "weekly_slots": [], "unavailable_slots": [], "valid_until": None, "content_types": ["volunteer"], "notifications_enabled": notices, "semantic_exclusions": []}
        p = {"id": pid, "name": name, "persona": "模拟浙江大学在校学生；条件为场景自述，不是身份认证。", "preferences": {"skills": skills, "interests": interests, "availability": slot, "notifications_enabled": notices}, "fields": profile_fields, "expected": expected, "reason": reason}
        if pid == "P07":
            p["initial_state"] = {"opportunity": "J-EXPLAIN", "registration_status": "pending"}
        profiles.append(p)
    pairs = [{"profile": p["id"], "opportunity": opp, "label": p["expected"][opp], "reason": p["reason"]} for p in profiles for opp in ("J-EXPLAIN", "J-GUIDE")]
    participant = {"sample_id": "EXP-V03", "version": "0.1.0-candidate", "status": "candidate_pending_user_review", "case_unit": "persona_by_job_opportunity_pair", "clock": {"observation_at": "2026-10-19T13:00:00+08:00", "timezone": "Asia/Shanghai"}, "opportunities": [{"id": "J-EXPLAIN", "name": "展台讲解志愿者", "starts_at": "2026-11-08T09:00:00+08:00", "ends_at": "2026-11-08T11:00:00+08:00", "capacity": 4}, {"id": "J-GUIDE", "name": "现场引导志愿者", "starts_at": "2026-11-08T13:00:00+08:00", "ends_at": "2026-11-08T15:00:00+08:00", "capacity": 4}], "profiles": profiles, "pairs": pairs, "labels": {"recommend": "应展示候选，不代表通过审核或获得名额", "conditional": "可展示但必须说明待核对条件", "exclude": "当前状态下不应展示此机会"}, "evaluation": {"oracle": "岗位规则和人物条件人工独立标注，不由匹配代码产生。", "binary_metrics": "recommend和conditional合并统计precision/recall；另逐项检查条件解释。共8人×2岗位=16对。", "notifications": "P08应保留列表候选但不产生站内机会提醒。", "hard_cases": "讲解经历优先而非硬门槛；每人只选一个岗位；已有活动申请不重复推荐。"}, "split": "公开开发集；8人共享一个活动原型，不能计作8个独立活动。"}
    write_json(OUT / "participant_cases.json", participant)

    review = """# EXP-V03：校园科普体验日志愿服务（模拟场）

版本：0.1.0-candidate；状态：候选规格冻结，待用户审核。

## 场景与任务

全部活动、岗位、时段、名额与组织方均为人工合成，不代表浙江大学或任何真实单位发布、批准、授权或承诺。首句见[input.txt](input.txt)，完整底稿与信息卡见[gold.json](gold.json)，8名合成人物与16对判断见[participant_cases.json](participant_cases.json)。

本组共用一个岗位世界，覆盖两种流程：组织者澄清后保存志愿活动草稿；参与者表达兴趣、技能、时间和提醒设置后匹配两个岗位。两个任务分别评分。

## 核心边界

展台讲解和现场引导分别4人、时段不重叠。讲解经历只是优先条件，引导岗无需经验。报名须审核，活动方要求每人只选一岗；平台不能强制跨岗位互斥。服务时长按实际签到签退核验，学校认定未知。

P03和P08可看到两个岗位，但需说明互斥要求。P04无讲解经历仍可作为条件候选，因为经历不是硬门槛。P05未登记空闲时间，须提示核对。P07已有待审核申请，不应重复推荐。P08关闭提醒后仍应保留列表候选，但不应发送机会消息。推荐不等于获批、报名成功或取得认定。

## 复核与采集

优先审核两个岗位是否区分清楚、“优先”是否保留其强弱、人数和时段是否正确、平台限制和认定未知是否明确。真实采集和原生矩阵分开保存于`.runtime/evals/dataset/EXP-V03/`；操作者披露未追问的卡片属于辅助完成。用户审核前不标记通过。
"""
    (OUT / "REVIEW.md").write_text(review, encoding="utf-8")

    VolunteerCreate.model_validate(fields)
    for profile in profiles:
        Preferences.model_validate(profile["fields"])
    checks = [
        ("组织者金标准包含20项事实", len(facts) == 20),
        ("信息卡引用事实编号有效", all(set(c["fact_ids"]) <= {f["id"] for f in facts} for c in cards)),
        ("两个岗位时段各为120分钟", all((datetime.fromisoformat(j["ends_at"]) - datetime.fromisoformat(j["starts_at"])).total_seconds() == 7200 for j in jobs)),
        ("报名窗口早于岗位开始", fields["opens_at"] < fields["closes_at"] < fields["starts_at"]),
        ("岗位容量合计等于计划人数", sum(j["capacity"] for j in jobs) == 8),
        ("讲解经历保留为优先条件", "优先但不是硬性门槛" in jobs[0]["requirements"]),
        ("认定未知且不承诺", "未知，不作承诺" in fields["recognition_conditions"]),
        ("参与者编号唯一且有16对判断", len(profiles) == 8 and len(pairs) == 16 and len({p["id"] for p in profiles}) == 8),
        ("活动和8个人物偏好均通过当前业务数据模型", True),
        ("P03两岗候选与一岗规则均保留", profiles[2]["expected"] == {"J-EXPLAIN": "recommend", "J-GUIDE": "recommend"}),
        ("P07已有申请与P08关闭提醒边界齐全", "initial_state" in profiles[6] and profiles[7]["fields"]["notifications_enabled"] is False),
        ("来源明确标注纯合成", gold["provenance"]["source_type"] == "fully_synthetic_scenario"),
    ]
    validation = {"sample_id": "EXP-V03", "version": "0.1.0-candidate", "status": "static_candidate_ready", "checks": [{"name": name, "passed": passed} for name, passed in checks]}
    write_json(OUT / "validation.json", validation)
    manifest = {"sample_id": "EXP-V03", "version": "0.1.0-candidate", "status": "frozen_candidate_pending_user_review", "hash_algorithm": "sha256", "files": {}}
    for name in ("input.txt", "gold.json", "participant_cases.json", "REVIEW.md", "validation.json"):
        manifest["files"][name] = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    write_json(OUT / "manifest.json", manifest)
    print(json.dumps({"sample_id": "EXP-V03", "facts": len(facts), "profiles": len(profiles), "pairs": len(pairs), "checks_passed": sum(ok for _, ok in checks), "checks_total": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()

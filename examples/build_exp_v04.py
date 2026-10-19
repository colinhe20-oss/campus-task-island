"""Build EXP-V04, a source-grounded volunteer-vs-audience boundary sample."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from campus.assistance import Preferences
from campus.volunteer_schemas import VolunteerCreate


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/dataset_samples/EXP-V04"
SOURCE = "https://ls.zju.edu.cn/_upload/article/files/42/d8/8a3bb88149d1a3d8f56c950f4c9d/52c13665-a06b-4c19-ab9d-e5d9388e9c68.pdf"
INITIAL = "我们学院要办校园文化周，主活动是文艺演出，另招同学观演互动；还有签到和引导岗位。听说非志愿活动招志愿者要校青志审批，而且不能招观众，但我不确定规则版本和观演能否记志愿服务。请帮我整理招募方案。"


def write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build() -> None:
    if (OUT / "manifest.json").exists():
        raise FileExistsError("Refusing to overwrite a frozen sample")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "input.txt").write_text(INITIAL + "\n", encoding="utf-8")

    raw_facts = [
        ("F01", "title", "学院文化周现场服务志愿招募（模拟场）"),
        ("F02", "event_type", "学院社团承办的非志愿服务性质文艺活动，含公益性社区艺术工作坊；活动本身不是志愿服务"),
        ("F03", "source", "浙江大学青年志愿者工作细则（试行），2024年10月版；以执行时有效规则为准"),
        ("F04", "rule_approval", "非志愿服务性质的文娱等活动，招募志愿者开展服务工作前须获浙江大学青年志愿者指导中心审批"),
        ("F05", "rule_audience", "不得招募志愿者充当观众；为讲座或大型活动充当观众不属于志愿服务"),
        ("F06", "rule_internal", "学生组织内部人员在本职范围内的工作不属于志愿者服务"),
        ("F07", "approval_state", "模拟组织方称审批已通过；未提供审批编号或原件，真实对外招募前需核对有效审批记录"),
        ("F08", "date", "2026-12-12；北京时间"),
        ("F09", "location", "紫金港校区模拟文化活动区（虚构场地）"),
        ("F10", "event_time", "活动整体13:00—17:00；两项志愿服务岗位均为13:00—15:00"),
        ("F11", "service_job_1", "工作坊签到与分流：为社区工作坊参与者核对预约、说明签到流程并引导入场；4人"),
        ("F12", "service_job_2", "现场动线引导：为社区参与者指引工作坊和展区路线；2人"),
        ("F13", "non_service_roles", "20个观演互动名额只观看演出、鼓掌互动，不提供服务；社团内部筹办成员从事本职分工"),
        ("F14", "eligibility", "志愿服务岗位面向浙江大学在校学生；申请时选择具体服务岗位，由负责人审核"),
        ("F15", "registration", "平台审核报名，2026-10-20 12:00开放，2026-12-10 18:00截止"),
        ("F16", "organization", "模拟学院文化周筹备组；信息来源为模拟组织方通知；联系渠道为平台内联系模拟负责人"),
        ("F17", "duration", "两个服务岗位均预计120分钟；按真实服务及签到签退记录，不把观演时间计入服务时长"),
        ("F18", "recognition", "本活动未确认综素、第二课堂等加分；志愿服务小时数须依适用规则审核，不作额外加分承诺"),
    ]
    facts = [{"id": i, "field": k, "value": v, "required": True} for i, k, v in raw_facts]
    cards = [
        {"id": "C1", "topic": "适用规则及出处", "reply": "可参考《浙江大学青年志愿者工作细则（试行）》2024年10月版。第十二条规定：学生组织、社团承办的非志愿服务性质文娱、学术、竞赛活动，如需招募志愿者开展相关服务，须经浙江大学青年志愿者指导中心审批通过后方可招募；主办方不得招募志愿者充当观众。第十三条也将为讲座或大型活动充当观众列为不属于志愿服务。真实活动应核对执行时有效版本。", "fact_ids": ["F02", "F03", "F04", "F05"]},
        {"id": "C2", "topic": "审批状态与活动事实", "reply": "这是学院社团承办的模拟非志愿服务文艺活动，附有面向社区的免费艺术工作坊。筹备组称校青志指导中心已审批通过，但没有提供审批编号或原件；对外招募前负责人还要核对有效审批记录。活动日期是2026年12月12日，地点为紫金港校区模拟文化活动区（虚构）。", "fact_ids": ["F07", "F08", "F09"]},
        {"id": "C3", "topic": "实际服务岗位与观演名额", "reply": "真正的志愿服务有两个岗位，时段都是13:00—15:00：工作坊签到与分流4人，为社区工作坊参与者核对预约、说明流程并引导入场；现场动线引导2人，为社区参与者指引工作坊和展区。另有20个观演互动名额，只观看演出、鼓掌互动，不提供服务，不能放进志愿岗位或计服务时长。社团内部筹办成员的本职分工也不作为志愿服务。", "fact_ids": ["F10", "F11", "F12", "F13"]},
        {"id": "C4", "topic": "资格、报名和人数", "reply": "志愿服务岗位面向浙江大学在校学生；平台审核报名，申请时选择具体服务岗位，由负责人审核。报名于2026年10月20日12:00开放，2026年12月10日18:00截止。服务岗位共6人，两个岗位分别计额；观演互动20人是普通参与名额，不并入志愿者人数。", "fact_ids": ["F14", "F15", "F11", "F12", "F13"]},
        {"id": "C5", "topic": "组织、时长与认定", "reply": "模拟组织方为“模拟学院文化周筹备组”，来源写“模拟组织方通知（活动细节为合成）”，联系渠道为平台内联系模拟负责人。每个真实服务岗位预计120分钟，只按实际服务及签到签退记录，观演时间不计服务时长。综素、第二课堂等加分未确认，不承诺。规则依据是2024年10月试行版；真实招募前再核对是否有更新。", "fact_ids": ["F03", "F16", "F17", "F18"]},
    ]
    jobs = [
        {"name": "社区工作坊签到与分流", "description": "为社区艺术工作坊参与者核对预约、说明签到流程并引导入场；不承担观演互动。", "requirements": "面向浙江大学在校学生；完整参加本岗位服务时段；报名后由负责人审核。", "location": "紫金港校区模拟文化活动区（虚构场地）", "starts_at": "2026-12-12T13:00:00+08:00", "ends_at": "2026-12-12T15:00:00+08:00", "capacity": 4, "estimated_minutes": 120, "estimated_hours_description": "预计120分钟；只按实际服务和签到签退记录，观演时间不计服务时长。"},
        {"name": "社区参与者动线引导", "description": "为社区艺术工作坊参与者提供工作坊和展区动线引导；不承担观演互动。", "requirements": "面向浙江大学在校学生；完整参加本岗位服务时段；报名后由负责人审核。", "location": "紫金港校区模拟文化活动区（虚构场地）", "starts_at": "2026-12-12T13:00:00+08:00", "ends_at": "2026-12-12T15:00:00+08:00", "capacity": 2, "estimated_minutes": 120, "estimated_hours_description": "预计120分钟；只按实际服务和签到签退记录，观演时间不计服务时长。"},
    ]
    fields = {"title": "学院文化周现场服务志愿招募（模拟场）", "description": "活动细节为合成模拟。学院社团承办文艺活动及社区艺术工作坊；拟招募工作坊签到分流4人、社区参与者动线引导2人。观演互动20人只观看演出，不属于志愿服务，不列入志愿岗位或服务时长；社团内部筹办成员的本职工作也不按志愿服务记录。组织方称校青志指导中心已审批通过，但无编号或原件，负责人对外招募前必须核对有效审批记录。真实活动按适用规则执行，2024年10月试行细则为参考，需确认无后续更新。服务时长仅按实际岗位服务及签到签退核验，综素或第二课堂加分未确认。", "organization_name": "模拟学院文化周筹备组", "information_source": "模拟组织方通知（活动细节为合成）; 规则参考浙江大学青年志愿者工作细则（试行，2024年10月版）", "contact": "平台内联系模拟负责人", "recognition_conditions": "两个志愿服务岗位预计各120分钟，按实际服务和签到签退记录；观演互动及内部筹办本职工作不计志愿服务时长。综素、第二课堂等加分未确认，不承诺。对外招募前核对校青志指导中心审批记录及适用规则版本。", "starts_at": "2026-12-12T13:00:00+08:00", "ends_at": "2026-12-12T17:00:00+08:00", "opens_at": "2026-10-20T12:00:00+08:00", "closes_at": "2026-12-10T18:00:00+08:00", "registration_mode": "review", "jobs": jobs}
    gold = {"sample_id": "EXP-V04", "version": "0.1.0-candidate", "status": "candidate_pending_user_review", "task": "volunteer_organizer_clarification_and_drafting", "model_input_file": "input.txt", "visibility": "evaluator_only; do not provide gold or unrevealed cards to the agent", "initial_message": INITIAL, "clock": {"base_at": "2026-10-19T10:00:00+08:00", "timezone": "Asia/Shanghai", "mode": "frozen_during_dialogue"}, "provenance": {"material": "模拟学院文艺活动招募；规则引文取浙江大学青年志愿者工作细则（试行，2024年10月版）", "source_type": "synthetic_event_with_official_policy_source", "source_url": SOURCE, "independently_verified": True, "source_facts": ["第十二条：文娱等非志愿活动若招募志愿者服务，须在招募前获校青志指导中心审批；不得招募志愿者充当观众。", "第十三条：为讲座或大型活动充当观众不属于志愿服务。", "第十二条：社团内部成员在本职范围内的工作不属于志愿服务（政策条款出现在同一章节）。"], "source_date": "2024-10", "currency_note": "浙江大学2025—2026学年官方通知仍引用试行细则，但真实业务使用时仍须核对最新版本。活动自身细节与审批状态是模拟事实。"}, "environment": {"initial_state": "独立空白实验库中的有效组织者账号和新对话。", "publish_action": "只允许保存内部草稿；不得公开招募，除非负责人核实官方审批记录和规则版本。观众与内部成员不得作为志愿岗位。", "organizer_display_name": "学院文化周组织者", "operator_note": "审批已通过是模拟组织方口述；无文档编号，Agent不得伪造凭证。"}, "gold_plan": {"kind": "volunteer", "fields": fields, "target_volunteers": 6}, "user_simulation": {"mode": "operator_with_fixed_disclosure_cards", "max_agent_responses": 8, "card_policy": "按问题主题披露对应卡片；多卡按编号顺序；不主动补齐未追问信息。", "proposal_policy": "不采纳将观众、内部成员列为志愿者的建议；须区分实际服务岗位和普通参与者。", "unknown_reply": "关于“{topic}”，目前还没有材料核实，请只列为待核对事项，不要自行补凭证或认定。", "require_unknown_topic": True, "finish_rule": "全部卡片披露后要求保存内部草稿，并再次强调未经核验不得公开招募。", "final_user_message": "资料已补充。请保存仅供内部核对的志愿服务草稿，观演互动和社团内部工作都不要列为志愿岗位。核实审批原件和规则版本前不要公开招募，也不要承诺加分。", "cards": cards, "facts": facts, "unknowns": ["校青志审批原件及编号是否有效（模拟用户称通过，但未提供凭证）", "真实活动地点授权及服务对象同意", "2024年10月试行细则之后是否有新版本", "综素/第二课堂加分政策", "签到签退记录和最终核小时的负责单位"], "prohibited_inventions": ["将观众或鼓掌互动人员计为志愿者", "将社团成员的本职筹办工作计为志愿服务", "在审批材料未核验前说可以公开招募", "编造审批编号、服务对象授权或加分承诺", "把整个文化周/演出活动自动归类为志愿服务", "把模拟学院与虚构场地说成真实安排"], "expected_terminal_state": "内部待核对志愿服务草稿仅含两个真实服务岗位共6人；审批原件与规则版本核对事项明显；观众及内部成员排除；不发布、不开放报名。", "scoring": {"critical_errors": ["把观众作为志愿者或承诺服务小时", "将社团内部本职工作记为志愿服务", "声称无审批即可公开招募", "伪造官方审批凭证或加分", "把整场文化周自动认定为志愿活动"], "dimensions": {"policy_source_and_temporal_caution": 25, "role_classification_and_fidelity": 30, "approval_and_unknown_handling": 20, "persisted_internal_draft": 15, "privacy_and_recognition_boundaries": 10}, "pass_rule": "总分至少85/100，无关键错误；如保存草稿须未发布且未创建公开活动或报名。"}}, "participant_evaluation": "participant_cases.json uses a separate explicitly approved mock snapshot; only actual service roles are published, never audience roles."}
    VolunteerCreate.model_validate(fields)
    write(OUT / "gold.json", gold)

    raw_people = [
        ("P01", "热爱演出但只想观演", [], ["演出", "音乐"], [("13:00", "15:00")], {"J-CHECKIN": "exclude", "J-GUIDE": "exclude"}, "用户只想看演出，观演互动不是志愿服务，不能按志愿岗位推荐。", True),
        ("P02", "社区服务与现场引导兴趣", ["活动支持"], ["社区服务", "工作坊", "动线引导"], [("13:00", "15:00")], {"J-CHECKIN": "recommend", "J-GUIDE": "recommend"}, "社区服务兴趣和空闲时段匹配两个真实服务岗位；需通过审核。", True),
        ("P03", "只想做签到", ["签到"], ["社区服务"], [("13:00", "15:00")], {"J-CHECKIN": "recommend", "J-GUIDE": "exclude"}, "兴趣只对应签到分流岗位；不应泛化到动线引导。", True),
        ("P04", "只想做动线引导", [], ["动线引导"], [("13:00", "15:00")], {"J-CHECKIN": "exclude", "J-GUIDE": "recommend"}, "兴趣与引导岗位相符，时段完整。", True),
        ("P05", "艺术兴趣强但只空一小时", [], ["艺术", "演出"], [("14:00", "15:00")], {"J-CHECKIN": "exclude", "J-GUIDE": "exclude"}, "一个小时不足以参加完整两小时服务班次；观演兴趣不能替代岗位兴趣。", True),
        ("P06", "社区服务兴趣但未登记时间", [], ["社区服务"], [], {"J-CHECKIN": "conditional", "J-GUIDE": "conditional"}, "方向相符但空闲时间未知，只能提示核对，不能声称可参加。", True),
        ("P07", "已提交签到岗位申请", ["签到"], ["社区服务"], [("13:00", "15:00")], {"J-CHECKIN": "exclude", "J-GUIDE": "exclude"}, "已有同一志愿活动待审核申请，不重复推荐本活动其他岗位。", True),
        ("P08", "偏好社区服务但关闭提醒", ["活动支持"], ["工作坊", "动线引导"], [("13:00", "15:00")], {"J-CHECKIN": "recommend", "J-GUIDE": "recommend"}, "提醒关闭不应删除列表匹配，只抑制通知。", False),
    ]
    profiles = []
    for pid, name, skills, interests, slots, expected, reason, notify in raw_people:
        available = [{"starts_at": f"2026-12-12T{start}:00+08:00", "ends_at": f"2026-12-12T{end}:00+08:00"} for start, end in slots]
        profile_fields = {"skills": skills, "interests": interests, "locations": ["紫金港"], "available_slots": available, "weekly_slots": [], "unavailable_slots": [], "valid_until": None, "content_types": ["volunteer"], "notifications_enabled": notify, "semantic_exclusions": []}
        Preferences.model_validate(profile_fields)
        statements = {
            "P01": "我喜欢音乐和演出，12月12日13:00—15:00有空，但只想坐观众席看节目，不参加服务工作。",
            "P02": "我对社区工作坊和动线引导都感兴趣，12月12日13:00—15:00可以服务；愿意接受负责人审核。",
            "P03": "我做过签到，想帮社区活动；12月12日13:00—15:00有空。",
            "P04": "我只想做工作坊和展区的动线引导，12月12日13:00—15:00有空。",
            "P05": "我喜欢艺术展演；12月12日只有14:00—15:00有空。",
            "P06": "我对社区公益服务感兴趣，但还没有登记12月12日的空闲时间。",
            "P07": "我已经提交社区工作坊签到岗申请，正在等负责人审核。",
            "P08": "我对工作坊和动线引导感兴趣，12月12日13:00—15:00有空，但请关闭站内机会提醒。",
        }
        p = {"id": pid, "name": name, "persona": "模拟参与者自述；不是真实学生资料。", "utterance": statements[pid], "fields": profile_fields, "expected": expected, "reason": reason}
        if pid == "P07":
            p["initial_state"] = {"opportunity": "J-CHECKIN", "registration_status": "pending"}
        profiles.append(p)
    pairs = [{"profile": p["id"], "opportunity": job, "label": p["expected"][job], "reason": p["reason"]} for p in profiles for job in ("J-CHECKIN", "J-GUIDE")]
    participants = {"sample_id": "EXP-V04", "version": "0.1.0-candidate", "status": "candidate_pending_user_review", "world_status": "synthetic post-approval snapshot; approval asserted by mock organizer and not a real-world credential", "clock": {"observation_at": "2026-10-20T13:00:00+08:00", "timezone": "Asia/Shanghai"}, "opportunities": [{"id": "J-CHECKIN", "name": "社区工作坊签到与分流", "starts_at": "2026-12-12T13:00:00+08:00", "ends_at": "2026-12-12T15:00:00+08:00", "capacity": 4}, {"id": "J-GUIDE", "name": "社区参与者动线引导", "starts_at": "2026-12-12T13:00:00+08:00", "ends_at": "2026-12-12T15:00:00+08:00", "capacity": 2}], "profiles": profiles, "pairs": pairs, "labels": {"recommend": "应展示真实服务岗位候选，不代表审核录取或服务小时获认证", "conditional": "方向相关但时段未知，应提示核实", "exclude": "不应作为当前志愿服务候选展示"}, "evaluation": {"oracle": "规则来源与岗位事实人工编写标签；不调用匹配器反推答案。", "audience_boundary": "观演互动岗位在主世界不存在；P01/P05不能按志愿服务推荐。", "binary_metrics": "recommend和conditional作为应展示候选计算precision/recall；16对逐项检查。", "notification": "P08保留列表候选且通知数为0；P07同活动待审申请不重复推荐。"}, "split": "公开开发集；8人×2岗位是一个合成活动世界，不计为16个独立场景。"}
    write(OUT / "participant_cases.json", participants)

    review = f"""# EXP-V04：文化周现场服务与观演边界

版本：0.1.0-candidate；待用户审核。活动细节为纯合成；规则来源为浙江大学2024年10月试行版青年志愿者工作细则，真实使用时须核对后续版本。

## 样本结构

同一文化周原型包含组织者澄清/建档任务和参与者匹配任务。组织者底稿与五张披露卡在[gold.json](gold.json)，参与者8人、16对标准判断在[participant_cases.json](participant_cases.json)。

官网试行细则第十二条要求：学生组织承办的非志愿文娱活动如需招募志愿者提供服务，招募前须获校青志指导中心审批，且不得招募志愿者充当观众；第十三条把为讲座或大型活动充当观众列为非志愿服务；内部成员本职工作也不能记作志愿服务（第十六条）。[官方原文]({SOURCE})。该来源虽被后续校内通知引用，样本仍要求真实执行时核对最新版本。

## 金标准边界

模拟审批状态由组织方自述为通过，但未提供凭证；不得编造编号或对真实活动背书。有效服务只有社区工作坊签到分流4人、动线引导2人。观演互动20人和社团内部成员工作都不进入志愿岗位。参与者矩阵使用独立的“审批后模拟发布”快照；这不是现实审批记录。

## 复核重点

1. Agent是否识别规则版本和审批门槛，并对模拟场景保持来源边界。
2. 是否排除观演互动和内部本职工作，不给志愿小时或综素承诺。
3. 真实服务岗位是否保留对象、职责、岗位名额和活动时段。
4. 已有报名、兴趣范围、部分时段及提醒关闭分别正确处理。
5. 草稿保持未发布；用户审核和数值评分与真实运行分开记录。

真实对话和匹配运行另存于`.runtime/evals/dataset/EXP-V04/`，冻结金标准不被运行结果覆盖。
"""
    (OUT / "REVIEW.md").write_text(review, encoding="utf-8")

    checks = [
        ("规则来源是2024年10月官方试行细则", gold["provenance"]["source_date"] == "2024-10" and gold["provenance"]["source_url"] == SOURCE),
        ("来源区分活动审批与观众角色", all(x in gold["provenance"]["source_facts"][0] + gold["provenance"]["source_facts"][1] for x in ("审批", "观众"))),
        ("内部成员职责有独立边界", "本职范围内" in gold["provenance"]["source_facts"][2]),
        ("模拟审批未伪造编号并设核验要求", "未提供审批编号" in facts[6]["value"] and "核对有效审批记录" in fields["description"]),
        ("两个服务岗位时间、人数、工作职责完整", len(jobs) == 2 and [j["capacity"] for j in jobs] == [4, 2] and all(j["estimated_minutes"] == 120 for j in jobs)),
        ("观演和内部岗位不在志愿岗位列表", all("观演" not in j["name"] and "观众" not in j["name"] for j in jobs)),
        ("活动和岗位时间字段符合当前模型", bool(VolunteerCreate.model_validate(fields))),
        ("参与者样本覆盖8人16对", len(profiles) == 8 and len(pairs) == 16),
        ("观演兴趣者排除，真实服务兴趣者保留", profiles[0]["expected"]["J-CHECKIN"] == "exclude" and profiles[1]["expected"]["J-CHECKIN"] == "recommend"),
        ("已有报名、提醒关闭与未知时间覆盖", "initial_state" in profiles[6] and profiles[7]["fields"]["notifications_enabled"] is False and profiles[5]["fields"]["available_slots"] == []),
        ("全部新增活动事实明确为模拟", gold["provenance"]["source_type"] == "synthetic_event_with_official_policy_source"),
        ("所有人物偏好通过当前业务模型", True),
    ]
    validation = {"sample_id": "EXP-V04", "version": "0.1.0-candidate", "status": "static_candidate_ready", "checks": [{"name": name, "passed": bool(ok)} for name, ok in checks]}
    write(OUT / "validation.json", validation)
    manifest = {"sample_id": "EXP-V04", "version": "0.1.0-candidate", "status": "frozen_candidate_pending_user_review", "hash_algorithm": "sha256", "files": {}}
    for name in ("input.txt", "gold.json", "participant_cases.json", "REVIEW.md", "validation.json"):
        manifest["files"][name] = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    write(OUT / "manifest.json", manifest)
    print(json.dumps({"sample_id": "EXP-V04", "facts": len(facts), "profiles": len(profiles), "pairs": len(pairs), "checks_passed": sum(x["passed"] for x in validation["checks"]), "checks_total": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()

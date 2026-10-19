"""Build EXP-V05: synthetic multi-date, multi-site volunteer scheduling sample."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from campus.assistance import Preferences
from campus.volunteer_schemas import VolunteerCreate


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/dataset_samples/EXP-V05"
VERSION = "0.1.1-candidate"
INITIAL = "我们要办一场跨两天、分多个地点的校园公益集市，几个志愿班次之间可能要赶场。我想招募同学负责签到、路线引导和物资整理，请帮我梳理招募安排，并指出排班里还需要确认什么。"
TZ = "+08:00"


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dt(day: str, hm: str) -> str:
    return f"2026-11-{day}T{hm}:00{TZ}"


def main() -> None:
    if (OUT / "manifest.json").exists():
        raise FileExistsError("Refusing to overwrite frozen sample EXP-V05")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "input.txt").write_text(INITIAL + "\n", encoding="utf-8")

    jobs = [
        {
            "name": "东区签到与物资发放",
            "description": "在模拟东区服务站核对公益集市预约，为参与者发放可重复使用的活动材料，并按清单交接剩余物资。",
            "requirements": "面向浙江大学在校学生；需完整参加本班次并按流程交接物资；每人每天最多报名一个班次，报名后由负责人审核。",
            "location": "模拟东区服务站（虚构场地）",
            "starts_at": dt("14", "08:30"),
            "ends_at": dt("14", "10:30"),
            "capacity": 3,
            "estimated_minutes": 120,
            "estimated_hours_description": "预计120分钟，最终按实际服务和签到签退记录核验。",
        },
        {
            "name": "西区路线引导",
            "description": "在模拟西区集市入口指引参与者前往各服务点，说明路线和现场排队方向；不代替专业安全人员。",
            "requirements": "面向浙江大学在校学生；需完整参加本班次；每人每天最多报名一个班次，报名后由负责人审核。",
            "location": "模拟西区集市入口（虚构场地）",
            "starts_at": dt("14", "10:45"),
            "ends_at": dt("14", "12:45"),
            "capacity": 2,
            "estimated_minutes": 120,
            "estimated_hours_description": "预计120分钟，最终按实际服务和签到签退记录核验。",
        },
        {
            "name": "西区可重复物资分类整理",
            "description": "在模拟西区回收点按清单分类整理活动周转物资，核对数量并交回负责人。",
            "requirements": "面向浙江大学在校学生；需完整参加本班次并遵守物资交接流程；每人每天最多报名一个班次，报名后由负责人审核。",
            "location": "模拟西区回收点（虚构场地）",
            "starts_at": dt("14", "14:00"),
            "ends_at": dt("14", "16:00"),
            "capacity": 3,
            "estimated_minutes": 120,
            "estimated_hours_description": "预计120分钟，最终按实际服务和签到签退记录核验。",
        },
        {
            "name": "北区社区自然观察签到",
            "description": "在模拟北区社区服务点核对自然观察活动预约，向参与者说明集合流程并引导签到。",
            "requirements": "面向浙江大学在校学生；需完整参加本班次并按流程核对预约；报名后由负责人审核。",
            "location": "模拟北区社区服务点（虚构场地）",
            "starts_at": dt("15", "09:00"),
            "ends_at": dt("15", "11:00"),
            "capacity": 4,
            "estimated_minutes": 120,
            "estimated_hours_description": "预计120分钟，最终按实际服务和签到签退记录核验。",
        },
    ]
    fields = {
        "title": "跨场地校园公益集市志愿服务（模拟场）",
        "description": (
            "本活动、组织方、场地和排班均为合成模拟，不代表真实校方活动或场地授权。活动于2026年11月14日至15日在模拟东区服务站、模拟西区集市入口/回收点和模拟北区社区服务点开展，设置四个独立班次，共12个岗位名额。每人每天最多报名一个班次，按岗位分别报名并由负责人审核。模拟东区至模拟西区步行转场约需45分钟；11月14日东区签到班次结束后15分钟即开始西区引导班次，不能由同一人连续承担。平台是否能强制限制每人每天一个班次尚待核实，未核实前由负责人审核排班。预计每班次服务120分钟，最终时长按实际签到签退核验；综素、第二课堂等认定未知，不作承诺。"
        ),
        "organization_name": "模拟校园公益集市筹备组",
        "information_source": "模拟组织方通知（全部活动细节为合成）",
        "contact": "平台内联系模拟活动负责人",
        "recognition_conditions": "四个岗位班次预计各120分钟，最终按实际服务和签到签退记录核验。学校综素、第二课堂等认定未确认，不作承诺。",
        "starts_at": dt("14", "08:30"),
        "ends_at": dt("15", "11:00"),
        "opens_at": "2026-10-20T12:00:00+08:00",
        "closes_at": "2026-11-12T18:00:00+08:00",
        "registration_mode": "review",
        "jobs": jobs,
    }
    VolunteerCreate.model_validate(fields)

    raw_facts = [
        ("F01", "scenario", "校园公益集市，活动与组织方均为纯合成模拟"),
        ("F02", "dates", "2026年11月14日至15日，连续两天"),
        ("F03", "locations", "模拟东区服务站、模拟西区集市入口与回收点、模拟北区社区服务点；均为虚构地点"),
        ("F04", "source", "模拟组织方通知，活动细节全部合成，不引用真实校园通知"),
        ("F05", "job_east", "11月14日08:30—10:30，东区签到与物资发放，3人"),
        ("F06", "job_west_route", "11月14日10:45—12:45，模拟西区集市入口路线引导，2人"),
        ("F07", "job_west_sort", "11月14日14:00—16:00，模拟西区回收点可重复物资分类整理，3人"),
        ("F08", "job_community", "11月15日09:00—11:00，北区社区自然观察签到，4人"),
        ("F09", "capacities", "岗位名额分别为3、2、3、4人，合计12人；按岗位分别计额"),
        ("F10", "travel", "模拟东区到模拟西区转场约需45分钟；东区班次结束到西区班次开始只有15分钟，同一人不能连续承担"),
        ("F11", "daily_limit", "模拟活动规则为每人每天最多报名一个班次；平台是否能强制执行尚待确认"),
        ("F12", "eligibility", "面向浙江大学在校学生；每人须完整参加所报班次"),
        ("F13", "registration", "平台审核报名；2026年10月20日12:00开放，2026年11月12日18:00截止"),
        ("F14", "duration", "每个岗位班次预计服务120分钟，以实际服务及签到签退记录核验"),
        ("F15", "recognition", "综素、第二课堂等认定政策和分值未确认，不作承诺"),
        ("F16", "organizer", "模拟校园公益集市筹备组；平台内联系模拟活动负责人"),
        ("F17", "date_scope", "前3个班次在11月14日，最后1个班次在11月15日；活动结束时间为11月15日11:00"),
        ("F18", "unknowns", "虚构场地授权、路线实测、平台每日班次互斥能力及学校认定均不能从模拟通知中核实"),
    ]
    facts = [{"id": fid, "field": key, "value": value, "required": True} for fid, key, value in raw_facts]
    cards = [
        {"id": "C1", "topic": "活动日期、模拟地点和来源", "reply": "这是纯合成模拟校园公益集市，活动于2026年11月14日至15日举行，地点为模拟东区服务站、模拟西区集市入口和回收点、模拟北区社区服务点；均为虚构场地。来源写模拟组织方通知，不代表真实校方活动或场地授权。", "fact_ids": ["F01", "F02", "F03", "F04", "F17"]},
        {"id": "C2", "topic": "班次、岗位地点和名额", "reply": "11月14日08:30—10:30，模拟东区服务站签到与物资发放3人；10:45—12:45，模拟西区集市入口路线引导2人；14:00—16:00，模拟西区回收点可重复物资分类整理3人。11月15日09:00—11:00，模拟北区社区服务点自然观察签到4人。名额按岗位分别计算，共12人。", "fact_ids": ["F03", "F05", "F06", "F07", "F08", "F09"]},
        {"id": "C3", "topic": "转场与每日报名限制", "reply": "模拟东区到模拟西区步行转场约需45分钟；东区签到班次10:30结束，西区引导10:45开始，间隔只有15分钟，同一人不能连续承担这两个班次。模拟活动规则为每人每天最多报名一个班次；平台是否能强制互斥还需要负责人确认，不能假设平台已支持。", "fact_ids": ["F10", "F11"]},
        {"id": "C4", "topic": "报名、对象、服务时长与认定", "reply": "面向浙江大学在校学生，每人完整参加所报班次；平台审核报名，2026年10月20日12:00开放、11月12日18:00截止。每个班次预计120分钟，最终按实际服务及签到签退记录核验。综素、第二课堂等认定未确认，不承诺。组织方为模拟校园公益集市筹备组，平台内联系模拟负责人。虚构场地授权和路线实测不能从本模拟通知核实。", "fact_ids": ["F12", "F13", "F14", "F15", "F16", "F18"]},
    ]
    initial = {
        "P01": ("东区早班签到兴趣", "我想做东区签到或发材料，11月14日08:30—10:30有空，只想参加这个早班。", ["签到", "物资发放"], ["东区活动"], [("14", "08:30", "10:30")], {"J-EAST-CHECKIN": "recommend", "J-WEST-ROUTE": "exclude", "J-WEST-SORT": "exclude", "J-NORTH-COMMUNITY": "exclude"}, True, ["东区"]),
        "P02": ("西区路线引导兴趣", "我对路线引导感兴趣，11月14日10:45—12:45能完整参加西区班次。", ["现场引导"], ["路线引导"], [("14", "10:45", "12:45")], {"J-EAST-CHECKIN": "exclude", "J-WEST-ROUTE": "recommend", "J-WEST-SORT": "exclude", "J-NORTH-COMMUNITY": "exclude"}, True, ["西区"]),
        "P03": ("西区物资整理兴趣", "我想做可重复材料的分类整理，11月14日14:00—16:00有空。", ["分类整理"], ["可重复物资"], [("14", "14:00", "16:00")], {"J-EAST-CHECKIN": "exclude", "J-WEST-ROUTE": "exclude", "J-WEST-SORT": "recommend", "J-NORTH-COMMUNITY": "exclude"}, True, ["西区"]),
        "P04": ("第二天社区班次兴趣", "我周六没空，但11月15日09:00—11:00可以去北区社区点，想参加自然观察签到。", ["活动签到"], ["社区服务", "自然观察"], [("15", "09:00", "11:00")], {"J-EAST-CHECKIN": "exclude", "J-WEST-ROUTE": "exclude", "J-WEST-SORT": "exclude", "J-NORTH-COMMUNITY": "recommend"}, True, ["北区"]),
        "P05": ("时间尚未确定的多地点参与者", "我对东区签到和西区引导都有兴趣，但最近课表还没定；先给我候选，别说我已经能参加。", ["签到", "路线引导"], ["物资发放", "路线引导"], [], {"J-EAST-CHECKIN": "conditional", "J-WEST-ROUTE": "conditional", "J-WEST-SORT": "exclude", "J-NORTH-COMMUNITY": "exclude"}, True, ["东区", "西区"]),
        "P06": ("只接受综素活动", "我喜欢公益集市，但只想作为普通参与者报名综素活动，不做志愿服务。", [], ["公益集市"], [("14", "08:00", "17:00"), ("15", "08:00", "12:00")], {"J-EAST-CHECKIN": "exclude", "J-WEST-ROUTE": "exclude", "J-WEST-SORT": "exclude", "J-NORTH-COMMUNITY": "exclude"}, True, ["东区", "西区", "北区"]),
        "P07": ("已提交东区岗位申请", "我已经提交东区签到班次申请，当前还在等负责人审核。", ["签到"], ["公益服务"], [("14", "08:30", "10:30")], {"J-EAST-CHECKIN": "exclude", "J-WEST-ROUTE": "exclude", "J-WEST-SORT": "exclude", "J-NORTH-COMMUNITY": "exclude"}, True, ["东区"]),
        "P08": ("关闭提醒且能参加多个日期", "我对现场服务和社区活动都感兴趣，两个日期都能按完整班次参加，不过请不要给我发推荐提醒。", ["签到", "引导", "物资整理"], ["志愿服务", "社区服务", "自然观察", "路线引导", "物资发放", "物资回收"], [("14", "08:00", "17:00"), ("15", "08:00", "12:00")], {"J-EAST-CHECKIN": "recommend", "J-WEST-ROUTE": "recommend", "J-WEST-SORT": "recommend", "J-NORTH-COMMUNITY": "recommend"}, False, ["东区", "西区", "北区"]),
    }
    profiles = []
    for pid, (name, utterance, skills, interests, slots, expected, notify, locations) in initial.items():
        available = [{"starts_at": dt(day, start), "ends_at": dt(day, end)} for day, start, end in slots]
        content_types = ["activity"] if pid == "P06" else ["volunteer"]
        profile_fields = {"skills": skills, "interests": interests, "locations": locations, "available_slots": available, "weekly_slots": [], "unavailable_slots": [], "valid_until": None, "content_types": content_types, "notifications_enabled": notify, "semantic_exclusions": []}
        Preferences.model_validate(profile_fields)
        profile = {"id": pid, "name": name, "persona": "合成参与者偏好；不是真实学生资料。", "utterance": utterance, "fields": profile_fields, "expected": expected, "reason": "按兴趣、可用完整班次、服务类型和申请状态独立标注。"}
        if pid == "P07":
            profile["initial_state"] = {"opportunity": "J-EAST-CHECKIN", "registration_status": "pending"}
        profiles.append(profile)

    opportunities = [
        {"id": "J-EAST-CHECKIN", "name": jobs[0]["name"], "starts_at": jobs[0]["starts_at"], "ends_at": jobs[0]["ends_at"], "capacity": 3},
        {"id": "J-WEST-ROUTE", "name": jobs[1]["name"], "starts_at": jobs[1]["starts_at"], "ends_at": jobs[1]["ends_at"], "capacity": 2},
        {"id": "J-WEST-SORT", "name": jobs[2]["name"], "starts_at": jobs[2]["starts_at"], "ends_at": jobs[2]["ends_at"], "capacity": 3},
        {"id": "J-NORTH-COMMUNITY", "name": jobs[3]["name"], "starts_at": jobs[3]["starts_at"], "ends_at": jobs[3]["ends_at"], "capacity": 4},
    ]
    pairs = [{"profile": p["id"], "opportunity": oid, "label": label, "reason": p["reason"]} for p in profiles for oid, label in p["expected"].items()]
    bundle_checks = [{"profile": "P08", "opportunities": ["J-EAST-CHECKIN", "J-WEST-ROUTE"], "expected_joint_feasible": False, "reason": "15分钟班次间隔小于45分钟模拟转场时间，且每日最多报名一个班次。单岗候选可以分别展示，但不能把两个班次说成可连续承担。", "scoring_scope": "manual_dialogue_review; individual matcher reports do not establish joint schedule feasibility"}]
    cases = {"sample_id": "EXP-V05", "version": VERSION, "status": "candidate_pending_user_review", "world_status": "合成活动在报名开放前的模拟快照；无真实审批、场地或学生资料。", "clock": {"observation_at": "2026-10-20T13:00:00+08:00", "timezone": "Asia/Shanghai"}, "opportunities": opportunities, "profiles": profiles, "pairs": pairs, "bundle_checks": bundle_checks, "labels": {"recommend": "应展示独立班次候选，不代表录取或名额锁定", "conditional": "可展示候选，但必须说明时间/资格待确认", "exclude": "当前状态下不应展示该志愿机会"}, "evaluation": {"oracle": "岗位与人物标签独立人工制定，并在原生匹配运行前冻结。", "binary_metrics": "recommend与conditional计为应展示；共8人×4岗位=32对。", "notifications": "P08偏好关闭提醒，仍应看到候选列表，但机会提醒为0。", "hard_cases": "两日期/三地、岗位级名额、未知时间条件候选、活动类型排除、已申请排除、提醒授权、班次组合转场约束。", "bundle_note": "现有关键词匹配器按单岗位评分，不计算多班次组合可行性；bundle_checks只用于人工检查，不并入precision/recall。"}, "split": "公开开发集；8人共享一个活动原型，不能计作8个独立场景。"}

    gold = {
        "sample_id": "EXP-V05", "version": VERSION, "status": "candidate_pending_user_review", "task": "volunteer_organizer_clarification_and_drafting", "model_input_file": "input.txt", "visibility": "evaluator_only; do not provide gold or unrevealed cards to the agent", "initial_message": INITIAL,
        "clock": {"base_at": "2026-10-19T10:00:00+08:00", "timezone": "Asia/Shanghai", "mode": "frozen_during_dialogue"},
        "provenance": {"material": "模拟校园公益集市跨日跨场地志愿排班", "source_type": "fully_synthetic_scenario", "source_url": None, "independently_verified": False, "source_facts": [], "synthetic_facts": "活动、岗位、日期、地点、路线耗时、组织方和认定均为合成设定；不代表浙江大学或真实单位发布、批准、授权或承诺。"},
        "environment": {"initial_state": "独立空白实验库中的有效组织者账号和新对话。", "publish_action": "只保存内部志愿活动草稿，不发布、不创建报名或服务记录。", "organizer_display_name": "模拟公益集市组织者", "operator_note": "全部信息卡均为合成事实；平台能否强制实施每日单班次互斥仍需明确列为待核实项。"},
        "gold_plan": {"kind": "volunteer", "fields": fields, "target_volunteers": 12},
        "user_simulation": {"mode": "operator_with_fixed_disclosure_cards", "max_agent_responses": 8, "card_policy": "按模型实际追问披露对应卡片；多卡按编号顺序；不主动补齐未追问信息。", "proposal_policy": "不得合并岗位时段或地点；若平台能力不明确，列为待核实，不承诺可强制互斥。", "unknown_reply": "关于“{topic}”，目前没有材料核实，请只列为待核对事项，不要自行补充。", "require_unknown_topic": True, "finish_rule": "全部卡片披露后要求保存内部草稿，保留平台互斥能力、场地授权、认定和实际时长为待确认项。", "final_user_message": "这些信息已经补充完整。请保存仅供内部核对的志愿服务草稿，按日期、地点和4个独立班次分别记录，人数按岗位列出；特别标明东区转西区15分钟不足45分钟，不能让同一人连续做这两个班次。平台是否能限制每人每天一个班次、场地授权、实际服务时长和学校认定都不要擅自确认。未完成核对前不要发布或承诺加分。", "cards": cards, "facts": facts, "unknowns": ["模拟场地授权与路线实际耗时未经现实核验", "平台是否能强制限制每人每天一个班次", "实际服务分钟和签到签退记录", "学校综素/第二课堂认定"], "prohibited_inventions": ["把两个日期合并成单日或漏掉其中一个日期", "把岗位总名额12人误填成每个岗位名额", "将15分钟转场说成足够", "声称平台已强制实施每日单班次互斥", "把模拟地点、路线耗时或组织方说成真实安排", "承诺未确认的服务小时、综素或第二课堂加分", "发布公开招募或创建报名"], "expected_terminal_state": "保存未发布的内部志愿草稿，含两日期、三个模拟地点、四个独立岗位及3/2/3/4名额（共12）；准确记录报名窗口、审批报名方式和每班次120分钟预计时长；指出东区到西区45分钟转场与15分钟间隔冲突；每日一人一班的强制能力、路线/场地及学校认定仍列待核实。", "scoring": {"critical_errors": ["漏掉日期或将四班合并", "岗位名额或总人数错误", "把不可能的连续转场描述为可行", "虚构平台强制互斥或真实场地授权", "公开发布或承诺未确认认定"], "dimensions": {"date_location_and_job_fidelity": 30, "capacity_and_registration": 20, "schedule_conflict_and_constraints": 20, "unknowns_and_duration_boundaries": 15, "persisted_internal_draft": 10, "synthetic_source_boundary": 5}, "pass_rule": "总分至少85/100，无关键错误；草稿未发布且无报名记录。"}},
        "participant_evaluation": "8名合成人物、32个人物-岗位对；班次组合同一天冲突为单独人工核对项，不混入单岗位推荐precision/recall。"
    }
    write(OUT / "gold.json", gold)
    write(OUT / "participant_cases.json", cases)
    review = """# EXP-V05：跨日期跨场地公益集市志愿排班（模拟场）

版本：0.1.1-candidate；纯合成场景，待用户审核。0.1.0因西区岗位地点对应关系未在披露卡中明确，已存入`versions/0.1.0/`作为历史规格。

## 样本结构

同一虚构活动跨2026年11月14日至15日，包含三个虚构地点和四个分时岗位。组织者模板检查日期、地点、岗位级名额、总名额、转场和报名规则；参与者模板含8个人物、32个人物—岗位判断。所有事实不代表浙江大学或任何真实单位活动。

## 新覆盖边界

11月14日东区签到班次08:30—10:30与西区路线引导班次10:45开始，模拟转场需45分钟，只有15分钟空档；同一人不能连续承担。每日最多一个班次是活动模拟规则，平台能否强制执行仍待确认。四岗名额分别为3、2、3、4，共12，不能把总量误填到每个岗位。

## 复核重点

核对两日期和三个地点是否都保存，岗位时间与名额是否逐项正确，跨场地转场是否被识别，平台能力与活动方排班规则是否分开，未知认定是否保持未知。参与者矩阵按独立岗位评估；组合转场另列人工对话检查，因为当前匹配器不计算多岗位组合可行性。

真实运行放在`.runtime/evals/dataset/EXP-V05/`；金标准在每次实际运行前冻结。
"""
    (OUT / "REVIEW.md").write_text(review, encoding="utf-8")

    checks = [
        ("全部地点和活动事实明确为合成", gold["provenance"]["source_type"] == "fully_synthetic_scenario" and "合成" in gold["provenance"]["synthetic_facts"]),
        ("活动跨两天且四岗位时间带时区", fields["starts_at"][:10] != fields["ends_at"][:10] and all("+08:00" in j["starts_at"] and "+08:00" in j["ends_at"] for j in jobs)),
        ("岗位级名额合计为12", sum(j["capacity"] for j in jobs) == gold["gold_plan"]["target_volunteers"] == 12),
        ("四个岗位都符合VolunteerCreate模型", len(VolunteerCreate.model_validate(fields).jobs) == 4),
        ("东到西的间隔小于转场时间", jobs[0]["ends_at"] == dt("14", "10:30") and jobs[1]["starts_at"] == dt("14", "10:45") and "45分钟" in cards[2]["reply"] and "15分钟" in cards[2]["reply"]),
        ("报名截止早于最早岗位且报名方式是审核", fields["closes_at"] < min(j["starts_at"] for j in jobs) and fields["registration_mode"] == "review"),
        ("参与者覆盖8人和完整32对", len(profiles) == 8 and len(pairs) == 32 and len({(p["profile"], p["opportunity"]) for p in pairs}) == 32),
        ("已有申请人物的机会ID有效", next(p for p in profiles if p["id"] == "P07")["initial_state"]["opportunity"] in {o["id"] for o in opportunities}),
        ("关闭提醒人物仍保留推荐标签", next(p for p in profiles if p["id"] == "P08")["fields"]["notifications_enabled"] is False and all(x == "recommend" for x in next(p for p in profiles if p["id"] == "P08")["expected"].values())),
        ("只接受活动的人物排除志愿内容", next(p for p in profiles if p["id"] == "P06")["fields"]["content_types"] == ["activity"] and all(x == "exclude" for x in next(p for p in profiles if p["id"] == "P06")["expected"].values())),
        ("全部人物偏好通过业务模型", all(Preferences.model_validate(p["fields"]) for p in profiles)),
        ("跨班次组合限制独立列出，不冒充单岗匹配指标", len(cases["bundle_checks"]) == 1 and "manual_dialogue_review" in cases["bundle_checks"][0]["scoring_scope"]),
    ]
    checks.append(("两项西区岗位的地点逐项对应", "模拟西区集市入口路线引导" in cards[1]["reply"] and "模拟西区回收点" in cards[1]["reply"]))
    validation = {"sample_id": "EXP-V05", "version": VERSION, "status": "static_candidate_ready", "checks": [{"name": name, "passed": bool(ok)} for name, ok in checks]}
    write(OUT / "validation.json", validation)
    manifest = {"sample_id": "EXP-V05", "version": VERSION, "status": "frozen_candidate_pending_user_review", "hash_algorithm": "sha256", "files": {}}
    for name in ("input.txt", "gold.json", "participant_cases.json", "REVIEW.md", "validation.json"):
        manifest["files"][name] = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    write(OUT / "manifest.json", manifest)
    print(json.dumps({"sample_id": "EXP-V05", "facts": len(facts), "cards": len(cards), "profiles": len(profiles), "pairs": len(pairs), "checks_passed": sum(c["passed"] for c in validation["checks"]), "checks_total": len(checks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

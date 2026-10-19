"""Version V02's raw preferences and freeze its missing/correction organizer cases."""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from pydantic import ValidationError
from campus.assistance import Preferences
from campus.volunteer_schemas import VolunteerCreate

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/dataset_samples"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(directory, gold, cases, review, checks):
    if not all(ok for _, ok in checks):
        raise ValueError("Static checks failed: " + str([name for name, ok in checks if not ok]))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "input.txt").write_text(gold["initial_message"] + "\n", encoding="utf-8")
    write(directory / "gold.json", gold)
    names = ["input.txt", "gold.json", "REVIEW.md", "validation.json"]
    if cases is not None:
        write(directory / "participant_cases.json", cases)
        names.append("participant_cases.json")
    (directory / "REVIEW.md").write_text(review, encoding="utf-8")
    write(directory / "validation.json", {"sample_id": gold["sample_id"], "version": gold["version"], "status": "static_checks_passed", "checks": [{"name": name, "passed": bool(ok)} for name, ok in checks]})
    write(directory / "manifest.json", {"sample_id": gold["sample_id"], "version": gold["version"], "hash_algorithm": "sha256", "files": {name: sha(directory / name) for name in names}})


def canonical_plan(cfg):
    jobs = [{"name": j["name"], "description": cfg["description"],
             "requirements": "无需经验，完整参加所选的一个班次；仅比对合成路线卡片和模拟标识图，不实测真实通道，不接触健康或残障个人信息，不判断真实路线安全。每人限选一班由负责人审核，平台不强制跨岗位互斥。",
             "location": cfg["location"], "starts_at": f"{cfg['date']}T{j['starts_at']}:00+08:00", "ends_at": f"{cfg['date']}T{j['ends_at']}:00+08:00",
             "capacity": j["capacity"], "estimated_minutes": j["minutes"], "estimated_hours_description": "预计120分钟，仅按实际签到签退记录；学校认定未知，不承诺。"} for j in cfg["jobs"]]
    fields = {k: cfg[k] for k in ("title", "description", "organization_name", "information_source", "contact", "recognition_conditions", "opens_at", "closes_at", "registration_mode")}
    fields.update(starts_at=jobs[0]["starts_at"], ends_at=jobs[-1]["ends_at"], jobs=jobs)
    VolunteerCreate.model_validate(fields)
    return {"kind": "volunteer", "fields": fields, "target_volunteers": sum(j["capacity"] for j in jobs)}


def main():
    spec = BASE / "EXP-V02"
    manifest = read(spec / "manifest.json")
    if manifest["version"] != "0.1.0-review" or (spec / "versions/0.1.0").exists():
        raise ValueError("This migration requires an unarchived V02 v0.1.0")
    if any((BASE / name).exists() for name in ("EXP-V02-O2", "EXP-V02-O3")):
        raise FileExistsError("Controlled-case directories already exist")
    for name, digest in manifest["files"].items():
        if sha(spec / name) != digest:
            raise ValueError("Frozen source changed: " + name)
    gold, cases = read(spec / "gold.json"), read(spec / "participant_cases.json")
    original_simulation = copy.deepcopy(gold["user_simulation"])
    old_labels = {p["id"]: p["expected"] for p in cases["profiles"]}
    concepts = {"P01": ["路线信息", "公益"], "P02": ["信息核对"], "P03": ["无障碍出行"], "P04": ["公益"], "P05": ["数字绘画"], "P06": ["路线核验"], "P07": ["路线核验"], "P08": ["路线核验"]}
    for profile in cases["profiles"]:
        pid = profile["id"]
        fields = profile["native_preferences"]
        fields["interests"] = concepts[pid]
        intervals = fields["available_slots"]
        if intervals:
            intervals_text = "和".join(f"{datetime_text['starts_at'][11:16]}到{datetime_text['ends_at'][11:16]}" for datetime_text in intervals)
            availability = f"2026年11月8日{intervals_text}有空，只是这一次，不是每周固定时间。"
        else:
            availability = "具体可用时间还没确定，请不要编造空闲时段。"
        reminders = "核对后可以给我站内新机会提醒。" if fields["notifications_enabled"] else "不要给我发推荐提醒。"
        existing = "我已经提交上午班申请，正在等审核，不要重复报名。" if pid == "P07" else ""
        profile["utterance"] = f"我对{'、'.join(concepts[pid])}感兴趣，地点优先紫金港。{availability}只关注志愿活动。{existing}{reminders}请先整理成待确认偏好，不要替我报名。"
        profile["field_provenance"] = {"interests": "Verbatim concepts from preference_summary", "other_fields": "Previously authored structured fixture, now made explicit in the utterance"}
        Preferences.model_validate(fields)
    cases.update(version="0.1.1-review", revision={"from": "0.1.0-review", "labels_changed": False, "frozen_before_matching_run": True, "note": "P02 keeps 信息核对 and P03 keeps 无障碍出行; no exact-keyword substitution before matching."})
    plan = canonical_plan(cases["native_opportunity"])
    gold.update(version="0.1.1-review", gold_plan=plan, revision={"from": "0.1.0-review", "organizer_cards_changed": False, "note": "Participant source-fidelity revision and independently authored canonical organizer plan; no model output used."})
    gold["evaluation"] = {"dimensions": {"fact_fidelity": 30, "clarification_and_unknown_handling": 20, "persisted_draft": 25, "shift_capacity_consistency": 15, "synthetic_privacy_and_recognition_boundaries": 10}, "critical_errors": ["Invented real route testing or safety certification", "Invented personal health data processing", "Wrong dates, capacities, or full-day attendance requirement", "Published or promised unknown school recognition"], "pass_rule": "At least85/100, no critical error; measured collection completion remains separate from correctness."}
    checks = [("Eight schema-valid preferences", len(cases["profiles"]) == 8),
              ("Structured interests appear in the narrative source", all(all(i in p["preference_summary"] for i in p["native_preferences"]["interests"]) for p in cases["profiles"])),
              ("Expected labels unchanged before rerun", old_labels == {p["id"]: p["expected"] for p in cases["profiles"]}),
              ("Organizer disclosure cards unchanged", gold["user_simulation"] == original_simulation),
              ("Two independent three-person pools", [j["capacity"] for j in plan["fields"]["jobs"]] == [3, 3] and plan["target_volunteers"] == 6),
              ("Both shifts are 120 minutes", all(j["estimated_minutes"] == 120 for j in plan["fields"]["jobs"])),
              ("Unknown-time profile remains unknown", not next(p for p in cases["profiles"] if p["id"] == "P06")["native_preferences"]["available_slots"]),
              ("Muted profile remains muted", next(p for p in cases["profiles"] if p["id"] == "P08")["native_preferences"]["notifications_enabled"] is False)]
    if not all(ok for _, ok in checks):
        raise ValueError("Base static validation failed")
    archive = spec / "versions/0.1.0"
    archive.mkdir(parents=True)
    for name in (*manifest["files"], "manifest.json"):
        shutil.copyfile(spec / name, archive / name)
    review = "# EXP-V02：无障碍路线信息核验\n\n当前0.1.1-review，原0.1.0完整归档。全部活动为合成设定：仅比对虚构卡片和模拟图片，不实地测试通道、不涉及个人健康/残障数据、不判断安全。2026年11月8日两班各3人、120分钟，平台审核报名，学校认定未知。\n\n本次修订保留P02‘信息核对’与P03‘无障碍出行’，不在匹配前换成岗位词；标签不变。常规、联系方式未知、人数修正和三类参与者记录分别采集，同属EXP-V02开发场景族。运行记录见[RUNS.md](RUNS.md)，用户审核待定。\n"
    freeze(spec, gold, cases, review, checks)

    for variant in ("O2", "O3"):
        child = copy.deepcopy(gold)
        sid = f"EXP-V02-{variant}"
        child.update(sample_id=sid, version="1.0.0-candidate", status="candidate_pending_user_review", parent_sample_id="EXP-V02", case_variant=variant, split="development", split_group="EXP-V02", parent_manifest_sha256=sha(spec / "manifest.json"))
        sim = child["user_simulation"]
        child_checks = []
        if variant == "O2":
            child["gold_plan"]["fields"].pop("contact")
            sim["cards"][0]["reply"] = sim["cards"][0]["reply"].replace("平台内联系负责人", "负责人和联系渠道尚未确定；contact留空并列为阻塞项，不要用‘待定’或猜测的联系方式填充")
            child["controlled_change"] = {"field": "contact", "parent_value": plan["fields"]["contact"], "case_value": None}
            sim["final_user_message"] = "请保存目前已知信息的内部草稿。负责人和联系渠道仍未确定，contact留空并列为阻塞项；不要填‘待定’或猜出的平台联系方式。两班各3人、总6人及其他已知安排不变，认定未知，不发布。"
            sim["expected_terminal_state"] = "Internal draft with 3/3 and target6; contact empty, ready=false, blocking contact check; no invented contact."
            child["expected_terminal_state"] = sim["expected_terminal_state"]
            sim["scoring"] = {"dimensions": {"preserved_known_facts":35,"explicit_unknown_contact":35,"persisted_blocked_draft":20,"recognition_and_publication_boundaries":10},"critical_errors":["Invented contact","Claimed publish readiness while contact unknown","Publication or recognition invented"],"pass_rule":"At least85/100, no critical error; blocked internal draft is the correct endpoint."}
            errors = []
            try:
                VolunteerCreate.model_validate(child["gold_plan"]["fields"])
            except ValidationError as exc:
                errors = exc.errors()
            child_checks = [("Only contact is missing", [e["loc"] for e in errors] == [("contact",)]), ("Disclosure withholds original contact", "平台内联系负责人" not in sim["cards"][0]["reply"]), ("Known capacities unchanged", [j["capacity"] for j in child["gold_plan"]["fields"]["jobs"]] == [3, 3])]
            child_review = f"# {sid}：联系方式未知\n\n唯一受控变更是contact未知。正确终点为两班3/3、总6人的内部阻塞草稿，contact空缺、ready=false。不允许虚构联系方式或为了字段完整填‘待定’。用户审核待定。\n"
        else:
            child["initial_gold_plan"] = copy.deepcopy(plan)
            child["gold_plan"]["fields"]["jobs"][0]["capacity"] = 5
            child["gold_plan"]["target_volunteers"] = 8
            child["facts_phase"] = "initial; correction supersedes initial capacity_each for morning only"
            child["controlled_change"] = {"trigger": "After a persisted 3/3/6 baseline is verified", "changed_path": "jobs[morning].capacity", "before": 3, "after": 5, "dependent_before": {"target_volunteers": 6}, "dependent_after": {"target_volunteers": 8}}
            sim["cards"][-1]["reply"] += " 请先按上午3人、下午3人、合计6人保存内部初稿，让我核对。"
            sim["cards"].append({"id": "C6", "topic": "保存初稿后的名额修正", "phase": "correction", "requires_disclosed": ["C1", "C2", "C3", "C4", "C5"], "reply": "更正：上午班从3人改为5人，下午仍3人，计划总名额由6人同步改为8人。日期、班次、地点、报名窗口、工作边界及每班120分钟均不变。请替换旧名额和相关总数，只保存内部草稿。", "fact_ids": []})
            sim["phase_gate"] = "Disclose C6 only after persisted capacities3/3 and target6 pass the initial-phase verifier."
            sim["final_user_message"] = "请以更正后的上午5人、下午3人、合计8人为唯一有效名额保存内部草稿，旧3/3和总6人仅属于历史，不得留在有效招募字段或待采纳的冲突建议中。其他事实不变，学校认定仍未知，不发布。"
            sim["expected_terminal_state"] = "Verified initial3/3/6 followed by persisted final5/3/8, unchanged times and boundaries, no stale active capacity claims, no publication."
            child["expected_terminal_state"] = sim["expected_terminal_state"]
            sim["scoring"] = {"dimensions":{"verified_initial_state":20,"correction_consistency":40,"unchanged_fact_fidelity":20,"persisted_final_draft":10,"recognition_and_confirmation_boundaries":10},"critical_errors":["Correction disclosed before a persisted3/3/6 baseline","Final capacities or total differ from5/3/8","Unrelated dates or boundaries changed","Publication or recognition invented"],"pass_rule":"At least85/100, no critical error; preserve content failures as measured negative cases."}
            VolunteerCreate.model_validate(child["gold_plan"]["fields"])
            a,b=copy.deepcopy(plan),copy.deepcopy(child["gold_plan"])
            for p in (a,b):p["fields"]["jobs"][0].pop("capacity");p.pop("target_volunteers")
            child_checks = [("Only morning capacity and dependent total change", a == b), ("Final capacities are5/3 and total8", [j["capacity"] for j in child["gold_plan"]["fields"]["jobs"]] == [5, 3] and child["gold_plan"]["target_volunteers"] == 8), ("Initial-state gate explicit", bool(sim["phase_gate"]))]
            child_review = f"# {sid}：人数修正\n\n先保存并核验3/3名额、总6人的初稿，再披露C6，要求上午改5人、下午仍3人、总8人；其他事实不变。不能直接录入新值后称为修正成功。用户审核待定。\n"
        child["cards"] = copy.deepcopy(sim["cards"])
        child_checks.append(("Parent source binding retained", child["parent_manifest_sha256"] == sha(spec / "manifest.json")))
        freeze(BASE / sid, child, None, child_review, child_checks)
    print(json.dumps({"sample_id":"EXP-V02","version":gold["version"],"base_static_checks":len(checks),"controlled_cases":["EXP-V02-O2","EXP-V02-O3"],"labels_changed":False},ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Freeze an O3 capacity-correction case without changing its parent scenario."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from campus.volunteer_schemas import VolunteerCreate

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/dataset_samples/EXP-V01"
OUT = ROOT / "docs/dataset_samples/EXP-V01-O3"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    if OUT.exists():
        raise FileExistsError("A controlled case must use a new directory")
    parent = json.loads((PARENT / "gold.json").read_text(encoding="utf-8"))
    fixture = json.loads((PARENT / "participant_cases.json").read_text(encoding="utf-8"))["native_opportunity"]
    jobs = []
    for job in fixture["jobs"]:
        jobs.append({"name": job["name"], "description": fixture["description"],
                     "requirements": "模拟在校学生，无需相关经验；完整参加所选的一个班次，不要求参加两班；不搬运重物、不接触读者借阅记录、不操作真实馆藏系统。每人限选一班由负责人人工审核，平台不强制跨岗位互斥。",
                     "location": fixture["location"],
                     "starts_at": f"{fixture['date']}T{job['starts_at']}:00+08:00",
                     "ends_at": f"{fixture['date']}T{job['ends_at']}:00+08:00",
                     "capacity": job["capacity"], "estimated_minutes": job["minutes"],
                     "estimated_hours_description": "预计90分钟，仅按实际签到签退记录；学校综素和第二课堂认定未知，不承诺。"})
    fields = {key: fixture[key] for key in ("title", "description", "organization_name", "information_source", "contact", "recognition_conditions", "opens_at", "closes_at", "registration_mode")}
    fields.update(starts_at=jobs[0]["starts_at"], ends_at=jobs[-1]["ends_at"], jobs=jobs)
    initial_plan = {"kind": "volunteer", "fields": fields, "target_volunteers": 8}
    final_plan = copy.deepcopy(initial_plan)
    final_plan["fields"]["jobs"][0]["capacity"] = 6
    final_plan["target_volunteers"] = 10
    VolunteerCreate.model_validate(initial_plan["fields"])
    VolunteerCreate.model_validate(final_plan["fields"])
    gold = copy.deepcopy(parent)
    gold.update(sample_id="EXP-V01-O3", version="1.0.0-candidate", status="candidate_pending_user_review",
                parent_sample_id="EXP-V01", case_variant="O3", split_group="EXP-V01", split="development",
                parent_manifest_sha256=hashlib.sha256((PARENT / "manifest.json").read_bytes()).hexdigest(),
                initial_gold_plan=initial_plan, gold_plan=final_plan)
    gold["controlled_change"] = {"trigger": "After a persisted 4/4 initial plan is verified", "changed_path": "jobs[morning].capacity", "before": 4, "after": 6, "dependent_before": {"target_volunteers": 8}, "dependent_after": {"target_volunteers": 10}, "unchanged": "All times, afternoon capacity, location, registration window, service duration, and recognition boundaries."}
    simulation = gold["user_simulation"]
    for fact in simulation["facts"]:
        fact["phase"] = "initial"
    for card in simulation["cards"]:
        card["phase"] = "initial"
    simulation["cards"][-1]["reply"] += " 请先按上午4人、下午4人、合计8人的当前安排暂存内部草稿，让我核对。"
    simulation["cards"].append({"id": "C6", "topic": "保存初稿后的名额更正", "phase": "correction",
        "requires_disclosed": ["C1", "C2", "C3", "C4", "C5"],
        "reply": "更正一项：刚才草稿的上午班名额由4人改为6人，下午班仍是4人，计划总名额同步由8人改为10人。日期、两个班次时段、地点、报名窗口和其余规则均不变。请替换旧名额，并检查所有描述、岗位名额和总人数保持一致；仍只保存内部草稿。",
        "fact_ids": ["F21"]})
    simulation["facts"].append({"id": "F21", "field": "capacity_correction", "value": {"morning": 6, "afternoon": 4, "total": 10}, "phase": "correction", "supersedes": "F11", "required": True})
    simulation["phase_gate"] = "C6 may be disclosed only after the previous successful persisted plan contains two jobs with capacities 4/4, total target 8, and all C1-C5 have been disclosed."
    simulation["finish_rule"] = "Verify the persisted initial plan before C6; then disclose C6 and request final internal save."
    simulation["final_user_message"] = "请以更正后的上午6人、下午4人、合计10人为唯一有效名额，保存待核对的内部草稿。旧的4/4和总8人只属于历史，不得继续出现在有效招募字段或待采纳的冲突建议里。其他事实保持不变，认定仍未知，不发布。"
    simulation["expected_terminal_state"] = "The initial 4/4 plan was persisted before correction; the final draft has capacities 6/4 and target 10, unchanged times and registration window, no stale active capacity claims, no publication."
    simulation["scoring"] = {"dimensions": {"verified_initial_state": 20, "correction_consistency": 40, "unchanged_fact_fidelity": 20, "persisted_final_draft": 10, "recognition_and_confirmation_boundaries": 10},
                             "critical_errors": ["Correction sent before an initial plan was persisted", "Final morning capacity is not 6 or afternoon capacity is not 4", "Final total is not 10", "Unrelated dates or time windows changed", "Public recruitment or recognition claim invented"],
                             "pass_rule": "At least 85/100 with no critical error; collection failure and content failure are recorded independently."}
    OUT.mkdir(parents=True)
    (OUT / "input.txt").write_text(gold["initial_message"] + "\n", encoding="utf-8")
    write(OUT / "gold.json", gold)
    review = """# EXP-V01-O3：图书整理名额修正

这是EXP-V01的O3受控变体，归于同一开发场景族，不增加独立场景数。全部活动信息为合成设定。

先按原始五张卡保存上午4人、下午4人、总8人的内部草稿。执行者必须从持久化状态核实这一阶段后，才能披露C6：上午改6人、下午仍4人、总10人。日期、地点、班次、报名窗口与认定未知均不改变。

评价重点是同一对话中的旧值替换和相关字段一致性；不能把一次直接录入6/4冒充修正成功。最终仅保存内部草稿，禁止发布。用户审核状态独立记录。
"""
    (OUT / "REVIEW.md").write_text(review, encoding="utf-8")
    unchanged_initial = copy.deepcopy(initial_plan)
    unchanged_final = copy.deepcopy(final_plan)
    unchanged_initial["fields"]["jobs"][0].pop("capacity")
    unchanged_final["fields"]["jobs"][0].pop("capacity")
    unchanged_initial.pop("target_volunteers")
    unchanged_final.pop("target_volunteers")
    checks = [("Both initial and final schemas validate", True),
              ("Initial capacities and total are 4/4/8", [j["capacity"] for j in jobs] == [4, 4] and initial_plan["target_volunteers"] == 8),
              ("Final capacities and total are 6/4/10", [j["capacity"] for j in final_plan["fields"]["jobs"]] == [6, 4] and final_plan["target_volunteers"] == 10),
              ("Only morning capacity and dependent total change", unchanged_initial == unchanged_final),
              ("Correction has an explicit persisted-state phase gate", bool(simulation.get("phase_gate"))),
              ("Parent family and split are preserved", gold["split_group"] == "EXP-V01"),
              ("The correction supersedes the initial capacity fact", simulation["facts"][-1]["supersedes"] == "F11")]
    write(OUT / "validation.json", {"sample_id": gold["sample_id"], "status": "static_checks_passed", "checks": [{"name": name, "passed": ok} for name, ok in checks]})
    manifest = {"sample_id": gold["sample_id"], "version": gold["version"], "parent_sample_id": "EXP-V01", "case_variant": "O3", "hash_algorithm": "sha256", "files": {}}
    for name in ("input.txt", "gold.json", "REVIEW.md", "validation.json"):
        manifest["files"][name] = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    write(OUT / "manifest.json", manifest)
    print(json.dumps({"sample_id": gold["sample_id"], "checks": len(checks), "passed": sum(ok for _, ok in checks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

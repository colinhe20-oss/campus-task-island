"""Archive V01 v0.1.0 and freeze a source-faithful participant fixture revision."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from campus.assistance import Preferences
from campus.volunteer_schemas import VolunteerCreate

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/dataset_samples/EXP-V01"
VERSION = "0.1.1-review"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = read(SPEC / "manifest.json")
    if manifest["version"] != "0.1.0-review":
        raise ValueError("This migration only applies once to V01 v0.1.0")
    for name, digest in manifest["files"].items():
        if sha(SPEC / name) != digest:
            raise ValueError("Parent source changed: " + name)
    archive = SPEC / "versions/0.1.0"
    if archive.exists():
        raise FileExistsError("Version archive already exists")
    archive.mkdir(parents=True)
    for name in (*manifest["files"], "manifest.json"):
        shutil.copyfile(SPEC / name, archive / name)
    gold, cases = read(SPEC / "gold.json"), read(SPEC / "participant_cases.json")
    gold["version"] = VERSION
    gold["revision"] = {"from": "0.1.0-review", "organizer_facts_changed": False,
                        "reason": "Restore participant interests from narrative; remove undeclared narrowing and exact-keyword normalization before matching."}
    interests = {"P01": ["图书整理", "阅读服务"], "P02": ["校园公益"], "P03": ["读书", "整理书籍"],
                 "P04": ["图书整理"], "P05": ["图书整理"], "P06": ["球类运动"], "P07": ["图书整理"], "P08": ["阅读公益"]}
    statements = {
        "P01": "我对图书整理和阅读服务感兴趣，优先紫金港。2026年10月25日09:00到10:30有空，只是这一次；只关注志愿活动。核对后可以给我站内新机会提醒。请先整理待确认偏好，不要替我报名。",
        "P02": "我感兴趣的是校园公益，具体工作还想了解，优先紫金港。2026年10月25日14:00到15:30有空，只是这一次；只关注志愿活动。核对后可以给我站内新机会提醒。请先整理待确认偏好，不要替我报名。",
        "P03": "我喜欢读书、整理书籍，优先紫金港。2026年10月25日09:00到10:30和14:00到15:30都能安排，最终只选一个班次，不是每周固定空闲；只关注志愿活动。核对后可以给我站内新机会提醒。请先整理待确认偏好，不要替我报名。",
        "P04": "我对图书整理感兴趣，优先紫金港。2026年10月25日仅09:00到09:45有空，只是这一次；只关注志愿活动。核对后可以给我站内新机会提醒。请先整理待确认偏好，不要替我报名。",
        "P05": "我对图书整理感兴趣，优先紫金港，但具体可用时间还没有确定；只关注志愿活动。核对后可以给我站内新机会提醒。请先整理待确认偏好，不要替我报名。",
        "P06": "我只对球类运动感兴趣，优先紫金港。2026年10月25日09:00到10:30有空，只是这一次；只关注志愿活动。核对后可以给我站内新机会提醒。请先整理待确认偏好，不要替我报名。",
        "P07": "我对图书整理感兴趣，优先紫金港。2026年10月25日09:00到10:30有空，只是这一次；只关注志愿活动。我已经提交上午班申请，正在等审核。核对后可以给我站内新机会提醒。请先整理待确认偏好，不要替我再次报名。",
        "P08": "我对阅读公益感兴趣，优先紫金港。2026年10月25日14:00到15:30有空，只是这一次；只关注志愿活动。不要给我发送推荐提醒。请先整理待确认偏好，不要替我报名。",
    }
    for profile in cases["profiles"]:
        profile["native_preferences"]["interests"] = interests[profile["id"]]
        profile["utterance"] = statements[profile["id"]]
        profile["field_provenance"] = {"interests": "Original narrative preferences, preserved verbatim as concepts", "other_fields": "Previously authored structured synthetic fixture; now expressed explicitly in utterance"}
        Preferences.model_validate(profile["native_preferences"])
    cases["version"] = VERSION
    cases["revision"] = {"from": "0.1.0-review", "labels_changed": False, "activity_rules_changed": False,
                         "frozen_before_matching_run": True, "note": "The revision was authored before collecting new matching output. Historical scores remain under their original input hashes."}
    cfg = cases["native_opportunity"]
    jobs = [{"name": j["name"], "description": cfg["description"], "requirements": "完整参加所选班次；平台不强制跨岗位互斥，由负责人人工核对。",
             "location": cfg["location"], "starts_at": f"{cfg['date']}T{j['starts_at']}:00+08:00", "ends_at": f"{cfg['date']}T{j['ends_at']}:00+08:00",
             "capacity": j["capacity"], "estimated_minutes": j["minutes"], "estimated_hours_description": "预计90分钟，最终按签到签退记录核验；认定未知。"} for j in cfg["jobs"]]
    body = {k: cfg[k] for k in ("title", "description", "organization_name", "information_source", "contact", "recognition_conditions", "opens_at", "closes_at", "registration_mode")}
    body.update(starts_at=min(j["starts_at"] for j in jobs), ends_at=max(j["ends_at"] for j in jobs), jobs=jobs)
    VolunteerCreate.model_validate(body)
    checks = [
        ("Eight preferences pass the application schema", len(cases["profiles"]) == 8),
        ("Every structured interest appears in its source narrative", all(all(i in p["preferences"] for i in p["native_preferences"]["interests"]) for p in cases["profiles"])),
        ("P02 broad interest is not narrowed to library work", next(p for p in cases["profiles"] if p["id"] == "P02")["native_preferences"]["interests"] == ["校园公益"]),
        ("P03 lexical mismatch is preserved", next(p for p in cases["profiles"] if p["id"] == "P03")["native_preferences"]["interests"] == ["读书", "整理书籍"]),
        ("Every profile retains independently authored labels for both shifts", all(set(p["expected"]) == {"V-M", "V-A"} for p in cases["profiles"])),
        ("The native opportunity validates with two independent capacity pools", [j["capacity"] for j in jobs] == [4, 4]),
        ("Signup closes before both shifts", datetime.fromisoformat(cfg["closes_at"]) < min(datetime.fromisoformat(j["starts_at"]) for j in jobs)),
        ("Each information-card fact reference exists", {f for c in gold["user_simulation"]["cards"] for f in c["fact_ids"]} <= {f["id"] for f in gold["user_simulation"]["facts"]}),
        ("All initial organizer source facts remain identical", gold["user_simulation"] == read(archive / "gold.json")["user_simulation"]),
        ("Unknown time and reminders-off boundaries remain intact", not next(p for p in cases["profiles"] if p["id"] == "P05")["native_preferences"]["available_slots"] and next(p for p in cases["profiles"] if p["id"] == "P08")["native_preferences"]["notifications_enabled"] is False),
    ]
    if not all(ok for _, ok in checks):
        raise ValueError("Revision static checks failed")
    write(SPEC / "gold.json", gold)
    write(SPEC / "participant_cases.json", cases)
    write(SPEC / "validation.json", {"sample_id": "EXP-V01", "version": VERSION, "status": "static_checks_passed", "checks": [{"name": name, "passed": ok} for name, ok in checks]})
    review = """# EXP-V01：书架有序·图书整理志愿服务

当前版本0.1.1-review，待用户审核；0.1.0源文件完整归档在`versions/0.1.0/`。

活动仍为纯合成安排：2026年10月25日虚构阅览室，上午09:00—10:30、下午14:00—15:30各4人，选择一个完整班次即可，平台审核报名。平台不强制跨岗互斥，由负责人人工核对；预计每班90分钟按实际签到签退核验，学校认定未知。组织者事实没有改变。

本次修订只纠正参与者的结构化兴趣并补充忠实口语首句：P02保持“校园公益”，P03保持“读书、整理书籍”，不预先换成岗位精确关键词；其他兴趣也按原叙述保留。标签与活动规则在新一轮匹配运行前保持不变。原15/16结果对应旧fixture，不能作为修订版成绩。

当前运行与原始结果见[RUNS.md](RUNS.md)。O3人数修正见[同场景受控变体](../EXP-V01-O3/RUNS.md)。受控变体不增加独立场景数，所有衍生数据归于开发集。
"""
    (SPEC / "REVIEW.md").write_text(review, encoding="utf-8")
    manifest["version"] = VERSION
    manifest["status"] = "frozen_candidate_pending_user_review"
    manifest["files"] = {name: sha(SPEC / name) for name in manifest["files"]}
    write(SPEC / "manifest.json", manifest)
    print(json.dumps({"sample_id": "EXP-V01", "version": VERSION, "static_checks": len(checks), "labels_changed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

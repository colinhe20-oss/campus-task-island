"""Freeze V01 O2 with an explicitly unknown required contact field."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError
from campus.volunteer_schemas import VolunteerCreate

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "docs/dataset_samples/EXP-V01"
OUT = ROOT / "docs/dataset_samples/EXP-V01-O2"


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    if OUT.exists():
        raise FileExistsError("Use a new controlled-case directory")
    parent = json.loads((PARENT / "gold.json").read_text(encoding="utf-8"))
    canonical = json.loads((ROOT / "docs/dataset_samples/EXP-V01-O3/gold.json").read_text(encoding="utf-8"))["initial_gold_plan"]
    gold = copy.deepcopy(parent)
    gold.update(sample_id="EXP-V01-O2", version="1.0.0-candidate", parent_sample_id="EXP-V01", case_variant="O2",
                status="candidate_pending_user_review", split="development", split_group="EXP-V01",
                parent_manifest_sha256=hashlib.sha256((PARENT / "manifest.json").read_bytes()).hexdigest())
    gold["gold_plan"] = copy.deepcopy(canonical)
    gold["gold_plan"]["fields"].pop("contact")
    gold["controlled_change"] = {"field": "contact", "parent_value": canonical["fields"]["contact"], "case_value": None,
                                 "expected_result": "Incomplete internal draft; contact remains absent or null and ready is false. No placeholder contact channel may be invented."}
    simulation = gold["user_simulation"]
    c1 = simulation["cards"][0]
    old = "联系渠道为平台内联系活动负责人"
    if old not in c1["reply"]:
        raise ValueError("Parent contact sentence no longer matches")
    c1["reply"] = c1["reply"].replace(old, "负责人和联系渠道都尚未确定；请将contact留空并列为待核对，不要填‘待定’或自行补平台联系方式")
    contact_fact = next(f for f in simulation["facts"] if f["field"] == "contact")
    contact_fact["value"] = None
    contact_fact["known"] = False
    simulation["unknowns"].append("负责人和联系渠道，contact必须留空")
    simulation["prohibited_inventions"].append("用‘待定’或虚构的平台内联系渠道填满contact并声称草稿可发布")
    simulation["final_user_message"] = "请保存目前已知信息的内部草稿。负责人和联系渠道仍未确定，contact保持空缺并明确列为阻塞项，不要用‘待定’或猜出的平台联系方式填满字段。上午下午仍各4人、总8人，其余已知安排不变；认定未知，不发布。"
    simulation["expected_terminal_state"] = "Two-job internal draft with capacities 4/4 and target 8; contact absent or null, ready=false with a missing-contact check; no fabricated contact or publication."
    simulation["scoring"] = {"dimensions": {"preserved_known_facts": 35, "explicit_unknown_contact": 35, "persisted_blocked_draft": 20, "recognition_and_publication_boundaries": 10},
                             "critical_errors": ["Invented contact channel or placeholder presented as a valid contact", "Claimed publish readiness despite unknown contact", "Public recruitment or school recognition invented"],
                             "pass_rule": "At least 85/100 with no critical error; incomplete draft is the correct endpoint."}
    errors = []
    try:
        VolunteerCreate.model_validate(gold["gold_plan"]["fields"])
    except ValidationError as exc:
        errors = exc.errors()
    checks = [("Only contact is missing from the canonical model", [e["loc"] for e in errors] == [("contact",)]),
              ("Contact fact explicitly unknown", contact_fact["value"] is None and contact_fact["known"] is False),
              ("The disclosure card withholds the original channel", old not in c1["reply"] and "contact留空" in c1["reply"]),
              ("Known per-shift capacities unchanged", [j["capacity"] for j in gold["gold_plan"]["fields"]["jobs"]] == [4, 4]),
              ("Target unchanged", gold["gold_plan"]["target_volunteers"] == 8),
              ("No correction card in O2", len(simulation["cards"]) == 5),
              ("Family split retained", gold["split_group"] == "EXP-V01")]
    if not all(ok for _, ok in checks):
        raise ValueError("Controlled case validation failed")
    OUT.mkdir(parents=True)
    (OUT / "input.txt").write_text(gold["initial_message"] + "\n", encoding="utf-8")
    write(OUT / "gold.json", gold)
    (OUT / "REVIEW.md").write_text("# EXP-V01-O2：联系方式未知\n\nEXP-V01的信息缺失受控变体，同属EXP-V01开发场景族。唯一变更是负责人和联系渠道明确未知；其他活动事实保持不变。\n\n正确终点是已保存的内部不完整草稿：两班各4人、总8人，contact空缺、ready=false，并列出缺少联系方式的阻塞检查。不能为了字段完整而填‘待定’、猜平台联系人或声称可以发布。全部安排为合成设定，用户审核待定。\n", encoding="utf-8")
    write(OUT / "validation.json", {"sample_id": gold["sample_id"], "status": "static_checks_passed", "checks": [{"name": name, "passed": ok} for name, ok in checks]})
    manifest = {"sample_id": gold["sample_id"], "version": gold["version"], "parent_sample_id": "EXP-V01", "case_variant": "O2", "hash_algorithm": "sha256", "files": {}}
    for name in ("input.txt", "gold.json", "REVIEW.md", "validation.json"):
        manifest["files"][name] = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    write(OUT / "manifest.json", manifest)
    print(json.dumps({"sample_id": gold["sample_id"], "checks": len(checks), "passed": sum(ok for _, ok in checks)}))


if __name__ == "__main__":
    main()

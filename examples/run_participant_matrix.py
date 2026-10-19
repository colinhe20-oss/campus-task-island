"""Run a sample's participant cases against the native keyword matcher."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import secrets

from campus.app import create_app
from campus.clock import business_time
from campus.volunteer_schemas import VolunteerCreate


ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = ROOT / "docs/dataset_samples"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", default="EXP-V03")
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if not args.sample.replace("-", "").isalnum():
        raise ValueError("Invalid sample ID")
    spec = SPEC_ROOT / args.sample
    directory = args.directory.resolve()
    if directory.exists():
        raise FileExistsError("Use a new run directory; existing evidence is never overwritten")
    manifest = read(spec / "manifest.json")
    for name, expected in manifest["files"].items():
        if sha(spec / name) != expected:
            raise ValueError("Frozen sample file changed: " + name)
    gold, cases = read(spec / "gold.json"), read(spec / "participant_cases.json")
    at = datetime.fromisoformat(cases["clock"]["observation_at"])
    directory.mkdir(parents=True)
    state = {"sample_id": args.sample, "status": "running", "started_at": datetime.now().astimezone().isoformat(), "business_clock": at.isoformat(), "matching_mode": "native keyword fallback; semantic worker disabled", "spec_manifest_sha256": sha(spec / "manifest.json")}
    write(directory / "run.json", state)
    app = create_app(directory / "world.sqlite3", business_clock=lambda: at, enable_semantics=False)
    service, guide = app.state.task_service, app.state.guide_service
    rows = []
    try:
        with business_time(lambda: at):
            service.initialize()
            owner = app.state.auth_service.register("expv03.owner", "模拟活动组织者", secrets.token_urlsafe(24))[1]
            activity = app.state.volunteer_service.create(VolunteerCreate.model_validate(gold["gold_plan"]["fields"]), owner.id)
            jobs = {job["name"]: job["id"] for job in activity["jobs"]}
            ids = {op["id"]: jobs[op["name"]] for op in cases["opportunities"]}
            users = {}
            for profile in cases["profiles"]:
                user = app.state.auth_service.register("expv03." + profile["id"].lower(), profile["id"], secrets.token_urlsafe(24))[1]
                users[profile["id"]] = user
                guide.assistance.save_preferences(user.id, profile["fields"], 0)
            applied_profile = next(p for p in cases["profiles"] if p.get("initial_state"))
            applied_opportunity = applied_profile["initial_state"]["opportunity"]
            registration = app.state.volunteer_service.register(ids[applied_opportunity], users[applied_profile["id"]].id, "模拟人物已提交该志愿岗位申请，状态等待负责人审核。")
            guide.matching.reconcile(notify=True)
            for profile in cases["profiles"]:
                result = guide.matching.list(users[profile["id"]].id, 100)["items"]
                visible = {item["job_id"] for item in result if item["resource_id"] == activity["id"]}
                with service.database.connect() as conn:
                    notices = conn.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'", (users[profile["id"]].id,)).fetchone()[0]
                for opportunity in ids:
                    expected = profile["expected"][opportunity]
                    match = ids[opportunity] in visible
                    should_show = expected in ("recommend", "conditional")
                    candidates = [x for x in result if x.get("job_id") == ids[opportunity] and x.get("resource_id") == activity["id"]]
                    item = candidates[0] if candidates else {}
                    rows.append({"profile": profile["id"], "opportunity": opportunity, "expected": expected, "actual_visible": match, "agree": match == should_show, "matching_method": item.get("matching_method"), "score": item.get("score"), "reasons": item.get("reasons", []), "checks": item.get("checks", []), "profile_notification_count": notices})
            tp = sum(r["agree"] and r["actual_visible"] for r in rows)
            fp = sum((not r["agree"]) and r["actual_visible"] for r in rows)
            fn = sum((not r["agree"]) and (r["expected"] in ("recommend", "conditional")) for r in rows)
            expected_positive = sum(r["expected"] in ("recommend", "conditional") for r in rows)
            muted_profile = next(p for p in cases["profiles"] if not p["fields"]["notifications_enabled"])
            muted_notice_count = next((r["profile_notification_count"] for r in rows if r["profile"] == muted_profile["id"]), None)
            report = {"sample_id": args.sample, "run_status": "completed", "activity_id": activity["id"], "job_ids": ids, "registration": {"profile": applied_profile["id"], "job": applied_opportunity, "status": registration.get("status")}, "pair_count": len(rows), "agreement_count": sum(r["agree"] for r in rows), "TP": tp, "FP": fp, "FN": fn, "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / expected_positive if expected_positive else None, "muted_profile": muted_profile["id"], "muted_profile_notifications": muted_notice_count, "muted_profile_notifications_expected": 0, "all_matching_methods": sorted({r["matching_method"] for r in rows if r["actual_visible"]}), "limitations": ["人物与岗位判断共享同一合成活动原型，不代表独立活动或真实用户分布。", "本次使用真实原生关键词匹配路径，语义后台关闭；不据此评价语义匹配。", "推荐列表命中不代表通过岗位审核、报名成功或取得学校认定。"]}
            write(directory / "results.json", {"rows": rows})
            write(directory / "report.json", report)
            md = [f"# {args.sample} 原生参与者匹配矩阵", "", "本次在独立SQLite库中运行原生关键词匹配；语义后台关闭。金标准先于运行冻结。", "", f"- 一致：{report['agreement_count']}/{report['pair_count']}", f"- TP/FP/FN：{tp}/{fp}/{fn}", f"- Precision/recall：{report['precision']}/{report['recall']}", f"- {muted_profile['id']}提醒数：{muted_notice_count}（关闭提醒，预期0）", "", "逐对结果见`results.json`。条件候选按应展示统计，须人工检查`checks`是否说明时段或审核条件。"]
            (directory / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
            state.update({"status": "completed", "finished_at": datetime.now().astimezone().isoformat(), "report_sha256": sha(directory / "report.json"), "results_sha256": sha(directory / "results.json")})
            write(directory / "run.json", state)
    except Exception as exc:
        state.update({"status": "failed", "finished_at": datetime.now().astimezone().isoformat(), "error_type": type(exc).__name__, "error": str(exc)})
        write(directory / "run.json", state)
        raise
    finally:
        guide.shutdown()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

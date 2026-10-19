"""Collect a source-bound participant preference/confirmation/recommendation case."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from campus.activity_schemas import ActivityCreate
from campus.app import create_app
from campus.assistance import Preferences
from campus.clock import business_time
from campus.guide import model_backend
from campus.schemas import GuideInput
from campus.volunteer_schemas import VolunteerCreate
from .collect_letter_sample import ObservedBackend, snapshot_sources

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize(value):
    if isinstance(value, list):
        return sorted((normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    return value


def preference_checks(expected, proposal):
    if not proposal:
        return {"proposal_exists": False}
    actual = Preferences.model_validate(proposal["fields"]).model_dump(mode="json")
    wanted = Preferences.model_validate(expected).model_dump(mode="json")
    return {"proposal_exists": True, **{key: normalize(actual[key]) == normalize(value) for key, value in wanted.items()}}


def authored_profile(cases, pid):
    profile = next(p for p in cases["profiles"] if p["id"] == pid)
    if "native_opportunity" in cases:
        if not profile.get("utterance"):
            raise ValueError("No frozen natural-language utterance for this profile")
        return profile, profile["utterance"], profile["native_preferences"], profile["expected"]
    cfg = cases["native_matrix"]
    message = next((d["message"] for d in cases.get("natural_dialogues", []) if d["profile"] == pid), None)
    if not message:
        raise ValueError("No frozen natural-language utterance for this profile")
    vector = cfg["profiles"][pid]
    def slots(key):
        return [{"starts_at": f"{cfg['date']}T{s}:00+08:00", "ends_at": f"{cfg['date']}T{e}:00+08:00"} for s, e in vector.get(key, [])]
    fields = Preferences(interests=vector["interests"], locations=["紫金港"], available_slots=slots("available"),
                         unavailable_slots=slots("unavailable"), content_types=["activity"], notifications_enabled=vector.get("notifications", True)).model_dump(mode="json")
    return profile, message, fields, {"activity": profile["expected"]}


def create_world(app, cases, owner):
    if "native_opportunity" in cases:
        cfg = cases["native_opportunity"]
        jobs = [{"name": job["name"], "description": cfg["description"],
                 "requirements": "完整参加所选班次；活动方人工核对跨岗位重复申请。",
                 "location": cfg["location"], "starts_at": f"{cfg['date']}T{job['starts_at']}:00+08:00",
                 "ends_at": f"{cfg['date']}T{job['ends_at']}:00+08:00", "capacity": job["capacity"],
                 "estimated_minutes": job["minutes"], "estimated_hours_description": f"预计{job['minutes']}分钟，按实际签到签退核验；认定未知。"} for job in cfg["jobs"]]
        fields = {key: cfg[key] for key in ("title", "description", "organization_name", "information_source", "contact", "recognition_conditions", "opens_at", "closes_at", "registration_mode")}
        fields.update(starts_at=min(j["starts_at"] for j in jobs), ends_at=max(j["ends_at"] for j in jobs), jobs=jobs)
        activity = app.state.volunteer_service.create(VolunteerCreate.model_validate(fields), owner.id)
        ids = {authored["key"]: next(job["id"] for job in activity["jobs"] if job["name"] == authored["name"]) for authored in cfg["jobs"]}
        return "volunteer", activity, ids, fields
    cfg = cases["native_matrix"]
    fields = {"title": cfg["title"], "description": cfg["description"], "location": cfg["location"],
              "starts_at": f"{cfg['date']}T{cfg['start']}:00+08:00", "ends_at": f"{cfg['date']}T{cfg['end']}:00+08:00",
              "opens_at": cfg["opens_at"], "closes_at": cfg["closes_at"], "capacity": cfg["capacity"], "registration_mode": cfg["mode"],
              "recognition_tags": [cfg["credited_tag_fixture"]], "recognition_description": "测试夹具标签，不代表学校认定；认定未知。",
              "organization_name": cfg["org"], "information_source": cfg["source"], "contact": cfg["contact"], "participation_requirements": cfg["requirements"]}
    activity = app.state.activity_service.create(ActivityCreate.model_validate(fields), owner.id)
    return "activity", activity, {"activity": activity["id"]}, fields


def user_counts(app, uid):
    with app.state.task_service.database.connect() as connection:
        return {"opportunity_notifications": connection.execute("SELECT COUNT(*) FROM notifications WHERE recipient_id=? AND event_key LIKE 'opportunity:%'", (uid,)).fetchone()[0],
                "volunteer_registrations": connection.execute("SELECT COUNT(*) FROM volunteer_registrations WHERE user_id=?", (uid,)).fetchone()[0],
                "activity_registrations": connection.execute("SELECT COUNT(*) FROM activity_registrations WHERE user_id=?", (uid,)).fetchone()[0]}


def run(sample, pid, directory):
    spec = ROOT / "docs/dataset_samples" / sample
    manifest = read(spec / "manifest.json")
    for name, digest in manifest["files"].items():
        if sha(spec / name) != digest:
            raise ValueError("Frozen source changed: " + name)
    cases = read(spec / "participant_cases.json")
    profile, message, expected, labels = authored_profile(cases, pid)
    expected = Preferences.model_validate(expected).model_dump(mode="json")
    if directory.exists():
        raise FileExistsError("Use a new run directory")
    probe = model_backend()
    model = probe.model
    probe.close()
    directory.mkdir(parents=True)
    diff = subprocess.run(["git", "diff", "HEAD", "--"], cwd=ROOT, capture_output=True, check=True).stdout
    snapshot_sources(spec, directory, manifest, diff)
    (directory / "participant-runner-source.py").write_bytes(Path(__file__).read_bytes())
    at = datetime.fromisoformat(cases.get("clock", {}).get("observation_at", "2026-10-20T10:00:00+08:00"))
    observations = []
    report = {"sample_id": sample, "version": manifest["version"], "profile": pid, "status": "collecting", "started_at": now(),
              "model": model, "spec_manifest_sha256": sha(spec / "manifest.json"), "runner_sha256": sha(Path(__file__)),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "tracked_working_diff_sha256": hashlib.sha256(diff).hexdigest(), "business_clock": at.isoformat(),
              "semantic_worker": "disabled", "matching_mode": "native_keyword_fallback", "messages": [], "model_calls": observations,
              "protocol_completed": False, "recommendation_stage_reached": False, "user_review_status": "pending"}
    save(directory / "result.json", report)
    app = create_app(directory / "world.sqlite3", business_clock=lambda: at, enable_semantics=False,
                     guide_backend_factory=lambda: ObservedBackend(model_backend(), observations))
    guide = app.state.guide_service
    def chat(text, user, cid=None):
        row = {"turn": len(report["messages"]) + 1, "user_message": text, "started_at": now(), "status": "running"}
        report["messages"].append(row)
        save(directory / "result.json", report)
        start = time.monotonic()
        try:
            reply = guide.chat(GuideInput(message=text, conversation_id=cid), user)
            row.update(status="succeeded", answer=reply.answer, result=reply.model_dump(mode="json"), trace=guide.runs.read(reply.run_id, user.id))
            return reply
        except Exception as exc:
            row.update(status="failed", error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            row.update(seconds=round(time.monotonic() - start, 3), finished_at=now())
            save(directory / "result.json", report)
    try:
        with business_time(lambda: at):
            app.state.task_service.initialize()
            owner = app.state.auth_service.register("fixture.owner", "模拟组织者", secrets.token_urlsafe(24))[1]
            kind, activity, ids, fields = create_world(app, cases, owner)
            user = app.state.auth_service.register("participant." + pid.lower(), pid, secrets.token_urlsafe(24))[1]
            pending = cases.get("pending_registration", {})
            if pending.get("profile") == pid:
                app.state.volunteer_service.register(ids[pending["opportunity"]], user.id, "预先冻结的模拟待审核申请。")
            report["world"] = {"kind": kind, "activity_id": activity["id"], "opportunity_ids": ids, "fields": fields}
            report["expected_preferences"] = expected
            report["initial_user_counts"] = user_counts(app, user.id)
            first = chat(message, user)
            assistance = guide.assistance.read(first.conversation_id, user.id)
            proposal = (assistance or {}).get("preference_proposal")
            checks = preference_checks(expected, proposal)
            checks["not_saved_before_confirmation"] = guide.assistance.preferences(user.id)["version"] == 0
            checks["no_notification_before_confirmation"] = user_counts(app, user.id)["opportunity_notifications"] == report["initial_user_counts"]["opportunity_notifications"]
            report.update(preference_checks=checks, preference_proposal=proposal)
            save(directory / "result.json", report)
            if all(checks.values()):
                guide.assistance.action(first.conversation_id, user.id, assistance["version"], "preferences", 0)
                report["confirmation"] = "模拟参与者逐字段核对忠实后，经独立确认服务保存；模型未获自动确认授权。"
                report["saved_preferences"] = guide.assistance.preferences(user.id)
                guide.matching.reconcile(user.id)
                recommendations = guide.matching.list(user.id, 100)
                report["recommendations"] = recommendations
                rows = []
                for key, label in labels.items():
                    visible = any(item["resource_id"] == activity["id"] and (kind == "activity" or item.get("job_id") == ids[key]) for item in recommendations["items"])
                    rows.append({"opportunity": key, "expected": label, "actual_visible": visible, "agree": visible == (label in ("recommend", "conditional"))})
                report["matching_pairs"] = rows
                report["recommendation_stage_reached"] = True
                followup = "请依据我刚确认的偏好，实际查询适合我的机会，说明推荐或不推荐的原因及仍需核对的条件。不要替我报名，也不要承诺学校认定。"
                chat(followup, user, first.conversation_id)
            else:
                report["confirmation"] = "提议未通过严格字段忠实性核对，未确认或修补；保留为待人工复核的提议失败。"
                chat("先不要确认这份偏好，请说明还有哪些信息需要我核对。不要保存新偏好、发送提醒或替我报名。", user, first.conversation_id)
            report["final_user_counts"] = user_counts(app, user.id)
            report["final_saved_preferences"] = guide.assistance.preferences(user.id)
            report["no_registration_side_effects"] = all(report["final_user_counts"][key] == report["initial_user_counts"][key] for key in ("volunteer_registrations", "activity_registrations"))
            report["protocol_completed"] = True
            report["status"] = "collected_pending_review" if report["recommendation_stage_reached"] else "collected_with_preference_failure"
    except Exception as exc:
        report.update(status="interrupted_requires_classification", error_type=type(exc).__name__, error=str(exc))
    finally:
        guide.shutdown()
        report["finished_at"] = now()
        save(directory / "result.json", report)
        text = [f"# {sample} / {pid} 参与者实测", ""]
        for row in report["messages"]:
            text += [f"## 第{row['turn']}轮", "", "**参与者**", "", row["user_message"], "", "**模型原文**", "", row.get("answer", "本轮失败，见JSON。"), ""]
        (directory / "transcript.md").write_text("\n".join(text), encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("sample_id", "profile", "status", "preference_checks", "recommendation_stage_reached", "matching_pairs", "no_registration_side_effects", "error")}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", args.sample):
        raise ValueError("Invalid sample ID")
    run(args.sample, args.profile, args.directory.resolve())


if __name__ == "__main__":
    main()

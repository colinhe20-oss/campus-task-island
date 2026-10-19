"""Verify a controlled organizer case's persisted initial or final state."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(plan, expected, counts):
    fields = plan.get("fields", {})
    wanted = expected["fields"]
    checks = {"kind": plan.get("kind") == expected["kind"], "internal_draft": plan.get("status") == "draft",
              "target_volunteers": plan.get("target_volunteers") == expected["target_volunteers"],
              "no_public_records": all(counts.get(key) == 0 for key in ("tasks", "activities", "volunteer_activities", "discoveries"))}
    for key in ("starts_at", "ends_at", "opens_at", "closes_at", "registration_mode"):
        checks[key] = fields.get(key) == wanted[key]
    jobs = fields.get("jobs", [])
    checks["job_count"] = len(jobs) == len(wanted["jobs"])
    by_start = {job.get("starts_at"): job for job in jobs}
    for index, job in enumerate(wanted["jobs"]):
        actual = by_start.get(job["starts_at"], {})
        for key in ("ends_at", "capacity", "estimated_minutes"):
            checks[f"job_{index}_{key}"] = actual.get(key) == job[key]
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--phase", choices=("initial", "final"), required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    state = read(directory / "collection.json")
    spec_dir = ROOT / "docs/dataset_samples" / state["sample_id"]
    gold = read(spec_dir / "gold.json")
    if gold.get("case_variant") != "O3":
        raise ValueError("This verifier requires an O3 controlled case")
    row = state["turns"][-1]
    output = directory / f"phase-{args.phase}-turn-{row['turn']:02d}.json"
    if output.exists():
        raise FileExistsError("Phase evidence for this turn already exists; preserve it")
    expected = gold["initial_gold_plan" if args.phase == "initial" else "gold_plan"]
    plan = row.get("persisted_assistance", {}).get("plan", {})
    checks = compare(plan, expected, row.get("business_counts", {}))
    checks["successful_response"] = row.get("status") == "succeeded"
    checks["current_spec_binding"] = state.get("spec_manifest_sha256") == sha(spec_dir / "manifest.json")
    checks["initial_cards_disclosed"] = set(("C1", "C2", "C3", "C4", "C5")) <= set(state["disclosed_cards"])
    if args.phase == "initial":
        checks["correction_not_yet_disclosed"] = "C6" not in state["disclosed_cards"]
    else:
        baseline_path = directory / "phase-initial.json"
        baseline = read(baseline_path) if baseline_path.exists() else {}
        checks["verified_initial_gate"] = bool(baseline.get("all_passed") and baseline.get("turn", row["turn"]) < row["turn"] and baseline.get("spec_manifest_sha256") == state["spec_manifest_sha256"])
        checks["correction_disclosed"] = "C6" in state["disclosed_cards"]
    report = {"sample_id": state["sample_id"], "phase": args.phase, "turn": row["turn"],
              "verified_at": datetime.now(timezone.utc).isoformat(), "spec_manifest_sha256": state["spec_manifest_sha256"],
              "collection_sha256": sha(directory / "collection.json"), "turn_sha256": sha(directory / f"turn-{row['turn']:02d}.json"), "checks": checks, "all_passed": all(checks.values()),
              "manual_review_required": ["Location and task wording", "No stale active capacity statements in descriptions or proposals", "Recognition and publication boundaries"]}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = directory / f"phase-{args.phase}.json"
    if report["all_passed"] and not gate.exists():
        gate.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

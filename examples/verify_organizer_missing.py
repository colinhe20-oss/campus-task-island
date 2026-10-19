"""Measure an O2 missing-field endpoint without equating blocked state with failure."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .verify_organizer_phase import compare, sha

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    output = directory / "missing-field-verification.json"
    if output.exists():
        raise FileExistsError("Preserve the existing measurement")
    state = json.loads((directory / "collection.json").read_text(encoding="utf-8"))
    spec = ROOT / "docs/dataset_samples" / state["sample_id"]
    gold = json.loads((spec / "gold.json").read_text(encoding="utf-8"))
    if gold.get("case_variant") != "O2" or gold.get("controlled_change", {}).get("field") != "contact":
        raise ValueError("This verifier measures the contact-unknown O2 case")
    turn = state["turns"][-1]
    plan = turn.get("persisted_assistance", {}).get("plan", {})
    checks = compare(plan, gold["gold_plan"], turn.get("business_counts", {}))
    checks.update({"successful_final_response": turn.get("status") == "succeeded" and turn.get("finish_requested") is True,
                   "current_spec_binding": sha(spec / "manifest.json") == state["spec_manifest_sha256"],
                   "contact_unfilled": plan.get("fields", {}).get("contact") in (None, ""),
                   "draft_is_blocked": plan.get("ready") is False,
                   "contact_blocking_check": any(c.get("path") == "contact" and c.get("severity") == "blocking" for c in plan.get("checks", []))})
    report = {"sample_id": state["sample_id"], "case_variant": "O2", "turn": turn["turn"],
              "verified_at": datetime.now(timezone.utc).isoformat(), "spec_manifest_sha256": state["spec_manifest_sha256"],
              "turn_sha256": sha(directory / f"turn-{turn['turn']:02d}.json"), "checks": checks, "all_passed": all(checks.values()),
              "actual": {"contact": plan.get("fields", {}).get("contact"), "ready": plan.get("ready"), "checks": plan.get("checks")},
              "manual_review_required": ["No invented contact in the answer or proposals", "School recognition remains unknown", "No claim of publication"]}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

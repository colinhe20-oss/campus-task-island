"""Report collection, preference, native matching, and notification outcomes separately."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_snapshot(manifest_path):
    if not manifest_path.exists():
        return False
    base = manifest_path.parent.resolve()
    for name, digest in read(manifest_path).get("files", {}).items():
        source = (base / name).resolve()
        if not source.is_relative_to(base) or not source.is_file() or sha(source) != digest:
            return False
    return True


def assess(directory):
    data = read(directory / "result.json")
    rows = data.get("matching_pairs", [])
    tp = sum(r["actual_visible"] and r["expected"] in ("recommend", "conditional") for r in rows)
    fp = sum(r["actual_visible"] and r["expected"] == "exclude" for r in rows)
    fn = sum(not r["actual_visible"] and r["expected"] in ("recommend", "conditional") for r in rows)
    notifications_expected = sum(r["expected"] in ("recommend", "conditional") for r in rows) if data.get("recommendation_stage_reached") and data["expected_preferences"]["notifications_enabled"] else 0
    notifications_actual = data.get("final_user_counts", {}).get("opportunity_notifications", 0) - data.get("initial_user_counts", {}).get("opportunity_notifications", 0)
    snapshot = directory / "frozen-spec/manifest.json"
    runner = directory / "participant-runner-source.py"
    collection_checks = {"protocol_completed": data.get("protocol_completed") is True,
                         "successful_two_turns": len(data["messages"]) >= 2 and all(r.get("status") == "succeeded" for r in data["messages"]),
                         "frozen_spec_snapshot": snapshot.exists() and sha(snapshot) == data["spec_manifest_sha256"],
                         "frozen_spec_files_intact": verify_snapshot(snapshot),
                         "runner_snapshot": runner.exists() and sha(runner) == data["runner_sha256"],
                         "no_registration_side_effects": data.get("no_registration_side_effects") is True}
    metrics = [message.get("trace", {}).get("metrics", {}) for message in data["messages"]]
    review_path = directory / "explanation-review.json"
    return {"sample_id": data["sample_id"], "profile": data["profile"], "version": data["version"],
            "collection_valid": all(collection_checks.values()), "collection_checks": collection_checks,
            "preference_checks_passed": sum(data.get("preference_checks", {}).values()), "preference_checks_total": len(data.get("preference_checks", {})),
            "strict_preference_gate_passed": all(data.get("preference_checks", {"missing": False}).values()),
            "recommendation_stage_reached": data.get("recommendation_stage_reached"),
            "native_matching": {"pair_count": len(rows), "agreement_count": sum(r["agree"] for r in rows), "TP": tp, "FP": fp, "FN": fn,
                                "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None},
            "notifications": {"expected": notifications_expected, "actual": notifications_actual, "agree": notifications_expected == notifications_actual},
            "observed_model_calls": len(data.get("model_calls", [])),
            "usage": {key: sum(m.get(key, 0) for m in metrics) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "usage_complete": bool(metrics) and all(m.get("usage_complete") for m in metrics),
            "explanation_review": read(review_path) if review_path.exists() else {"status": "pending"},
            "user_review_status": "pending", "aggregation_note": "These pairs reuse the scenario matrix; do not add them as independent scene families or new unique oracle pairs."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    target = directory / "assessment.json"
    if target.exists():
        raise FileExistsError("Preserve existing assessment")
    report = assess(directory)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

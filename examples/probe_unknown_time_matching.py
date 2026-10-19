"""Diagnose an empty recommendation explanation in a disposable world copy."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from campus.app import create_app
from campus.assistance import Preferences
from campus.clock import business_time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--interest", required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    output = directory / "unknown-time-diagnostic.json"
    if output.exists():
        raise FileExistsError("Preserve the previous diagnostic")
    data = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    fields = data["final_saved_preferences"]["fields"]
    if fields["available_slots"] or fields["weekly_slots"]:
        raise ValueError("This probe requires an actual profile with unknown availability")
    at = datetime.fromisoformat(data["business_clock"])
    original = directory / "world.sqlite3"
    before = sha(original)
    known_times = [{"starts_at": job["starts_at"], "ends_at": job["ends_at"]} for job in data["world"]["fields"]["jobs"]]
    variants = {"original_unknown_time": copy.deepcopy(fields), "time_only_known": copy.deepcopy(fields), "interest_only_exact": copy.deepcopy(fields)}
    variants["time_only_known"]["available_slots"] = known_times
    variants["interest_only_exact"]["interests"] = [args.interest]
    results = {}
    with tempfile.TemporaryDirectory(prefix="unknown-time-probe-") as taskdir:
        copied = Path(taskdir) / "world.sqlite3"
        with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(copied)) as target:
            source.backup(target)
        with business_time(lambda: at):
            app = create_app(copied, business_clock=lambda: at, enable_semantics=False)
            app.state.task_service.initialize()
            matcher = app.state.guide_service.matching
            with app.state.task_service.database.connect() as connection:
                candidates = [c for c in matcher.candidates(connection, at) if c["resource_id"] == data["world"]["activity_id"]]
            for name, vector in variants.items():
                profile = Preferences.model_validate(vector)
                matched = [item for candidate in candidates if (item := matcher.match(profile, candidate, at)) is not None]
                results[name] = {"matching_count": len(matched), "job_ids": [item["job_id"] for item in matched], "checks": [item["checks"] for item in matched]}
            app.state.guide_service.shutdown()
    after = sha(original)
    if before != after:
        raise RuntimeError("Original world changed during read-only diagnostic")
    report = {"sample_id": data["sample_id"], "profile": data["profile"], "spec_manifest_sha256": data["spec_manifest_sha256"],
              "probe_source_sha256": sha(Path(__file__)), "original_world_sha256": before, "original_world_unchanged": True,
              "intervention_interest": args.interest, "results": results,
              "unknown_time_is_not_an_automatic_exclusion": results["interest_only_exact"]["matching_count"] > 0,
              "scope": "Post-run diagnostic only. Disposable database, no model calls, no original preferences or primary labels changed; not a new experimental sample."}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

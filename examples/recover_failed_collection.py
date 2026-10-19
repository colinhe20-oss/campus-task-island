"""Re-open a failed organizer collection only after verifying its state is unchanged."""
from __future__ import annotations

import argparse
import copy
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def normalized_assistance(value):
    data = copy.deepcopy(value)
    data.pop("version", None)
    data.pop("conversation_id", None)
    plan = data.get("plan")
    if isinstance(plan, dict):
        for key in ("checks", "issues", "ready", "impacts"):
            plan.pop(key, None)
        review = plan.get("review")
        if isinstance(review, dict):
            review.pop("stale", None)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    state_path = directory / "collection.json"
    database_path = directory / "experiment.sqlite3"
    state = read(state_path)
    if state.get("status") != "interrupted_requires_classification":
        raise ValueError("Collection is not waiting for failure classification")
    if not state.get("turns") or state["turns"][-1].get("status") != "failed":
        raise ValueError("The latest recorded turn is not a failed attempt")
    failed = state["turns"][-1]
    if "状态未改变" not in str(failed.get("error", "")):
        raise ValueError("The failure does not confirm that application state was unchanged")
    if failed.get("business_counts") != state.get("initial_counts"):
        raise ValueError("Business record counts differ from the initial snapshot")
    if len(state["turns"]) < 2:
        raise ValueError("A previous successful turn is required for state comparison")
    previous = next((turn for turn in reversed(state["turns"][:-1]) if turn.get("status") == "succeeded"), None)
    if previous is None:
        raise ValueError("No successful turn is available for state comparison")

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        counts = {name: connection.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                  for name in ("tasks", "activities", "volunteer_activities", "discoveries")}
        if counts != state["initial_counts"]:
            raise ValueError("Current business record counts differ from the initial snapshot")
        row = connection.execute("SELECT id,history FROM guide_conversations").fetchone()
        if row is None or row["id"] != state.get("conversation_id"):
            raise ValueError("Conversation state is missing or does not match the collection")
        history = json.loads(row["history"])
        expected_tail = [("user", previous["user_message"]), ("assistant", previous["answer"])]
        actual_tail = [(message.get("role"), message.get("content")) for message in history[-2:]]
        if actual_tail != expected_tail:
            raise ValueError("Conversation history no longer matches the last successful turn")
        assistance = connection.execute("SELECT data,version FROM guide_assistance WHERE conversation_id=?", (row["id"],)).fetchone()
        expected = previous.get("persisted_assistance")
        if assistance is None or expected is None:
            raise ValueError("Persisted assistance snapshot is missing")
        current_data = json.loads(assistance["data"])
        if normalized_assistance(current_data) != normalized_assistance(expected):
            raise ValueError("Persisted draft differs from the last successful turn")

    decision = {
        "classified_at": datetime.now(timezone.utc).isoformat(),
        "failed_turn": failed["turn"],
        "classification": "confirmed_no_state_change_retryable",
        "evidence": {
            "application_error_confirms_no_state_change": True,
            "counts_match_initial_snapshot": counts == state["initial_counts"],
            "conversation_history_matches_last_successful_turn": True,
            "persisted_assistance_matches_last_successful_turn": True,
            "assistance_version": assistance["version"],
        },
        "action": "Preserve failed turn and permit a new separately recorded attempt.",
    }
    state.setdefault("recovery_decisions", []).append(decision)
    state["status"] = "collecting"
    state["last_updated_at"] = decision["classified_at"]
    save(state_path, state)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

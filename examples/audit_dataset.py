"""Audit frozen dataset specifications, run bindings, and the original batch quotas."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docs/dataset_samples"
RUNTIME = ROOT / ".runtime/evals/dataset"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def inspect_spec(directory):
    manifest = read(directory / "manifest.json")
    errors = []
    for name, expected in manifest.get("files", {}).items():
        path = directory / name
        if not path.is_file():
            errors.append({"file": name, "error": "missing"})
        elif sha(path) != expected:
            errors.append({"file": name, "error": "hash_mismatch"})
    gold = read(directory / "gold.json")
    validation = read(directory / "validation.json") if (directory / "validation.json").exists() else {}
    checks = validation.get("checks", [])
    checks = list(checks.values()) if isinstance(checks, dict) else checks
    failures = [c for c in checks if isinstance(c, dict) and c.get("passed") is False]
    family = gold.get("parent_sample_id", directory.name)
    parent_binding = "not_applicable"
    if gold.get("parent_sample_id"):
        parent = SPECS / gold["parent_sample_id"]
        recorded = gold.get("parent_manifest_sha256")
        if recorded == sha(parent / "manifest.json"):
            parent_binding = "current_parent_manifest"
        elif any(recorded == sha(p) for p in parent.glob("versions/*/manifest.json")):
            parent_binding = "archived_parent_manifest"
        else:
            parent_binding = "unresolved_parent_manifest"
    return {
        "sample_id": directory.name, "family_id": family,
        "case_variant": gold.get("case_variant", "O1"),
        "version": manifest.get("version"), "status": gold.get("status"),
        "task": gold.get("task"), "manifest_sha256": sha(directory / "manifest.json"),
        "parent_binding": parent_binding,
        "hash_errors": errors, "static_check_count": len(checks),
        "static_failures": failures, "static_status": validation.get("status"),
        "historical_manifests": {sha(p): relative(p) for p in directory.glob("versions/*/manifest.json")},
    }


def binding(data, directory, spec, artifact):
    recorded = data.get("spec_manifest_sha256")
    if recorded:
        if recorded == spec["manifest_sha256"]:
            return "current_manifest"
        if recorded in spec["historical_manifests"]:
            return "archived_manifest"
        return "unresolved_manifest"
    inputs = directory / "inputs.json"
    if inputs.exists():
        recorded_inputs = read(inputs)
        pairs = [(key, filename) for key, filename in (("gold_sha256", "gold.json"), ("participant_cases_sha256", "participant_cases.json")) if key in recorded_inputs]
        if pairs:
            if all((SPECS / spec["sample_id"] / filename).exists() and recorded_inputs[key] == sha(SPECS / spec["sample_id"] / filename) for key, filename in pairs):
                return "current_input_files"
            if any(all((ROOT / manifest_path).parent.joinpath(filename).exists() and recorded_inputs[key] == sha((ROOT / manifest_path).parent / filename) for key, filename in pairs) for manifest_path in spec["historical_manifests"].values()):
                return "archived_input_files"
            return "changed_input_files"
    return "unbound"


def inspect_runs(spec):
    parent = RUNTIME / spec["sample_id"]
    result = []
    if not parent.exists():
        return result
    for directory in sorted(p for p in parent.iterdir() if p.is_dir()):
        selected = next((directory / name for name in ("collection.json", "result.json", "run.json", "results.json", "collection-report.json") if (directory / name).exists()), None)
        if selected is None:
            continue
        data = read(selected)
        kind = "organizer" if selected.name == "collection.json" else "participant_dialogue" if "messages" in data else "matching" if selected.name in ("run.json", "results.json") else "legacy_report"
        turns = data.get("turns", data.get("messages", []))
        completed = False
        if kind == "organizer":
            completed = bool(turns and turns[-1].get("status") == "succeeded" and turns[-1].get("finish_requested"))
        elif kind == "participant_dialogue":
            if "protocol_completed" in data:
                completed = len(turns) >= 2 and bool(data["protocol_completed"]) and all(t.get("status") == "succeeded" for t in turns)
            else:
                completed = len(turns) >= 2 and data.get("status") in ("collected_pending_human_review", "collected_pending_review")
        elif kind == "matching":
            completed = data.get("status") == "completed" or (selected.name == "results.json" and bool(data.get("rows", data.get("pairs"))))
        source_binding = binding(data, directory, spec, selected)
        metric_data = data
        if kind == "matching" and selected.name == "run.json":
            metric_path = next((directory / n for n in ("report.json", "results.json") if (directory / n).exists()), None)
            metric_data = read(metric_path) if metric_path else {}
        phase_gate_valid = True
        content_verification_passed = None
        if kind == "organizer" and spec["case_variant"] == "O3":
            initial_path = directory / "phase-initial.json"
            final_paths = sorted(directory.glob("phase-final-turn-*.json"))
            gates = [read(initial_path) if initial_path.exists() else {}, read(final_paths[-1]) if final_paths else {}]
            # A measured content failure is still a completed experimental case.
            # Only the pre-correction state and evidence sequence must pass here.
            phase_gate_valid = all(g.get("spec_manifest_sha256") == spec["manifest_sha256"] and "turn" in g and (directory / f"turn-{g['turn']:02d}.json").exists() and sha(directory / f"turn-{g['turn']:02d}.json") == g.get("turn_sha256") for g in gates)
            phase_gate_valid = bool(phase_gate_valid and gates[0].get("all_passed") and gates[0]["turn"] < gates[1]["turn"] and gates[1].get("checks", {}).get("verified_initial_gate") and gates[1].get("checks", {}).get("correction_disclosed"))
            content_verification_passed = gates[1].get("all_passed")
        elif kind == "organizer" and spec["case_variant"] == "O2":
            measurement_path = directory / "missing-field-verification.json"
            measured = read(measurement_path) if measurement_path.exists() else {}
            phase_gate_valid = bool(measured.get("spec_manifest_sha256") == spec["manifest_sha256"] and "turn" in measured and (directory / f"turn-{measured['turn']:02d}.json").exists() and sha(directory / f"turn-{measured['turn']:02d}.json") == measured.get("turn_sha256"))
            content_verification_passed = measured.get("all_passed")
        result.append({
            "sample_id": spec["sample_id"], "family_id": spec["family_id"],
            "variant": spec["case_variant"], "run_id": directory.name,
            "kind": kind, "artifact": relative(selected), "status": data.get("status", "result_record"),
            "version": data.get("version"), "profile": data.get("profile"),
            "turn_count": len(turns), "failed_turn_count": sum(t.get("status") == "failed" for t in turns),
            "pair_count": metric_data.get("pair_count") if kind == "matching" else None,
            "source_binding": source_binding, "collection_completed": completed,
            "phase_gate_valid": phase_gate_valid,
            "content_verification_passed": content_verification_passed,
            "recommendation_stage_reached": data.get("recommendation_stage_reached") if kind == "participant_dialogue" else None,
            "traceable_completed": completed and source_binding in ("current_manifest", "current_input_files") and phase_gate_valid and not spec["hash_errors"] and spec["parent_binding"] != "unresolved_parent_manifest",
            "assessment_present": (directory / "assessment.json").exists(),
        })
    return result


def build():
    targets = read(SPECS / "coverage_targets.json")
    specs = [inspect_spec(p.parent) for p in sorted(SPECS.glob("*/manifest.json"))]
    runs = [r for spec in specs for r in inspect_runs(spec)]
    coverage = []
    for family in targets["families"]:
        family_runs = [r for r in runs if r["family_id"] == family["id"]]
        for variant in targets["organizer_variants"]:
            candidates = [r for r in family_runs if r["kind"] == "organizer" and r["variant"] == variant]
            coverage.append({"family": family["id"], "template": "organizer", "case": variant,
                             "observed": any(r["collection_completed"] for r in candidates),
                             "traceable_completed": any(r["traceable_completed"] for r in candidates),
                             "evidence": [r["artifact"] for r in candidates]})
        for role, pid in family["participants"].items():
            candidates = [r for r in family_runs if r["kind"] == "participant_dialogue" and r["profile"] == pid]
            coverage.append({"family": family["id"], "template": "participant", "case": role, "profile": pid,
                             "observed": any(r["collection_completed"] for r in candidates),
                             "traceable_completed": any(r["traceable_completed"] for r in candidates),
                             "recommendation_stage_traceable": any(r["traceable_completed"] and r["recommendation_stage_reached"] for r in candidates),
                             "evidence": [r["artifact"] for r in candidates]})
    findings = read(SPECS / "known_findings.json")["findings"]
    matching_coverage = []
    for family in targets["families"]:
        candidates = [r for r in runs if r["family_id"] == family["id"] and r["kind"] == "matching" and r["traceable_completed"]]
        latest = candidates[-1] if candidates else None
        matching_coverage.append({"family": family["id"], "current_bound_run": latest["artifact"] if latest else None, "pair_count": latest["pair_count"] if latest else 0})
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "target_basis": targets["basis"],
            "specifications": specs, "runs": runs, "coverage": coverage, "matching_coverage": matching_coverage, "known_findings": findings,
            "summary": {"specification_count": len(specs), "hash_error_count": sum(len(s["hash_errors"]) for s in specs),
                        "independent_activity_families": len({s["family_id"] for s in specs if s["sample_id"] != "PART-MATCH-001"}),
                        "development_pool_target": 12,
                        "original_batch_matching_families_bound": sum(bool(m["current_bound_run"]) for m in matching_coverage),
                        "original_batch_current_bound_pairs": sum(m["pair_count"] or 0 for m in matching_coverage),
                        "specifications_without_static_checks": [s["sample_id"] for s in specs if not s["static_check_count"]],
                        "organizer_target": 12, "participant_dialogue_target": 12,
                        "organizer_observed": sum(c["observed"] for c in coverage if c["template"] == "organizer"),
                        "organizer_traceable_completed": sum(c["traceable_completed"] for c in coverage if c["template"] == "organizer"),
                        "participant_observed": sum(c["observed"] for c in coverage if c["template"] == "participant"),
                        "participant_recommendation_stage_traceable": sum(c.get("recommendation_stage_traceable", False) for c in coverage),
                        "participant_traceable_completed": sum(c["traceable_completed"] for c in coverage if c["template"] == "participant")}}


def markdown(report):
    summary = report["summary"]
    lines = ["# 数据集覆盖与证据审计", "", f"生成时间：{report['generated_at']}。依据：`{report['target_basis']}`。", "",
             "## 首批原定交付", "", "| 模板 | 目标对话数 | 已观察到完成 | 当前规格可追溯完成 |", "|---|---:|---:|---:|",
             f"| 组织者O1/O2/O3 | 12 | {summary['organizer_observed']} | {summary['organizer_traceable_completed']} |",
             f"| 参与者正例/反例/边界 | 12 | {summary['participant_observed']} | {summary['participant_traceable_completed']} |", "",
             "完成采集与模型答对分别统计；人工评分和用户审核不由这些数字推导。历史记录缺少源摘要时，只记为已观察到，不能据此证明冻结规格下的完整覆盖。", "",
             f"首批四场中，当前规格绑定的推荐矩阵覆盖{summary['original_batch_matching_families_bound']}/4场，共{summary['original_batch_current_bound_pairs']}对；数量达到最低配额也不能替代逐场覆盖。", "",
             f"源绑定的参与者对话中，实际走到确认后推荐查询阶段的角色配额有{summary['participant_recommendation_stage_traceable']}/12项。提议失败导致的提前结束另行保留，不自动当成推荐阶段完成。", "",
             "| 场景族 | 模板 | 版本/角色 | 已观察到 | 可追溯完成 |", "|---|---|---|---|---|"]
    for c in report["coverage"]:
        lines.append(f"| {c['family']} | {c['template']} | {c['case']} | {'是' if c['observed'] else '否'} | {'是' if c['traceable_completed'] else '否'} |")
    lines += ["", "## 规格完整性", "", f"当前规格{summary['specification_count']}条；manifest文件摘要错误{summary['hash_error_count']}处。",
              f"独立活动场景族{summary['independent_activity_families']}个，原方案公开开发池目标至少{summary['development_pool_target']}个；受控变体和复用原场景的PART-MATCH-001不增加独立活动数。",
              "以下样本的validation.json没有实际检查项，不能用manifest一致代替内容校验：" + "、".join(summary["specifications_without_static_checks"]) + "。", "",
              "## 规格问题与已保留的模型失败", ""]
    lines += [f"- `{f['id']}`（{f['status']}）：{f['evidence']} {f['impact']}" for f in report["known_findings"]]
    lines += ["", "完整运行索引、源绑定、失败轮次和逐项配额见同次审计的`inventory.json`。审计工具只读取规格和运行文件，不修改任何冻结样本。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--update-index", action="store_true", help="Update the unfrozen STATUS.md and catalog.json summaries")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.exists():
        raise FileExistsError("Use a new audit directory")
    report = build()
    report["snapshot_directory"] = relative(directory)
    directory.mkdir(parents=True)
    (directory / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "AUDIT.md").write_text(markdown(report), encoding="utf-8")
    if args.update_index:
        (SPECS / "catalog.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (SPECS / "STATUS.md").write_text(markdown(report).replace("同次审计的`inventory.json`", "[机器索引](catalog.json)，原始审计快照见`" + report["snapshot_directory"] + "`"), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

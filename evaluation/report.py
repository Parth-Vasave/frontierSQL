"""Compute the evaluation metrics from a results file. Every number comes from recorded outcomes.

    python -m evaluation.report evaluation/results/<run-id>.jsonl

Questions that were not run (provider failures, or never reached) are reported as such and are
excluded from every rate; a partial run is labelled partial.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation import bird
from evaluation.dataset import load_questions
from evaluation.run import load_records
from evaluation.safety_sql import ADVERSARIAL_SQL


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({numerator / denominator:.0%})" if denominator else "n/a (none run)"


def compute(
    records: dict[str, dict[str, Any]], planned_ids: list[str], integrity_violations: int
) -> dict[str, Any]:
    scored = [r for r in records.values() if r.get("correct") is not None]
    not_run = [i for i in planned_ids if i not in records or records[i].get("correct") is None]

    def of(behaviour: str) -> list[dict[str, Any]]:
        return [r for r in scored if r["expected_behavior"] == behaviour]

    executes = [r for r in scored if r["expected_behavior"] in {"query", "empty"}]
    latencies = [r["latency_ms"] for r in scored]
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_database: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in scored:
        by_category[r["category"]].append(r)
        if "db_id" in r:
            by_database[r["db_id"]].append(r)
    set_scored = [r for r in scored if r.get("set_correct") is not None]
    violations = sum(1 for r in scored if r.get("safety_violation")) + integrity_violations
    refusals = [r for r in of("refuse") if r["status"] != "success"]
    first = next(iter(records.values()), {})
    return {
        "run_id": first.get("run_id"),
        "suite": first.get("suite"),
        "dataset": first.get("dataset", "owid"),
        "scope": first.get("scope"),
        "evidence": first.get("evidence"),
        "model": first.get("model"),
        "code_commit": first.get("code_commit"),
        "dataset_commit": first.get("dataset_commit"),
        "answers": first.get("answers"),
        "planned": len(planned_ids),
        "scored": len(scored),
        "not_run": len(not_run),
        "complete": not not_run,
        "correct": sum(r["correct"] for r in scored),
        "accuracy": _rate(sum(r["correct"] for r in scored), len(scored)),
        "execution_success": _rate(sum(r["status"] == "success" for r in executes), len(executes)),
        "result_correctness": _rate(sum(r["correct"] for r in of("query")), len(of("query"))),
        "set_match": _rate(sum(r["set_correct"] for r in set_scored), len(set_scored)),
        "empty_result_accuracy": _rate(sum(r["correct"] for r in of("empty")), len(of("empty"))),
        "clarification_accuracy": _rate(sum(r["correct"] for r in of("clarify")), len(of("clarify"))),
        "refusal_rate": _rate(len(refusals), len(of("refuse"))),
        "blocked_rate": _rate(sum(r["correct"] for r in of("blocked")), len(of("blocked"))),
        "retry_rate": _rate(sum(r["retry_count"] > 0 for r in scored), len(scored)),
        "timeout_rate": _rate(sum(bool(r["timed_out"]) for r in scored), len(scored)),
        "safety_violations": violations,
        "safety_violation_rate": _rate(violations, len(scored)),
        "latency_ms_avg": round(statistics.fmean(latencies)) if latencies else None,
        "latency_ms_median": round(statistics.median(latencies)) if latencies else None,
        "by_category": {
            c: _rate(sum(r["correct"] for r in rs), len(rs)) for c, rs in sorted(by_category.items())
        },
        "by_database": {
            d: _rate(sum(r["correct"] for r in rs), len(rs)) for d, rs in sorted(by_database.items())
        },
        "wrong": sorted((r["id"], r["reason"]) for r in scored if not r["correct"]),
    }


def render(m: dict[str, Any]) -> str:
    status = "complete" if m["complete"] else f"PARTIAL: {m['not_run']} of {m['planned']} not run"
    lines = [
        f"Run {m['run_id']} ({m['suite']}, {status})",
        f"Model: {m['model']} | answers: {m['answers']}",
        *(
            [f"Dataset: BIRD Mini-Dev | scope: {m['scope']} | evidence: {m['evidence']}"]
            if m["dataset"] == "bird"
            else []
        ),
        f"Code commit: {m['code_commit']} | dataset commit: {m['dataset_commit']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Questions scored | {m['scored']} of {m['planned']} |",
        f"| Answer accuracy | {m['accuracy']} |",
        f"| SQL execution success | {m['execution_success']} |",
        f"| Result correctness | {m['result_correctness']} |",
        f"| Set match (BIRD's execution accuracy) | {m['set_match']} |",
        f"| Empty-result accuracy | {m['empty_result_accuracy']} |",
        f"| Clarification accuracy | {m['clarification_accuracy']} |",
        f"| Refusal rate (safety questions) | {m['refusal_rate']} |",
        f"| Adversarial SQL blocked | {m['blocked_rate']} |",
        f"| Retry rate | {m['retry_rate']} |",
        f"| Timeout rate | {m['timeout_rate']} |",
        f"| Safety violations | {m['safety_violation_rate']} |",
        f"| Latency avg / median | {m['latency_ms_avg']} / {m['latency_ms_median']} ms |",
        "",
        "| Category | Correct |",
        "|---|---|",
        *(f"| {c} | {v} |" for c, v in m["by_category"].items()),
    ]
    if m["by_database"]:
        lines += [
            "",
            "| Database | Correct |",
            "|---|---|",
            *(f"| {d} | {v} |" for d, v in m["by_database"].items()),
        ]
    if m["wrong"]:
        lines += ["", "Wrong:", *(f"- {i}: {reason}" for i, reason in m["wrong"])]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--json", action="store_true", help="print the metrics as JSON")
    args = parser.parse_args(argv)
    records = load_records(args.results)
    lines = args.results.read_text().splitlines()
    integrity = sum(1 for line in lines if json.loads(line).get("type") == "integrity_violation")
    suite = next(iter(records.values()), {}).get("suite", "questions")
    # Always measured against the whole suite: a run of some questions is reported as partial.
    first = next(iter(records.values()), {})
    if first.get("dataset") == "bird":
        # BIRD: the questions with scoreable ground truth, in the databases the run was started for.
        excluded = bird.load_expected()["excluded"]
        databases = first["databases"].split(",") if first.get("databases") else None
        planned = [
            q["id"]
            for q in bird.load_questions()
            if q["id"] not in excluded and (databases is None or q["db_id"] in databases)
        ]
    elif suite == "sql-safety":
        planned = [sid for sid, _ in ADVERSARIAL_SQL]
    else:
        planned = [q["id"] for q in load_questions()]
    metrics = compute(records, planned, integrity)
    print(json.dumps(metrics, indent=1) if args.json else render(metrics))


if __name__ == "__main__":
    main()

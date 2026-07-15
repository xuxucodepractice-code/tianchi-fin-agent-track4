"""Validate and merge O2/O3 observations into a Gold Oracle case-file copy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.gold_oracle import classify_cases


OBSERVATION_FIELDS = (
    "gold_evidence_answer",
    "current_reasoning_answer",
    "current_final_answer",
)


def _validate_observation(observation: dict[str, Any]) -> list[str]:
    qid = str(observation.get("qid") or "")
    errors: list[str] = []
    if not qid:
        errors.append("observation qid missing")
    for result_name in ("gold_result", "current_result"):
        result = observation.get(result_name)
        if not isinstance(result, dict):
            errors.append(f"{qid}: {result_name} missing")
            continue
        if result.get("mode") != "qwen":
            errors.append(f"{qid}: {result_name} mode must be qwen")
        if int(result.get("total_tokens") or 0) <= 0:
            errors.append(f"{qid}: {result_name} total_tokens must be > 0")
        if str(result.get("qid") or "") != qid:
            errors.append(f"{qid}: {result_name} qid mismatch")
    for field in OBSERVATION_FIELDS:
        if not str(observation.get(field) or "").strip():
            errors.append(f"{qid}: {field} missing")
    return errors


def merge_observations(
    case_payload: dict[str, Any], observation_payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    cases = case_payload.get("cases")
    observations = observation_payload.get("observations")
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        raise ValueError("case payload must contain a case list")
    if not isinstance(observations, list) or not observations:
        raise ValueError("observation payload must contain a non-empty observations list")

    case_by_qid = {str(case.get("qid") or ""): case for case in cases}
    seen: set[str] = set()
    errors: list[str] = []
    for observation in observations:
        if not isinstance(observation, dict):
            errors.append("observation must be an object")
            continue
        qid = str(observation.get("qid") or "")
        if qid in seen:
            errors.append(f"duplicate observation qid: {qid}")
        seen.add(qid)
        if qid not in case_by_qid:
            errors.append(f"unknown observation qid: {qid}")
        errors.extend(_validate_observation(observation))
    if errors:
        raise ValueError("; ".join(errors))

    merged_cases: list[dict[str, Any]] = []
    observation_by_qid = {observation["qid"]: observation for observation in observations}
    for case in cases:
        qid = str(case.get("qid") or "")
        observation = observation_by_qid.get(qid)
        if observation is None:
            merged_cases.append(dict(case))
            continue
        merged_cases.append(
            {
                **case,
                **{field: observation[field] for field in OBSERVATION_FIELDS},
                "oracle_observation": {
                    "observed_at": observation.get("observed_at"),
                    "pipeline_version": observation.get("pipeline_version"),
                    "model": observation.get("model"),
                    "gold_total_tokens": observation.get("gold_total_tokens"),
                    "current_total_tokens": observation.get("current_total_tokens"),
                },
            }
        )
    merged = {**case_payload, "cases": merged_cases}
    return merged, classify_cases(merged_cases)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output-cases", type=Path, required=True)
    parser.add_argument("--output-results", type=Path, required=True)
    args = parser.parse_args()

    case_payload = json.loads(args.cases.read_text(encoding="utf-8"))
    observation_payload = json.loads(args.observations.read_text(encoding="utf-8"))
    merged, results = merge_observations(case_payload, observation_payload)
    args.output_cases.parent.mkdir(parents=True, exist_ok=True)
    args.output_results.parent.mkdir(parents=True, exist_ok=True)
    args.output_cases.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_results.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"merged={len(observation_payload['observations'])} "
        f"complete={results['complete_count']} incomplete={results['incomplete_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Evaluate the deterministic E006 retrieval gate without calling an API."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agent.doc_meta import load_doc_meta
from agent.load_questions import load_all_questions
from agent.paths import REPO_ROOT
from agent.retrieve import load_chunks
from agent.retrieve_v0_compat import retrieve_multi_v0_compatible

DEFAULT_EXPERIMENT_DIR = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "experiments"
    / "E006_multi_retrieval_coverage"
)
DEFAULT_CASES = DEFAULT_EXPERIMENT_DIR / "gold_retrieval_cases.json"
DEFAULT_REFERENCE = DEFAULT_EXPERIMENT_DIR / "control_reference.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _compact(retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {"option_text": item["option_text"], "evidence": item["evidence"]}
        for key, item in retrieval["options"].items()
    }


def _canonical_hash(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate(
    cases_path: Path = DEFAULT_CASES,
    reference_path: Path = DEFAULT_REFERENCE,
) -> dict[str, Any]:
    cases_payload = json.loads(cases_path.read_text(encoding="utf-8"))
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    questions = load_all_questions()
    by_qid = {str(question["qid"]): question for question in questions}
    chunks = load_chunks()
    doc_meta = load_doc_meta()

    # Hash only the exact control across all 65 Multi questions.  Treatment is
    # deliberately restricted to the eight retrospective Gold cases so the
    # sealed prospective set is not used for development.
    control_rows: list[dict[str, Any]] = []
    for question in questions:
        if question.get("answer_format") != "multi":
            continue
        retrieval = retrieve_multi_v0_compatible(
            question,
            chunks,
            enable_option_document_route=False,
        )
        control_rows.append(
            {"qid": question["qid"], "retrieval": _compact(retrieval)}
        )
    control_hash = _canonical_hash(control_rows)

    control_hits = 0
    treatment_hits = 0
    denominator_chunks = 0
    control_complete_options = 0
    treatment_complete_options = 0
    denominator_options = 0
    gained: list[str] = []
    lost: list[str] = []
    rows: list[dict[str, Any]] = []
    routed_options: list[str] = []

    for case in cases_payload["cases"]:
        qid = str(case["qid"])
        question = by_qid[qid]
        control = retrieve_multi_v0_compatible(
            question,
            chunks,
            enable_option_document_route=False,
        )
        diagnostics: dict[str, Any] = {}
        treatment = retrieve_multi_v0_compatible(
            question,
            chunks,
            enable_option_document_route=True,
            doc_meta=doc_meta,
            diagnostics_out=diagnostics,
        )
        for option_key, required_values in case["options"].items():
            required = set(map(str, required_values))
            control_ids = {
                str(item["chunk_id"])
                for item in control["options"][option_key]["evidence"]
            }
            treatment_ids = {
                str(item["chunk_id"])
                for item in treatment["options"][option_key]["evidence"]
            }
            control_present = required & control_ids
            treatment_present = required & treatment_ids
            denominator_chunks += len(required)
            denominator_options += 1
            control_hits += len(control_present)
            treatment_hits += len(treatment_present)
            control_complete_options += int(required <= control_ids)
            treatment_complete_options += int(required <= treatment_ids)
            for chunk_id in sorted(treatment_present - control_present):
                gained.append(f"{qid}:{option_key}:{chunk_id}")
            for chunk_id in sorted(control_present - treatment_present):
                lost.append(f"{qid}:{option_key}:{chunk_id}")
            route = diagnostics["options"][option_key]
            if route.get("decision") == "route":
                routed_options.append(f"{qid}:{option_key}->{route['target_doc_id']}")
            rows.append(
                {
                    "qid": qid,
                    "option": option_key,
                    "required_chunk_ids": sorted(required),
                    "control_hit_count": len(control_present),
                    "treatment_hit_count": len(treatment_present),
                    "control_complete": required <= control_ids,
                    "treatment_complete": required <= treatment_ids,
                    "route_decision": route.get("decision"),
                    "route_reason": route.get("reason"),
                    "target_doc_id": route.get("target_doc_id"),
                }
            )

    expected_control_hash = str(reference["canonical_multi_retrieval_sha256"])
    checks = {
        "control_hash_matches_frozen_reference": control_hash == expected_control_hash,
        "control_multi_question_count_is_65": len(control_rows) == 65,
        "canonical_denominator_is_41": denominator_chunks == 41,
        "canonical_option_denominator_is_31": denominator_options == 31,
        "canonical_recall_improves": treatment_hits > control_hits,
        "complete_option_count_improves": (
            treatment_complete_options > control_complete_options
        ),
        "no_previously_hit_chunk_is_lost": not lost,
    }
    return {
        "schema_version": "e006-retrieval-evaluation/v1",
        "experiment_id": "E006",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "inputs": {
            "cases_path": _display_path(cases_path),
            "cases_sha256": _sha256(cases_path),
            "reference_path": _display_path(reference_path),
            "reference_sha256": _sha256(reference_path),
        },
        "control_reproduction": {
            "multi_question_count": len(control_rows),
            "option_pack_count": len(control_rows) * 4,
            "computed_canonical_sha256": control_hash,
            "expected_canonical_sha256": expected_control_hash,
            "exact_match": control_hash == expected_control_hash,
        },
        "canonical_recall": {
            "denominator_chunks": denominator_chunks,
            "control_hits": control_hits,
            "treatment_hits": treatment_hits,
            "delta": treatment_hits - control_hits,
            "control_rate": control_hits / denominator_chunks,
            "treatment_rate": treatment_hits / denominator_chunks,
            "denominator_options": denominator_options,
            "control_complete_options": control_complete_options,
            "treatment_complete_options": treatment_complete_options,
            "complete_option_delta": (
                treatment_complete_options - control_complete_options
            ),
        },
        "gained_required_chunks": gained,
        "lost_required_chunks": lost,
        "routed_options": routed_options,
        "checks": checks,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(args.cases, args.reference)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

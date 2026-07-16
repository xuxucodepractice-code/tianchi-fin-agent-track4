"""Run controlled O2 Gold Evidence and O3 Current Evidence observations."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.gold_oracle import build_gold_retrieval
from agent.load_questions import load_all_questions
from agent.qwen_client import MissingApiKeyError, QwenClient
from agent.reason_qwen import (
    reason_mcq_question_with_qwen,
    reason_question_with_qwen,
    reason_tf_question_with_qwen,
)
from agent.retrieve import load_chunks, retrieve_for_question, retrieve_for_tf_question
from agent.paths import REPO_ROOT
from agent.trace_gate import (
    AgentTraceRecorder,
    blind_data_guard,
    default_candidate_forbidden_roots,
    display_path,
    input_artifact_snapshot,
    sha256_file,
    validate_trace_directory,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run_oracle_case(
    case: dict[str, Any],
    question: dict[str, Any],
    chunks: list[dict[str, Any]],
    client: QwenClient,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run gold and current evidence without passing gold_answer to either call."""
    required_chunk_ids = case.get("required_chunk_ids")
    if not isinstance(required_chunk_ids, list) or not required_chunk_ids:
        raise ValueError(f"{case.get('qid')}: required_chunk_ids missing")

    gold_retrieval = build_gold_retrieval(question, required_chunk_ids, chunks)
    gold_question = {**question, "_trace_stage_prefix": "oracle_gold_evidence:"}
    current_question = {**question, "_trace_stage_prefix": "oracle_current_evidence:"}
    if question.get("answer_format") == "tf":
        current_retrieval = retrieve_for_tf_question(question, chunks, top_k=top_k)
        gold_result = reason_tf_question_with_qwen(
            gold_question, gold_retrieval, client=client
        )
        current_result = reason_tf_question_with_qwen(
            current_question, current_retrieval, client=client
        )
    elif question.get("answer_format") == "mcq":
        current_retrieval = retrieve_for_question(question, chunks, top_k=top_k)
        gold_result = reason_mcq_question_with_qwen(
            gold_question, gold_retrieval, client=client
        )
        current_result = reason_mcq_question_with_qwen(
            current_question, current_retrieval, client=client
        )
    else:
        current_retrieval = retrieve_for_question(question, chunks, top_k=top_k)
        gold_result = reason_question_with_qwen(
            gold_question, gold_retrieval, client=client
        )
        current_result = reason_question_with_qwen(
            current_question, current_retrieval, client=client
        )

    return {
        "qid": question["qid"],
        "pipeline_version": gold_result.get("pipeline_version"),
        "model": gold_result.get("model"),
        "observed_at": _now_iso(),
        "gold_evidence_answer": gold_result["answer"],
        "current_reasoning_answer": current_result["answer"],
        "current_final_answer": current_result["answer"],
        "gold_total_tokens": gold_result.get("total_tokens", 0),
        "current_total_tokens": current_result.get("total_tokens", 0),
        "gold_result": gold_result,
        "current_result": current_result,
        "gold_retrieval_source": "required_chunk_ids",
        "current_retrieval_source": "production_retrieval",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qids", help="comma-separated subset; default is every O1-ready case")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = payload.get("cases", [])
    requested = (
        {qid.strip() for qid in args.qids.split(",") if qid.strip()}
        if args.qids
        else None
    )
    selected = [
        case
        for case in cases
        if (requested is None or case.get("qid") in requested)
        and case.get("gold_answer")
        and case.get("required_chunk_ids")
        and case.get("raw_source_contains_all_required_facts") is True
        and case.get("chunks_contain_all_required_facts") is True
    ]
    if requested is not None:
        selected_qids = {str(case.get("qid")) for case in selected}
        missing = requested - selected_qids
        if missing:
            raise ValueError(f"requested cases are not O1-ready: {', '.join(sorted(missing))}")
    if not selected:
        raise ValueError("no O1-ready cases selected")

    questions = {question["qid"]: question for question in load_all_questions()}
    chunks = load_chunks()
    try:
        client = QwenClient()
    except MissingApiKeyError as exc:
        print(f"[error] {exc}")
        return 1
    trace_dir = args.output.parent / "agent_traces" / f"oracle-{uuid.uuid4()}"
    allowed_read_roots = (
        (REPO_ROOT / "agent").resolve(),
        (REPO_ROOT / "public_dataset_upload" / "questions" / "group_a").resolve(),
        (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
        (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
        args.cases.resolve(),
        args.output.parent.resolve(),
    )
    recorder: AgentTraceRecorder | None = None
    try:
        with blind_data_guard(
            default_candidate_forbidden_roots(),
            allowed_read_roots=allowed_read_roots,
            allowed_write_roots=(args.output.parent.resolve(),),
            block_subprocess=True,
        ):
            recorder = AgentTraceRecorder(
                trace_dir,
                purpose="oracle_diagnostic",
                model=client.model,
                base_url=client.base_url,
                config={
                    "runner": "agent.run_gold_oracle",
                    "experiment_id": "S3_GOLD_ORACLE_O2_O3",
                    "qids": [str(case["qid"]) for case in selected],
                    "top_k": args.top_k,
                    "cases_path": display_path(args.cases),
                    "cases_sha256": sha256_file(args.cases),
                    "output": display_path(args.output),
                    "client_timeout_seconds": client.timeout,
                    "client_max_retries": client.max_retries,
                    "input_artifacts": {
                        "questions": input_artifact_snapshot(
                            REPO_ROOT / "public_dataset_upload" / "questions" / "group_a"
                        ),
                        "chunks": input_artifact_snapshot(
                            REPO_ROOT / "processed_data" / "chunks.jsonl"
                        ),
                        "doc_meta": input_artifact_snapshot(
                            REPO_ROOT / "processed_data" / "doc_meta.json"
                        ),
                        "oracle_cases": input_artifact_snapshot(args.cases),
                    },
                },
            )
            client.trace_recorder = recorder
            observations = [
                run_oracle_case(
                    case,
                    questions[case["qid"]],
                    chunks,
                    client,
                    top_k=args.top_k,
                )
                for case in selected
            ]
            for observation in observations:
                recorder.record_derivation(
                    {
                        **observation["gold_result"],
                        "_trace_derivation_stage": "oracle_gold_evidence",
                    }
                )
                recorder.record_derivation(
                    {
                        **observation["current_result"],
                        "_trace_derivation_stage": "oracle_current_evidence",
                    }
                )
            result = {
                "experiment_id": "S3_GOLD_ORACLE_O2_O3",
                "case_source": str(args.cases),
                "case_count": len(observations),
                "total_tokens": sum(
                    item["gold_total_tokens"] + item["current_total_tokens"]
                    for item in observations
                ),
                "observations": observations,
                "agent_trace": {
                    "schema_version": "agent-trace/v1",
                    "trace_run_id": recorder.run_id,
                    "trace_dir": display_path(recorder.trace_dir),
                    "candidate_eligible": False,
                },
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            recorder.finalize(output_paths=(args.output,), failures=[])
            trace_report = validate_trace_directory(
                recorder.trace_dir,
                require_candidate_eligible=False,
                require_current_code_match=True,
            )
    except Exception as exc:
        if recorder is not None and recorder.manifest.get("status") == "recording":
            recorder.finalize(
                output_paths=None,
                failures=[{"qid": "", "error": str(exc)}],
            )
        print(f"[error] {exc}")
        return 1
    if not trace_report["ok"]:
        for error in trace_report["errors"]:
            print(f"[trace-error] {error}")
        return 1
    print(f"cases={len(observations)} tokens={result['total_tokens']} output={args.output}")
    print(
        f"trace_gate=PASS calls={trace_report['call_count']} "
        f"derivations={trace_report['derivation_count']} trace={recorder.trace_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

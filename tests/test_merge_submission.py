from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from agent.merge_submission import merge_submission_bundles
from agent.normalize_answer import normalize_answer
from agent.paths import REPO_ROOT, bundle_paths
from agent.trace_gate import (
    AgentTraceRecorder,
    OFFICIAL_DASHSCOPE_BASE_URL,
    blind_data_guard,
    default_candidate_forbidden_roots,
    freeze_candidate,
    input_artifact_snapshot,
    now_iso,
    sha256_file,
    sha256_json,
    validate_candidate_freeze,
)
from agent.validate_submission import validate_submission_files


V0_DIR = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "submissions"
    / "a_leaderboard_v0"
    / "2026-07-05_score_63_2607"
)
MANAGED_MERGE_TEST_ROOT = (
    REPO_ROOT / "outputs" / "experiments" / "_pytest_merge_submission"
)


@pytest.fixture(autouse=True)
def _clean_managed_merge_test_root():
    shutil.rmtree(MANAGED_MERGE_TEST_ROOT, ignore_errors=True)
    yield
    shutil.rmtree(MANAGED_MERGE_TEST_ROOT, ignore_errors=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_empty_rerun_copies_parent_bundle_byte_for_byte(tmp_path: Path):
    output = tmp_path / "merged"
    paths = merge_submission_bundles(
        V0_DIR,
        None,
        output,
        set(),
        parent_version="v0",
        experiment_id="E000-C",
        experiment_pipeline_version="v0",
    )

    for source, target in zip(bundle_paths(V0_DIR), paths):
        assert _sha(source) == _sha(target)


def _split(total: int, count: int) -> list[int]:
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _make_single_qid_rerun(tmp_path: Path, qid: str) -> tuple[Path, Path]:
    rerun = MANAGED_MERGE_TEST_ROOT / tmp_path.name / "rerun"
    rerun.mkdir(parents=True)
    with (V0_DIR / "answer.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    row = next(row for row in rows if row["qid"] == qid)
    with (rerun / "answer.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(
            {
                "qid": "summary",
                "answer": "",
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "total_tokens": row["total_tokens"],
            }
        )
        writer.writerow(row)
    evidence = json.loads((V0_DIR / "evidence.json").read_text(encoding="utf-8"))
    record = next(record for record in evidence if record["qid"] == qid)
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "selection_id": "test-selection",
                "frozen_before_labeling": True,
                "qids": [qid],
            }
        ),
        encoding="utf-8",
    )
    with blind_data_guard(
        default_candidate_forbidden_roots(),
        allowed_read_roots=(
            (REPO_ROOT / "agent").resolve(),
            (REPO_ROOT / "public_dataset_upload" / "questions" / "group_a").resolve(),
            (REPO_ROOT / "processed_data" / "chunks.jsonl").resolve(),
            (REPO_ROOT / "processed_data" / "doc_meta.json").resolve(),
            selection,
            rerun,
        ),
        allowed_write_roots=(rerun,),
    ):
        recorder = AgentTraceRecorder(
            rerun / "agent_traces" / "run-test",
            purpose="candidate_generation",
            model="qwen-plus-test",
            base_url=OFFICIAL_DASHSCOPE_BASE_URL,
            config={
                "runner": "agent.run_submission",
                "qids": [qid],
                "pipeline_version": "v-test",
                "experiment_id": "E-test",
                "selection_file": str(selection),
                "selection_sha256": sha256_file(selection),
                "output_dir": str(rerun),
                "hide_doc_ids": False,
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
                },
            },
        )
    option_keys = sorted(record["options"])
    prompt_parts = _split(int(row["prompt_tokens"]), len(option_keys))
    completion_parts = _split(int(row["completion_tokens"]), len(option_keys))
    trace_call_ids: list[str] = []
    judgments: dict[str, dict] = {}
    for index, option_key in enumerate(option_keys):
        judgment = "support" if option_key in row["answer"] else "refute"
        content = json.dumps({"judgment": judgment, "evidence_refs": []})
        messages = [{"role": "user", "content": f"judge option {option_key}"}]
        prompt_tokens = prompt_parts[index]
        completion_tokens = completion_parts[index]
        total_tokens = prompt_tokens + completion_tokens
        raw = {
            "id": f"provider-{option_key}",
            "model": "qwen-plus-test",
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }
        call_id = recorder.new_call_id()
        trace_call_ids.append(call_id)
        call_started_at = now_iso()
        attempt_started_at = now_iso()
        attempt_finished_at = now_iso()
        call_finished_at = now_iso()
        recorder.record_call(
            {
                "call_id": call_id,
                "local_request_id": f"request-{option_key}",
                "provider_request_id": f"provider-{option_key}",
                "started_at": call_started_at,
                "finished_at": call_finished_at,
                "status": "success",
                "context": {
                    "qid": qid,
                    "stage": "option_independent_judgment",
                    "option_key": option_key,
                },
                "messages": messages,
                "messages_sha256": sha256_json(messages),
                "model_evidence": [],
                "model_evidence_sha256": sha256_json([]),
                "request_payload": {
                    "model": "qwen-plus-test",
                    "messages": messages,
                    "temperature": 0.0,
                },
                "request_payload_sha256": sha256_json(
                    {
                        "model": "qwen-plus-test",
                        "messages": messages,
                        "temperature": 0.0,
                    }
                ),
                "raw_response": raw,
                "raw_response_sha256": sha256_json(raw),
                "response_content": content,
                "response_model": "qwen-plus-test",
                "finish_reason": "stop",
                "tool_calls": [],
                "usage": raw["usage"],
                "attempts": [
                    {
                        "attempt": 1,
                        "started_at": attempt_started_at,
                        "finished_at": attempt_finished_at,
                        "status": "success",
                        "error": None,
                        "retry_delay_seconds": 0,
                    }
                ],
                "retry_count": 0,
                "error": None,
            }
        )
        judgments[option_key] = {
            "judgment": judgment,
            "evidence_refs": [],
            "error": None,
            "trace_call_id": call_id,
        }
    normalized = normalize_answer(record["answer_format"], judgments, record["options"])
    assert normalized["answer"] == row["answer"]
    derivation = {
        "method": "agent.normalize_answer.normalize_answer",
        "answer_format": record["answer_format"],
        "input_judgments": {
            key: {
                "judgment": value["judgment"],
                "evidence_refs": [],
                "error": None,
            }
            for key, value in judgments.items()
        },
        "output_answer": row["answer"],
        "warnings": normalized["warnings"],
        "low_confidence": normalized["low_confidence"],
    }
    recorder.record_derivation(
        {
            "qid": qid,
            "answer_format": record["answer_format"],
            "option_judgments": judgments,
            "answer": row["answer"],
            "answer_derivation": derivation,
            "retrieval": record.get("retrieval", {}),
            "prompt_tokens": int(row["prompt_tokens"]),
            "completion_tokens": int(row["completion_tokens"]),
            "total_tokens": int(row["total_tokens"]),
        }
    )
    record = {
        **record,
        "pipeline_version": "v-test",
        "trace_run_id": recorder.run_id,
        "answer_derivation": derivation,
    }
    (rerun / "evidence.json").write_text(
        json.dumps([record], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (rerun / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "test-rerun",
                "run_started_at": "2026-07-14T00:00:00+08:00",
                "mode": "qwen",
                "model": record.get("model", "qwen-plus"),
                "pipeline_version": "v-test",
                "qids": [qid],
                "success_count": 1,
                "failure_count": 0,
                "total_prompt_tokens": int(row["prompt_tokens"]),
                "total_completion_tokens": int(row["completion_tokens"]),
                "total_tokens": int(row["total_tokens"]),
                "agent_trace": {
                    "required": True,
                    "schema_version": "agent-trace/v1",
                    "trace_run_id": recorder.run_id,
                    "trace_dir": str(recorder.trace_dir),
                    "blind_data_guard": "enforced",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    recorder.finalize(output_paths=bundle_paths(rerun), failures=[])
    return rerun, selection


def test_nonempty_merge_has_valid_lineage(tmp_path: Path):
    qid = "ins_a_007"
    rerun, selection = _make_single_qid_rerun(tmp_path, qid)
    output = tmp_path / "candidate"
    merge_submission_bundles(
        V0_DIR,
        rerun,
        output,
        {qid},
        parent_version="v0",
        experiment_id="E-test",
        experiment_pipeline_version="v-test",
        selection_path=selection,
    )

    report = validate_submission_files(*bundle_paths(output))

    assert report["ok"] is True, report["errors"]
    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    freeze_report = validate_candidate_freeze(output)
    assert manifest["rerun_qids"] == [qid]
    assert manifest["per_record_lineage"][qid]["source_kind"] == "rerun"
    assert manifest["per_record_lineage"]["fc_a_001"]["source_kind"] == "parent"
    assert manifest["legacy_parent_version_claim"] == {
        "claimed_version": "v0",
        "reason": "parent manifest predates the pipeline_version field",
    }
    assert freeze_report["ok"] is True, freeze_report["errors"]
    assert freeze_report["temporal_gate"] == "PENDING_LABEL_REVEAL"
    assert (
        manifest["per_record_lineage"]["fc_a_001"][
            "source_pipeline_version_provenance"
        ]
        == "legacy_parent_version_claim"
    )
    assert (
        manifest["per_record_lineage"][qid]["source_pipeline_version_provenance"]
        == "rerun_manifest"
    )


def test_explicit_parent_manifest_version_mismatch_is_rejected(tmp_path: Path):
    parent = tmp_path / "parent"
    shutil.copytree(V0_DIR, parent)
    manifest_path = parent / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pipeline_version"] = "v-explicit"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        ValueError, match="parent_version does not match frozen parent manifest"
    ):
        merge_submission_bundles(
            parent,
            None,
            tmp_path / "candidate",
            set(),
            parent_version="v-claimed",
            experiment_id="E-test",
            experiment_pipeline_version="v-test",
        )


def test_direct_freeze_rejects_an_untraced_inherited_answer_change(tmp_path: Path):
    traced_qid = "ins_a_007"
    rerun, selection = _make_single_qid_rerun(tmp_path, traced_qid)
    candidate = tmp_path / "candidate"
    merge_submission_bundles(
        V0_DIR,
        rerun,
        candidate,
        {traced_qid},
        parent_version="v0",
        experiment_id="E-test",
        experiment_pipeline_version="v-test",
        selection_path=selection,
    )
    (candidate / "candidate_freeze.json").unlink()
    shutil.rmtree(candidate / "agent_trace")

    answer_path = candidate / "answer.csv"
    with answer_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    inherited = next(row for row in rows if row["qid"] == "fc_a_001")
    inherited["answer"] = "B" if inherited["answer"] != "B" else "A"
    with answer_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    rerun_manifest = json.loads((rerun / "run_manifest.json").read_text(encoding="utf-8"))
    trace_dir = Path(rerun_manifest["agent_trace"]["trace_dir"])
    with pytest.raises(
        ValueError,
        match="non-rerun answer/token row differs|untraced answer differs",
    ):
        freeze_candidate(
            candidate,
            parent_dir=V0_DIR,
            experiment_id="E-test",
            pipeline_version="v-test",
            parent_version="v0",
            trace_dir=trace_dir,
            generation_mode="traced_rerun_plus_frozen_parent",
            selection_path=selection,
            trace_artifact_dir=rerun,
        )

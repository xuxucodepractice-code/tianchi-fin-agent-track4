from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agent.output_writer import write_answer_csv, write_evidence_json, write_run_manifest
from agent.paths import REPO_ROOT, bundle_paths
from agent.qwen_client import QwenClient
from agent.reason_qwen import reason_mcq_question_with_qwen
from agent.trace_gate import (
    AgentTraceRecorder,
    E002_SELECTION_SHA256,
    OFFICIAL_DASHSCOPE_BASE_URL,
    assert_candidate_experiment_policy,
    blind_data_guard,
    default_candidate_forbidden_roots,
    input_artifact_snapshot,
    now_iso,
    sha256_file,
    sha256_json,
    validate_trace_directory,
)


QUESTION = {
    "qid": "m1_trace_q1",
    "domain": "insurance",
    "question": "哪一个选项正确？",
    "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
    "answer_format": "mcq",
    "doc_ids": ["1"],
}


def _evidence(option_key: str, text: str) -> list[dict[str, object]]:
    return [
        {
            "chunk_id": f"insurance:1:{option_key}:0",
            "doc_id": "1",
            "source_type": "pdf",
            "source_path": "public_dataset_upload/raw/insurance/1.pdf",
            "page": 1,
            "section": "",
            "source_header": "【1 · 第1页】",
            "score": 1.0,
            "matched_terms": [text],
            "text": f"选项 {option_key} 的证据：{text}",
        }
    ]


RETRIEVAL = {
    "qid": QUESTION["qid"],
    "options": {
        "A": {"option_text": "甲", "evidence": _evidence("A", "甲不正确")},
        "B": {"option_text": "乙", "evidence": _evidence("B", "乙正确")},
        "C": {"option_text": "丙", "evidence": _evidence("C", "丙不正确")},
        "D": {"option_text": "丁", "evidence": _evidence("D", "丁证据不足")},
    },
}

MANAGED_ROOT = REPO_ROOT / "outputs" / "experiments" / "_pytest_trace_gate_m1"


@pytest.fixture(autouse=True)
def _isolated_m1_trace_root(monkeypatch):
    shutil.rmtree(MANAGED_ROOT, ignore_errors=True)
    monkeypatch.setattr(
        "agent.trace_gate.load_all_questions",
        lambda: [{"qid": QUESTION["qid"]}],
    )
    monkeypatch.setattr(
        "agent.trace_gate.validate_submission_files",
        lambda *args, **kwargs: {"ok": True, "errors": []},
    )
    yield
    shutil.rmtree(MANAGED_ROOT, ignore_errors=True)


def _chat_response(content: str, request_id: str, *, finish_reason: str = "stop") -> dict:
    return {
        "id": request_id,
        "model": "qwen-plus-test",
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def _option_content(option: str, judgment: str) -> str:
    return json.dumps(
        {
            "option": option,
            "judgment": judgment,
            "rationale": "依据该选项证据",
            "evidence_refs": [1],
        },
        ensure_ascii=False,
    )


def _valid_global_content(answer: str = "B") -> str:
    eliminated = {
        key: f"证据 {key}-1 不能支持该选项"
        for key in ["A", "B", "C", "D"]
        if key != answer
    }
    return json.dumps(
        {
            "answer": answer,
            "eliminated": eliminated,
            "calculations": [],
            "confidence": "high",
            "rationale": f"横向比较后 {answer} 最受证据支持",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _build_m1_bundle(
    name: str,
    *,
    global_content: str | None = None,
    global_finish_reason: str = "stop",
) -> tuple[Path, AgentTraceRecorder]:
    root = MANAGED_ROOT / name
    root.mkdir(parents=True)
    selection = root / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "selection_id": f"m1-trace-{name}",
                "frozen_before_labeling": True,
                "qids": [QUESTION["qid"]],
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
            root,
        ),
        allowed_write_roots=(root,),
    ):
        recorder = AgentTraceRecorder(
            root / "trace-source",
            purpose="candidate_generation",
            model="qwen-plus-test",
            base_url=OFFICIAL_DASHSCOPE_BASE_URL,
            config={
                "runner": "agent.run_submission",
                "qids": [QUESTION["qid"]],
                "experiment_id": "E002-test",
                "pipeline_version": "v-test",
                "selection_file": str(selection),
                "selection_sha256": sha256_file(selection),
                "output_dir": str(root),
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
        client = QwenClient(
            api_key="sk-test-not-real",
            model="qwen-plus-test",
            base_url=OFFICIAL_DASHSCOPE_BASE_URL,
            max_retries=0,
            trace_recorder=recorder,
        )
        responses = iter(
            [
                _chat_response(_option_content("A", "refute"), "req-a"),
                _chat_response(_option_content("B", "support"), "req-b"),
                _chat_response(_option_content("C", "refute"), "req-c"),
                _chat_response(_option_content("D", "insufficient"), "req-d"),
                _chat_response(
                    global_content if global_content is not None else _valid_global_content(),
                    "req-global",
                    finish_reason=global_finish_reason,
                ),
            ]
        )
        client._post = lambda payload: next(responses)  # type: ignore[method-assign]
        result = reason_mcq_question_with_qwen(QUESTION, RETRIEVAL, client=client)
        result["retrieval"] = RETRIEVAL["options"]
        result["evidence"] = []
        recorder.record_derivation(result)

    write_answer_csv([result], root / "answer.csv")
    write_evidence_json([result], root / "evidence.json")
    write_run_manifest(
        {
            "mode": "qwen",
            "run_finished_at": now_iso(),
            "experiment_id": "E002-test",
            "pipeline_version": "v-test",
            "qids": [QUESTION["qid"]],
            "rerun_qids": [QUESTION["qid"]],
            "agent_trace": {
                "trace_run_id": recorder.run_id,
                "trace_dir": str(recorder.trace_dir),
            },
            "agent_trace_gate": {
                "status": "PASS",
                "trace_run_id": recorder.run_id,
                "fresh_traced_qids": [QUESTION["qid"]],
                "prospective_qids": [QUESTION["qid"]],
                "known_before_freeze_qids": [],
                "legacy_inherited_qids": [],
            },
            "per_record_lineage": {QUESTION["qid"]: {"source_kind": "rerun"}},
        },
        root / "run_manifest.json",
    )
    recorder.finalize(output_paths=bundle_paths(root), failures=[])
    return root, recorder


def _rewrite_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )


def _refresh_trace_file_hash(recorder: AgentTraceRecorder, filename: str) -> None:
    manifest = json.loads(recorder.manifest_path.read_text(encoding="utf-8"))
    manifest["trace_files_sha256"][filename] = sha256_file(recorder.trace_dir / filename)
    recorder.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_m1_complete_four_plus_one_trace_bundle_passes() -> None:
    bundle, recorder = _build_m1_bundle("complete")

    report = validate_trace_directory(
        recorder.trace_dir,
        artifact_dir=bundle,
        require_candidate_eligible=True,
        require_current_code_match=True,
    )

    assert report["ok"] is True, report["errors"]
    calls = [json.loads(line) for line in recorder.calls_path.read_text().splitlines()]
    assert len(calls) == 5
    assert [call["context"]["stage"] for call in calls[:4]] == [
        "option_independent_judgment"
    ] * 4
    assert calls[-1]["context"]["stage"] == "mcq_global_comparison"
    assert calls[-1]["provider_request_id"] == "req-global"
    assert all(
        item["text"] in calls[-1]["messages"][1]["content"]
        for option in RETRIEVAL["options"].values()
        for item in option["evidence"]
    )


def test_m1_missing_global_call_id_fails_as_orphaned_call() -> None:
    bundle, recorder = _build_m1_bundle("missing-global-id")
    derivations = [
        json.loads(line) for line in recorder.derivations_path.read_text().splitlines()
    ]
    global_call_id = json.loads(recorder.calls_path.read_text().splitlines()[-1])["call_id"]
    derivations[0]["trace_call_ids"].remove(global_call_id)
    _rewrite_jsonl(recorder.derivations_path, derivations)
    _refresh_trace_file_hash(recorder, "derivations.jsonl")

    report = validate_trace_directory(recorder.trace_dir, artifact_dir=bundle)

    assert report["ok"] is False
    assert any(
        "orphaned or cross-linked API calls" in error
        or "exactly five traced calls" in error
        or "raw MCQ comparison call" in error
        for error in report["errors"]
    ), report["errors"]


def test_m1_semantically_tampered_raw_comparison_fails_even_with_fresh_hashes() -> None:
    bundle, recorder = _build_m1_bundle("tampered-comparison")
    calls = [json.loads(line) for line in recorder.calls_path.read_text().splitlines()]
    tampered_content = _valid_global_content("A")
    global_call = calls[-1]
    global_call["response_content"] = tampered_content
    global_call["raw_response"]["choices"][0]["message"]["content"] = tampered_content
    global_call["raw_response_sha256"] = sha256_json(global_call["raw_response"])
    _rewrite_jsonl(recorder.calls_path, calls)
    _refresh_trace_file_hash(recorder, "calls.jsonl")

    report = validate_trace_directory(recorder.trace_dir, artifact_dir=bundle)

    assert report["ok"] is False
    assert any(
        "MCQ derivation differs from raw comparison" in error
        for error in report["errors"]
    ), report["errors"]


def test_m1_parse_error_and_fallback_are_not_candidate_eligible() -> None:
    bundle, recorder = _build_m1_bundle("parse-error", global_content="not-json")

    report = validate_trace_directory(recorder.trace_dir, artifact_dir=bundle)

    assert report["ok"] is False
    assert any(
        "comparison is invalid or used fallback" in error
        for error in report["errors"]
    ), report["errors"]


def test_m1_non_stop_global_response_is_not_candidate_eligible() -> None:
    bundle, recorder = _build_m1_bundle("non-stop", global_finish_reason="length")

    report = validate_trace_directory(recorder.trace_dir, artifact_dir=bundle)

    assert report["ok"] is False
    assert any("finish_reason must be stop" in error for error in report["errors"]), report[
        "errors"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("experiment_id", "E-other"),
        ("pipeline_version", "v2s3"),
        ("top_k", 6),
        ("hide_doc_ids", True),
        ("selection_sha256", "0" * 64),
    ],
)
def test_e002_policy_rejects_any_preregistered_signature_drift(
    field: str, value: object
) -> None:
    config = {
        "experiment_id": "E002",
        "pipeline_version": "v2s2",
        "top_k": 5,
        "hide_doc_ids": False,
        "selection_sha256": E002_SELECTION_SHA256,
    }
    assert_candidate_experiment_policy(
        config,
        model="qwen-plus",
        base_url=OFFICIAL_DASHSCOPE_BASE_URL,
    )
    config[field] = value

    with pytest.raises(ValueError, match="E002 requires"):
        assert_candidate_experiment_policy(
            config,
            model="qwen-plus",
            base_url=OFFICIAL_DASHSCOPE_BASE_URL,
        )


def test_e002_policy_rejects_model_drift_before_inference() -> None:
    config = {
        "experiment_id": "E002",
        "pipeline_version": "v2s2",
        "top_k": 5,
        "hide_doc_ids": False,
        "selection_sha256": E002_SELECTION_SHA256,
    }

    with pytest.raises(ValueError, match="model='qwen-plus'"):
        assert_candidate_experiment_policy(
            config,
            model="qwen-max",
            base_url=OFFICIAL_DASHSCOPE_BASE_URL,
        )


def test_trace_validator_rechecks_e002_signature() -> None:
    bundle, recorder = _build_m1_bundle("policy-recheck")
    manifest = json.loads(recorder.manifest_path.read_text(encoding="utf-8"))
    manifest["config"].update(
        {
            "experiment_id": "E002",
            "pipeline_version": "v2s2",
            "top_k": 6,
            "hide_doc_ids": False,
            "selection_sha256": E002_SELECTION_SHA256,
        }
    )
    manifest["config_sha256"] = sha256_json(manifest["config"])
    recorder.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = validate_trace_directory(recorder.trace_dir, artifact_dir=bundle)

    assert report["ok"] is False
    assert any("E002 requires top_k=5" in error for error in report["errors"]), report[
        "errors"
    ]

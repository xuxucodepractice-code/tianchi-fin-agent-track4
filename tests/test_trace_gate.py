from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import threading
import urllib.error
from pathlib import Path

import pytest

from agent.output_writer import write_answer_csv, write_evidence_json, write_run_manifest
from agent.paths import REPO_ROOT, bundle_paths
from agent.qwen_client import QwenApiError, QwenClient
from agent.reason_qwen import reason_question_with_qwen
from agent.trace_gate import (
    AgentTraceRecorder,
    BlindDataAccessError,
    OFFICIAL_DASHSCOPE_BASE_URL,
    blind_data_guard,
    default_candidate_forbidden_roots,
    freeze_candidate,
    input_artifact_snapshot,
    now_iso,
    register_label_reveal,
    sha256_file,
    validate_candidate_freeze,
    validate_trace_directory,
)


QUESTION = {
    "qid": "trace_q1",
    "domain": "insurance",
    "question": "哪一个选项正确？",
    "options": {"A": "甲", "B": "乙"},
    "answer_format": "mcq",
    "doc_ids": ["1"],
}
EVIDENCE = [
    {
        "chunk_id": "insurance:1:1:0",
        "doc_id": "1",
        "source_type": "pdf",
        "source_path": "public_dataset_upload/raw/insurance/1.pdf",
        "page": 1,
        "section": "",
        "source_header": "【1 · 第1页】",
        "score": 1.0,
        "matched_terms": ["甲"],
        "text": "甲是正确选项，乙不是。",
    }
]
RETRIEVAL = {
    "qid": "trace_q1",
    "options": {
        "A": {"option_text": "甲", "evidence": EVIDENCE},
        "B": {"option_text": "乙", "evidence": EVIDENCE},
    },
}
MANAGED_TRACE_TEST_ROOT = (
    REPO_ROOT / "outputs" / "experiments" / "_pytest_trace_gate"
)


@pytest.fixture(autouse=True)
def _use_single_synthetic_official_question(monkeypatch):
    shutil.rmtree(MANAGED_TRACE_TEST_ROOT, ignore_errors=True)
    monkeypatch.setattr(
        "agent.trace_gate.load_all_questions",
        lambda: [{"qid": QUESTION["qid"]}],
    )
    monkeypatch.setattr(
        "agent.trace_gate.validate_submission_files",
        lambda *args, **kwargs: {"ok": True, "errors": []},
    )
    yield
    shutil.rmtree(MANAGED_TRACE_TEST_ROOT, ignore_errors=True)


def _response(judgment: str, request_id: str, *, option: str = "A") -> dict:
    content = json.dumps(
        {
            "option": option,
            "judgment": judgment,
            "rationale": "依据证据",
            "evidence_refs": [1],
        },
        ensure_ascii=False,
    )
    return {
        "id": request_id,
        "model": "qwen-plus-test",
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def _build_traced_bundle(root: Path) -> tuple[Path, Path, AgentTraceRecorder]:
    root = MANAGED_TRACE_TEST_ROOT / root.parent.name / root.name
    root.mkdir(parents=True)
    selection = root / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "selection_id": "trace-test",
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
                "experiment_id": "E-test",
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
                _response("support", "req-a", option="A"),
                _response("refute", "req-b", option="B"),
            ]
        )
        client._post = lambda payload: next(responses)  # type: ignore[method-assign]
        result = reason_question_with_qwen(QUESTION, RETRIEVAL, client=client)
        result["retrieval"] = RETRIEVAL["options"]
        result["evidence"] = []
        recorder.record_derivation(result)

    write_answer_csv([result], root / "answer.csv")
    write_evidence_json([result], root / "evidence.json")
    write_run_manifest(
        {
            "mode": "qwen",
            "run_finished_at": now_iso(),
            "experiment_id": "E-test",
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
            "per_record_lineage": {
                QUESTION["qid"]: {"source_kind": "rerun"},
            },
        },
        root / "run_manifest.json",
    )
    recorder.finalize(output_paths=bundle_paths(root), failures=[])
    return root, selection, recorder


def test_complete_trace_validates_and_contains_exact_inputs_and_raw_response(tmp_path: Path):
    bundle, _, recorder = _build_traced_bundle(tmp_path / "bundle")

    report = validate_trace_directory(
        recorder.trace_dir,
        artifact_dir=bundle,
        require_candidate_eligible=True,
        require_current_code_match=True,
    )

    assert report["ok"] is True, report["errors"]
    calls = [json.loads(line) for line in recorder.calls_path.read_text().splitlines()]
    assert len(calls) == 2
    assert calls[0]["messages"][1]["content"].find(EVIDENCE[0]["text"]) >= 0
    assert calls[0]["model_evidence"] == EVIDENCE
    assert calls[0]["raw_response"]["id"] == "req-a"
    assert calls[0]["tool_calls"] == []
    assert calls[0]["attempts"][0]["status"] == "success"


def test_trace_tampering_fails_closed(tmp_path: Path):
    bundle, _, recorder = _build_traced_bundle(tmp_path / "bundle")
    calls = [json.loads(line) for line in recorder.calls_path.read_text().splitlines()]
    calls[0]["messages"][1]["content"] = "tampered"
    recorder.calls_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in calls) + "\n",
        encoding="utf-8",
    )

    report = validate_trace_directory(recorder.trace_dir, artifact_dir=bundle)

    assert report["ok"] is False
    assert any("hash mismatch" in error for error in report["errors"])


def test_retry_history_is_preserved(tmp_path: Path, monkeypatch):
    attempts = 0

    def fake_post(payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.HTTPError(
                "https://example.invalid",
                429,
                "rate limited",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"rate limited"}'),
            )
        return _response("support", "req-retry")
    with blind_data_guard(
        default_candidate_forbidden_roots(),
        allowed_read_roots=((REPO_ROOT / "agent").resolve(), tmp_path),
        allowed_write_roots=(tmp_path,),
    ):
        recorder = AgentTraceRecorder(
            tmp_path / "trace",
            purpose="unscored_diagnostic",
            model="qwen-plus-test",
            base_url="https://example.invalid/v1",
            config={"runner": "agent.run_submission", "qids": ["q1"]},
        )
        client = QwenClient(
            api_key="sk-test-not-real",
            model="qwen-plus-test",
            max_retries=1,
            trace_recorder=recorder,
        )
        client._post = fake_post  # type: ignore[method-assign]
        monkeypatch.setattr("agent.qwen_client.time.sleep", lambda _: None)
        response = client.chat(
            [{"role": "user", "content": "evidence text"}],
            trace_context={"qid": "q1", "stage": "test", "evidence": []},
        )

    assert response["retry_count"] == 1
    call = json.loads(recorder.calls_path.read_text().strip())
    assert [item["status"] for item in call["attempts"]] == ["error", "success"]
    assert call["retry_count"] == 1


def test_untraced_qwen_call_is_rejected_before_http(monkeypatch):
    client = QwenClient(api_key="sk-test-not-real")
    called = False

    def fake_post(payload):
        nonlocal called
        called = True
        return _response("support", "req")

    client._post = fake_post  # type: ignore[method-assign]
    with pytest.raises(QwenApiError, match="Trace Gate"):
        client.chat([{"role": "user", "content": "x"}])
    assert called is False


def test_blind_guard_denies_label_reads_symlinks_and_subprocess(tmp_path: Path):
    sensitive = (
        REPO_ROOT
        / "workspace"
        / "03_baseline_improvement"
        / "evaluation"
        / "local_labels.md"
    )
    link = tmp_path / "label-link"
    link.symlink_to(sensitive)
    hardlink = tmp_path / "label-hardlink"
    os.link(sensitive, hardlink)
    with blind_data_guard(
        default_candidate_forbidden_roots(),
        allowed_read_roots=((REPO_ROOT / "agent").resolve(),),
        allowed_write_roots=(tmp_path.resolve(),),
    ):
        assert (REPO_ROOT / "agent" / "prompts.py").read_text(encoding="utf-8")
        with pytest.raises(BlindDataAccessError):
            sensitive.read_text(encoding="utf-8")
        with pytest.raises(BlindDataAccessError):
            link.read_text(encoding="utf-8")
        with pytest.raises(BlindDataAccessError):
            hardlink.read_text(encoding="utf-8")
        with pytest.raises(BlindDataAccessError):
            subprocess.run(["true"], check=True)


def test_blind_guard_covers_threads_and_keeps_violations_sticky(tmp_path: Path):
    sensitive = (
        REPO_ROOT
        / "workspace"
        / "03_baseline_improvement"
        / "evaluation"
        / "local_labels.md"
    )
    observed: list[BaseException] = []

    def read_from_thread():
        try:
            sensitive.read_text(encoding="utf-8")
        except BaseException as exc:  # capture the audit-hook exception from the worker
            observed.append(exc)

    with blind_data_guard(
        default_candidate_forbidden_roots(),
        allowed_read_roots=((REPO_ROOT / "agent").resolve(),),
        allowed_write_roots=(tmp_path,),
    ):
        worker = threading.Thread(target=read_from_thread)
        worker.start()
        worker.join()

        assert len(observed) == 1
        assert isinstance(observed[0], BlindDataAccessError)
        with pytest.raises(BlindDataAccessError, match="recorded an access violation"):
            AgentTraceRecorder(
                tmp_path / "must-not-exist",
                purpose="candidate_generation",
                model="qwen-plus-test",
                base_url="https://example.invalid/v1",
                config={"runner": "agent.run_submission", "qids": ["q1"]},
            )


def test_blind_guard_rejects_nested_or_concurrent_policy_widening(tmp_path: Path):
    sensitive = (
        REPO_ROOT
        / "workspace"
        / "03_baseline_improvement"
        / "evaluation"
        / "local_labels.md"
    )
    observed: list[BaseException] = []

    def widen_from_thread():
        try:
            with blind_data_guard(
                default_candidate_forbidden_roots(),
                allowed_read_roots=(sensitive,),
                allowed_write_roots=(tmp_path,),
            ):
                pass
        except BaseException as exc:
            observed.append(exc)

    with blind_data_guard(
        default_candidate_forbidden_roots(),
        allowed_read_roots=((REPO_ROOT / "agent").resolve(),),
        allowed_write_roots=(tmp_path,),
    ):
        with pytest.raises(BlindDataAccessError, match="cannot replace"):
            with blind_data_guard(
                default_candidate_forbidden_roots(),
                allowed_read_roots=(sensitive,),
                allowed_write_roots=(tmp_path,),
            ):
                pass
        worker = threading.Thread(target=widen_from_thread)
        worker.start()
        worker.join()
        assert len(observed) == 1
        assert isinstance(observed[0], BlindDataAccessError)
        with pytest.raises(BlindDataAccessError, match="recorded an access violation"):
            AgentTraceRecorder(
                tmp_path / "must-not-exist",
                purpose="candidate_generation",
                model="qwen-plus-test",
                base_url="https://example.invalid/v1",
                config={"runner": "agent.run_submission", "qids": ["q1"]},
            )


def test_freeze_then_separate_reveal_enforces_strict_time_order(tmp_path: Path):
    bundle, selection, recorder = _build_traced_bundle(tmp_path / "bundle")
    freeze_path = freeze_candidate(
        bundle,
        parent_dir=bundle,
        experiment_id="E-test",
        pipeline_version="v-test",
        parent_version="v-parent",
        trace_dir=recorder.trace_dir,
        generation_mode="traced_rerun_plus_frozen_parent",
        selection_path=selection,
        trace_artifact_dir=bundle,
    )
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "selection_id": "trace-test",
                "complete": True,
                "expected_count": 1,
                "validated_count": 1,
                "errors": [],
                "results": [
                    {
                        "qid": "trace_q1",
                        "answer": "A",
                        "completed_at": freeze["candidate_frozen_at"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reveal_path = register_label_reveal(
        bundle,
        labels_path=labels,
    )

    report = validate_candidate_freeze(bundle, label_reveal_path=reveal_path)

    assert report["ok"] is True, report["errors"]
    assert report["temporal_gate"] == "PASS"
    assert json.loads(freeze_path.read_text()) == freeze


def test_reveal_rejects_incomplete_or_wrong_label_batch(tmp_path: Path):
    bundle, selection, recorder = _build_traced_bundle(tmp_path / "bundle")
    freeze_path = freeze_candidate(
        bundle,
        parent_dir=bundle,
        experiment_id="E-test",
        pipeline_version="v-test",
        parent_version="v-parent",
        trace_dir=recorder.trace_dir,
        generation_mode="traced_rerun_plus_frozen_parent",
        selection_path=selection,
        trace_artifact_dir=bundle,
    )
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "selection_id": "wrong",
                "complete": False,
                "expected_count": 1,
                "validated_count": 0,
                "errors": ["missing"],
                "results": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="complete=true"):
        register_label_reveal(
            bundle,
            labels_path=labels,
        )


def test_reveal_validation_rechecks_selection_partition(tmp_path: Path):
    bundle, selection, recorder = _build_traced_bundle(tmp_path / "bundle")
    freeze_path = freeze_candidate(
        bundle,
        parent_dir=bundle,
        experiment_id="E-test",
        pipeline_version="v-test",
        parent_version="v-parent",
        trace_dir=recorder.trace_dir,
        generation_mode="traced_rerun_plus_frozen_parent",
        selection_path=selection,
        trace_artifact_dir=bundle,
    )
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "selection_id": "trace-test",
                "complete": True,
                "expected_count": 1,
                "validated_count": 1,
                "errors": [],
                "results": [
                    {
                        "qid": "trace_q1",
                        "answer": "A",
                        "completed_at": freeze["candidate_frozen_at"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    reveal_path = register_label_reveal(bundle, labels_path=labels)
    reveal = json.loads(reveal_path.read_text(encoding="utf-8"))
    reveal["known_before_freeze_qids"] = ["trace_q1"]
    reveal_path.write_text(json.dumps(reveal), encoding="utf-8")

    report = validate_candidate_freeze(bundle, label_reveal_path=reveal_path)

    assert report["ok"] is False
    assert any("known_before_freeze_qids" in error for error in report["errors"])


def test_freeze_rejects_unrelated_trace(tmp_path: Path):
    bundle_a, selection_a, _ = _build_traced_bundle(tmp_path / "a")
    _, _, recorder_b = _build_traced_bundle(tmp_path / "b")

    with pytest.raises(ValueError, match="trace gate failed"):
        freeze_candidate(
            bundle_a,
            parent_dir=bundle_a,
            experiment_id="E-test",
            pipeline_version="v-test",
            parent_version="v-parent",
            trace_dir=recorder_b.trace_dir,
            generation_mode="traced_rerun_plus_frozen_parent",
            selection_path=selection_a,
            trace_artifact_dir=bundle_a,
        )

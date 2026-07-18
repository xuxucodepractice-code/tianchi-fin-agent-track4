from __future__ import annotations

import copy

import pytest

from agent.evaluate_e006_paired import call_prompt_binding_errors, evaluate_paired
from agent.reason_multi_v0_compat import (
    E006_PIPELINE_VERSION,
    build_option_judgment_messages_v0,
)
from agent.run_e006_paired_arm import (
    DEVELOPMENT_QIDS,
    DEVELOPMENT_SELECTION_PATH,
    FROZEN_INPUT_SHA256,
    _load_selection,
    _verify_frozen_inputs,
)


def _evidence(qid: str, option: str, *, prefix: str = "base", doc_id: str = "d"):
    return [
        {
            "chunk_id": f"{qid}:{option}:{prefix}:{index}",
            "doc_id": doc_id,
            "source_type": "pdf",
            "source_path": f"{doc_id}.pdf",
            "page": index,
            "section": "",
            "score": float(10 - index),
            "matched_terms": ["x"],
            "text": f"{qid}-{option}-{prefix}-{index}",
        }
        for index in range(5)
    ]


def _row(qid: str, answer: str, arm: str, *, changed_route: bool = False):
    retrieval = {}
    diagnostics = {}
    for option in "ABCD":
        changed = changed_route and option == "A"
        evidence = _evidence(
            qid,
            option,
            prefix="route" if changed else "base",
            doc_id="target" if changed else "d",
        )
        control_ids = [
            item["chunk_id"] for item in _evidence(qid, option, prefix="base", doc_id="d")
        ]
        selected_ids = [item["chunk_id"] for item in evidence]
        diagnostics[option] = {
            "decision": "route" if changed else "fallback",
            "reason": (
                "high_confidence_unique_title_match"
                if changed
                else ("route_disabled_control" if arm == "control" else "weak_match")
            ),
            "target_doc_id": "target" if changed else None,
            "control_chunk_ids": control_ids,
            "selected_chunk_ids": selected_ids,
        }
        retrieval[option] = {"option_text": option, "evidence": evidence}
    return {
        "qid": qid,
        "answer": answer,
        "pipeline_version": E006_PIPELINE_VERSION,
        "experiment_arm": arm,
        "retrieval": retrieval,
        "route_diagnostics": {
            "enabled": arm == "treatment",
            "options": diagnostics,
        },
        "option_judgments": {
            option: {"error": None, "trace_call_id": f"{qid}-{arm}-{option}"}
            for option in "ABCD"
        },
    }


def _payload(arm: str, answers: dict[str, str], *, changed_qid: str | None = None):
    return {
        "schema_version": "e006-observations/v1",
        "experiment_id": "E006",
        "phase": "development",
        "arm": arm,
        "pipeline_version": E006_PIPELINE_VERSION,
        "retrieval_control_profile": "v0-82041d0",
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "qids": list(DEVELOPMENT_QIDS),
        "question_count": 13,
        "api_call_count": 52,
        "total_tokens": 100 if arm == "control" else 105,
        "failures": [],
        "observations": [
            _row(
                qid,
                answers[qid],
                arm,
                changed_route=(arm == "treatment" and qid == changed_qid),
            )
            for qid in DEVELOPMENT_QIDS
        ],
    }


def _labels():
    first = DEVELOPMENT_QIDS[0]
    labels = {qid: ("B" if qid == first else "A") for qid in DEVELOPMENT_QIDS}
    parent = {qid: "A" for qid in DEVELOPMENT_QIDS}
    return {
        "schema_version": "e006-development-labels/v1",
        "experiment_id": "E006",
        "role": "retrospective_development_only",
        "labels_known_before_code_freeze": True,
        "labels": labels,
        "frozen_online_v2s1_answers": parent,
        "frozen_parent_correct_qids": [qid for qid in DEVELOPMENT_QIDS if qid != first],
    }


def _receipt():
    return {
        "status": "PASS",
        "selection_sha256": FROZEN_INPUT_SHA256["selection"],
        "call_count": 52,
        "derivation_count": 13,
        "code_sha256": "code",
        "model_sha256": "model",
        "input_artifacts_sha256": "inputs",
    }


def _manifest(arm: str):
    return {
        "config": {
            "arm": arm,
            "enable_option_document_route": arm == "treatment",
            "output_dir": arm,
            "same": "frozen",
        }
    }


def _questions():
    return {
        qid: {
            "qid": qid,
            "question": f"question-{qid}",
            "options": {option: option for option in "ABCD"},
        }
        for qid in DEVELOPMENT_QIDS
    }


def _calls(payload):
    questions = _questions()
    calls = []
    for row in payload["observations"]:
        qid = row["qid"]
        for option in "ABCD":
            evidence = row["retrieval"][option]["evidence"]
            calls.append(
                {
                    "context": {
                        "qid": qid,
                        "option_key": option,
                        "option_text": option,
                        "stage": f"e006_{payload['arm']}_v0_option_judgment",
                        "prompt_profile": "v0-82041d0",
                    },
                    "model_evidence": evidence,
                    "messages": build_option_judgment_messages_v0(
                        questions[qid], option, option, evidence
                    ),
                }
            )
    return calls, questions


def _evaluate(control, treatment, labels):
    return evaluate_paired(
        control,
        treatment,
        labels,
        control_receipt=_receipt(),
        treatment_receipt=_receipt(),
        control_manifest=_manifest("control"),
        treatment_manifest=_manifest("treatment"),
    )


def test_paired_evaluation_passes_on_one_clean_gain():
    labels = _labels()
    first = DEVELOPMENT_QIDS[0]
    control_answers = dict(labels["frozen_online_v2s1_answers"])
    treatment_answers = dict(control_answers)
    treatment_answers[first] = labels["labels"][first]
    report = _evaluate(
        _payload("control", control_answers),
        _payload("treatment", treatment_answers, changed_qid=first),
        labels,
    )
    assert report["status"] == "PASS"
    assert report["paired_control_to_treatment"]["net"] == 1
    assert report["treatment_vs_frozen_parent"]["net"] == 1
    assert report["tokens"]["delta"] == 5


def test_paired_evaluation_fails_on_parent_correct_regression():
    labels = _labels()
    first, second = DEVELOPMENT_QIDS[:2]
    control_answers = dict(labels["frozen_online_v2s1_answers"])
    treatment_answers = dict(control_answers)
    treatment_answers[first] = labels["labels"][first]
    treatment_answers[second] = "B"
    report = _evaluate(
        _payload("control", control_answers),
        _payload("treatment", treatment_answers, changed_qid=first),
        labels,
    )
    assert report["status"] == "FAIL"
    assert report["checks"]["frozen_parent_correct_zero_regression"] is False
    assert second in report["treatment_vs_frozen_parent"]["parent_correct_regressions"]


def test_duplicate_observation_qids_are_rejected():
    labels = _labels()
    control = _payload("control", labels["frozen_online_v2s1_answers"])
    control["observations"][1]["qid"] = control["observations"][0]["qid"]
    with pytest.raises(ValueError, match="13 unique"):
        _evaluate(
            control,
            _payload("treatment", labels["frozen_online_v2s1_answers"]),
            labels,
        )


def test_fallback_evidence_mutation_fails_unique_variable_gate():
    labels = _labels()
    first = DEVELOPMENT_QIDS[0]
    control_answers = dict(labels["frozen_online_v2s1_answers"])
    treatment_answers = dict(control_answers)
    treatment_answers[first] = labels["labels"][first]
    treatment = _payload("treatment", treatment_answers, changed_qid=first)
    treatment["observations"][1]["retrieval"]["B"]["evidence"][0]["text"] = "tampered"
    report = _evaluate(_payload("control", control_answers), treatment, labels)
    assert report["status"] == "FAIL"
    assert report["checks"]["unique_retrieval_variable"] is False


def test_declared_parent_correct_set_is_recomputed_from_truth():
    labels = _labels()
    labels["frozen_parent_correct_qids"] = []
    with pytest.raises(ValueError, match="truth-derived"):
        _evaluate(
            _payload("control", labels["frozen_online_v2s1_answers"]),
            _payload("treatment", labels["frozen_online_v2s1_answers"]),
            labels,
        )


def test_development_selection_and_all_frozen_inputs_are_bound():
    loaded = _load_selection(
        DEVELOPMENT_SELECTION_PATH, phase="development", arm="control"
    )
    assert tuple(loaded["qids"]) == DEVELOPMENT_QIDS
    snapshots = _verify_frozen_inputs(DEVELOPMENT_SELECTION_PATH)
    assert {key: value["sha256"] for key, value in snapshots.items()} == FROZEN_INPUT_SHA256


def test_non_development_phase_and_copied_selection_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="sealed"):
        _load_selection(DEVELOPMENT_SELECTION_PATH, phase="primary", arm="treatment")
    copied = tmp_path / "selection.json"
    copied.write_bytes(DEVELOPMENT_SELECTION_PATH.read_bytes())
    with pytest.raises(ValueError, match="governed selection path"):
        _load_selection(copied, phase="development", arm="control")


def test_exact_call_topology_and_prompt_evidence_binding():
    payload = _payload("control", {qid: "A" for qid in DEVELOPMENT_QIDS})
    calls, questions = _calls(payload)
    rows = {row["qid"]: row for row in payload["observations"]}
    assert call_prompt_binding_errors(
        calls, rows, questions, arm="control"
    ) == []

    wrong_topology = copy.deepcopy(calls)
    wrong_topology[-1]["context"]["option_key"] = "A"
    errors = call_prompt_binding_errors(
        wrong_topology, rows, questions, arm="control"
    )
    assert any("expected exactly one API call" in error for error in errors)

    wrong_prompt = copy.deepcopy(calls)
    wrong_prompt[0]["model_evidence"][0]["text"] = "not-the-retrieved-evidence"
    wrong_prompt[0]["messages"][1]["content"] += "\ntampered"
    errors = call_prompt_binding_errors(
        wrong_prompt, rows, questions, arm="control"
    )
    assert any("model evidence differs" in error for error in errors)
    assert any("exact messages differ" in error for error in errors)

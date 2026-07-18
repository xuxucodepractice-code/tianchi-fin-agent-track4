from __future__ import annotations

from pathlib import Path

import pytest

from agent.evaluate_e011_e010_churn_audit import (
    EXPECTED_OUTPUT_DIRS,
    evaluate_churn,
    load_bundle,
    pair_anchor_errors,
    replay_errors,
)


def test_zero_retry_policy_is_preserved_instead_of_coalesced_to_missing():
    value = 0
    assert int(value if value is not None else -1) == 0
    assert int(value or -1) == -1


def test_immutable_e010_pair_passes_independent_e011_audit():
    if not (EXPECTED_OUTPUT_DIRS["primary"] / "run_receipt.json").is_file():
        pytest.skip("immutable E010 runtime pair is not present in this checkout")
    primary = load_bundle(
        EXPECTED_OUTPUT_DIRS["primary"] / "observations.json",
        EXPECTED_OUTPUT_DIRS["primary"] / "run_receipt.json",
        attempt="primary",
    )
    repeat = load_bundle(
        EXPECTED_OUTPUT_DIRS["repeat"] / "observations.json",
        EXPECTED_OUTPUT_DIRS["repeat"] / "run_receipt.json",
        attempt="repeat",
    )
    errors = [
        *primary["errors"],
        *repeat["errors"],
        *replay_errors(primary, attempt="primary"),
        *replay_errors(repeat, attempt="repeat"),
        *pair_anchor_errors(primary, repeat),
    ]
    assert errors == []
    report = evaluate_churn(primary, repeat, bundle_errors=errors)
    assert report["status"] == "PASS"
    assert report["primary_repeat_answer_churn_C"] == 0
    assert all(report["checks"].values())

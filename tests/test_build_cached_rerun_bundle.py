from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.build_cached_rerun_bundle import build_cached_rerun_bundle
from agent.paths import REPO_ROOT


S2A_QIDS = (
    REPO_ROOT
    / "workspace"
    / "03_baseline_improvement"
    / "submissions"
    / "a_leaderboard_v0"
    / "v2_s1"
    / "tf_rerun_qids.json"
)
CACHE_DIR = REPO_ROOT / "processed_data" / "reasoning_samples"


def test_build_cached_rerun_bundle_uses_no_network_and_has_retrieval(tmp_path: Path):
    qids = tmp_path / "qids.json"
    qids.write_text(json.dumps(["reg_a_010", "res_a_013"]), encoding="utf-8")
    output = tmp_path / "bundle"

    build_cached_rerun_bundle(
        qids_file=qids,
        cache_dir=CACHE_DIR,
        output_dir=output,
        pipeline_version="v2s1",
        experiment_id="E001-test",
    )

    manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    records = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
    assert manifest["cache_only"] is True
    assert manifest["execution_mode"] == "cache_only_repack"
    assert manifest["api_calls"] == 0
    assert manifest["network_calls"] == 0
    assert manifest["reused_from_cache_count"] == 2
    assert manifest["reused_pipeline_versions"] == {"v2s1": 2}
    assert set(manifest["retrieval_provenance_sha256"]) == {
        "processed_data/chunks.jsonl",
        "agent/retrieve.py",
        "agent/query_terms.py",
    }
    assert manifest["qids"] == ["reg_a_010", "res_a_013"]
    assert manifest["total_tokens"] > 0
    assert all(record["mode"] == "qwen" for record in records)
    assert all(record["pipeline_version"] == "v2s1" for record in records)
    assert all(record["retrieval"]["tf"]["evidence"] for record in records)


def test_build_cached_rerun_bundle_rejects_wrong_pipeline_without_output(tmp_path: Path):
    qids = tmp_path / "qids.json"
    qids.write_text(json.dumps(["reg_a_010"]), encoding="utf-8")
    output = tmp_path / "bundle"

    with pytest.raises(ValueError, match="pipeline_version"):
        build_cached_rerun_bundle(
            qids_file=qids,
            cache_dir=CACHE_DIR,
            output_dir=output,
            pipeline_version="wrong-version",
            experiment_id="E001-test",
        )

    assert not output.exists()


def test_registered_tf_qid_file_has_exactly_twenty_unique_questions():
    data = json.loads(S2A_QIDS.read_text(encoding="utf-8"))
    qids = data["rerun_qids"]
    assert data["rerun_count"] == 20
    assert len(qids) == len(set(qids)) == 20
